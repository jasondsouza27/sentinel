importScripts('ocr-utils.js');

const ENDPOINT = 'http://127.0.0.1:8787';
const SCRIPT_ID = 'sentinel-autoscan';
const SCAN_TIMEOUT_MS = 8000;
const ALL_SITES = '<all_urls>';
// "Auto-scan every website" is stored as these two patterns in the auto-scan site list.
const EVERY_SITE = ['http://*/*', 'https://*/*'];
const CAPTURE_GAP_MS = 1000;      // Chrome allows about two screenshots per second
const SHOT_TTL_MS = 30000;
const OFFSCREEN_IDLE_MS = 120000;
const OCR_TIMEOUT_MS = 90000;     // a first run also starts the OCR engine

chrome.runtime.onInstalled.addListener(() => {
  chrome.contextMenus.create({ id: 'sentinel-selection', title: 'Check selected text with Sentinel', contexts: ['selection'] });
  chrome.contextMenus.create({ id: 'sentinel-link', title: 'Check link with Sentinel', contexts: ['link'] });
  reinjectOpenTabs().catch(() => {});
});

// After the extension is reloaded or updated, scanners already running in open tabs are cut off
// from it and stop themselves. Give those tabs the new scanner so they keep being checked
// without the user reloading every page.
async function reinjectOpenTabs() {
  const patterns = await sites();
  if (!patterns.length) return;
  for (const tab of await chrome.tabs.query({ url: patterns })) {
    chrome.scripting.executeScript({ target: { tabId: tab.id }, files: ['scanner.js'] }).catch(() => {});
  }
}

chrome.contextMenus.onClicked.addListener(async (info) => {
  const submitted = info.menuItemId === 'sentinel-link'
    ? { url: info.linkUrl || '' }
    : { message: info.selectionText || '' };
  await chrome.storage.session.set({ pendingCheck: submitted });
  try { await chrome.action.openPopup(); } catch (_) { /* The toolbar popup can be opened manually. */ }
});

// Auto-scan sites are stored as match patterns such as "https://mail.example/*".
async function sites() {
  const { autoscanSites } = await chrome.storage.local.get('autoscanSites');
  return Array.isArray(autoscanSites) ? autoscanSites : [];
}

// True when auto-scan covers a page pattern, either by its own entry or by "every website".
async function covers(pattern) {
  const list = await sites();
  return list.includes(pattern) || list.includes(pattern.startsWith('https:') ? 'https://*/*' : 'http://*/*');
}

// Turn "every website" on or off and apply it to tabs that are already open.
async function setEverySite(enabled) {
  const current = await sites();
  const next = enabled ? [...new Set([...current, ...EVERY_SITE])] : current.filter(site => !EVERY_SITE.includes(site));
  await chrome.storage.local.set({ autoscanSites: next });
  await syncRegistration(next);
  const tabs = await chrome.tabs.query({ url: EVERY_SITE });
  for (const tab of tabs) {
    if (enabled) {
      chrome.scripting.executeScript({ target: { tabId: tab.id }, files: ['scanner.js'] }).catch(() => {});
    } else if (!next.includes(patternFor(tab.url))) {  // sites turned on individually keep scanning
      chrome.tabs.sendMessage(tab.id, { type: 'sentinel-stop' }).catch(() => {});
      chrome.action.setBadgeText({ tabId: tab.id, text: '' });
    }
  }
}

async function syncRegistration(patterns) {
  const existing = await chrome.scripting.getRegisteredContentScripts({ ids: [SCRIPT_ID] });
  if (!patterns.length) {
    if (existing.length) await chrome.scripting.unregisterContentScripts({ ids: [SCRIPT_ID] });
    return;
  }
  const script = { id: SCRIPT_ID, matches: patterns, js: ['scanner.js'], runAt: 'document_idle', persistAcrossSessions: true };
  if (existing.length) await chrome.scripting.updateContentScripts([script]);
  else await chrome.scripting.registerContentScripts([script]);
}

async function setSite(pattern, enabled, tabId) {
  const current = await sites();
  const next = enabled ? [...new Set([...current, pattern])] : current.filter(site => site !== pattern);
  await chrome.storage.local.set({ autoscanSites: next });
  await syncRegistration(next);
  if (tabId == null) return;
  if (enabled) {
    await chrome.scripting.executeScript({ target: { tabId }, files: ['scanner.js'] });
  } else {
    chrome.tabs.sendMessage(tabId, { type: 'sentinel-stop' }).catch(() => {});
    chrome.action.setBadgeText({ tabId, text: '' });
  }
}

async function scan(items) {
  const controller = new AbortController();
  const timer = setTimeout(() => controller.abort(), SCAN_TIMEOUT_MS);
  try {
    const response = await fetch(ENDPOINT + '/api/scan', {
      method: 'POST', headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ items }), signal: controller.signal,
    });
    const value = await response.json();
    return response.ok ? value : { error: value.error || 'The scan failed' };
  } catch {
    return { error: 'Start the local Sentinel app to use auto-scan.' };
  } finally {
    clearTimeout(timer);
  }
}

// ---- Text in images: screenshot -> offscreen OCR, all on this computer ----
const shots = new Map();          // shot id -> { tabId, dataUrl }
let nextShot = 1, lastCapture = 0, creating = null, ocrJobs = 0, idleTimer = 0;

function patternFor(url) {
  try {
    const parsed = new URL(url || '');
    if (parsed.protocol === 'http:' || parsed.protocol === 'https:') return `${parsed.protocol}//${parsed.hostname}/*`;
  } catch { /* Not a web page. */ }
  return null;
}

async function activeTabId(windowId) {
  const [active] = await chrome.tabs.query({ active: true, windowId });
  return active?.id;
}

// Screenshot the visible tab, only for the top frame of an auto-scan site with
// image reading on, and only while that tab is the one on screen.
async function capture(tab, frameId) {
  const { ocrEnabled } = await chrome.storage.local.get('ocrEnabled');
  if (!ocrEnabled) return { error: 'Reading text in images is off.' };
  const pattern = patternFor(tab.url);
  if (frameId !== 0 || !pattern || !(await covers(pattern))) return { error: 'Auto-scan is off for this page.' };
  // Reserve a capture slot first, so requests from several tabs are spaced out.
  const slot = Math.max(Date.now(), lastCapture + CAPTURE_GAP_MS);
  lastCapture = slot;
  if (slot > Date.now()) await new Promise(resolve => setTimeout(resolve, slot - Date.now()));
  if (await activeTabId(tab.windowId) !== tab.id) return { error: 'The tab is not on screen.' };
  let dataUrl;
  try {
    dataUrl = await chrome.tabs.captureVisibleTab(tab.windowId, { format: 'png' });
  } catch (error) {
    return { error: error.message || 'The screenshot failed.' };
  }
  // The user may have switched tabs while the screenshot was taken.
  if (await activeTabId(tab.windowId) !== tab.id) return { error: 'The tab is not on screen.' };
  const shot = String(nextShot++);
  shots.set(shot, { tabId: tab.id, dataUrl });
  setTimeout(() => shots.delete(shot), SHOT_TTL_MS);
  return { shot };
}

async function ensureOffscreen() {
  const open = chrome.runtime.getContexts
    ? (await chrome.runtime.getContexts({ contextTypes: ['OFFSCREEN_DOCUMENT'] })).length > 0
    : false;
  if (open) return;
  creating ||= chrome.offscreen.createDocument({
    url: 'offscreen.html', reasons: ['WORKERS'],
    justification: 'Reads text in screenshots of sites the user turned on, on this computer.',
  }).finally(() => { creating = null; });
  await creating;
}

function closeWhenIdle() {
  clearTimeout(idleTimer);
  idleTimer = setTimeout(() => {
    if (!ocrJobs) chrome.offscreen.closeDocument().catch(() => {});
  }, OFFSCREEN_IDLE_MS);
}

async function readShot(tab, message) {
  const shot = shots.get(message.shot);
  if (!shot || shot.tabId !== tab.id) return { error: 'The screenshot expired.' };
  shots.delete(message.shot);
  const regions = SentinelOcr.validRegions(message.regions);
  if (!regions || !(message.viewportWidth > 0)) return { error: 'The image regions are not valid.' };
  ocrJobs += 1;
  try {
    await ensureOffscreen();
    let timer;
    const reply = await Promise.race([
      chrome.runtime.sendMessage({
        target: 'sentinel-offscreen', type: 'ocr', dataUrl: shot.dataUrl, viewportWidth: message.viewportWidth, regions,
      }),
      new Promise(resolve => { timer = setTimeout(() => resolve({ error: 'Reading text in images timed out.' }), OCR_TIMEOUT_MS); }),
    ]).finally(() => clearTimeout(timer));
    return reply || { error: 'Text in images could not be read.' };
  } catch (error) {
    return { error: error.message || 'Text in images could not be read.' };
  } finally {
    ocrJobs -= 1;
    closeWhenIdle();
  }
}

chrome.runtime.onMessage.addListener((message, sender, reply) => {
  if (message?.type === 'sentinel-capture' && sender.tab) {
    capture(sender.tab, sender.frameId).then(reply);
    return true;
  }
  if (message?.type === 'sentinel-ocr' && sender.tab) {
    readShot(sender.tab, message).then(reply);
    return true;
  }
  if (message?.type === 'sentinel-scan' && sender.tab) {
    scan(message.items).then(reply);
    return true;
  }
  if (message?.type === 'sentinel-flags' && sender.tab) {
    const total = (message.high || 0) + (message.review || 0);
    chrome.action.setBadgeText({ tabId: sender.tab.id, text: total ? String(total) : '' });
    chrome.action.setBadgeBackgroundColor({ tabId: sender.tab.id, color: message.high ? '#c4644d' : '#b8862e' });
    return false;
  }
  if (message?.type === 'sentinel-autoscan-every-site' && !sender.tab) {
    setEverySite(Boolean(message.enabled)).then(() => reply({ ok: true }), error => reply({ error: error.message }));
    return true;
  }
  if (message?.type === 'sentinel-autoscan-set' && !sender.tab) {
    setSite(message.pattern, message.enabled, message.tabId).then(() => reply({ ok: true }),
      error => reply({ error: error.message }));
    return true;
  }
  return false;
});

// If the user removes a site's access in Chrome settings, stop scanning it.
chrome.permissions.onRemoved.addListener(async ({ origins = [] }) => {
  if (origins.includes(ALL_SITES)) await chrome.storage.local.set({ ocrEnabled: false });
  const remaining = (await sites()).filter(site => !origins.includes(site));
  await chrome.storage.local.set({ autoscanSites: remaining });
  await syncRegistration(remaining);
});
