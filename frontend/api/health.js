import { proxyToBackend } from './_proxy.js';

export default function handler(req, res) {
  return proxyToBackend('/health', req, res);
}
