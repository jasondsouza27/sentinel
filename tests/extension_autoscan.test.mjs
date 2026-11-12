import assert from 'node:assert/strict';
import { readFileSync } from 'node:fs';
import test from 'node:test';
import { createContext, runInContext } from 'node:vm';

// Values made inside the vm context have other prototypes; compare them as JSON.
const same = (actual, expected) => assert.deepEqual(JSON.parse(JSON.stringify(actual)), expected);
const script = readFileSync(new URL('../extension/background.js', import.meta.url), 'utf8');
const ocrUtils = readFileSync(new URL('../extension/ocr-utils.js', import.meta.url), 'utf8');

function setup(fetchImpl, { activeTab = 4, offscreenReply = { results: [] }, openTabs = null } = {}) {
  const listeners = {};
  const store = {};
  let registered = [];
  const calls = { fetched: [], injected: [], stopped: [], badges: [], captures: [], offscreen: [], created: 0 };
  let contexts = [];
  const event = name => ({ addListener: fn => { listeners[name] = fn; } });
  const chrome = {
    runtime: {
      onInstalled: event('installed'), onMessage: event('message'),
      getContexts: async () => contexts,
      sendMessage: async message => { calls.offscreen.push(message); return offscreenReply; },
    },
    offscreen: {
      createDocument: async () => { calls.created += 1; contexts = [{ contextType: 'OFFSCREEN_DOCUMENT' }]; },
      closeDocument: async () => { contexts = []; },
    },
    contextMenus: { create: () => {}, onClicked: event('menu') },
    permissions: { onRemoved: event('removed') },
    storage: {
      local: { get: async key => ({ [key]: store[key] }), set: async value => Object.assign(store, value) },
      session: { set: async () => {} },
    },
    scripting: {
      getRegisteredContentScripts: async () => registered,
      registerContentScripts: async scripts => { registered = scripts; },
      updateContentScripts: async scripts => { registered = scripts; },
      unregisterContentScripts: async () => { registered = []; },
      executeScript: async details => { calls.injected.push(details); },
    },
    tabs: {
      sendMessage: async (tabId, message) => { calls.stopped.push([tabId, message]); },
      query: async filter => (filter?.url && openTabs) ? openTabs : [{ id: typeof activeTab === 'function' ? activeTab() : activeTab }],
      captureVisibleTab: async (windowId, options) => { calls.captures.push([windowId, options]); return 'data:image/png;base64,AAAA'; },
    },
    action: { setBadgeText: value => calls.badges.push(value), setBadgeBackgroundColor: () => {}, openPopup: async () => {} },
  };
  const fetch = async (url, options) => { calls.fetched.push([url, JSON.parse(options.body)]); return fetchImpl(); };
  // Long timers (screenshot expiry, closing the idle OCR page) must not keep the test process alive.
  const timer = (fn, ms) => { const handle = setTimeout(fn, ms); if (ms >= 5000) handle.unref(); return handle; };
  const context = createContext({ chrome, fetch, AbortController, setTimeout: timer, clearTimeout, URL });
  context.importScripts = () => runInContext(ocrUtils, context);
  runInContext(script, context);
  const send = (message, sender = {}) => new Promise(resolve => {
    const async = listeners.message(message, sender, resolve);
    if (!async) resolve(undefined);
  });
  return { send, calls, store, registered: () => registered, listeners, ocr: context.SentinelOcr };
}

test('scan requests from a tab are relayed to the local scan endpoint', async () => {
  const env = setup(async () => new Response(JSON.stringify({ results: [{ id: '1', severity: 'high' }] })));
  const reply = await env.send({ type: 'sentinel-scan', items: [{ id: '1', text: 'x' }] }, { tab: { id: 4 } });
  assert.equal(reply.results[0].severity, 'high');
  assert.equal(env.calls.fetched[0][0], 'http://127.0.0.1:8787/api/scan');
  same(env.calls.fetched[0][1], { items: [{ id: '1', text: 'x' }] });
});

test('an unavailable server returns an error, never results', async () => {
  const env = setup(async () => { throw new TypeError('Failed to fetch'); });
  const reply = await env.send({ type: 'sentinel-scan', items: [{ id: '1', text: 'x' }] }, { tab: { id: 4 } });
  assert.match(reply.error, /Start the local Sentinel app/);
  assert.equal(reply.results, undefined);
});

test('scan requests that do not come from a tab are ignored', async () => {
  const env = setup(async () => new Response('{}'));
  assert.equal(await env.send({ type: 'sentinel-scan', items: [] }, {}), undefined);
  assert.equal(env.calls.fetched.length, 0);
});

test('turning a site on and off registers, injects and stops the scanner', async () => {
  const env = setup(async () => new Response('{}'));
  await env.send({ type: 'sentinel-autoscan-set', pattern: 'https://chat.example/*', enabled: true, tabId: 7 });
  same(env.store.autoscanSites, ['https://chat.example/*']);
  same(env.registered()[0].matches, ['https://chat.example/*']);
  assert.equal(env.calls.injected[0].target.tabId, 7);
  await env.send({ type: 'sentinel-autoscan-set', pattern: 'https://chat.example/*', enabled: false, tabId: 7 });
  same(env.store.autoscanSites, []);
  assert.equal(env.registered().length, 0);
  same(env.calls.stopped[0], [7, { type: 'sentinel-stop' }]);
});

test('site settings cannot be changed from a web page', async () => {
  const env = setup(async () => new Response('{}'));
  const reply = await env.send({ type: 'sentinel-autoscan-set', pattern: 'https://*/*', enabled: true, tabId: 1 }, { tab: { id: 1 } });
  assert.equal(reply, undefined);
  assert.equal(env.store.autoscanSites, undefined);
});

test('removing site access in Chrome stops scanning that site', async () => {
  const env = setup(async () => new Response('{}'));
  await env.send({ type: 'sentinel-autoscan-set', pattern: 'https://a.example/*', enabled: true });
  await env.send({ type: 'sentinel-autoscan-set', pattern: 'https://b.example/*', enabled: true });
  await env.listeners.removed({ origins: ['https://a.example/*'] });
  same(env.store.autoscanSites, ['https://b.example/*']);
});

test('every-website auto-scan registers for all pages and injects into open tabs', async () => {
  const openTabs = [{ id: 11, url: 'https://news.example/a' }, { id: 12, url: 'http://forum.example/t/1' }];
  const env = setup(async () => new Response('{}'), { openTabs });
  const reply = await env.send({ type: 'sentinel-autoscan-every-site', enabled: true });
  assert.equal(reply.ok, true);
  same(env.store.autoscanSites, ['http://*/*', 'https://*/*']);
  same(env.registered()[0].matches, ['http://*/*', 'https://*/*']);
  same(env.calls.injected.map(d => d.target.tabId).sort(), [11, 12]);
});

test('turning every-website off keeps sites that were turned on individually', async () => {
  const openTabs = [{ id: 11, url: 'https://news.example/a' }, { id: 13, url: 'https://chat.example/room' }];
  const env = setup(async () => new Response('{}'), { openTabs });
  await env.send({ type: 'sentinel-autoscan-set', pattern: 'https://chat.example/*', enabled: true });
  await env.send({ type: 'sentinel-autoscan-every-site', enabled: true });
  await env.send({ type: 'sentinel-autoscan-every-site', enabled: false });
  same(env.store.autoscanSites, ['https://chat.example/*']);
  same(env.registered()[0].matches, ['https://chat.example/*']);
  same(env.calls.stopped, [[11, { type: 'sentinel-stop' }]]);
});

test('after a reload or update, open tabs on auto-scan sites get the new scanner', async () => {
  const openTabs = [{ id: 21, url: 'https://mail.example/inbox' }, { id: 22, url: 'https://mail.example/thread/1' }];
  const env = setup(async () => new Response('{}'), { openTabs });
  await env.send({ type: 'sentinel-autoscan-set', pattern: 'https://mail.example/*', enabled: true });
  env.calls.injected.length = 0;
  env.listeners.installed({ reason: 'update' });
  await new Promise(resolve => setTimeout(resolve, 10));
  same(env.calls.injected.map(d => d.target.tabId).sort(), [21, 22]);
});

test('with no auto-scan sites, a reload injects nothing', async () => {
  const env = setup(async () => new Response('{}'), { openTabs: [{ id: 31, url: 'https://x.example/' }] });
  env.listeners.installed({ reason: 'install' });
  await new Promise(resolve => setTimeout(resolve, 10));
  assert.equal(env.calls.injected.length, 0);
});

test('every-website auto-scan cannot be switched on from a web page', async () => {
  const env = setup(async () => new Response('{}'));
  const reply = await env.send({ type: 'sentinel-autoscan-every-site', enabled: true }, { tab: { id: 1 } });
  assert.equal(reply, undefined);
  assert.equal(env.store.autoscanSites, undefined);
});

test('flag counts update the toolbar badge for that tab', async () => {
  const env = setup(async () => new Response('{}'));
  await env.send({ type: 'sentinel-flags', high: 2, review: 1 }, { tab: { id: 3 } });
  same(env.calls.badges.at(-1), { tabId: 3, text: '3' });
});

// ---- Text in images ----
const tab = { id: 4, windowId: 9, url: 'https://chat.example/room/1' };
const region = { id: '0', x: 10, y: 20, w: 300, h: 120 };

async function imageReady(env) {
  await env.send({ type: 'sentinel-autoscan-set', pattern: 'https://chat.example/*', enabled: true });
  env.store.ocrEnabled = true;
}

test('an auto-scan site with image reading on gets a screenshot, then OCR results', async () => {
  const env = setup(async () => new Response('{}'), { offscreenReply: { results: [{ id: '0', text: 'Pay the fee now', qr: null }] } });
  await imageReady(env);
  const shot = await env.send({ type: 'sentinel-capture' }, { tab, frameId: 0 });
  assert.ok(shot.shot);
  same(env.calls.captures[0], [9, { format: 'png' }]);
  const reply = await env.send({ type: 'sentinel-ocr', shot: shot.shot, viewportWidth: 1280, regions: [region] }, { tab, frameId: 0 });
  assert.equal(reply.results[0].text, 'Pay the fee now');
  assert.equal(env.calls.created, 1);
  const sent = env.calls.offscreen[0];
  assert.equal(sent.target, 'sentinel-offscreen');
  assert.equal(sent.dataUrl, 'data:image/png;base64,AAAA');
  same(sent.regions, [region]);
  // A screenshot is used once and then dropped.
  const again = await env.send({ type: 'sentinel-ocr', shot: shot.shot, viewportWidth: 1280, regions: [region] }, { tab, frameId: 0 });
  assert.match(again.error, /expired/);
});

test('no screenshot is taken when image reading is off', async () => {
  const env = setup(async () => new Response('{}'));
  await env.send({ type: 'sentinel-autoscan-set', pattern: 'https://chat.example/*', enabled: true });
  const reply = await env.send({ type: 'sentinel-capture' }, { tab, frameId: 0 });
  assert.match(reply.error, /off/);
  assert.equal(env.calls.captures.length, 0);
});

test('no screenshot is taken on a site where auto-scan is off, or from a frame', async () => {
  const env = setup(async () => new Response('{}'));
  await imageReady(env);
  const other = await env.send({ type: 'sentinel-capture' }, { tab: { ...tab, url: 'https://bank.example/' }, frameId: 0 });
  assert.match(other.error, /Auto-scan is off/);
  const frame = await env.send({ type: 'sentinel-capture' }, { tab, frameId: 3 });
  assert.match(frame.error, /Auto-scan is off/);
  assert.equal(env.calls.captures.length, 0);
});

test('image reading also works on pages covered by every-website auto-scan', async () => {
  const env = setup(async () => new Response('{}'), { openTabs: [] });
  await env.send({ type: 'sentinel-autoscan-every-site', enabled: true });
  env.store.ocrEnabled = true;
  const shot = await env.send({ type: 'sentinel-capture' }, { tab: { ...tab, url: 'https://anything.example/page' }, frameId: 0 });
  assert.ok(shot.shot);
});

test('no screenshot is taken when the tab is not the one on screen', async () => {
  const env = setup(async () => new Response('{}'), { activeTab: 99 });
  await imageReady(env);
  const reply = await env.send({ type: 'sentinel-capture' }, { tab, frameId: 0 });
  assert.match(reply.error, /not on screen/);
  assert.equal(env.calls.captures.length, 0);
});

test('a screenshot taken while the user switched tabs is discarded', async () => {
  let checks = 0;
  const env = setup(async () => new Response('{}'), { activeTab: () => (checks++ === 0 ? 4 : 5) });
  await imageReady(env);
  const reply = await env.send({ type: 'sentinel-capture' }, { tab, frameId: 0 });
  assert.match(reply.error, /not on screen/);
});

test('a screenshot cannot be read by another tab or with invalid regions', async () => {
  const env = setup(async () => new Response('{}'));
  await imageReady(env);
  const shot = await env.send({ type: 'sentinel-capture' }, { tab, frameId: 0 });
  const stolen = await env.send({ type: 'sentinel-ocr', shot: shot.shot, viewportWidth: 1280, regions: [region] }, { tab: { ...tab, id: 5 }, frameId: 0 });
  assert.match(stolen.error, /expired/);
  const shot2 = await env.send({ type: 'sentinel-capture' }, { tab, frameId: 0 });
  const bad = await env.send({ type: 'sentinel-ocr', shot: shot2.shot, viewportWidth: 1280, regions: [{ id: '0', x: -5, y: 0, w: 300, h: 120 }] }, { tab, frameId: 0 });
  assert.match(bad.error, /not valid/);
  assert.equal(env.calls.offscreen.length, 0);
});

test('removing all-sites access in Chrome turns image reading off', async () => {
  const env = setup(async () => new Response('{}'));
  await imageReady(env);
  await env.listeners.removed({ origins: ['<all_urls>'] });
  assert.equal(env.store.ocrEnabled, false);
  same(env.store.autoscanSites, ['https://chat.example/*']);
});

test('OCR helpers: regions, crops, text and QR codes', () => {
  const { ocr } = setup(async () => new Response('{}'));
  assert.equal(ocr.validRegions([]), null);
  assert.equal(ocr.validRegions(Array.from({ length: 5 }, (_, i) => ({ ...region, id: String(i) }))), null);
  assert.equal(ocr.validRegions([{ ...region, w: 10 }]), null);
  assert.equal(ocr.validRegions([{ ...region, id: 7 }]), null);
  same(ocr.validRegions([{ ...region, extra: 'x' }]), [region]);

  // A 2x (Retina) screenshot keeps its size; a 1x one is enlarged for OCR.
  same(ocr.planCrop(region, 2560, 1600, 1280), { sx: 20, sy: 40, sw: 600, sh: 240, upscale: 1 });
  same(ocr.planCrop(region, 1280, 800, 1280), { sx: 10, sy: 20, sw: 300, sh: 120, upscale: 2 });
  // Regions are clipped to the screenshot.
  assert.equal(ocr.planCrop({ ...region, x: 1270 }, 1280, 800, 1280), null);

  assert.equal(ocr.cleanText('  Pay the   fee\nnow to keep access  ', 82), 'Pay the fee now to keep access');
  assert.equal(ocr.cleanText('Pay the fee now to keep access', 20), '');
  assert.equal(ocr.cleanText('|| -- ~ ..', 90), '');

  same(ocr.describeQr('http://203.0.113.50/refund'), { url: 'http://203.0.113.50/refund' });
  assert.match(ocr.describeQr('upi://pay?pa=x@bank&pn=Prize%20Desk&am=499').text, /UPI payment to Prize Desk of 499/);
  assert.equal(ocr.describeQr('WIFI:S:home;T:WPA;P:secret;;'), null);
  assert.equal(ocr.describeQr('javascript:alert(1)'), null);
});
