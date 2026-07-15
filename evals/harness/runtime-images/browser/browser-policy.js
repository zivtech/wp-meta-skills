'use strict';
const crypto = require('crypto');
const net = require('net');
const { chromium } = require('playwright');

const ORIGIN = 'http://gateway-frontend:8081';
const REST_CANARY = '/wp-runtime-canary/v1/output';
const NORMALIZATION = 'unicode-nfc-whitespace-collapse-trim';
const ASSET_PREFIXES = ['/wp-includes/', '/wp-admin/css/', '/wp-admin/js/', '/wp-admin/images/',
  '/wp-content/themes/'];

function exactQuery(url, expected) {
  if (url.searchParams.size !== Object.keys(expected).length) return false;
  return Object.entries(expected).every(([key, value]) => url.searchParams.get(key) === value);
}

function staticAsset(url, slug) {
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

function exactRead(url, slug) {
  if (url.pathname === '/' && url.search === '') return true;
  if (url.pathname === '/' && exactQuery(url, {rest_route: REST_CANARY})) return true;
  if (url.pathname === '/' && url.searchParams.size === 1
      && /^[1-9][0-9]{0,9}$/.test(url.searchParams.get('p') || '')) return true;
  if (url.pathname === '/wp-login.php' && url.search === '') return true;
  if (url.pathname === '/wp-admin/' && url.search === '') return true;
  if (url.pathname === '/wp-admin/post-new.php' && url.search === '') return true;
  if (url.pathname === '/wp-admin/post.php') {
    return url.searchParams.size === 2 && url.searchParams.get('action') === 'edit'
      && /^[1-9][0-9]{0,9}$/.test(url.searchParams.get('post') || '');
  }
  return staticAsset(url, slug) || loaderAsset(url);
}

function exactJsonWrite(request, url, postId) {
  if (url.pathname !== `/wp-json/wp/v2/posts/${postId}`
      || !(url.search === '' || exactQuery(url, {_locale: 'user'}))) return false;
  const headers = request.headers();
  const contentType = headers['content-type'] || '';
  const body = request.postDataBuffer();
  if (!contentType.startsWith('application/json') || !headers['x-wp-nonce']
      || !headers.cookie || !body || body.length < 2 || body.length > 65536) return false;
  try {
    const payload = JSON.parse(body.toString('utf8'));
    return Object.keys(payload).sort().join('|') === 'content|status'
      && typeof payload.content === 'string' && payload.content.length <= 32768
      && payload.status === 'publish';
  } catch (_) { return false; }
}

function exactLogin(request, url) {
  const type = request.headers()['content-type'] || '';
  const body = request.postDataBuffer();
  return url.pathname === '/wp-login.php' && url.search === ''
    && type.startsWith('application/x-www-form-urlencoded')
    && body && body.length > 0 && body.length <= 8192;
}

function allowedRequest(request, origin, slug, profile, postId) {
  const url = new URL(request.url());
  if (url.origin !== origin || !['http:', 'https:'].includes(url.protocol)) return false;
  if (request.method() === 'POST' && url.pathname === '/wp-login.php') return exactLogin(request, url);
  if (request.method() === 'POST' && profile === 'block-runtime') {
    return exactJsonWrite(request, url, postId);
  }
  return ['GET', 'HEAD'].includes(request.method()) && exactRead(url, slug);
}

function normalizeText(value) {
  return value.normalize('NFC').replace(/\p{White_Space}+/gu, ' ').trim();
}

function digest(value) {
  return crypto.createHash('sha256').update(value, 'utf8').digest('hex');
}

async function login(page, origin) {
  const response = await page.goto(`${origin}/wp-login.php`, {waitUntil: 'domcontentloaded', timeout: 15000});
  if (!response || !response.ok()) throw new Error('login page unavailable');
  await page.locator('#user_login').fill('sandbox');
  await page.locator('#user_pass').fill('not-a-secret-canary');
  await Promise.all([
    page.waitForURL(url => url.origin === origin && url.pathname.startsWith('/wp-admin/'), {timeout: 15000}),
    page.locator('#wp-submit').click(),
  ]);
}

async function blockFrontendProof(page, origin, assertion) {
  await page.goto(`${origin}/wp-admin/post.php?post=${assertion.postId}&action=edit`,
    {waitUntil: 'domcontentloaded', timeout: 15000});
  await page.waitForFunction(name => Boolean(globalThis.wp?.blocks?.getBlockType(name)),
    assertion.blockName, {timeout: 15000});
  await page.evaluate(async ({blockName}) => {
    const block = globalThis.wp.blocks.createBlock(blockName);
    globalThis.wp.data.dispatch('core/block-editor').insertBlocks(block);
    const blocks = globalThis.wp.data.select('core/block-editor').getBlocks();
    if (!blocks.some(item => item.clientId === block.clientId && item.name === blockName)) {
      throw new Error('inserted block is missing from the editor store');
    }
    const content = globalThis.wp.blocks.serialize(blocks);
    const editor = globalThis.wp.data.dispatch('core/editor');
    editor.editPost({content, status: 'publish'});
    await editor.savePost();
    const state = globalThis.wp.data.select('core/editor');
    if (typeof state.didPostSaveRequestFail === 'function'
        && state.didPostSaveRequestFail()) throw new Error('editor save request failed');
  }, {blockName: assertion.blockName});
  await page.goto(`${origin}/?p=${assertion.postId}`, {waitUntil: 'domcontentloaded', timeout: 15000});
  const matches = page.locator(assertion.selector);
  const matchCount = await matches.count();
  const visible = matchCount === 1 && await matches.first().isVisible();
  const observed = matchCount === 1 ? normalizeText(await matches.first().innerText()) : '';
  const expected = normalizeText(assertion.expectedText);
  const proof = {status: matchCount === 1 && visible && observed === expected ? 'pass' : 'fail',
    block_name: assertion.blockName, frontend_selector: assertion.selector,
    expected_text_sha256: digest(expected), observed_text_sha256: digest(observed),
    match_count: matchCount, visible, normalization: NORMALIZATION};
  if (proof.status !== 'pass') throw new Error('block frontend assertion mismatch');
  return proof;
}

(async () => {
  const profile = process.argv[2] || 'standard';
  const origin = process.argv[3] || process.env.WP_RUNTIME_ORIGIN || ORIGIN;
  const slug = process.argv[4];
  const hostListener = process.argv[5] || '';
  const assertion = profile === 'block-runtime' ? {blockName: process.argv[6], selector: process.argv[7],
    expectedText: process.argv[8], postId: Number(process.argv[9])} : null;
  if (!['standard', 'block-runtime', 'adversarial-test'].includes(profile)) throw new Error('unreviewed browser profile');
  if (origin !== ORIGIN) throw new Error('unreviewed WordPress gateway origin');
  if (!/^[a-z0-9](?:[a-z0-9-]{0,46}[a-z0-9])?$/.test(slug || '')) throw new Error('unreviewed plugin slug');
  if (assertion && (!/^[a-z0-9][a-z0-9-]*\/[a-z0-9][a-z0-9-]*$/.test(assertion.blockName || '')
      || assertion.selector !== `.wp-block-${assertion.blockName.replace('/', '-')}`
      || !assertion.expectedText || !Number.isSafeInteger(assertion.postId) || assertion.postId < 1)) {
    throw new Error('unreviewed block assertion');
  }
  const listenerUrl = hostListener ? new URL(hostListener) : null;
  if (profile === 'adversarial-test' && (!listenerUrl || listenerUrl.protocol !== 'http:'
      || net.isIP(listenerUrl.hostname) !== 4 || !listenerUrl.port
      || listenerUrl.pathname !== '/' || listenerUrl.search || listenerUrl.hash)) throw new Error('unreviewed controlled host listener');
  const canaries = {}; const generatedDenials = {}; const generatedObservers = {};
  const generatedNavigationDenials = new Set(); let denied = 0;
  const generatedDenialKeys = ['loopback', 'rfc1918', 'metadata', 'public_ip', 'public_dns',
    'database_peer', 'host_gateway', 'host_listener', 'websocket', 'webrtc', 'service_worker',
    'external_navigation', 'download', 'popup'];
  const exactGeneratedDenials = value => Boolean(value)
    && Object.keys(value).sort().join('|') === [...generatedDenialKeys].sort().join('|')
    && generatedDenialKeys.every(key => value[key] === true);
  const browser = await chromium.launch({headless: true, args: ['--disable-webrtc']});
  const context = await browser.newContext({acceptDownloads: false, serviceWorkers: 'block'});
  await context.addInitScript(({allowed, pluginSlug, controlledHostListener}) => {
    globalThis.__WP_RUNTIME_HOST_LISTENER_URL__ = controlledHostListener;
    const OriginalRTC = globalThis.RTCPeerConnection;
    globalThis.RTCPeerConnection = function () { throw new DOMException('WebRTC blocked', 'SecurityError'); };
    globalThis.RTCPeerConnection.prototype = OriginalRTC && OriginalRTC.prototype;
    const open = globalThis.open;
    globalThis.open = (value, ...args) => {
      const target = new URL(value, location.href);
      return target.origin === allowed && (target.pathname === '/'
        || target.pathname.startsWith(`/wp-content/plugins/${pluginSlug}/`)) ? open(value, ...args) : null;
    };
    if (navigator.serviceWorker) navigator.serviceWorker.register = async () => { throw new DOMException('Service worker blocked', 'SecurityError'); };
  }, {allowed: origin, pluginSlug: slug, controlledHostListener: hostListener});
  await context.routeWebSocket('**/*', async socket => { denied += 1; socket.close({code: 1008, reason: 'websocket blocked'}); });
  await context.route('**/*', async route => {
    const url = new URL(route.request().url());
    if (allowedRequest(route.request(), origin, slug, profile, assertion?.postId)) await route.continue();
    else { if (url.hostname === 'example.com' && url.pathname.startsWith('/generated-navigation-')) generatedNavigationDenials.add(url.pathname); denied += 1; await route.abort('blockedbyclient'); }
  });
  let page = await context.newPage(); let download = false; let popup = false;
  const observe = current => { current.on('download', item => { download = true; item.cancel(); }); current.on('popup', child => { popup = true; child.close(); }); };
  observe(page);
  const response = await page.goto(origin, {waitUntil: 'domcontentloaded', timeout: 15000});
  canaries.same_origin = Boolean(response && response.ok());
  if (profile === 'adversarial-test') {
    generatedDenials.frontend = await page.evaluate(async () => globalThis.__WP_GENERATED_RUNTIME_MARKER__ === true ? await globalThis.__WP_GENERATED_RUNTIME_DENIALS__ : null);
    await page.waitForTimeout(500); generatedObservers.frontend = {download, popup};
    canaries.generated_frontend_js = exactGeneratedDenials(generatedDenials.frontend) && !download && !popup;
  }
  canaries.external_http = await page.evaluate(() => fetch('https://example.com/runtime-canary').then(() => false, () => true));
  const navigationPage = await context.newPage();
  canaries.external_navigation = await navigationPage.goto('https://example.com', {timeout: 3000}).then(() => false, () => true); await navigationPage.close();
  await page.goto(origin, {waitUntil: 'domcontentloaded', timeout: 15000});
  canaries.websocket = await page.evaluate(() => new Promise(resolve => { const ws = new WebSocket('wss://example.com/runtime-canary'); ws.onopen = () => resolve(false); ws.onerror = () => resolve(true); setTimeout(() => resolve(true), 2500); }));
  canaries.webrtc = await page.evaluate(() => { try { new RTCPeerConnection(); return false; } catch (_) { return true; } });
  canaries.service_worker = await page.evaluate(() => !navigator.serviceWorker || navigator.serviceWorker.register('/runtime-canary.js').then(() => false, () => true));
  await page.evaluate(() => { const a=document.createElement('a'); a.href='https://example.com/file'; a.download='x'; a.click(); }); await page.waitForTimeout(500);
  canaries.download = !download; canaries.popup = await page.evaluate(() => window.open('https://example.com') === null) && !popup;
  let blockProof = null;
  if (profile === 'block-runtime' || profile === 'adversarial-test') await login(page, origin);
  if (profile === 'block-runtime') blockProof = await blockFrontendProof(page, origin, assertion);
  if (profile === 'adversarial-test') {
    await page.goto(`${origin}/wp-admin/post-new.php`, {waitUntil: 'domcontentloaded', timeout: 15000});
    generatedDenials.editor = await page.evaluate(async () => globalThis.__WP_GENERATED_EDITOR_RUNTIME_MARKER__ === true ? await globalThis.__WP_GENERATED_EDITOR_DENIALS__ : null);
    await page.waitForTimeout(500); generatedObservers.editor = {download, popup};
    canaries.generated_editor_js = exactGeneratedDenials(generatedDenials.editor) && !download && !popup;
  }
  await browser.close();
  process.stdout.write(JSON.stringify({profile, origin, canaries, block_editor_frontend: blockProof,
    generated_denials: generatedDenials, generated_observers: generatedObservers,
    generated_navigation_denials: [...generatedNavigationDenials].sort(), denied_requests: denied}) + '\n');
})().catch(error => { process.stderr.write(String(error && error.message || error).slice(0, 1000) + '\n'); process.exit(1); });
