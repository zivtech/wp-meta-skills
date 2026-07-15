'use strict';
const dns = require('dns').promises;
const http = require('http');

const slug = process.argv[2];
if (!/^[a-z0-9](?:[a-z0-9-]{0,46}[a-z0-9])?$/.test(slug || '')) throw new Error('gateway requires an exact plugin slug');
const ORIGIN = 'http://gateway-frontend:8081';
const REST_CANARY = '/wp-runtime-canary/v1/output';
const ASSET_PREFIXES = ['/wp-includes/', '/wp-admin/css/', '/wp-admin/js/', '/wp-admin/images/',
  '/wp-content/themes/'];

function exactQuery(url, expected) {
  if (url.searchParams.size !== Object.keys(expected).length) return false;
  return Object.entries(expected).every(([key, value]) => url.searchParams.get(key) === value);
}

function staticAsset(url) {
  const prefixes = [...ASSET_PREFIXES, `/wp-content/plugins/${slug}/`];
  if (!prefixes.some(prefix => url.pathname.startsWith(prefix))) return false;
  if (!/[.](?:css|js|mjs|svg|png|gif|jpe?g|webp|woff2?|ttf)$/i.test(url.pathname)) return false;
  return [...url.searchParams.keys()].every(key => key === 'ver');
}

function loaderAsset(url) {
  if (!['/wp-admin/load-styles.php', '/wp-admin/load-scripts.php'].includes(url.pathname)) return false;
  const allowed = key => ['c', 'dir', 'ver'].includes(key) || /^load(?:\[chunk_[0-9]+\])?$/.test(key);
  return url.searchParams.size > 0 && [...url.searchParams].every(([key, value]) => (
    allowed(key) && value.length > 0 && value.length <= 4096
  ));
}

function exactRead(url) {
  if (url.pathname === '/' && url.search === '') return true;
  if (url.pathname === '/' && exactQuery(url, {rest_route: REST_CANARY})) return true;
  if (url.pathname === '/' && url.searchParams.size === 1
      && /^[1-9][0-9]{0,9}$/.test(url.searchParams.get('p') || '')) return true;
  if (url.pathname === '/wp-login.php' && url.search === '') return true;
  if (url.pathname === '/wp-admin/' && url.search === '') return true;
  if (url.pathname === '/wp-admin/post-new.php' && url.search === '') return true;
  if (url.pathname === '/wp-admin/post.php') return url.searchParams.size === 2
    && url.searchParams.get('action') === 'edit'
    && /^[1-9][0-9]{0,9}$/.test(url.searchParams.get('post') || '');
  return staticAsset(url) || loaderAsset(url);
}

function writeRoute(url) {
  const prefix = '/wp-json/wp/v2/posts/';
  return url.pathname.startsWith(prefix)
    && /^[1-9][0-9]{0,9}$/.test(url.pathname.slice(prefix.length))
    && (url.search === '' || exactQuery(url, {_locale: 'user'}));
}

function allowed(request) {
  const url = new URL(request.url, ORIGIN);
  if (request.method === 'POST' && url.pathname === '/wp-login.php') return url.search === '';
  if (request.method === 'POST') return writeRoute(url);
  return ['GET', 'HEAD'].includes(request.method) && exactRead(url);
}

function reject(response, upstream) {
  if (upstream) upstream.destroy();
  if (!response.headersSent) response.writeHead(403, {'content-type': 'text/plain'});
  response.end('blocked');
}

function boundedLogin(request, response, upstream) {
  const type = String(request.headers['content-type'] || '');
  const length = Number(request.headers['content-length'] || 0);
  if (!type.startsWith('application/x-www-form-urlencoded')
      || !Number.isSafeInteger(length) || length < 1 || length > 8192) {
    reject(response, upstream); return;
  }
  request.pipe(upstream);
}

function boundedJsonWrite(request, response, upstream) {
  const type = String(request.headers['content-type'] || '');
  const length = Number(request.headers['content-length'] || 0);
  const nonce = String(request.headers['x-wp-nonce'] || '');
  const cookie = String(request.headers.cookie || '');
  if (!type.startsWith('application/json') || !/^[A-Za-z0-9]{10,20}$/.test(nonce)
      || !cookie || cookie.length > 4096 || !Number.isSafeInteger(length)
      || length < 2 || length > 65536) { reject(response, upstream); return; }
  const chunks = []; let bytes = 0;
  request.on('data', chunk => { bytes += chunk.length; if (bytes > 65536) reject(response, upstream); else chunks.push(chunk); });
  request.on('end', () => {
    if (upstream.destroyed) return;
    try {
      const body = Buffer.concat(chunks);
      const payload = JSON.parse(body.toString('utf8'));
      const valid = Object.keys(payload).sort().join('|') === 'content|status'
        && typeof payload.content === 'string' && payload.content.length <= 32768
        && payload.status === 'publish';
      if (!valid) { reject(response, upstream); return; }
      upstream.end(body);
    } catch (_) { reject(response, upstream); }
  });
  request.on('error', () => reject(response, upstream));
}

function upstreamHeaders(request) {
  const headers = {host: 'gateway-frontend:8081', connection: 'close'};
  if (request.headers.cookie) headers.cookie = request.headers.cookie;
  if (request.method === 'POST') {
    headers['content-type'] = request.headers['content-type'];
    headers['content-length'] = request.headers['content-length'];
  }
  if (request.headers['x-wp-nonce']) headers['x-wp-nonce'] = request.headers['x-wp-nonce'];
  return headers;
}

function forward(request, response) {
  if (!allowed(request)) { reject(response); return; }
  const upstream = http.request({hostname: 'wordpress-application', port: 8080,
    method: request.method, path: request.url, headers: upstreamHeaders(request)}, incoming => {
    let bytes = 0; const headers = {...incoming.headers};
    if (headers.location) {
      const target = new URL(headers.location, ORIGIN);
      if (target.origin !== ORIGIN) { incoming.destroy(); reject(response); return; }
      headers.location = `${target.pathname}${target.search}`;
    }
    response.writeHead(incoming.statusCode || 502, headers);
    incoming.on('data', chunk => { bytes += chunk.length; if (bytes > 1024 * 1024) { incoming.destroy(); response.destroy(); } else response.write(chunk); });
    incoming.on('end', () => response.end()); incoming.on('error', () => response.destroy());
  });
  upstream.setTimeout(5000, () => upstream.destroy());
  upstream.on('error', () => { if (!response.headersSent) response.writeHead(502, {'content-type': 'text/plain'}); response.end('unavailable'); });
  const url = new URL(request.url, ORIGIN);
  if (request.method !== 'POST') upstream.end();
  else if (url.pathname === '/wp-login.php') boundedLogin(request, response, upstream);
  else boundedJsonWrite(request, response, upstream);
}

(async () => {
  const {address} = await dns.lookup('gateway-frontend', {family: 4});
  const server = http.createServer(forward);
  server.requestTimeout = 10000; server.headersTimeout = 5000; server.maxRequestsPerSocket = 100;
  server.listen(8081, address);
})().catch(error => { process.stderr.write(`${String(error && error.message || error).slice(0, 500)}\n`); process.exit(1); });
