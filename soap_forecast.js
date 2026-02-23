/**
 * Ad Manager SOAP API - ForecastService getTrafficData
 * For future forecasting (v1 API does not support FUTURE_SELL_THROUGH)
 * @see https://developers.google.com/ad-manager/api/forecasting
 */

const version = 'v202511';
const baseUrl = `https://ads.google.com/apis/ads/publisher/${version}`;

async function soapPost(url, envelope, accessToken) {
  const res = await fetch(url, {
    method: 'POST',
    headers: {
      'Content-Type': 'text/xml; charset=utf-8',
      'Authorization': `Bearer ${accessToken}`,
    },
    body: envelope,
  });
  const text = await res.text();
  if (!res.ok) throw new Error(`SOAP ${res.status}: ${text.slice(0, 300)}`);
  return text;
}

async function getRootAdUnitId(networkCode, accessToken, v1RootId = null) {
  if (v1RootId) return String(v1RootId);
  const ns = 'https://www.google.com/apis/ads/publisher/v202511';
  const envelope = `<?xml version="1.0" encoding="UTF-8"?>
<soapenv:Envelope xmlns:soapenv="http://schemas.xmlsoap.org/soap/envelope/" xmlns:ns1="${ns}">
  <soapenv:Header>
    <ns1:RequestHeader soapenv:mustUnderstand="0">
      <ns1:networkCode>${networkCode}</ns1:networkCode>
      <ns1:applicationName>gam-cli/1.0</ns1:applicationName>
    </ns1:RequestHeader>
  </soapenv:Header>
  <soapenv:Body>
    <ns1:getAdUnitsByStatement>
      <ns1:filterStatement><ns1:query>WHERE parentId IS NULL LIMIT 1</ns1:query></ns1:filterStatement>
    </ns1:getAdUnitsByStatement>
  </soapenv:Body>
</soapenv:Envelope>`;
  const xml = await soapPost(`${baseUrl}/InventoryService`, envelope, accessToken);
  if (/faultstring|soap:Fault/i.test(xml)) {
    const m = xml.match(/<faultstring[^>]*>([^<]+)<\/faultstring>/i) || xml.match(/<soap:Text[^>]*>([^<]+)/i);
    throw new Error(m ? m[1].trim() : 'SOAP fault');
  }
  const idMatch = xml.match(/<ns1:id>(\d+)<\/ns1:id>|<id>(\d+)<\/id>/);
  return idMatch ? (idMatch[1] || idMatch[2]) : null;
}

async function getTrafficData(networkCode, rootAdUnitId, startStr, endStr, accessToken) {
  const [sy, sm, sd] = startStr.split('-').map(Number);
  const [ey, em, ed] = endStr.split('-').map(Number);
  const ns = 'https://www.google.com/apis/ads/publisher/v202511';

  const soap = require('strong-soap').soap;
  const BearerSecurity = require('strong-soap').BearerSecurity;
  const soapClient = await new Promise((res, rej) => {
    soap.createClient(`${baseUrl}/ForecastService?wsdl`, { endpoint: `${baseUrl}/ForecastService` }, (err, c) =>
      err ? rej(err) : res(c)
    );
  });
  soapClient.setSecurity(new BearerSecurity(accessToken));
  soapClient.addSoapHeader(
    { networkCode, applicationName: 'gam-cli/1.0' },
    { nsURI: ns, name: 'RequestHeader' }
  );

  const result = await new Promise((resolve, reject) => {
    soapClient.getTrafficData(
      {
        trafficDataRequest: {
          targeting: {
            inventoryTargeting: {
              targetedAdUnits: [{ adUnitId: rootAdUnitId, includeDescendants: true }],
            },
          },
          requestedDateRange: {
            startDate: { year: sy, month: sm, day: sd },
            endDate: { year: ey, month: em, day: ed },
          },
        },
      },
      (err, data) => (err ? reject(err) : resolve(data))
    );
  });

  const series = result?.rval?.forecastedTimeSeries;
  if (!series?.values) return 0;
  const vals = Array.isArray(series.values) ? series.values : [series.values];
  return vals.reduce((a, b) => a + (Number(b) || 0), 0);
}

module.exports = { getRootAdUnitId, getTrafficData };
