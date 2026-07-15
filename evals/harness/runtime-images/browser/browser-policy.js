'use strict';
const crypto = require('crypto');
const net = require('net');
const requestPolicy = require('./request-policy');

const ORIGIN = requestPolicy.ORIGIN;
const NORMALIZATION = 'unicode-nfc-whitespace-collapse-trim';

async function allowedRequest(request, context) {
  const normalized = {
    url: request.url(), method: request.method(), headers: await request.allHeaders(),
  };
  const kind = requestPolicy.classifyRequest(normalized, context);
  if (!kind) return false;
  if (kind === 'read') return true;
  return requestPolicy.validateBody(kind, request.postDataBuffer(), context);
}

function normalizeText(value) {
  return value.normalize('NFC').replace(/\p{White_Space}+/gu, ' ').trim();
}

function digest(value) {
  return crypto.createHash('sha256').update(value, 'utf8').digest('hex');
}

function editorReady() {
  try {
    const data = globalThis.wp?.data;
    const blocks = globalThis.wp?.blocks;
    if (!data || !blocks || typeof blocks.createBlock !== 'function') return false;
    const blockActions = data.dispatch('core/block-editor');
    const editorActions = data.dispatch('core/editor');
    const blockState = data.select('core/block-editor');
    const editorState = data.select('core/editor');
    return Boolean(blockActions && typeof blockActions.insertBlocks === 'function'
      && editorActions && typeof editorActions.editPost === 'function'
      && typeof editorActions.savePost === 'function'
      && blockState && typeof blockState.getBlocks === 'function'
      && editorState);
  } catch (_) {
    return false;
  }
}

async function waitForEditor(page, origin, expectedPostId) {
  try {
    await page.waitForFunction(editorReady, null, {timeout: 15000});
  } catch (error) {
    if (error?.name !== 'TimeoutError') throw error;
    const snapshot = await page.evaluate(({expectedOrigin, postId}) => {
      const data = globalThis.wp?.data;
      const blocks = globalThis.wp?.blocks;
      const blockActions = data?.dispatch('core/block-editor');
      const editorActions = data?.dispatch('core/editor');
      const blockState = data?.select('core/block-editor');
      const editorState = data?.select('core/editor');
      const query = [...new URLSearchParams(location.search)];
      const observedPostId = typeof editorState?.getCurrentPostId === 'function'
        ? editorState.getCurrentPostId() : null;
      return {data: Boolean(data), createBlock: typeof blocks?.createBlock === 'function',
        blockActions: Boolean(blockActions), editorActions: Boolean(editorActions),
        insertBlocks: typeof blockActions?.insertBlocks === 'function',
        editPost: typeof editorActions?.editPost === 'function',
        savePost: typeof editorActions?.savePost === 'function',
        blockState: Boolean(blockState), getBlocks: typeof blockState?.getBlocks === 'function',
        editorState: Boolean(editorState), currentPostId: Number.isSafeInteger(observedPostId)
          ? observedPostId : null, exactEditUrl: location.origin === expectedOrigin
          && location.pathname === '/wp-admin/post.php' && query.length === 2
          && query.some(([key, value]) => key === 'post' && value === String(postId))
          && query.some(([key, value]) => key === 'action' && value === 'edit')};
    }, {expectedOrigin: origin, postId: expectedPostId}).catch(() => ({evaluation: false}));
    throw new Error(`editor readiness timed out: ${JSON.stringify(snapshot)}`);
  }
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
  try {
    await page.waitForFunction(name => Boolean(globalThis.wp?.blocks?.getBlockType(name)),
      assertion.blockName, {timeout: 15000});
  } catch (error) {
    if (error?.name !== 'TimeoutError') throw error;
    throw new Error('target block registration timed out');
  }
  await waitForEditor(page, origin, assertion.postId);
  await page.evaluate(async ({blockName}) => {
    const block = globalThis.wp.blocks.createBlock(blockName);
    const blockActions = globalThis.wp.data.dispatch('core/block-editor');
    const editorActions = globalThis.wp.data.dispatch('core/editor');
    if (!blockActions || typeof blockActions.insertBlocks !== 'function'
        || !editorActions || typeof editorActions.editPost !== 'function'
        || typeof editorActions.savePost !== 'function') {
      throw new Error('editor actions became unavailable after readiness');
    }
    blockActions.insertBlocks(block);
    const blocks = globalThis.wp.data.select('core/block-editor').getBlocks();
    if (!blocks.some(item => item.clientId === block.clientId && item.name === blockName)) {
      throw new Error('inserted block is missing from the editor store');
    }
    const content = globalThis.wp.blocks.serialize(blocks);
    editorActions.editPost({content, status: 'publish'});
    await editorActions.savePost();
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

async function main() {
  const { chromium } = require('playwright');
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
      || !assertion.expectedText || assertion.postId !== requestPolicy.BLOCK_CANARY_POST_ID)) {
    throw new Error('unreviewed block assertion');
  }
  const policyContext = {origin, slug, profile, postId: assertion?.postId || 0};
  if (!requestPolicy.validContext(policyContext)) throw new Error('unreviewed browser request context');
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
    if (await allowedRequest(route.request(), policyContext)) await route.continue();
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
}

if (require.main === module) {
  main().catch(error => {
    process.stderr.write(String(error && error.message || error).slice(0, 1000) + '\n');
    process.exit(1);
  });
}

module.exports = Object.freeze({editorReady});
