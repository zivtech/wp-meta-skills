'use strict';

const dns = require('dns').promises;
const http = require('http');

const slug = process.argv[2];
if (!/^[a-z0-9](?:[a-z0-9-]{0,46}[a-z0-9])?$/.test(slug || '')) {
  throw new Error('gateway requires an exact plugin slug');
}

const allowedPrefixes = [
  '/wp-includes/',
  `/wp-content/plugins/${slug}/`,
  '/wp-content/themes/',
  '/wp-admin/',
];
const restCanary = '/wp-runtime-canary/v1/output';

function allowed(request) {
  const url = new URL(request.url, 'http://gateway-frontend:8081');
  const path = url.pathname;
  if (request.method === 'POST') return path === '/wp-login.php';
  if (!['GET', 'HEAD'].includes(request.method)) return false;
  const rootAllowed = path === '/' && (url.search === ''
    || (url.searchParams.size === 1 && url.searchParams.get('rest_route') === restCanary));
  return rootAllowed || path === '/wp-login.php'
    || allowedPrefixes.some(prefix => path.startsWith(prefix));
}

function boundedLogin(request, response, upstream) {
  const contentType = String(request.headers['content-type'] || '');
  const length = Number(request.headers['content-length'] || 0);
  if (!contentType.startsWith('application/x-www-form-urlencoded')
      || !Number.isSafeInteger(length) || length < 1 || length > 8192) {
    response.writeHead(413, {'content-type': 'text/plain'});
    response.end('blocked');
    upstream.destroy();
    return false;
  }
  request.pipe(upstream);
  return true;
}

function upstreamHeaders(request) {
  const headers = {host: 'gateway-frontend:8081', connection: 'close'};
  if (request.headers.cookie) headers.cookie = request.headers.cookie;
  if (request.method === 'POST') {
    headers['content-type'] = request.headers['content-type'];
    headers['content-length'] = request.headers['content-length'];
  }
  return headers;
}

function forward(request, response) {
  if (!allowed(request)) {
    response.writeHead(403, {'content-type': 'text/plain'});
    response.end('blocked');
    return;
  }
  const upstream = http.request({
    hostname: 'wordpress-application', port: 8080, method: request.method, path: request.url,
    headers: upstreamHeaders(request),
  }, incoming => {
    let bytes = 0;
    const headers = {...incoming.headers};
    if (headers.location) {
      const target = new URL(headers.location, 'http://gateway-frontend:8081');
      if (target.origin !== 'http://gateway-frontend:8081') {
        incoming.destroy(); response.writeHead(502); response.end('blocked'); return;
      }
      headers.location = `${target.pathname}${target.search}`;
    }
    response.writeHead(incoming.statusCode || 502, headers);
    incoming.on('data', chunk => {
      bytes += chunk.length;
      if (bytes > 1024 * 1024) {
        incoming.destroy();
        response.destroy();
      } else {
        response.write(chunk);
      }
    });
    incoming.on('end', () => response.end());
    incoming.on('error', () => response.destroy());
  });
  upstream.setTimeout(5000, () => upstream.destroy());
  upstream.on('error', () => {
    if (!response.headersSent) response.writeHead(502, {'content-type': 'text/plain'});
    response.end('unavailable');
  });
  if (request.method === 'POST') boundedLogin(request, response, upstream);
  else upstream.end();
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
