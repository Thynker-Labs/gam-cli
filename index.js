#!/usr/bin/env node

const fs = require('fs');
const path = require('path');
const yaml = require('js-yaml');

const CONFIG_DIR = path.join(process.env.HOME || process.env.USERPROFILE, '.gam-cli');
const CONFIG_FILE = path.join(CONFIG_DIR, 'config.yaml');
const ERROR_LOG_FILE = path.join(CONFIG_DIR, 'errors.log');

function ensureConfigDir() {
  if (!fs.existsSync(CONFIG_DIR)) {
    fs.mkdirSync(CONFIG_DIR, { recursive: true });
  }
}

function logError(error, context = 'unknown') {
  ensureConfigDir();
  const timestamp = new Date().toISOString();
  const message = error?.stack || error?.message || String(error);
  const entry = `[${timestamp}] [${context}] ${message}\n\n`;
  fs.appendFileSync(ERROR_LOG_FILE, entry, 'utf-8');
}

function exitWithLoggedError(error, context) {
  logError(error, context);
  console.error(`Error: ${error.message}`);
  console.error(`Details logged to: ${ERROR_LOG_FILE}`);
  process.exit(1);
}

function loadConfig() {
  if (!fs.existsSync(CONFIG_FILE)) {
    console.log(`No config found at ${CONFIG_FILE}`);
    console.log('Run with: gam init <path-to-gam.yaml>');
    process.exit(1);
  }

  try {
    const configContent = fs.readFileSync(CONFIG_FILE, 'utf-8');
    return yaml.load(configContent);
  } catch (error) {
    exitWithLoggedError(error, 'loadConfig');
  }
}

async function initGAM(configPath) {
  try {
    const resolvedPath = path.isAbsolute(configPath)
      ? configPath
      : path.resolve(process.cwd(), configPath);
    if (!fs.existsSync(resolvedPath)) {
      throw new Error(`Config file not found: ${resolvedPath}`);
    }
    const config = yaml.load(fs.readFileSync(resolvedPath, 'utf-8'));
    ensureConfigDir();

    // Validate required fields
    if (!config.ad_manager) {
      throw new Error('Invalid config: missing "ad_manager" section');
    }
    if (!config.ad_manager.network_code) {
      throw new Error('Invalid config: missing "ad_manager.network_code"');
    }

    fs.writeFileSync(CONFIG_FILE, fs.readFileSync(resolvedPath, 'utf-8'));

    console.log('Configuration saved!');
    console.log(`Network Code: ${config.ad_manager.network_code}`);
  } catch (error) {
    exitWithLoggedError(error, 'initGAM');
  }
}

class GAMService {
  constructor() {
    this.config = loadConfig();
    this.networkCode = this.config.ad_manager.network_code;
  }

  getClientOptions() {
    const adManagerConfig = this.config.ad_manager;
    const options = { fallback: true };
    if (adManagerConfig.path_to_private_key_file) {
      const credsPath = path.isAbsolute(adManagerConfig.path_to_private_key_file)
        ? adManagerConfig.path_to_private_key_file
        : path.resolve(process.cwd(), adManagerConfig.path_to_private_key_file);
      if (fs.existsSync(credsPath)) {
        options.keyFilename = credsPath;
      } else {
        throw new Error(`Credentials file not found: ${credsPath}`);
      }
    }
    return options;
  }

  async getUser() {
    const { UserServiceClient } = require('@google-ads/admanager').v1;
    const client = new UserServiceClient(this.getClientOptions());
    try {
      const name = `networks/${this.networkCode}/users/me`;
      const me = await client.getUser({ name });
      return {
        displayName: me.displayName ?? me.name,
        email: me.email,
        id: me.name?.split('/').pop(),
        roleName: me.roleName ?? me.role,
      };
    } catch (err) {
      if (err.message?.includes('not found') || err.code === 5) {
        return {
          displayName: 'Authenticated User',
          email: '(verify with: gcloud auth application-default print-access-token)',
          id: '-',
          roleName: '-',
        };
      }
      throw err;
    }
  }

  async getOrders(limit = 10, status = null, debug = false) {
    const { OrderServiceClient } = require('@google-ads/admanager').v1;
    const client = new OrderServiceClient(this.getClientOptions());
    const parent = `networks/${this.networkCode}`;
    const now = new Date();
    const nowStr = now.toISOString();

    const request = {
      parent,
      pageSize: 500,
    };
    const statusMap = {
      delivering: ['APPROVED', 3],
      approved: ['APPROVED', 3],
      active: ['APPROVED', 3],
      draft: ['DRAFT', 1],
      pending_approval: ['PENDING_APPROVAL', 2],
      disapproved: ['DISAPPROVED', 4],
      paused: ['PAUSED', 5],
      canceled: ['CANCELED', 6],
      deleted: ['DELETED', 7],
    };
    const matchStatus = status ? statusMap[status.toLowerCase()] : null;
    const wantCurrentlyDelivering = status && ['delivering', 'approved', 'active'].includes(status.toLowerCase());

    if (matchStatus) {
      request.filter = `status = "${matchStatus[0]}"`;
    }

    function parseTime(t) {
      if (!t) return null;
      if (typeof t === 'string') return new Date(t).getTime();
      if (typeof t === 'object') {
        const sec = t.seconds ?? t._seconds;
        const nano = t.nanos ?? t._nanos ?? 0;
        if (sec !== undefined && sec !== null) return (Number(sec) || 0) * 1000 + (Number(nano) || 0) / 1e6;
      }
      return null;
    }

    const orders = [];
    const iterable = client.listOrdersAsync(request);
    const nowMs = Date.now();
    for await (const order of iterable) {
      const orderStatus = order.status ?? order.state;
      const statusStr = String(orderStatus || '');
      const statusMatch = !matchStatus ||
        orderStatus === matchStatus?.[1] ||
        statusStr.toUpperCase() === matchStatus?.[0];
      if (!statusMatch) continue;

      if (wantCurrentlyDelivering) {
        const startMs = parseTime(order.startTime ?? order.start_time);
        const endMs = parseTime(order.endTime ?? order.end_time);
        const unlimited = order.unlimitedEndTime ?? order.unlimited_end_time;
        if (debug && orders.length === 0) {
          console.error('[debug] Sample order:', {
            name: order.displayName,
            startTime: order.startTime ?? order.start_time,
            endTime: order.endTime ?? order.end_time,
            unlimitedEndTime: unlimited,
            startMs,
            endMs,
            now: new Date(nowMs).toISOString(),
          });
        }
        if (!startMs || startMs > nowMs) continue;
        if (!unlimited && (!endMs || endMs < nowMs)) continue;
        const oneYearAgo = nowMs - 365.25 * 24 * 60 * 60 * 1000;
        if (startMs < oneYearAgo) continue;
      }

      const statusNumToName = { 1: 'DRAFT', 2: 'PENDING_APPROVAL', 3: 'APPROVED', 4: 'DISAPPROVED', 5: 'PAUSED', 6: 'CANCELED', 7: 'DELETED' };
      let displayStatus = typeof orderStatus === 'number' ? (statusNumToName[orderStatus] ?? orderStatus) : statusStr;
      if (wantCurrentlyDelivering) displayStatus = 'DELIVERING';

      const startMs = parseTime(order.startTime ?? order.start_time);
      const endMs = parseTime(order.endTime ?? order.end_time);
      const unlimited = order.unlimitedEndTime ?? order.unlimited_end_time;

      orders.push({
        id: order.name?.split('/').pop(),
        name: order.displayName ?? order.name,
        status: displayStatus,
        startDate: startMs ? new Date(startMs).toISOString().slice(0, 10) : '-',
        endDate: unlimited ? 'Ongoing' : (endMs ? new Date(endMs).toISOString().slice(0, 10) : '-'),
        currency: order.currencyCode ?? '-',
        advertiserId: order.advertiser?.split('/').pop() ?? '-',
        lineItemCount: null,
      });
      if (orders.length >= limit) break;
    }

    const token = await this._getRestAccessToken();
    const orderIds = orders.map(o => o.id);
    const [lineCounts, metrics] = await Promise.all([
      token ? this._getLineItemCounts(orderIds, token) : {},
      this._getOrderMetrics(orderIds),
    ]);
    orders.forEach(o => {
      o.lineItemCount = lineCounts[o.id] ?? 0;
      o.impressions = metrics[o.id]?.impressions ?? 0;
      o.clicks = metrics[o.id]?.clicks ?? 0;
    });
    return orders;
  }

  async _getOrderMetrics(orderIds) {
    if (orderIds.length === 0) return {};
    try {
      const { ReportServiceClient } = require('@google-ads/admanager').v1;
      const client = new ReportServiceClient(this.getClientOptions());
      const parent = `networks/${this.networkCode}`;
      const report = {
        displayName: 'gam-cli-orders-metrics',
        reportDefinition: {
          dimensions: ['ORDER_ID'],
          metrics: ['AD_SERVER_IMPRESSIONS', 'AD_SERVER_CLICKS'],
          dateRange: { relative: 'LAST_90_DAYS' },
          reportType: 'HISTORICAL',
        },
        visibility: 'HIDDEN',
      };
      const [created] = await client.createReport({ parent, report });
      const reportName = created.name;
      const [operation] = await client.runReport({ name: reportName });
      const [response] = await operation.promise();
      const resultName = response.reportResult;
      if (!resultName) return {};
      const metricsMap = {};
      const iterable = client.fetchReportResultRowsAsync({ name: resultName });
      for await (const row of iterable) {
        const dims = row.dimensionValues || [];
        const orderId = dims[0]?.intValue ?? dims[0]?.stringValue ?? dims[0];
        const vals = row.metricValueGroups?.[0]?.primaryValues || [];
        const impressions = Number(vals[0]?.intValue ?? vals[0]?.stringValue ?? vals[0] ?? 0);
        const clicks = Number(vals[1]?.intValue ?? vals[1]?.stringValue ?? vals[1] ?? 0);
        if (orderId != null) metricsMap[String(orderId)] = { impressions, clicks };
      }
      return metricsMap;
    } catch (err) {
      if (process.env.GAM_DEBUG) console.warn('Order metrics (impressions/clicks):', err.message);
      return {};
    }
  }

  async _getLineItemMetrics(lineItemIds) {
    if (lineItemIds.length === 0) return {};
    try {
      const { ReportServiceClient } = require('@google-ads/admanager').v1;
      const client = new ReportServiceClient(this.getClientOptions());
      const parent = `networks/${this.networkCode}`;
      const report = {
        displayName: 'gam-cli-lineitems-metrics',
        reportDefinition: {
          dimensions: ['LINE_ITEM_ID'],
          metrics: ['AD_SERVER_IMPRESSIONS', 'AD_SERVER_CLICKS'],
          dateRange: { relative: 'LAST_90_DAYS' },
          reportType: 'HISTORICAL',
        },
        visibility: 'HIDDEN',
      };
      const [created] = await client.createReport({ parent, report });
      const reportName = created.name;
      const [operation] = await client.runReport({ name: reportName });
      const [response] = await operation.promise();
      const resultName = response.reportResult;
      if (!resultName) return {};
      const metricsMap = {};
      const iterable = client.fetchReportResultRowsAsync({ name: resultName });
      for await (const row of iterable) {
        const dims = row.dimensionValues || [];
        const lineItemId = dims[0]?.intValue ?? dims[0]?.stringValue ?? dims[0];
        const vals = row.metricValueGroups?.[0]?.primaryValues || [];
        const impressions = Number(vals[0]?.intValue ?? vals[0]?.stringValue ?? vals[0] ?? 0);
        const clicks = Number(vals[1]?.intValue ?? vals[1]?.stringValue ?? vals[1] ?? 0);
        if (lineItemId != null) metricsMap[String(lineItemId)] = { impressions, clicks };
      }
      return metricsMap;
    } catch (err) {
      if (process.env.GAM_DEBUG) console.warn('Line item metrics (impressions/clicks):', err.message);
      return {};
    }
  }

  async _getRestAccessToken() {
    const { GoogleAuth } = require('google-auth-library');
    const opts = this.getClientOptions();
    const authOpts = { scopes: ['https://www.googleapis.com/auth/admanager'] };
    if (opts.keyFilename) authOpts.keyFilename = opts.keyFilename;
    if (opts.credentials) authOpts.credentials = opts.credentials;
    const auth = new GoogleAuth(authOpts);
    const client = await auth.getClient();
    const tokenRes = await client.getAccessToken();
    return tokenRes?.token || (typeof tokenRes === 'string' ? tokenRes : null);
  }

  async _getLineItemCounts(orderIds, accessToken) {
    if (orderIds.length === 0) return {};
    const baseUrl = 'https://admanager.googleapis.com/v1';
    const parent = `networks/${this.networkCode}`;
    const totalCounts = {};
    await Promise.all(orderIds.map(async (orderId) => {
      let count = 0;
      let pageToken = null;
      do {
        const params = new URLSearchParams({
          pageSize: '1000',
          filter: `order = "networks/${this.networkCode}/orders/${orderId}"`,
        });
        if (pageToken) params.set('pageToken', pageToken);
        const res = await fetch(`${baseUrl}/${parent}/lineItems?${params}`, {
          headers: { Authorization: `Bearer ${accessToken}` },
        });
        if (!res.ok) { totalCounts[orderId] = 0; return; }
        const data = await res.json();
        count += data.lineItems?.length ?? 0;
        pageToken = data.nextPageToken || null;
      } while (pageToken);
      totalCounts[orderId] = count;
    }));
    return totalCounts;
  }

  async getLineItems(orderId = null, limit = 10) {
    const accessToken = await this._getRestAccessToken();
    if (!accessToken) throw new Error('Failed to obtain access token');
    const baseUrl = 'https://admanager.googleapis.com/v1';
    const parent = `networks/${this.networkCode}`;
    const params = new URLSearchParams({ pageSize: String(Math.min(limit, 1000)) });
    if (orderId) {
      params.set('filter', `order = "networks/${this.networkCode}/orders/${orderId}"`);
    }
    const url = `${baseUrl}/${parent}/lineItems?${params}`;
    const res = await fetch(url, {
      headers: { Authorization: `Bearer ${accessToken}` },
    });
    if (!res.ok) {
      const err = await res.text();
      throw new Error(`Ad Manager API: ${res.status} ${err}`);
    }
    const data = await res.json();
    const items = data.lineItems || [];
    const parseTime = (t) => {
      if (!t) return null;
      const ms = Date.parse(t);
      return Number.isNaN(ms) ? null : ms;
    };
    const lineItems = items.map(li => {
      const id = li.name?.split('/').pop();
      const startMs = parseTime(li.startTime);
      const endMs = parseTime(li.endTime);
      const goalUnits = li.goal?.units != null ? parseInt(li.goal.units, 10) : null;
      const goalUnitType = li.goal?.unitType ?? 'UNIT_TYPE_UNSPECIFIED';
      return {
        id,
        name: li.displayName ?? li.name,
        orderId: li.order?.split('/').pop(),
        status: li.status ?? li.state,
        lineItemType: li.lineItemType,
        startDate: startMs ? new Date(startMs).toISOString().slice(0, 10) : '-',
        endDate: endMs ? new Date(endMs).toISOString().slice(0, 10) : '-',
        goalUnits,
        goalUnitType,
      };
    });
    const lineItemIds = lineItems.map(li => li.id).filter(Boolean);
    const metrics = await this._getLineItemMetrics(lineItemIds);
    lineItems.forEach(li => {
      li.impressions = metrics[li.id]?.impressions ?? 0;
      li.clicks = metrics[li.id]?.clicks ?? 0;
      li.ctr = li.impressions > 0 ? ((li.clicks / li.impressions) * 100).toFixed(2) + '%' : '-';
      if (li.goalUnits != null && li.goalUnits > 0) {
        const delivered = li.goalUnitType === 'CLICKS' ? li.clicks : li.impressions;
        li.progress = ((delivered / li.goalUnits) * 100).toFixed(1) + '%';
      } else {
        li.progress = '-';
      }
    });
    return lineItems;
  }

  async getNetworks() {
    const { NetworkServiceClient } = require('@google-ads/admanager').v1;
    const client = new NetworkServiceClient(this.getClientOptions());
    const [response] = await client.listNetworks({});
    const networks = response.networks || [];
    return networks.map(n => ({
      networkCode: n.name?.split('/').pop() ?? n.networkCode,
      displayName: n.displayName ?? n.name,
      propertyCode: n.propertyCode,
    }));
  }

  async getCreatives(limit = 10) {
    throw new Error('Creatives not yet supported in @google-ads/admanager v1. Use the GAM UI or legacy API.');
  }

  /** Inventory presets: run-of-site (all), desktop banners, mobile banners */
  static get INVENTORY_PRESETS() {
    return {
      'run-of-site': {
        label: 'Run of site (all sites)',
        sizes: ['All'],
        sizeFilter: null,
      },
      desktop: {
        label: 'Desktop banners',
        sizes: ['970x250', '300x250', '300x600', '728x90'],
        sizeFilter: (s) => ['970x250', '300x250', '300x600', '728x90'].includes(s),
      },
      mobile: {
        label: 'Mobile banners',
        sizes: ['320x50', '320x100', '300x50', '320x480', '300x250', '728x90'],
        sizeFilter: (s) => ['320x50', '320x100', '300x50', '320x480', '300x250', '728x90'].includes(s),
      },
    };
  }

  async getInventory(preset = null, startDate = null, endDate = null) {
    const presets = GAMService.INVENTORY_PRESETS;
    const which = preset && presets[preset] ? [preset] : Object.keys(presets);
    const today = new Date();
    const start = startDate || today;
    const end = endDate || (() => { const d = new Date(today); d.setDate(d.getDate() + 30); return d; })();
    const startStr = start.toISOString().slice(0, 10);
    const endStr = end.toISOString().slice(0, 10);
    const useCustomRange = !!(startDate || endDate);
    const isFutureRange = start > new Date();
    let historicalData = null, forecastData = null, historicalErr = null, forecastErr = null;
    if (isFutureRange) {
      const f = await this._getInventoryForecast(startStr, endStr);
      forecastData = f.data;
      forecastErr = f.error;
      if (!forecastData) {
        historicalData = null;
        historicalErr = forecastErr || 'Future forecasting not available (requires Ad Manager 360)';
      }
    } else {
      const h = await this._getInventoryHistorical(startStr, endStr, useCustomRange);
      historicalData = h.data;
      historicalErr = h.error;
      if (!historicalData) {
        const f = await this._getInventoryForecast(startStr, endStr);
        forecastData = f.data;
        forecastErr = f.error;
      }
    }
    const lastError = historicalErr || forecastErr;
    const rows = [];
    for (const key of which) {
      const p = presets[key];
      const sizesStr = p.sizes.join(', ');
      if (forecastData) {
        const agg = this._aggregateForecastByPreset(forecastData, p);
        rows.push({
          preset: key,
          label: p.label,
          sizes: sizesStr,
          available: agg.available,
          forecasted: agg.forecasted,
          reserved: agg.reserved,
          str: agg.str,
          mode: 'forecast',
        });
      } else if (historicalData) {
        const agg = this._aggregateForecastByPreset(historicalData, p);
        rows.push({
          preset: key,
          label: p.label,
          sizes: sizesStr,
          available: agg.impressions ?? agg.available ?? '0',
          forecasted: '-',
          reserved: '-',
          str: '-',
          mode: 'historical',
        });
      } else {
        rows.push({
          preset: key,
          label: p.label,
          sizes: sizesStr,
          available: '-',
          forecasted: '-',
          reserved: '-',
          str: '-',
          mode: null,
        });
      }
    }
    return {
      rows,
      startStr,
      endStr,
      mode: forecastData ? 'forecast' : (historicalData ? 'historical' : null),
      error: lastError,
      isFutureRange,
    };
  }

  _parseDateForReport(dateStr) {
    const [y, m, d] = dateStr.split('-').map(Number);
    return { year: y, month: m, day: d };
  }

  async _getInventoryForecast(startStr, endStr) {
    // Try v1 Report API (FUTURE_SELL_THROUGH) first - may work for more networks
    try {
      const { ReportServiceClient } = require('@google-ads/admanager').v1;
      const client = new ReportServiceClient(this.getClientOptions());
      const parent = `networks/${this.networkCode}`;
      const report = {
        displayName: 'gam-cli-inventory-forecast',
        reportDefinition: {
          dimensions: ['REQUESTED_AD_SIZES'],
          metrics: ['AVAILABLE_IMPRESSIONS', 'FORECASTED_IMPRESSIONS', 'RESERVED_IMPRESSIONS'],
          dateRange: {
            fixed: {
              startDate: this._parseDateForReport(startStr),
              endDate: this._parseDateForReport(endStr),
            },
          },
          reportType: 'FUTURE_SELL_THROUGH',
        },
        visibility: 'HIDDEN',
      };
      const [created] = await client.createReport({ parent, report });
      const reportName = created.name;
      const [operation] = await client.runReport({ name: reportName });
      const [response] = await operation.promise();
      const resultName = response.reportResult;
      if (!resultName) return { data: null, error: 'Report run returned no result' };
      const bySize = {};
      const iterable = client.fetchReportResultRowsAsync({ name: resultName });
      for await (const row of iterable) {
        const dims = row.dimensionValues || [];
        const sizeVal = dims[0]?.stringValue ?? dims[0]?.intValue ?? dims[0];
        const vals = row.metricValueGroups?.[0]?.primaryValues || [];
        const available = Number(vals[0]?.intValue ?? vals[0]?.stringValue ?? vals[0] ?? 0);
        const forecasted = Number(vals[1]?.intValue ?? vals[1]?.stringValue ?? vals[1] ?? 0);
        const reserved = Number(vals[2]?.intValue ?? vals[2]?.stringValue ?? vals[2] ?? 0);
        if (sizeVal != null) {
          const s = String(sizeVal).replace(/\s/g, '');
          if (!bySize[s]) bySize[s] = { available: 0, forecasted: 0, reserved: 0 };
          bySize[s].available += available;
          bySize[s].forecasted += forecasted;
          bySize[s].reserved += reserved;
        }
      }
      return { data: bySize, error: null };
    } catch (v1Err) {
      // Fallback to SOAP getTrafficData (Ad Manager 360 only)
      const soapResult = await this._getTrafficDataSoap(startStr, endStr);
      if (soapResult.data != null) return soapResult;
      return { data: null, error: v1Err?.message || soapResult.error || String(v1Err) };
    }
  }

  async _getTrafficDataSoap(startStr, endStr) {
    try {
      const { getRootAdUnitId, getTrafficData } = require('./soap_forecast');
      const accessToken = await this._getRestAccessToken();
      if (!accessToken) return { data: null, error: 'No access token' };
      let v1RootId = null;
      try {
        const { AdUnitServiceClient } = require('@google-ads/admanager').v1;
        const client = new AdUnitServiceClient(this.getClientOptions());
        const [r] = await client.listAdUnits({
          parent: `networks/${this.networkCode}`,
          pageSize: 100,
        });
        const root = (r.adUnits || []).find(u => !(u.parentPath || u.parent_path || []).length);
        if (root) v1RootId = String(root.adUnitId ?? root.ad_unit_id ?? root.name?.split('/').pop() ?? '');
      } catch (_) {}
      const rootId = await getRootAdUnitId(this.networkCode, accessToken, v1RootId || undefined);
      if (!rootId) return { data: null, error: 'Could not get root ad unit' };
      const total = await getTrafficData(this.networkCode, rootId, startStr, endStr, accessToken);
      const bySize = { _total: { forecasted: total, available: total, reserved: 0 } };
      return { data: bySize, error: null };
    } catch (err) {
      return { data: null, error: err?.message || String(err) };
    }
  }

  async _getInventoryHistorical(startStr, endStr, useFixedRange = true) {
    try {
      const { ReportServiceClient } = require('@google-ads/admanager').v1;
      const client = new ReportServiceClient(this.getClientOptions());
      const parent = `networks/${this.networkCode}`;
      const dateRange = useFixedRange
        ? {
            fixed: {
              startDate: this._parseDateForReport(startStr),
              endDate: this._parseDateForReport(endStr),
            },
          }
        : { relative: 'LAST_30_DAYS' };
      const report = {
        displayName: 'gam-cli-inventory-historical',
        reportDefinition: {
          dimensions: ['REQUESTED_AD_SIZES'],
          metrics: ['AD_SERVER_IMPRESSIONS'],
          dateRange,
          reportType: 'HISTORICAL',
        },
        visibility: 'HIDDEN',
      };
      const [created] = await client.createReport({ parent, report });
      const reportName = created.name;
      const [operation] = await client.runReport({ name: reportName });
      const [response] = await operation.promise();
      const resultName = response.reportResult;
      if (!resultName) return { data: null, error: 'Report run returned no result' };
      const bySize = {};
      const iterable = client.fetchReportResultRowsAsync({ name: resultName });
      for await (const row of iterable) {
        const dims = row.dimensionValues || [];
        const sizeVal = dims[0]?.stringValue ?? dims[0]?.intValue ?? dims[0];
        const vals = row.metricValueGroups?.[0]?.primaryValues || [];
        const impressions = Number(vals[0]?.intValue ?? vals[0]?.stringValue ?? vals[0] ?? 0);
        if (sizeVal != null) {
          const s = String(sizeVal).replace(/\s/g, '');
          if (!bySize[s]) bySize[s] = { impressions: 0 };
          bySize[s].impressions += impressions;
        }
      }
      return { data: bySize, error: null };
    } catch (err) {
      return { data: null, error: err?.message || String(err) };
    }
  }

  _aggregateForecastByPreset(bySize, preset) {
    if (bySize._total) {
      const t = bySize._total;
      return {
        available: (t.available ?? t.forecasted ?? 0).toLocaleString(),
        forecasted: (t.forecasted ?? 0).toLocaleString(),
        reserved: (t.reserved ?? 0).toLocaleString(),
        str: t.forecasted > 0 ? (((t.reserved ?? 0) / t.forecasted) * 100).toFixed(1) + '%' : '-',
        impressions: (t.forecasted ?? t.available ?? 0).toLocaleString(),
      };
    }
    let available = 0, forecasted = 0, reserved = 0, impressions = 0;
    let hasImpressionData = false;
    for (const [size, data] of Object.entries(bySize)) {
      const norm = size.replace(/\s/g, '');
      const include = preset.sizeFilter === null || preset.sizeFilter(norm);
      if (include) {
        if (data.impressions != null) {
          impressions += data.impressions;
          hasImpressionData = true;
        } else {
          available += data.available ?? 0;
          forecasted += data.forecasted ?? 0;
          reserved += data.reserved ?? 0;
        }
      }
    }
    if (hasImpressionData) {
      return { impressions: impressions.toLocaleString() };
    }
    const str = forecasted > 0 ? ((reserved / forecasted) * 100).toFixed(1) + '%' : '-';
    return {
      available: available.toLocaleString(),
      forecasted: forecasted.toLocaleString(),
      reserved: reserved.toLocaleString(),
      str,
      impressions: impressions.toLocaleString(),
    };
  }

  async _getAdUnitsAndSizes(limit) {
    try {
      const { AdUnitServiceClient } = require('@google-ads/admanager').v1;
      const client = new AdUnitServiceClient(this.getClientOptions());
      const parent = `networks/${this.networkCode}`;
      const all = [];
      let token = null;
      do {
        const [response] = await client.listAdUnits({
          parent,
          pageSize: Math.min(100, limit - all.length),
          pageToken: token,
        });
        const units = response.adUnits || [];
        for (const u of units) {
          const sz = u.adUnitSizes || u.ad_unit_sizes || [];
          const sizes = sz.map(s => {
            const sizeObj = s.size ?? s;
            const w = sizeObj?.width;
            const h = sizeObj?.height;
            return w != null && h != null ? `${w}x${h}` : null;
          }).filter(Boolean);
          all.push({ name: u.displayName ?? u.name, sizes });
        }
        token = response.nextPageToken || null;
      } while (token && all.length < limit);
      return all;
    } catch (err) {
      if (process.env.GAM_DEBUG) console.warn('Ad units list:', err.message);
      return null;
    }
  }

  _countAdUnitsForPreset(adUnits, preset) {
    if (preset.sizeFilter === null) return adUnits.length;
    let count = 0;
    for (const u of adUnits) {
      for (const s of u.sizes) {
        if (preset.sizeFilter(s)) {
          count++;
          break;
        }
      }
    }
    return count;
  }
}

function parseDate(str) {
  if (!str || typeof str !== 'string') return null;
  const s = str.trim();
  if (/^\d{8}$/.test(s)) {
    const dd = parseInt(s.slice(0, 2), 10);
    const mm = parseInt(s.slice(2, 4), 10) - 1;
    const yyyy = parseInt(s.slice(4, 8), 10);
    const d = new Date(yyyy, mm, dd);
    return isNaN(d.getTime()) ? null : d;
  }
  if (/^\d{4}-\d{2}-\d{2}$/.test(s)) {
    const d = new Date(s);
    return isNaN(d.getTime()) ? null : d;
  }
  const d = new Date(s);
  return isNaN(d.getTime()) ? null : d;
}

function formatJson(data) {
  console.log(JSON.stringify(data, null, 2));
}

function formatTable(headers, rows) {
  const colWidths = headers.map((h, i) => 
    Math.max(h.length, ...rows.map(r => String(r[i] || 'N/A').slice(0, 50).length))
  );
  
  const headerLine = headers.map((h, i) => h.padEnd(colWidths[i])).join('  ');
  console.log(headerLine);
  console.log('-'.repeat(headerLine.length));
  
  rows.forEach(row => {
    console.log(row.map((v, i) => String(v || 'N/A').slice(0, colWidths[i]).padEnd(colWidths[i])).join('  '));
  });
}

async function main() {
  const args = process.argv.slice(2);
  
  if (args.length === 0) {
    console.log(`
GAM CLI - Google Ad Manager Command Line Tool

Usage:
  gam init <config.yaml>     Initialize with GAM config file
  gam user                  Show current user info
  gam orders                List orders
  gam line-items            List line items
  gam inventory             Show available inventory (by preset)
  gam networks              List available networks
  gam creatives             List creatives

Options:
  --config, -c <path>       Config file path (default: ~/.gam-cli/config.yaml)
  --limit, -l <num>         Limit number of results
  --order-id <id>           Filter by order ID (for line-items)
  --preset <name>           Inventory preset: run-of-site, desktop, mobile
  --start <date>            Start date (DDMMYYYY or YYYY-MM-DD, default: today)
  --end <date>              End date (DDMMYYYY or YYYY-MM-DD, default: today+30)
  --status <status>         Filter by status (for orders)
  --json                    Output as JSON
  --debug                   Show debug info (for troubleshooting)

Examples:
  gam init gam.yaml
  gam user
  gam orders --limit 20
  gam line-items --order-id 12345
  gam inventory --preset desktop --start 12022026 --end 30062026
  gam networks
  gam creatives --json
`);
    process.exit(0);
  }

  const command = args[0];
  
  if (command === 'init') {
    const configPath = args[1];
    if (!configPath) {
      console.error('Error: Config path required');
      console.error('Usage: gam init <path-to-gam.yaml>');
      process.exit(1);
    }
    await initGAM(configPath);
    process.exit(0);
  }

  // Parse common options
  let limit = 10;
  let orderId = null;
  let preset = null;
  let startDate = null;
  let endDate = null;
  let status = null;
  let json = false;
  
  let debug = false;
  for (let i = 1; i < args.length; i++) {
    if (args[i] === '--limit' || args[i] === '-l') {
      limit = parseInt(args[++i], 10);
    } else if (args[i] === '--order-id') {
      orderId = args[++i];
    } else if (args[i] === '--preset') {
      preset = args[++i];
    } else if (args[i] === '--start') {
      startDate = parseDate(args[++i]);
    } else if (args[i] === '--end') {
      endDate = parseDate(args[++i]);
    } else if (args[i] === '--status') {
      status = args[++i];
    } else if (args[i] === '--json') {
      json = true;
    } else if (args[i] === '--debug') {
      debug = true;
    }
  }

  try {
    const gam = new GAMService();
    
    if (command === 'user') {
      const user = await gam.getUser();
      if (json) {
        formatJson(user);
      } else {
        console.log('\n=== GAM Connection Info ===\n');
        console.log(`User: ${user.displayName}`);
        console.log(`Email: ${user.email}`);
        console.log(`User ID: ${user.id}`);
        console.log(`Role: ${user.roleName}`);
      }
    } 
    else if (command === 'orders') {
      const orders = await gam.getOrders(limit, status, debug);
      if (json) {
        formatJson(orders);
      } else {
        console.log(`\n=== Orders (all orders in network, showing ${orders.length}) ===\n`);
        if (orders.length === 0) {
          console.log('No orders found in this network.');
        } else {
          formatTable(
            ['ID', 'Name', 'Status', 'Start', 'End', 'Impressions', 'Clicks', 'Line Items', 'Currency'],
            orders.map(o => [
              o.id,
              o.name?.slice(0, 25),
              o.status,
              o.startDate ?? '-',
              o.endDate ?? '-',
              (o.impressions ?? 0).toLocaleString(),
              (o.clicks ?? 0).toLocaleString(),
              o.lineItemCount ?? '-',
              o.currency ?? '-',
            ])
          );
        }
      }
    }
    else if (command === 'line-items') {
      const lineItems = await gam.getLineItems(orderId, limit);
      if (json) {
        formatJson(lineItems);
      } else {
        console.log(`\n=== Line Items (showing ${lineItems.length}) ===\n`);
        formatTable(
          ['ID', 'Name', 'Order ID', 'Status', 'Start', 'End', 'Impressions', 'Clicks', 'Progress', 'CTR'],
          lineItems.map(li => [
            li.id,
            li.name?.slice(0, 28),
            li.orderId,
            li.status,
            li.startDate ?? '-',
            li.endDate ?? '-',
            (li.impressions ?? 0).toLocaleString(),
            (li.clicks ?? 0).toLocaleString(),
            li.progress ?? '-',
            li.ctr ?? '-',
          ])
        );
      }
    }
    else if (command === 'inventory') {
      const inv = await gam.getInventory(preset, startDate, endDate);
      if (json) {
        formatJson(inv);
      } else {
        const rangeStr = `${inv.startStr} to ${inv.endStr}`;
        if (inv.isFutureRange && !inv.mode) {
          console.log(`\n=== Inventory (${rangeStr}) ===`);
          if (inv.error) {
            const err = String(inv.error);
            if (/UNSUPPORTED_OPERATION/i.test(err)) {
              console.log('\ngetTrafficData is only available for Ad Manager 360 networks.');
            } else {
              console.log('\n' + inv.error);
            }
          }
          console.log('\nNote: For future forecasting, use Ad Manager 360 or run Future sell-through report in the UI (Inventory > Reports).\n');
        } else {
          console.log(`\n=== Inventory Impressions (${rangeStr}) ===\n`);
          if (inv.rows.length === 0) {
            console.log('No inventory data.');
          } else {
          const headers = inv.mode === 'forecast'
            ? ['Preset', 'Sizes', 'Available', 'Forecasted', 'Reserved', 'STR%']
            : ['Preset', 'Sizes', 'Impressions'];
          const rows = inv.rows.map(r =>
            inv.mode === 'forecast'
              ? [r.preset, r.sizes?.slice(0, 40), r.available, r.forecasted, r.reserved, r.str]
              : [r.preset, r.sizes?.slice(0, 40), r.available]
          );
          formatTable(headers, rows);
          }
        }
        if (!inv.mode && inv.error && !inv.isFutureRange) {
          const errStr = typeof inv.error === 'string' ? inv.error : inv.error?.message || JSON.stringify(inv.error);
          const shortErr = errStr.length > 200 ? errStr.slice(0, 200) + '...' : errStr;
          console.log('\nReport error:', shortErr);
          console.log('Try: gam inventory --start 01012025 --end 23022025 (past date range for historical)');
        }
      }
    }
    else if (command === 'networks') {
      const networks = await gam.getNetworks();
      if (json) {
        formatJson(networks);
      } else {
        console.log('\n=== Available Networks ===\n');
        networks.forEach(n => {
          console.log(`Network Code: ${n.networkCode}`);
          console.log(`Display Name: ${n.displayName}`);
          console.log(`Property Code: ${n.propertyCode}`);
          console.log();
        });
      }
    }
    else if (command === 'creatives') {
      const creatives = await gam.getCreatives(limit);
      if (json) {
        formatJson(creatives);
      } else {
        console.log(`\n=== Creatives (showing ${creatives.length}) ===\n`);
        formatTable(
          ['ID', 'Name', 'Advertiser ID'],
          creatives.map(c => [c.id, c.name?.slice(0, 40), c.advertiserId])
        );
      }
    }
    else {
      console.error(`Unknown command: ${command}`);
      console.error('Run "gam" without args to see available commands');
      process.exit(1);
    }
  } catch (error) {
    exitWithLoggedError(error, `gam ${command}`);
  }
}

main();
