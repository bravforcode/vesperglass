import { proxyToBackend } from './_proxy.js';

export default function handler(req, res) {
  return proxyToBackend('/api/screen', req, res);
}
