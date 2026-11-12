const ENDPOINT = 'http://127.0.0.1:8787';
const $ = id => document.getElementById(id);
let currentSnapshot = null;
let saved = false;
let analysisVersion = 0;
const pendingSaves = new Set();

function line(parent, tag, text) {
  const element = document.createElement(tag);
  element.textContent = text;
  parent.append(element);
  return element;
}

async function request(path, body) {
  let response;
  try {
    response = await fetch(ENDPOINT + path, {
      method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify(body),
    });
  } catch {
    throw new Error('Start the local Sentinel app, then retry.');
  }
  const value = await response.json();
  if (!response.ok) throw new Error(value.error || 'The check failed');
  return value;
}

// Colour family for a finding card; presentation only.
function tone(category) {
  if (['high', 'smishing'].includes(category)) return 'high';
  if (['review', 'indicators_for_review', 'spam'].includes(category)) return 'review';
  if (['low_observed_concern', 'not_flagged', 'ham'].includes(category)) return 'low';
  return 'neutral';
}

function draw(name, item, profile = false, paired = false) {
  const div = document.createElement('div');
  const category = paired ? (item.state === 'available' ? item.category : item.state)
    : profile ? item.status : item.level;
  div.className = `finding tone-${tone(category)}`;
  line(div, 'strong', `${name}: ${category.replaceAll('_', ' ')}`);
  if (item.evidence?.length) {
    const list = document.createElement('ul');
    item.evidence.forEach(fact => line(list, 'li', fact));
    div.append(list);
  }
  if (paired && item.unavailable_checks?.length) item.unavailable_checks.forEach(check => line(div, 'p', `Could not check: ${check}`));
  if (paired && item.uncertainty) line(div, 'p', item.uncertainty);
  line(div, 'p', item.action);
  return div;
}

function drawHarm(item) {
  const card = draw('English directed-abuse model', item, false, true);
  line(card, 'p', `Learned category: ${String(item.category).replaceAll('_', ' ')}.`);
  const coverage = item.coverage || {};
  if (coverage.used_context_turns) line(card, 'p', `Context: ${coverage.used_context_turns} preceding turns used.`);
  else line(card, 'p', 'Context unavailable: target-only assessment.');
  if (coverage.language_assumed) line(card, 'p', 'Language: English is assumed.');
  else if (coverage.language) line(card, 'p', `Declared language: ${coverage.language}.`);
  if (Array.isArray(item.model_contributions)) {
    item.model_contributions.forEach(value => line(card, 'p', `Model contribution: ${typeof value === 'string' ? value : JSON.stringify(value)}`));
  }
  const probability = item.calibrated_probability;
  if (['complete', 'degraded'].includes(item.state) && typeof probability === 'number' && Number.isFinite(probability) && probability >= 0 && probability <= 1) {
    line(card, 'p', `Calibrated probability: ${(probability * 100).toFixed(1)}% on the evaluated distribution.`);
  }
  return card;
}

function drawTextModel(item, message) {
  const card = document.createElement('div');
  card.className = 'finding';
  if (item.state !== 'available') {
    line(card, 'strong', 'Learned scam-text model: unavailable');
    line(card, 'p', 'Rules still apply.');
    return card;
  }
  card.className = `finding tone-${tone(item.category)}`;
  line(card, 'strong', `Learned scam-text model: ${item.label}`);
  line(card, 'p', `Scam probability ${(item.calibrated_probability * 100).toFixed(1)}% (calibrated; threshold ${(item.threshold * 100).toFixed(1)}%).`);
  const marks = (item.explanation || []).filter(c => message.slice(c.start, c.end) === c.word).sort((a, b) => a.start - b.start);
  if (marks.length) {
    const text = document.createElement('p');
    text.className = 'highlighted';
    let cursor = 0;
    for (const c of marks) {
      if (c.start < cursor) continue;
      line(text, 'span', message.slice(cursor, c.start));
      line(text, 'mark', c.word);
      cursor = c.end;
    }
    line(text, 'span', message.slice(cursor));
    card.append(text);
  }
  line(card, 'p', item.action);
  return card;
}

function setChecking(busy) { $('check').disabled = busy; }
function invalidate() {
  analysisVersion += 1;
  currentSnapshot = null;
  saved = false;
  $('result').hidden = true;
  $('findings').replaceChildren();
  $('save').disabled = true;
  $('save-status').textContent = '';
  $('error').textContent = '';
  setChecking(false);
}
for (const id of ['message', 'url']) $(id).addEventListener('input', invalidate);
$('save').disabled = true;

$('selection').onclick = async () => {
  invalidate();
  const version = analysisVersion;
  try {
    const [tab] = await chrome.tabs.query({ active: true, currentWindow: true });
    const [selection] = await chrome.scripting.executeScript({ target: { tabId: tab.id }, func: () => window.getSelection()?.toString() || '' });
    if (version !== analysisVersion) return;
    if (!selection.result.trim()) throw new Error('Select text on the page first.');
    $('message').value = selection.result.trim();
  } catch (error) {
    if (version === analysisVersion) $('error').textContent = error.message || 'This page cannot be read by the extension.';
  }
};

$('check').onclick = async () => {
  invalidate();
  const version = analysisVersion;
  const input = { message: $('message').value.trim(), url: $('url').value.trim() };
  setChecking(true);
  try {
    const response = await request('/api/analyze', input);
    if (version !== analysisVersion) return;
    const { assessment_receipt, ...result } = response;
    const cards = [draw('Message & link', result.fraud),
      draw('Harmful content observations', result.harmful_content), draw('Profile', result.profile, true)];
    if (result.paired_assessment) cards.push(draw('Paired message–link model', result.paired_assessment, false, true));
    if (result.harm_assessment) cards.push(drawHarm(result.harm_assessment));
    if (result.text_model) cards.splice(1, 0, drawTextModel(result.text_model, input.message));
    if (result.harmful_content?.level === 'high' && result.fraud?.level !== 'high') cards.unshift(cards.splice(1 + (result.text_model ? 1 : 0), 1)[0]);
    $('findings').replaceChildren(...cards);
    $('result').hidden = false;
    const receipt = typeof assessment_receipt === 'string' && assessment_receipt ? assessment_receipt : null;
    currentSnapshot = { input, result, receipt };
    $('save').disabled = !receipt;
    if (!receipt) $('save-status').textContent = 'Restart the local Sentinel service and recheck to save this assessment.';
  } catch (error) {
    if (version === analysisVersion) $('error').textContent = error.message;
  } finally {
    if (version === analysisVersion) setChecking(false);
  }
};

$('save').onclick = async () => {
  const version = analysisVersion;
  const snapshot = currentSnapshot;
  if (!snapshot?.receipt || saved || pendingSaves.has(version)) return;
  pendingSaves.add(version);
  $('save').disabled = true;
  $('save-status').textContent = 'Saving…';
  try {
    await request('/api/cases', { input: snapshot.input, result: snapshot.result, assessment_receipt: snapshot.receipt });
    if (version === analysisVersion) {
      saved = true;
      $('save-status').textContent = 'Saved in the local app.';
    }
  } catch (error) {
    if (version === analysisVersion) {
      if (/recheck|expired|restart|receipt/i.test(error.message)) currentSnapshot.receipt = null;
      $('save').disabled = saved || !currentSnapshot.receipt;
      $('save-status').textContent = error.message;
    }
  } finally { pendingSaves.delete(version); }
};

$('open').onclick = () => chrome.tabs.create({ url: ENDPOINT });

(async () => {
  const version = analysisVersion;
  const { pendingCheck } = await chrome.storage.session.get('pendingCheck');
  if (!pendingCheck) return;
  if (version === analysisVersion) {
    if (pendingCheck.message) $('message').value = pendingCheck.message;
    if (pendingCheck.url) $('url').value = pendingCheck.url;
    invalidate();
  }
  await chrome.storage.session.remove('pendingCheck');
})();
