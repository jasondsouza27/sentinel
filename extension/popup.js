const ENDPOINT = 'http://127.0.0.1:8787';
const $ = (id) => document.getElementById(id);
let submitted = null;
let saved = false;

function line(parent, tag, text) {
  const element = document.createElement(tag);
  element.textContent = text;
  parent.append(element);
  return element;
}

async function request(path, body) {
  const response = await fetch(ENDPOINT + path, {
    method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify(body),
  });
  const value = await response.json();
  if (!response.ok) throw new Error(value.error || 'The check failed');
  return value;
}

function draw(name, item, profile = false, paired = false) {
  const div = document.createElement('div');
  div.className = 'finding';
  const category = paired ? (item.state === 'available' ? item.category : item.state)
    : profile ? item.status : item.level;
  line(div, 'strong', `${name}: ${category.replaceAll('_', ' ')}`);
  if (item.evidence?.length) {
    const list = document.createElement('ul');
    item.evidence.forEach((fact) => line(list, 'li', fact));
    div.append(list);
  }
  if (paired && item.unavailable_checks?.length) {
    item.unavailable_checks.forEach((check) => line(div, 'p', `Could not check: ${check}`));
  }
  if (paired && item.uncertainty) line(div, 'p', item.uncertainty);
  line(div, 'p', item.action);
  return div;
}

$('selection').onclick = async () => {
  $('error').textContent = '';
  try {
    const [tab] = await chrome.tabs.query({ active: true, currentWindow: true });
    const [selection] = await chrome.scripting.executeScript({ target: { tabId: tab.id }, func: () => window.getSelection()?.toString() || '' });
    if (!selection.result.trim()) throw new Error('Select text on the page first.');
    $('message').value = selection.result.trim();
  } catch (error) { $('error').textContent = error.message || 'This page cannot be read by the extension.'; }
};

$('check').onclick = async () => {
  $('error').textContent = '';
  submitted = { message: $('message').value.trim(), url: $('url').value.trim() };
  saved = false;
  $('save').disabled = false;
  $('save-status').textContent = '';
  try {
    const result = await request('/api/analyze', submitted);
    const cards = [
      draw('Message & link', result.fraud),
      draw('Harmful content', result.harmful_content),
      draw('Profile', result.profile, true),
    ];
    if (result.paired_assessment) cards.push(draw('Paired message–link model', result.paired_assessment, false, true));
    $('findings').replaceChildren(...cards);
    $('result').hidden = false;
  } catch (error) {
    $('result').hidden = true;
    $('error').textContent = error.message.includes('fetch') ? 'Start the local Sentinel app, then retry.' : error.message;
  }
};

$('save').onclick = async () => {
  if (!submitted || saved) return;
  try {
    await request('/api/cases', { input: submitted });
    saved = true;
    $('save').disabled = true;
    $('save-status').textContent = 'Saved in the local app.';
  } catch (error) { $('save-status').textContent = error.message; }
};

$('open').onclick = () => chrome.tabs.create({ url: ENDPOINT });

(async () => {
  const { pendingCheck } = await chrome.storage.session.get('pendingCheck');
  if (!pendingCheck) return;
  if (pendingCheck.message) $('message').value = pendingCheck.message;
  if (pendingCheck.url) $('url').value = pendingCheck.url;
  await chrome.storage.session.remove('pendingCheck');
})();
