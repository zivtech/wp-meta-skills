'use strict';
const net = require('net');
const { chromium } = require('playwright');

(async () => {
  const profile = process.argv[2] || 'standard';
  const origin = process.argv[3] || process.env.WP_RUNTIME_ORIGIN || 'http://gateway-frontend:8081';
  const slug = process.argv[4];
  const hostListener = process.argv[5] || '';
  if (!['standard', 'adversarial-test'].includes(profile)) throw new Error('unreviewed browser profile');
  if (origin !== 'http://gateway-frontend:8081') throw new Error('unreviewed WordPress gateway origin');
  if (!/^[a-z0-9](?:[a-z0-9-]{0,46}[a-z0-9])?$/.test(slug || '')) throw new Error('unreviewed plugin slug');
  const listenerUrl = hostListener ? new URL(hostListener) : null;
  if (profile === 'adversarial-test' && (!listenerUrl || listenerUrl.protocol !== 'http:'
      || net.isIP(listenerUrl.hostname) !== 4 || !listenerUrl.port
      || listenerUrl.pathname !== '/' || listenerUrl.search || listenerUrl.hash)) {
    throw new Error('unreviewed controlled host listener');
  }
  const restCanary = '/wp-runtime-canary/v1/output';
  const allowedPath = (url, method = 'GET') => {
    if (url.origin !== origin) return false;
    if (method === 'POST') return url.pathname === '/wp-login.php';
    if (!['GET', 'HEAD'].includes(method)) return false;
    const rootAllowed = url.pathname === '/' && (url.search === ''
      || (url.searchParams.size === 1 && url.searchParams.get('rest_route') === restCanary));
    return rootAllowed || url.pathname === '/wp-login.php'
      || ['/wp-includes/', `/wp-content/plugins/${slug}/`, '/wp-content/themes/',
        '/wp-admin/'].some(prefix => url.pathname.startsWith(prefix));
  };
  const canaries = {};
  const generatedDenials = {};
  const generatedObservers = {};
  const generatedNavigationDenials = new Set();
  const generatedDenialKeys = [
    'loopback', 'rfc1918', 'metadata', 'public_ip', 'public_dns',
    'database_peer', 'host_gateway', 'host_listener', 'websocket', 'webrtc',
    'service_worker', 'external_navigation', 'download', 'popup',
  ];
  const exactGeneratedDenials = value => Boolean(value)
    && Object.keys(value).sort().join('|') === [...generatedDenialKeys].sort().join('|')
    && generatedDenialKeys.every(key => value[key] === true);
  let denied = 0;
  const browser = await chromium.launch({headless: true, args: ['--disable-webrtc']});
  const context = await browser.newContext({acceptDownloads: false, serviceWorkers: 'block'});
  await context.addInitScript(({allowed, pluginSlug, controlledHostListener}) => {
    globalThis.__WP_RUNTIME_HOST_LISTENER_URL__ = controlledHostListener;
    const OriginalRTC = globalThis.RTCPeerConnection;
    globalThis.RTCPeerConnection = function () { throw new DOMException('WebRTC blocked', 'SecurityError'); };
    globalThis.RTCPeerConnection.prototype = OriginalRTC && OriginalRTC.prototype;
    const open = globalThis.open;
    const popupAllowed = (value) => {
      const target = new URL(value, location.href);
      return target.origin === allowed && (target.pathname === '/'
        || target.pathname.startsWith(`/wp-content/plugins/${pluginSlug}/`));
    };
    globalThis.open = (url, ...args) => popupAllowed(url) ? open(url, ...args) : null;
    if (navigator.serviceWorker) navigator.serviceWorker.register = async () => { throw new DOMException('Service worker blocked', 'SecurityError'); };
  }, {allowed: origin, pluginSlug: slug, controlledHostListener: hostListener});
  await context.routeWebSocket('**/*', async (socket) => {
    denied += 1; socket.close({code: 1008, reason: 'websocket blocked'});
  });
  await context.route('**/*', async (route) => {
    const url = new URL(route.request().url());
    if (['http:', 'https:'].includes(url.protocol)
        && allowedPath(url, route.request().method())) await route.continue();
    else {
      if (url.hostname === 'example.com'
          && url.pathname.startsWith('/generated-navigation-')) {
        generatedNavigationDenials.add(url.pathname);
      }
      denied += 1; await route.abort('blockedbyclient');
    }
  });
  let page = await context.newPage();
  let download = false; let popup = false;
  const observe = current => {
    current.on('download', item => { download = true; item.cancel(); });
    current.on('popup', child => { popup = true; child.close(); });
  };
  observe(page);
  const response = await page.goto(origin, {waitUntil: 'domcontentloaded', timeout: 15000});
  canaries.same_origin = Boolean(response && response.ok());
  if (profile === 'adversarial-test') {
    generatedDenials.frontend = await page.evaluate(async () => (
      globalThis.__WP_GENERATED_RUNTIME_MARKER__ === true
        ? await globalThis.__WP_GENERATED_RUNTIME_DENIALS__ : null
    ));
    await page.waitForTimeout(500);
    generatedObservers.frontend = {download, popup};
    canaries.generated_frontend_js = exactGeneratedDenials(generatedDenials.frontend)
      && !download && !popup;
  }
  canaries.external_http = await page.evaluate(() => fetch('https://example.com/runtime-canary').then(() => false, () => true));
  const navigationPage = await context.newPage();
  canaries.external_navigation = await navigationPage.goto('https://example.com', {timeout: 3000}).then(() => false, () => true);
  await navigationPage.close();
  await page.goto(origin, {waitUntil: 'domcontentloaded', timeout: 15000});
  canaries.websocket = await page.evaluate(() => new Promise(resolve => {
    const ws = new WebSocket('wss://example.com/runtime-canary');
    ws.onopen = () => resolve(false); ws.onerror = () => resolve(true); setTimeout(() => resolve(true), 2500);
  }));
  canaries.webrtc = await page.evaluate(() => { try { new RTCPeerConnection(); return false; } catch (_) { return true; } });
  canaries.service_worker = await page.evaluate(() => !navigator.serviceWorker
    || navigator.serviceWorker.register('/runtime-canary.js').then(() => false, () => true));
  await page.evaluate(() => { const a=document.createElement('a'); a.href='https://example.com/file'; a.download='x'; a.click(); });
  await page.waitForTimeout(500);
  canaries.download = !download;
  canaries.popup = await page.evaluate(() => window.open('https://example.com') === null) && !popup;
  if (profile === 'adversarial-test') {
    const loginResponse = await page.goto(`${origin}/wp-login.php`, {waitUntil: 'domcontentloaded', timeout: 15000});
    if (!loginResponse || !loginResponse.ok()) {
      throw new Error(`login page unavailable: ${loginResponse && loginResponse.status()}`);
    }
    await page.locator('#user_login').waitFor({state: 'visible', timeout: 5000});
    await page.locator('#user_login').fill('sandbox');
    await page.locator('#user_pass').fill('not-a-secret-canary');
    await Promise.all([
      page.waitForURL(url => url.origin === origin && url.pathname.startsWith('/wp-admin/'), {timeout: 15000}),
      page.locator('#wp-submit').click(),
    ]);
    await page.goto(`${origin}/wp-admin/post-new.php`, {waitUntil: 'domcontentloaded', timeout: 15000});
    generatedDenials.editor = await page.evaluate(async () => (
      globalThis.__WP_GENERATED_EDITOR_RUNTIME_MARKER__ === true
        ? await globalThis.__WP_GENERATED_EDITOR_DENIALS__ : null
    ));
    await page.waitForTimeout(500);
    generatedObservers.editor = {download, popup};
    canaries.generated_editor_js = exactGeneratedDenials(generatedDenials.editor)
      && !download && !popup;
  }
  await browser.close();
  process.stdout.write(JSON.stringify({profile, origin, canaries,
    generated_denials: generatedDenials, generated_observers: generatedObservers,
    generated_navigation_denials: [...generatedNavigationDenials].sort(),
    denied_requests: denied}) + '\n');
})().catch(error => {
  process.stderr.write(String(error && error.message || error).slice(0, 1000) + '\n');
  process.exit(1);
});
