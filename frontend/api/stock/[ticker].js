import { proxyToBackend } from '../_proxy.js';

export default function handler(req, res) {
  const { ticker } = req.query;
  return proxyToBackend(`/api/stock/${ticker}`, req, res);
}
