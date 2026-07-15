'use strict';

const ORIGIN = 'http://gateway-frontend:8081';
const REST_CANARY = '/wp-runtime-canary/v1/output';
const BLOCK_CANARY_POST_ID = 910011;
const DOCUMENT_RESPONSE_BYTES = 1048576;
const ASSET_RESPONSE_BYTES = 1209512;
const PROFILES = new Set(['standard', 'block-runtime', 'adversarial-test']);
const ASSET_PREFIXES = ['/wp-includes/', '/wp-admin/css/', '/wp-admin/js/',
  '/wp-admin/images/', '/wp-content/themes/'];

function validContext(context) {
  if (!context || context.origin !== ORIGIN || !PROFILES.has(context.profile)) return false;
  if (!/^[a-z0-9](?:[a-z0-9-]{0,46}[a-z0-9])?$/.test(context.slug || '')) return false;
  const expected = context.profile === 'block-runtime' ? BLOCK_CANARY_POST_ID : 0;
  return context.postId === expected;
}

function boundedUrl(rawUrl, origin) {
  if (typeof rawUrl !== 'string' || rawUrl.length < 1 || rawUrl.length > 8192) return null;
  try {
    const url = new URL(rawUrl, origin);
    return url.origin === origin && ['http:', 'https:'].includes(url.protocol) ? url : null;
  } catch (_) {
    return null;
  }
}

function exactQuery(url, expected) {
  const entries = [...url.searchParams];
  if (entries.length !== Object.keys(expected).length) return false;
  if (new Set(entries.map(([key]) => key)).size !== entries.length) return false;
  return entries.every(([key, value]) => Object.hasOwn(expected, key)
    && expected[key] === value);
}

function staticAsset(url, slug) {
  const prefixes = [...ASSET_PREFIXES, `/wp-content/plugins/${slug}/`];
  if (!prefixes.some(prefix => url.pathname.startsWith(prefix))) return false;
  if (!/[.](?:css|js|mjs|svg|png|gif|jpe?g|webp|woff2?|ttf)$/i.test(url.pathname)) return false;
  if (url.searchParams.size === 0) return true;
  return url.searchParams.size === 1 && [...url.searchParams][0][0] === 'ver'
    && [...url.searchParams][0][1].length > 0 && [...url.searchParams][0][1].length <= 128;
}

function loaderAsset(url) {
  if (!['/wp-admin/load-styles.php', '/wp-admin/load-scripts.php'].includes(url.pathname)) return false;
  const entries = [...url.searchParams];
  const names = new Set(entries.map(([key]) => key));
  const allowed = key => ['c', 'dir', 'ver'].includes(key)
    || /^load(?:\[chunk_[0-9]+\])?$/.test(key);
  return url.search.length <= 8192 && entries.length >= 1 && entries.length <= 64
    && names.size === entries.length
    && entries.every(([key, value]) => allowed(key) && value.length > 0 && value.length <= 4096);
}

function exactRead(url, context) {
  if (url.pathname === '/' && url.search === '') return true;
  if (url.pathname === '/' && exactQuery(url, {rest_route: REST_CANARY})) return true;
  if (staticAsset(url, context.slug) || loaderAsset(url)) return true;
  if (context.profile === 'block-runtime') {
    if (url.pathname === '/' && exactQuery(url, {p: String(context.postId)})) return true;
    if (url.pathname === '/wp-login.php' && url.search === '') return true;
    if (url.pathname === '/wp-admin/' && url.search === '') return true;
    return url.pathname === '/wp-admin/post.php'
      && exactQuery(url, {post: String(context.postId), action: 'edit'});
  }
  if (context.profile === 'adversarial-test') {
    return (url.pathname === '/wp-login.php' || url.pathname === '/wp-admin/'
      || url.pathname === '/wp-admin/post-new.php') && url.search === '';
  }
  return false;
}

function exactMime(value, expected) {
  const normalized = String(value || '').trim().toLowerCase();
  return normalized === expected || normalized === `${expected}; charset=utf-8`;
}

function loginClass(url, headers, context) {
  if (!['block-runtime', 'adversarial-test'].includes(context.profile)) return null;
  if (url.pathname !== '/wp-login.php' || url.search !== '') return null;
  return exactMime(headers['content-type'], 'application/x-www-form-urlencoded') ? 'login' : null;
}

function jsonWriteClass(url, headers, context) {
  if (context.profile !== 'block-runtime') return null;
  if (url.pathname !== `/wp-json/wp/v2/posts/${context.postId}`
      || !(url.search === '' || exactQuery(url, {_locale: 'user'}))) return null;
  const nonce = String(headers['x-wp-nonce'] || '');
  const cookie = String(headers.cookie || '');
  if (!exactMime(headers['content-type'], 'application/json')
      || !/^[A-Za-z0-9]{10,20}$/.test(nonce)
      || cookie.length < 1 || cookie.length > 4096) return null;
  return 'json-write';
}

function classifyRequest(request, context) {
  if (!validContext(context)) return null;
  const url = boundedUrl(request.url, context.origin);
  if (!url) return null;
  const method = String(request.method || '').toUpperCase();
  const headers = request.headers || {};
  if (method === 'POST') return loginClass(url, headers, context);
  if (method === 'PUT') return jsonWriteClass(url, headers, context);
  return ['GET', 'HEAD'].includes(method) && exactRead(url, context) ? 'read' : null;
}

function validateBody(kind, body, context) {
  if (!Buffer.isBuffer(body)) return false;
  if (kind === 'login') return body.length >= 1 && body.length <= 8192;
  if (kind !== 'json-write' || body.length < 2 || body.length > 65536) return false;
  try {
    const payload = JSON.parse(body.toString('utf8'));
    return validContext(context) && Object.keys(payload).sort().join('|') === 'content|id|status'
      && payload.id === context.postId
      && typeof payload.content === 'string'
      && Buffer.byteLength(payload.content, 'utf8') <= 32768
      && payload.status === 'publish';
  } catch (_) {
    return false;
  }
}

function responseByteCeiling(request, context) {
  const kind = classifyRequest(request, context);
  if (!kind) return 0;
  if (kind !== 'read') return DOCUMENT_RESPONSE_BYTES;
  const url = boundedUrl(request.url, context.origin);
  if (!url) return 0;
  return staticAsset(url, context.slug) ? ASSET_RESPONSE_BYTES : DOCUMENT_RESPONSE_BYTES;
}

function nextResponseByteCount(current, chunkLength, ceiling) {
  if (![current, chunkLength, ceiling].every(Number.isSafeInteger)
      || current < 0 || chunkLength < 0 || ceiling < 1
      || current > ceiling || chunkLength > ceiling - current) return null;
  return current + chunkLength;
}

module.exports = {
  ASSET_RESPONSE_BYTES, BLOCK_CANARY_POST_ID, DOCUMENT_RESPONSE_BYTES, ORIGIN,
  classifyRequest, nextResponseByteCount, responseByteCeiling, validContext, validateBody,
};
