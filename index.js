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
    const config = yaml.load(fs.readFileSync(configPath, 'utf-8'));
    ensureConfigDir();

    // Validate required fields
    if (!config.ad_manager) {
      throw new Error('Invalid config: missing "ad_manager" section');
    }
    if (!config.ad_manager.network_code) {
      throw new Error('Invalid config: missing "ad_manager.network_code"');
    }

    fs.writeFileSync(CONFIG_FILE, fs.readFileSync(configPath, 'utf-8'));

    console.log('Configuration saved!');
    console.log(`Network Code: ${config.ad_manager.network_code}`);
  } catch (error) {
    exitWithLoggedError(error, 'initGAM');
  }
}

class GAMService {
  constructor() {
    this.config = loadConfig();
  }

  getAdManagerClient() {
    const { AdManager } = require('@google-ads/admanager');
    
    const adManagerConfig = this.config.ad_manager;
    
    return new AdManager({
      applicationName: adManagerConfig.application_name || 'gam-cli',
      networkCode: adManagerConfig.network_code,
      credentials: adManagerConfig.path_to_private_key_file 
        ? JSON.parse(fs.readFileSync(adManagerConfig.path_to_private_key_file, 'utf-8'))
        : undefined,
    });
  }

  async getUser() {
    const client = this.getAdManagerClient();
    const { UserService } = require('@google-ads/admanager').v1;
    
    const userService = new UserService({ client });
    const me = await userService.getCurrentUser();
    
    return {
      displayName: me.displayName,
      email: me.email,
      id: me.id,
      roleName: me.roleName,
    };
  }

  async getOrders(limit = 10, status = null) {
    const client = this.getAdManagerClient();
    const { OrderService } = require('@google-ads/admanager').v1;
    
    const orderService = new OrderService({ client });
    
    let query = 'id > 0';
    if (status) {
      query += ` AND status = '${status}'`;
    }
    
    const orders = await orderService.getOrdersByStatement({
      query,
      orderBy: 'id DESC',
      limit,
    });
    
    return (orders.results || []).map(o => ({
      id: o.id,
      name: o.name,
      status: o.status,
      advertiserId: o.advertiserId,
      startDateTime: o.startDateTime?.date ? `${o.startDateTime.date.year}-${String(o.startDateTime.date.month).padStart(2,'0')}-${String(o.startDateTime.date.day).padStart(2,'0')}` : null,
      endDateTime: o.endDateTime?.date ? `${o.endDateTime.date.year}-${String(o.endDateTime.date.month).padStart(2,'0')}-${String(o.endDateTime.date.day).padStart(2,'0')}` : null,
    }));
  }

  async getLineItems(orderId = null, limit = 10) {
    const client = this.getAdManagerClient();
    const { LineItemService } = require('@google-ads/admanager').v1;
    
    const lineItemService = new LineItemService({ client });
    
    let query = 'id > 0';
    if (orderId) {
      query += ` AND orderId = ${orderId}`;
    }
    
    const lineItems = await lineItemService.getLineItemsByStatement({
      query,
      orderBy: 'id DESC',
      limit,
    });
    
    return (lineItems.results || []).map(li => ({
      id: li.id,
      name: li.name,
      orderId: li.orderId,
      status: li.status,
      lineItemType: li.lineItemType,
    }));
  }

  async getNetworks() {
    const client = this.getAdManagerClient();
    const { NetworkService } = require('@google-ads/admanager').v1;
    
    const networkService = new NetworkService({ client });
    const networks = await networkService.getAllNetworks();
    
    return (networks || []).map(n => ({
      networkCode: n.networkCode,
      displayName: n.displayName,
      propertyCode: n.propertyCode,
    }));
  }

  async getCreatives(limit = 10) {
    const client = this.getAdManagerClient();
    const { CreativeService } = require('@google-ads/admanager').v1;
    
    const creativeService = new CreativeService({ client });
    
    const creatives = await creativeService.getCreativesByStatement({
      query: 'id > 0',
      orderBy: 'id DESC',
      limit,
    });
    
    return (creatives.results || []).map(c => ({
      id: c.id,
      name: c.name,
      advertiserId: c.advertiserId,
    }));
  }
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
  gam networks              List available networks
  gam creatives             List creatives

Options:
  --config, -c <path>       Config file path (default: ~/.gam-cli/config.yaml)
  --limit, -l <num>         Limit number of results
  --order-id <id>           Filter by order ID (for line-items)
  --status <status>         Filter by status (for orders)
  --json                    Output as JSON

Examples:
  gam init gam.yaml
  gam user
  gam orders --limit 20
  gam line-items --order-id 12345
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
  let status = null;
  let json = false;
  
  for (let i = 1; i < args.length; i++) {
    if (args[i] === '--limit' || args[i] === '-l') {
      limit = parseInt(args[++i], 10);
    } else if (args[i] === '--order-id') {
      orderId = args[++i];
    } else if (args[i] === '--status') {
      status = args[++i];
    } else if (args[i] === '--json') {
      json = true;
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
      const orders = await gam.getOrders(limit, status);
      if (json) {
        formatJson(orders);
      } else {
        console.log(`\n=== Orders (showing ${orders.length}) ===\n`);
        formatTable(
          ['ID', 'Name', 'Status'],
          orders.map(o => [o.id, o.name?.slice(0, 40), o.status])
        );
      }
    }
    else if (command === 'line-items') {
      const lineItems = await gam.getLineItems(orderId, limit);
      if (json) {
        formatJson(lineItems);
      } else {
        console.log(`\n=== Line Items (showing ${lineItems.length}) ===\n`);
        formatTable(
          ['ID', 'Name', 'Order ID', 'Status'],
          lineItems.map(li => [li.id, li.name?.slice(0, 35), li.orderId, li.status])
        );
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
