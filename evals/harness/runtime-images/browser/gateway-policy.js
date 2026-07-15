'use strict';
const dns = require('dns').promises;
const http = require('http');
const requestPolicy = require('./request-policy');

const slug = process.argv[2];
const profile = process.argv[3];
const postId = Number(process.argv[4]);
const policyContext = {origin: requestPolicy.ORIGIN, slug, profile, postId};
if (require.main === module && !requestPolicy.validContext(policyContext)) {
  throw new Error('gateway requires an exact request context');
}

function requestClass(request) {
  return requestPolicy.classifyRequest({
    url: request.url, method: request.method, headers: request.headers,
  }, policyContext);
}

function responseCeiling(request) {
  return requestPolicy.responseByteCeiling({
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

function upstreamHeaders(request, kind) {
  const headers = {host: 'gateway-frontend:8081', connection: 'close'};
  if (request.headers.cookie) headers.cookie = request.headers.cookie;
  if (request.method === 'POST') {
    headers['content-type'] = request.headers['content-type'];
    headers['content-length'] = request.headers['content-length'];
  }
  if (kind === 'json-write') {
    headers['x-http-method-override'] = request.headers['x-http-method-override'];
  }
  if (request.headers['x-wp-nonce']) headers['x-wp-nonce'] = request.headers['x-wp-nonce'];
  return headers;
}

function forward(request, response) {
  const kind = requestClass(request);
  const ceiling = responseCeiling(request);
  if (!kind || !ceiling) { reject(response); return; }
  const upstream = http.request({hostname: 'wordpress-application', port: 8080,
    method: request.method, path: request.url, headers: upstreamHeaders(request, kind)}, incoming => {
    let bytes = 0; const headers = {...incoming.headers};
    if (headers['content-length'] !== undefined) {
      const declared = Number(headers['content-length']);
      if (!Number.isSafeInteger(declared) || declared < 0 || declared > ceiling) {
        incoming.destroy(); reject(response); return;
      }
    }
    if (headers.location) {
      const target = new URL(headers.location, requestPolicy.ORIGIN);
      if (target.origin !== requestPolicy.ORIGIN) { incoming.destroy(); reject(response); return; }
      headers.location = `${target.pathname}${target.search}`;
    }
    response.writeHead(incoming.statusCode || 502, headers);
    incoming.on('data', chunk => {
      const next = requestPolicy.nextResponseByteCount(bytes, chunk.length, ceiling);
      if (next === null) { incoming.destroy(); response.destroy(); }
      else { bytes = next; response.write(chunk); }
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

if (require.main === module) {
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
}

module.exports = Object.freeze({upstreamHeaders});
