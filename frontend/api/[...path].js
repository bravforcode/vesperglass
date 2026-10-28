import { proxyToBackend } from './_proxy.js';

export default function handler(req, res) {
  const p = Array.isArray(req.query.path) ? req.query.path.join('/') : (req.query.path || '');
  return proxyToBackend(`/api/${p}`, req, res);
}
