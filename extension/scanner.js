// Sentinel auto-scan content script. It runs only on sites the user turned on in
// the popup. It reads visible text and links (never form fields or editable
// text), sends them to the local Sentinel app through the background worker,
// and marks risky items in an overlay without changing the page's own content.
// If the user also turns on "Read text in images", it asks the background worker
// to screenshot the visible tab and read text and QR codes in on-screen images
// on this computer (see offscreen.js).
(() => {
  if (globalThis.__sentinelAutoScan) return;
  const BLOCKS = 'p,li,td,th,dd,dt,blockquote,pre,figcaption,h1,h2,h3,h4,h5,h6,[role="listitem"],[role="article"],[role="row"],[role="gridcell"]';
  const SKIP = 'script,style,noscript,template,textarea,input,select,option,svg,canvas,[contenteditable=""],[contenteditable="true"],[aria-hidden="true"]';
  const MIN_TEXT = 20, MIN_SHORT_TEXT = 8, MAX_TEXT = 2000, BATCH = 25, FLUSH_MS = 700, RESCAN_MS = 800;
  const MAX_REGIONS = 4;           // images read per screenshot (matches ocr-utils.js)

  const units = new WeakMap();     // element -> { id, key }
  const seen = new Map();          // content key -> result (or 'pending')
  const elementsByKey = new Map(); // content key -> Set of elements
  const queue = new Map();         // content key -> item
  const markers = new Map();       // element -> { marker, result }
  const fromImages = new Map();    // content key -> { qr } for items read from images
  let nextId = 1, flushTimer = 0, rescanTimer = 0, pausedUntil = 0, stopped = false;

  const host = document.createElement('sentinel-autoscan');
  const root = host.attachShadow({ mode: 'closed' });
  const sheet = new CSSStyleSheet();
  sheet.replaceSync(`
    :host{all:initial}
    .layer{position:fixed;inset:0;pointer-events:none;z-index:2147483646}
    .mark{position:fixed;pointer-events:auto;cursor:pointer;width:22px;height:22px;border-radius:50%;border:1.5px solid #ece7de;
      box-shadow:0 2px 8px rgba(0,0,0,.45);font:italic 600 13px/18px ui-serif,"New York","Iowan Old Style",Georgia,serif;color:#141412;text-align:center;padding:0;
      transition:transform .25s cubic-bezier(.22,.9,.26,1)}
    .mark:hover{transform:scale(1.12)}
    .mark.high{background:#e0866f}.mark.review{background:#d8ad5c}
    .ring{position:fixed;pointer-events:none;border:1.5px solid;border-radius:8px}
    .ring.high{border-color:rgba(224,134,111,.75)}.ring.review{border-color:rgba(216,173,92,.7)}
    .panel{position:fixed;pointer-events:auto;max-width:320px;background:#181816;color:#ece7de;border:1px solid rgba(236,231,222,.13);border-radius:16px;
      box-shadow:0 24px 48px -20px rgba(0,0,0,.8),0 2px 6px rgba(0,0,0,.3);padding:16px 18px;
      font:13px/1.5 -apple-system,BlinkMacSystemFont,"SF Pro Text","Segoe UI",system-ui,sans-serif;-webkit-font-smoothing:antialiased}
    .panel strong{display:block;margin-bottom:6px;font:400 16px/1.3 ui-serif,"New York","Iowan Old Style",Georgia,serif;color:#e0866f}
    .panel.review strong{color:#d8ad5c}
    .panel ul{margin:8px 0;padding-left:16px;color:#bfb8ad}.panel li{margin:3px 0}
    .panel p{margin:8px 0;color:#8b857b;font-size:12px}
    .panel button{margin-top:6px;border:1px solid rgba(236,231,222,.2);background:transparent;color:#ece7de;border-radius:999px;padding:6px 14px;
      font:500 11.5px -apple-system,BlinkMacSystemFont,"Segoe UI",system-ui,sans-serif;cursor:pointer}
    .panel button:hover{border-color:#d4b48c}
  `);
  // A constructed stylesheet is not blocked by the page's style-src policy.
  root.adoptedStyleSheets = [sheet];
  const layer = document.createElement('div');
  layer.className = 'layer';
  root.append(layer);
  let panel = null;
  document.documentElement.append(host);

  function visible(element) {
    if (!element.isConnected) return false;
    if (element.checkVisibility && !element.checkVisibility({ checkOpacity: true, checkVisibilityCSS: true })) return false;
    const box = element.getBoundingClientRect();
    return box.width > 0 && box.height > 0;
  }

  // A text's unit is its *nearest* block: a known block element or any element that is not
  // displayed inline. (Jumping to a distant block such as Gmail's role="listitem" message made
  // the email body part of a container that was then dropped in favour of its header cells.)
  function unitFor(node, blockCache) {
    const parent = node.parentElement;
    if (!parent || parent.closest(SKIP) || host.contains(parent)) return null;
    const isBlock = element => {
      if (!blockCache.has(element)) {
        blockCache.set(element, element.matches(BLOCKS) || !getComputedStyle(element).display.startsWith('inline'));
      }
      return blockCache.get(element);
    };
    let element = parent;
    while (element && element !== document.body && !isBlock(element)) element = element.parentElement;
    return element && element !== document.body ? element : null;
  }

  function collect(scope) {
    const found = new Set();
    const blockCache = new Map();  // per pass: display can change between passes
    const walker = document.createTreeWalker(scope, NodeFilter.SHOW_TEXT, {
      acceptNode: node => node.nodeValue.trim().length > 2 ? NodeFilter.FILTER_ACCEPT : NodeFilter.FILTER_REJECT,
    });
    for (let node = walker.nextNode(); node; node = walker.nextNode()) {
      const unit = unitFor(node, blockCache);
      if (unit) found.add(unit);
    }
    // Keep the innermost units so one message is not also scanned inside its container.
    // (Walking up from each unit is linear; comparing every pair froze large pages such as Gmail.)
    const containers = new Set();
    for (const unit of found) {
      for (let up = unit.parentElement; up; up = up.parentElement) {
        if (found.has(up)) containers.add(up);
      }
    }
    return [...found].filter(element => !containers.has(element));
  }

  function itemFor(element) {
    const text = (element.innerText || '').replace(/\s+/g, ' ').trim().slice(0, MAX_TEXT);
    const link = element.matches('a[href]') ? element : element.querySelector('a[href^="http"]');
    const url = link && /^https?:/i.test(link.href) ? link.href : '';
    const linkText = link ? (link.innerText || '').trim().slice(0, 500) : '';
    // Short text is scanned when it has at least two words ("you will die", "you idiot"), so short
    // chat messages are not missed; single words such as menu labels are skipped. Short link-only
    // items are scanned when their link text names a site (possible mismatch).
    const words = text.split(' ').filter(Boolean).length;
    if (text.length < MIN_SHORT_TEXT || (text.length < MIN_TEXT && words < 2)) {
      if (!(url && /[a-z0-9-]\.[a-z]{2,}/i.test(linkText))) return null;
    }
    return { text, url, link_text: linkText };
  }

  // Scan units only when they are on screen.
  const onScreen = new IntersectionObserver(entries => {
    for (const entry of entries) {
      if (!entry.isIntersecting) continue;
      onScreen.unobserve(entry.target);
      enqueue(entry.target);
    }
  }, { rootMargin: '200px 0px' });

  function enqueue(element, item = itemFor(element), image = null) {
    if (stopped || !visible(element)) return;
    if (!item) return;
    const key = `${image ? 'image\u0000' : ''}${item.text}\u0000${item.url}\u0000${item.link_text}`;
    if (image) fromImages.set(key, image);
    units.set(element, { key });
    if (!elementsByKey.has(key)) elementsByKey.set(key, new Set());
    elementsByKey.get(key).add(element);
    const known = seen.get(key);
    if (known && known !== 'pending') return show(element, known);
    if (known === 'pending') return;
    seen.set(key, 'pending');
    queue.set(key, { id: String(nextId++), ...item });
    if (queue.size >= BATCH) flush(); else if (!flushTimer) flushTimer = setTimeout(flush, FLUSH_MS);
  }

  async function flush() {
    clearTimeout(flushTimer);
    flushTimer = 0;
    if (stopped || !queue.size) return;
    if (Date.now() < pausedUntil) { flushTimer = setTimeout(flush, pausedUntil - Date.now()); return; }
    const batch = [...queue.entries()].slice(0, BATCH);
    batch.forEach(([key]) => queue.delete(key));
    const keyById = new Map(batch.map(([key, item]) => [item.id, key]));
    let reply;
    try {
      reply = await toExtension({ type: 'sentinel-scan', items: batch.map(([, item]) => item) });
    } catch (error) {
      reply = { error: error.message };
    }
    if (stopped) return;
    if (!reply || reply.error) {
      // Sentinel is not running or rejected the batch: retry later; never show a safe verdict.
      batch.forEach(([key, item]) => queue.set(key, item));
      pausedUntil = Date.now() + 15000;
      flushTimer = setTimeout(flush, 15000);
      return;
    }
    for (const result of reply.results || []) {
      const key = keyById.get(result.id);
      if (!key) continue;
      result.method = reply.method;
      if (fromImages.has(key)) result.image = fromImages.get(key);
      seen.set(key, result);
      for (const element of elementsByKey.get(key) || []) show(element, result);
    }
    report();
    if (queue.size) flush();
  }

  function show(element, result) {
    if (result.severity === 'none' || markers.has(element) || !element.isConnected) return;
    const ring = document.createElement('div');
    ring.className = `ring ${result.severity}`;
    const marker = document.createElement('button');
    marker.className = `mark ${result.severity}`;
    marker.type = 'button';
    marker.textContent = '!';
    marker.title = 'Sentinel: click for details';
    marker.addEventListener('click', event => { event.stopPropagation(); openPanel(element, result, marker); });
    layer.append(ring, marker);
    markers.set(element, { marker, ring, result });
    place();
    report();
  }

  function openPanel(element, result, marker) {
    panel?.remove();
    panel = document.createElement('div');
    panel.className = `panel ${result.severity}`;
    const title = document.createElement('strong');
    title.textContent = result.severity === 'high' ? 'Sentinel: high concern' : 'Sentinel: worth a closer look';
    const list = document.createElement('ul');
    for (const fact of result.evidence) {
      const li = document.createElement('li');
      li.textContent = fact;
      list.append(li);
    }
    const action = document.createElement('p');
    action.textContent = result.action || '';
    const note = document.createElement('p');
    const read = document.createElement('p');
    if (result.image) {
      read.textContent = 'Read from an image on this computer (OCR); the text may contain reading mistakes.'
        + (result.image.qr ? ` Its QR code: ${result.image.qr}` : '');
    }
    const sources = ['evidence rules'];
    if (result.method?.includes('learned')) sources.push('an experimental text model trained on English SMS');
    if (result.community) sources.push('campaigns reported by other Sentinel users');
    note.textContent = `Based on ${sources.join(', ')}; this cannot prove the content is safe or fraudulent.`;
    const close = document.createElement('button');
    close.type = 'button';
    close.textContent = 'Close';
    close.addEventListener('click', () => { panel.remove(); panel = null; });
    panel.append(title, list, action, ...(result.image ? [read] : []), note, close);
    layer.append(panel);
    const box = marker.getBoundingClientRect();
    panel.style.top = `${Math.min(box.bottom + 6, innerHeight - panel.offsetHeight - 8)}px`;
    panel.style.left = `${Math.max(8, Math.min(box.left - 280, innerWidth - panel.offsetWidth - 8))}px`;
  }

  let placing = false;
  function place() {
    if (placing) return;
    placing = true;
    requestAnimationFrame(() => {
      placing = false;
      for (const [element, { marker, ring }] of markers) {
        if (!element.isConnected) { dropMarker(element); continue; }
        const box = element.getBoundingClientRect();
        const hidden = box.bottom < 0 || box.top > innerHeight || box.width === 0;
        marker.hidden = ring.hidden = hidden;
        if (hidden) continue;
        Object.assign(ring.style, { top: `${box.top - 3}px`, left: `${box.left - 3}px`, width: `${box.width + 6}px`, height: `${box.height + 6}px` });
        Object.assign(marker.style, { top: `${box.top - 9}px`, left: `${Math.min(box.right - 13, innerWidth - 26)}px` });
      }
    });
  }

  // Removing a marker (the message was deleted, edited or re-rendered) must lower the toolbar
  // count too; several removals in one pass send a single update.
  let reportTimer = 0;
  function dropMarker(element) {
    const old = markers.get(element);
    if (!old) return;
    old.marker.remove();
    old.ring.remove();
    markers.delete(element);
    if (!reportTimer) reportTimer = setTimeout(() => { reportTimer = 0; if (!stopped) report(); }, 0);
  }

  function report() {
    const counts = { high: 0, review: 0 };
    for (const { result } of markers.values()) counts[result.severity] += 1;
    toExtension({ type: 'sentinel-flags', ...counts });
  }

  function rescan(scope = document.body) {
    if (stopped || !scope) return;
    for (const element of collect(scope)) {
      const previous = units.get(element);
      if (previous) {
        const item = itemFor(element);
        const key = item && `${item.text}\u0000${item.url}\u0000${item.link_text}`;
        if (key === previous.key) continue;
        // The element's text changed: drop the old marker and scan it again.
        dropMarker(element);
        units.delete(element);
      }
      onScreen.observe(element);
    }
    rescanImages(scope);
  }

  // ---- Text in images (optional) ----
  // Images, canvases and inline SVGs that are mostly on screen are queued. A few
  // at a time, the overlay is hidden, the background worker screenshots the tab,
  // and the offscreen document reads text and QR codes in their regions. The
  // text found is then checked like any other page text.
  const IMAGES = 'img,canvas,svg';
  const MIN_IMAGE_W = 120, MIN_IMAGE_H = 40, MIN_SHOWN = 0.6, OCR_GAP_MS = 400, OCR_RETRY_MS = 10000;
  let ocrOn = false, ocrBusy = false, ocrTimer = 0, nextImage = 1;
  let imageKeyOf = new WeakMap();  // element -> image key last queued
  const elementKeys = new WeakMap(); // canvas/svg element -> stable key
  const imageResults = new Map();  // image key -> scan item, or null when nothing was found
  const imageQueue = new Set();
  const imagesOnScreen = new IntersectionObserver(entries => {
    for (const entry of entries) {
      if (entry.isIntersecting && shownRegion(entry.target)) imageQueue.add(entry.target);
    }
    scheduleImages(0);
  }, { threshold: [0, 0.25, 0.5, 0.6, 0.75, 1] });

  function imageKey(element) {
    if (element.tagName === 'IMG') return `img\u0000${element.currentSrc || element.src}`;
    if (!elementKeys.has(element)) elementKeys.set(element, `element\u0000${nextImage++}`);
    return elementKeys.get(element);
  }

  function imageCandidate(element) {
    if (host.contains(element) || element.closest('[aria-hidden="true"]')) return false;
    if (element.tagName.toLowerCase() === 'svg' && element.parentElement?.closest('svg')) return false;
    if (element.tagName === 'IMG' && !(element.complete && element.naturalWidth > 0)) {
      element.addEventListener('load', () => rescanImages(element), { once: true });
      return false;
    }
    const box = element.getBoundingClientRect();
    return box.width >= MIN_IMAGE_W && box.height >= MIN_IMAGE_H && visible(element);
  }

  function rescanImages(scope = document.body) {
    if (stopped || !ocrOn || !scope) return;
    const found = scope.matches?.(IMAGES) ? [scope] : [...scope.querySelectorAll(IMAGES)];
    for (const element of found) {
      if (!imageCandidate(element)) continue;
      const key = imageKey(element);
      if (imageKeyOf.get(element) === key) continue;
      // A new or changed image (for example a carousel): drop any old marker.
      dropMarker(element);
      imageKeyOf.set(element, key);
      imagesOnScreen.observe(element);
    }
  }

  // The part of an element on screen, in CSS pixels, if enough of it shows.
  function shownRegion(element) {
    if (!element.isConnected) return null;
    const box = element.getBoundingClientRect();
    const width = document.documentElement.clientWidth || innerWidth;
    const height = document.documentElement.clientHeight || innerHeight;
    const x = Math.max(0, box.left), y = Math.max(0, box.top);
    const w = Math.min(width, box.right) - x, h = Math.min(height, box.bottom) - y;
    if (w <= 0 || h <= 0) return null;
    // Mostly on screen, or (for images taller than the window) filling most of it.
    if ((w * h) / (box.width * box.height) < MIN_SHOWN && w * h < MIN_SHOWN * width * height) return null;
    return { x: Math.round(x), y: Math.round(y), w: Math.round(w), h: Math.round(h) };
  }

  function scheduleImages(delay) {
    if (stopped || !ocrOn || ocrBusy || ocrTimer || !imageQueue.size) return;
    ocrTimer = setTimeout(() => { ocrTimer = 0; readImages(); }, delay);
  }

  function imageItem(read) {
    const qr = read.qr || null;
    const text = [read.text, qr?.text].filter(Boolean).join(' ').slice(0, MAX_TEXT);
    if (text.length < MIN_TEXT && !qr?.url) return null;
    return { item: { text, url: qr?.url || '', link_text: '' }, image: { qr: qr?.url || '' } };
  }

  function done(element, key, found) {
    imageQueue.delete(element);
    imagesOnScreen.unobserve(element);
    if (found) enqueue(element, found.item, found.image);
  }

  const frames = () => new Promise(resolve => requestAnimationFrame(() => requestAnimationFrame(resolve)));
  async function ask(message) {
    return toExtension(message);
  }

  async function readImages() {
    if (stopped || !ocrOn || ocrBusy) return;
    if (document.visibilityState !== 'visible') { ocrTimer = setTimeout(() => { ocrTimer = 0; readImages(); }, OCR_RETRY_MS); return; }
    const batch = [];
    for (const element of [...imageQueue]) {
      const key = imageKey(element);
      if (!element.isConnected || imageKeyOf.get(element) !== key) { imageQueue.delete(element); continue; }
      if (imageResults.has(key)) { done(element, key, imageResults.get(key)); continue; }
      if (shownRegion(element)) batch.push({ element, key });
      if (batch.length >= MAX_REGIONS) break;
    }
    if (!batch.length) return;
    ocrBusy = true;
    let retry = false;
    try {
      // Hide Sentinel's own markers so they are not read as part of the image.
      layer.style.visibility = 'hidden';
      await frames();
      const regions = [];
      batch.forEach(({ element }, index) => {
        const region = shownRegion(element);
        if (region) regions.push({ id: String(index), ...region });
      });
      if (!regions.length) return;
      const shot = await ask({ type: 'sentinel-capture' });
      layer.style.visibility = '';
      if (!shot?.shot) { retry = true; return; }
      const reply = await ask({ type: 'sentinel-ocr', shot: shot.shot, viewportWidth: innerWidth, regions });
      if (!reply || reply.error) { retry = true; return; }
      for (const read of reply.results || []) {
        const entry = batch[Number(read.id)];
        if (!entry) continue;
        const found = imageItem(read);
        imageResults.set(entry.key, found);
        if (!stopped) done(entry.element, entry.key, found);
      }
    } finally {
      layer.style.visibility = '';
      ocrBusy = false;
      scheduleImages(retry ? OCR_RETRY_MS : OCR_GAP_MS);
    }
  }

  function setImageReading(on) {
    ocrOn = on;
    if (on) return rescanImages();
    clearTimeout(ocrTimer);
    ocrTimer = 0;
    imageQueue.clear();
    imagesOnScreen.disconnect();
    imageKeyOf = new WeakMap();
  }

  const onStorage = (changes, area) => {
    if (area === 'local' && changes.ocrEnabled) setImageReading(Boolean(changes.ocrEnabled.newValue));
  };

  // Rescan after the page changes. A burst of changes is grouped (RESCAN_MS of quiet), but pages
  // that never go quiet (Gmail, chat apps, live feeds) still get a rescan every MAX_RESCAN_WAIT_MS.
  // Only the changed parts are rescanned, unless so much changed that a full pass is simpler.
  const MAX_RESCAN_WAIT_MS = 1500, MAX_ROOTS = 300;
  const changedRoots = new Set();
  let firstChange = 0;
  function runRescan() {
    rescanTimer = 0;
    firstChange = 0;
    const roots = [...changedRoots].filter(node => node.isConnected);
    changedRoots.clear();
    if (roots.length > MAX_ROOTS || roots.includes(document.body)) {
      rescan();
    } else {
      const rootSet = new Set(roots);
      for (const root of roots) {
        let covered = false;  // skip roots inside another changed root
        for (let up = root.parentElement; up; up = up.parentElement) if (rootSet.has(up)) { covered = true; break; }
        if (!covered) rescan(root);
      }
    }
    place();
  }
  const changes = new MutationObserver(records => {
    for (const record of records) {
      const node = record.type === 'characterData' ? record.target.parentElement : record.target;
      if (node && !host.contains(node)) changedRoots.add(node);
    }
    if (!changedRoots.size) return;
    const now = Date.now();
    if (!firstChange) firstChange = now;
    clearTimeout(rescanTimer);
    rescanTimer = setTimeout(runRescan, Math.max(0, Math.min(RESCAN_MS, firstChange + MAX_RESCAN_WAIT_MS - now)));
  });

  // When the extension is reloaded or updated, Chrome cuts this copy of the scanner off from it
  // (chrome.runtime disappears). Shut down cleanly instead of throwing on every send; the new
  // version is injected into this tab by the background worker.
  function extensionAlive() {
    try { return Boolean(globalThis.chrome?.runtime?.id); } catch { return false; }
  }

  async function toExtension(message) {
    if (!extensionAlive()) {
      stop();
      return { error: 'Sentinel was reloaded; the new version takes over this page.' };
    }
    try {
      return await chrome.runtime.sendMessage(message);
    } catch (error) {
      if (!extensionAlive()) stop();
      return { error: error.message };
    }
  }

  function stop() {
    if (stopped) return;
    stopped = true;
    changes.disconnect();
    onScreen.disconnect();
    imagesOnScreen.disconnect();
    try { chrome.storage.onChanged.removeListener(onStorage); } catch { /* cut off from the extension */ }
    clearTimeout(ocrTimer);
    clearTimeout(flushTimer);
    clearTimeout(rescanTimer);
    removeEventListener('scroll', place, true);
    removeEventListener('resize', place);
    host.remove();
    delete globalThis.__sentinelAutoScan;
  }

  chrome.runtime.onMessage.addListener(message => {
    if (message?.type === 'sentinel-stop') stop();
  });
  addEventListener('scroll', place, { capture: true, passive: true });
  addEventListener('resize', place, { passive: true });
  document.addEventListener('click', event => { if (panel && !event.composedPath().includes(host)) { panel.remove(); panel = null; } });
  changes.observe(document.body, { childList: true, subtree: true, characterData: true });
  globalThis.__sentinelAutoScan = { stop };
  rescan();
  chrome.storage.onChanged.addListener(onStorage);
  chrome.storage.local.get('ocrEnabled').then(({ ocrEnabled }) => { if (ocrEnabled && !stopped) setImageReading(true); }, () => {});
})();
