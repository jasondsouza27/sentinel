// Popup control for auto-scan on the current site. Turning it on asks Chrome for
// access to that site only; turning it off stops the scanner and gives access back.
//
// "Read text in images" applies to every auto-scan site. Chrome lets an extension
// screenshot a tab only with access to all sites (or right after a click on it),
// so turning it on asks for that access; screenshots are still taken only on
// auto-scan sites, read on this computer and never saved. Turning it off gives
// that access back.
(async () => {
  const ALL = { origins: ['<all_urls>'] };
  const ocr = document.getElementById('ocr');
  const ocrStatus = document.getElementById('ocr-status');
  const { ocrEnabled = false } = await chrome.storage.local.get('ocrEnabled');
  ocr.checked = Boolean(ocrEnabled) && await chrome.permissions.contains(ALL);
  const describeOcr = () => {
    ocrStatus.textContent = ocr.checked
      ? 'On for auto-scan sites. Screenshots are read on this computer and never saved.'
      : 'Off. Turning it on asks Chrome to allow screenshots.';
  };
  describeOcr();
  ocr.addEventListener('change', async () => {
    const enabled = ocr.checked;
    ocr.disabled = true;
    try {
      // Must run directly in the click handler so Chrome shows its permission prompt.
      if (enabled && !await chrome.permissions.request(ALL)) {
        ocr.checked = false;
        ocrStatus.textContent = 'Chrome did not allow screenshots.';
        return;
      }
      await chrome.storage.local.set({ ocrEnabled: enabled });
      if (!enabled) await chrome.permissions.remove(ALL).catch(() => {});
      describeOcr();
    } catch (error) {
      ocr.checked = !enabled;
      ocrStatus.textContent = error.message || 'Reading text in images could not be changed.';
    } finally {
      ocr.disabled = false;
    }
  });
})();

// "Auto-scan every website": checks visible text on every page automatically, so nothing has to be
// selected. Chrome asks once for access to all sites; turning it off gives that access back.
const EVERY_SITE = ['http://*/*', 'https://*/*'];

async function everySiteOn() {
  const { autoscanSites = [] } = await chrome.storage.local.get('autoscanSites');
  return EVERY_SITE.every(p => autoscanSites.includes(p)) && await chrome.permissions.contains({ origins: EVERY_SITE });
}

(async () => {
  const all = document.getElementById('autoscan-all');
  const status = document.getElementById('autoscan-all-status');
  all.checked = await everySiteOn();
  const describe = () => {
    status.textContent = all.checked
      ? 'On: every page is checked automatically. Text goes only to Sentinel on this computer.'
      : 'Off. Turn on to check every page without selecting text.';
  };
  describe();
  all.addEventListener('change', async () => {
    const enabled = all.checked;
    all.disabled = true;
    try {
      // Must run directly in the click handler so Chrome shows its permission prompt.
      if (enabled && !await chrome.permissions.request({ origins: EVERY_SITE })) {
        all.checked = false;
        status.textContent = 'Chrome access to all sites was not granted.';
        return;
      }
      const reply = await chrome.runtime.sendMessage({ type: 'sentinel-autoscan-every-site', enabled });
      if (reply?.error) throw new Error(reply.error);
      if (!enabled) await chrome.permissions.remove({ origins: EVERY_SITE }).catch(() => {});
      describe();
      document.dispatchEvent(new Event('sentinel-every-site-changed'));
    } catch (error) {
      all.checked = !enabled;
      status.textContent = error.message || 'Auto-scan could not be changed.';
    } finally {
      all.disabled = false;
    }
  });
})();

(async () => {
  const toggle = document.getElementById('autoscan');
  const status = document.getElementById('autoscan-status');
  const [tab] = await chrome.tabs.query({ active: true, currentWindow: true });
  let pattern = null;
  try {
    const url = new URL(tab?.url || '');
    if (url.protocol === 'http:' || url.protocol === 'https:') pattern = `${url.protocol}//${url.hostname}/*`;
  } catch { /* Not a web page. */ }
  if (!pattern) {
    toggle.disabled = true;
    status.textContent = 'Auto-scan works on web pages only.';
    return;
  }
  const host = new URL(tab.url).hostname;
  const refresh = async () => {
    const { autoscanSites = [] } = await chrome.storage.local.get('autoscanSites');
    if (await everySiteOn()) {  // covered by "every website"; this switch has nothing to add
      toggle.checked = true;
      toggle.disabled = true;
      status.textContent = `Scanning ${host} (every website is on).`;
      return;
    }
    toggle.disabled = false;
    toggle.checked = autoscanSites.includes(pattern) && await chrome.permissions.contains({ origins: [pattern] });
    describe();
  };
  const describe = () => {
    status.textContent = toggle.checked
      ? `Scanning visible text on ${host}. Nothing is saved.`
      : `Off for ${host}.`;
  };
  await refresh();
  document.addEventListener('sentinel-every-site-changed', refresh);

  toggle.addEventListener('change', async () => {
    const enabled = toggle.checked;
    toggle.disabled = true;
    try {
      // Must run directly in the click handler so Chrome shows its permission prompt.
      if (enabled && !await chrome.permissions.request({ origins: [pattern] })) {
        toggle.checked = false;
        status.textContent = 'Chrome access to this site was not granted.';
        return;
      }
      const reply = await chrome.runtime.sendMessage({ type: 'sentinel-autoscan-set', pattern, enabled, tabId: tab.id });
      if (reply?.error) throw new Error(reply.error);
      // The Sentinel app's own address is a required permission and cannot be removed.
      if (!enabled && pattern !== 'http://127.0.0.1/*') await chrome.permissions.remove({ origins: [pattern] }).catch(() => {});
      describe();
    } catch (error) {
      toggle.checked = !enabled;
      status.textContent = error.message || 'Auto-scan could not be changed.';
    } finally {
      toggle.disabled = false;
    }
  });
})();
