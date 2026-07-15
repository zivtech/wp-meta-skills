'use strict';
const dns = require('dns').promises;
const http = require('http');
const requestPolicy = require('./request-policy');

const slug = process.argv[2];
const profile = process.argv[3];
const postId = Number(process.argv[4]);
const policyContext = {origin: requestPolicy.ORIGIN, slug, profile, postId};
if (!requestPolicy.validContext(policyContext)) throw new Error('gateway requires an exact request context');

function requestClass(request) {
  return requestPolicy.classifyRequest({
    url: request.url, method: request.method, headers: request.headers,
  }, policyContext);
}

function reject(response, upstream) {
  if (upstream) upstream.destroy();
  if (!response.headersSent) response.writeHead(403, {'content-type': 'text/plain'});
  response.end('blocked');
}

function boundedBody(request, response, upstream, kind) {
  const length = Number(request.headers['content-length'] || 0);
  const ceiling = kind === 'login' ? 8192 : 65536;
  if (!Number.isSafeInteger(length) || length < 1 || length > ceiling) {
    reject(response, upstream); return;
  }
  const chunks = []; let bytes = 0; let rejected = false;
  request.on('data', chunk => {
    if (rejected) return;
    bytes += chunk.length;
    if (bytes > ceiling) { rejected = true; reject(response, upstream); }
    else chunks.push(chunk);
  });
  request.on('end', () => {
    if (rejected || upstream.destroyed) return;
    const body = Buffer.concat(chunks);
    if (body.length !== length || !requestPolicy.validateBody(kind, body, policyContext)) {
      reject(response, upstream); return;
    }
    upstream.end(body);
  });
  request.on('error', () => { if (!rejected) reject(response, upstream); });
}

function upstreamHeaders(request) {
  const headers = {host: 'gateway-frontend:8081', connection: 'close'};
  if (request.headers.cookie) headers.cookie = request.headers.cookie;
  if (['POST', 'PUT'].includes(request.method)) {
    headers['content-type'] = request.headers['content-type'];
    headers['content-length'] = request.headers['content-length'];
  }
  if (request.headers['x-wp-nonce']) headers['x-wp-nonce'] = request.headers['x-wp-nonce'];
  return headers;
}

function forward(request, response) {
  const kind = requestClass(request);
  if (!kind) { reject(response); return; }
  const upstream = http.request({hostname: 'wordpress-application', port: 8080,
    method: request.method, path: request.url, headers: upstreamHeaders(request)}, incoming => {
    let bytes = 0; const headers = {...incoming.headers};
    if (headers.location) {
      const target = new URL(headers.location, requestPolicy.ORIGIN);
      if (target.origin !== requestPolicy.ORIGIN) { incoming.destroy(); reject(response); return; }
      headers.location = `${target.pathname}${target.search}`;
    }
    response.writeHead(incoming.statusCode || 502, headers);
    incoming.on('data', chunk => {
      bytes += chunk.length;
      if (bytes > 1024 * 1024) { incoming.destroy(); response.destroy(); }
      else response.write(chunk);
    });
    incoming.on('end', () => response.end());
    incoming.on('error', () => response.destroy());
  });
  upstream.setTimeout(5000, () => upstream.destroy());
  upstream.on('error', () => {
    if (!response.headersSent) response.writeHead(502, {'content-type': 'text/plain'});
    response.end('unavailable');
  });
  if (kind === 'read') upstream.end();
  else boundedBody(request, response, upstream, kind);
}

(async () => {
  const {address} = await dns.lookup('gateway-frontend', {family: 4});
  const server = http.createServer(forward);
  server.requestTimeout = 10000;
  server.headersTimeout = 5000;
  server.maxRequestsPerSocket = 100;
  server.listen(8081, address);
})().catch(error => {
  process.stderr.write(`${String(error && error.message || error).slice(0, 500)}\n`);
  process.exit(1);
});
