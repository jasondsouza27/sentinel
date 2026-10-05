chrome.runtime.onInstalled.addListener(() => {
  chrome.contextMenus.create({ id: 'sentinel-selection', title: 'Check selected text with Sentinel', contexts: ['selection'] });
  chrome.contextMenus.create({ id: 'sentinel-link', title: 'Check link with Sentinel', contexts: ['link'] });
});

chrome.contextMenus.onClicked.addListener(async (info) => {
  const submitted = info.menuItemId === 'sentinel-link'
    ? { url: info.linkUrl || '' }
    : { message: info.selectionText || '' };
  await chrome.storage.session.set({ pendingCheck: submitted });
  try { await chrome.action.openPopup(); } catch (_) { /* The toolbar popup can be opened manually. */ }
});
