const BACKEND_BASE = process.env.BACKEND_URL || 'https://stocknomist.168-222-27-36.sslip.io';
const BACKEND_AUTH = process.env.BACKEND_AUTH || 'Basic YWRtaW46c3RvY2tub21pc3QyMDI2';

export async function proxyToBackend(path, req, res) {
  if (req.method === 'OPTIONS') {
    res.setHeader('Access-Control-Allow-Origin', '*');
    res.setHeader('Access-Control-Allow-Methods', 'GET, POST, OPTIONS');
    res.setHeader('Access-Control-Allow-Headers', 'Content-Type, Authorization');
    return res.status(200).end();
  }

  const queryIdx = (req.url || '').indexOf('?');
  const queryStr = queryIdx !== -1 ? req.url.slice(queryIdx) : '';
  const targetUrl = `${BACKEND_BASE}${path}${queryStr}`;

  try {
    const headers = {
      'Authorization': BACKEND_AUTH,
      'Accept': 'application/json',
    };
    if (req.headers['content-type']) {
      headers['Content-Type'] = req.headers['content-type'];
    }

    const options = {
      method: req.method || 'GET',
      headers,
    };

    if (req.method !== 'GET' && req.method !== 'HEAD' && req.body) {
      options.body = typeof req.body === 'string' ? req.body : JSON.stringify(req.body);
    }

    const upstream = await fetch(targetUrl, options);
    const contentType = upstream.headers.get('content-type') || 'application/json';
    const body = await upstream.text();

    res.setHeader('Content-Type', contentType);
    res.setHeader('Access-Control-Allow-Origin', '*');
    res.setHeader('Access-Control-Allow-Methods', 'GET, POST, OPTIONS');
    res.setHeader('Access-Control-Allow-Headers', 'Content-Type, Authorization');
    res.setHeader('Cache-Control', 'public, s-maxage=30, stale-while-revalidate=60');
    return res.status(upstream.status).send(body);
  } catch (err) {
    return res.status(502).json({
      error: 'Upstream VPS connection error',
      details: err.message,
      targetUrl,
    });
  }
}
