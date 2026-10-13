const $ = (id) => document.getElementById(id);
let currentInput = null;
let currentResult = null;
let currentReceipt = null;
let currentCaseId = null;
let analysisVersion = 0;
const pendingSaves = new Set();

async function api(path, options = {}) {
  let response;
  try {
    response = await fetch(path, {
      ...options,
      headers: options.body ? { 'Content-Type': 'application/json' } : undefined,
    });
  } catch {
    throw new Error('Cannot reach the local Sentinel service. Start Sentinel and try again.');
  }
  const data = await response.json();
  if (!response.ok) throw new Error(data.error || `Request failed (${response.status})`);
  return data;
}

function inputData() {
  const structured = conversationEditor.read();
  const isStructured = Boolean(structured.conversation_kind);
  const result = { ...structured };
  if (isStructured) result.message = structured.conversation_turns.find(turn => turn.turn_id === structured.target_turn_id).text;
  for (const id of ['message', 'url', 'conversation']) {
    if (isStructured && id !== 'url') continue;
    const value = $(id).value.trim();
    if (value) result[id] = value;
  }
  const profile = {};
  if ($('username').value.trim()) profile.username = $('username').value.trim();
  for (const [id, key] of [['age', 'account_age_days'], ['posts', 'posts_last_24h'], ['followers', 'followers_count'], ['following', 'following_count']]) {
    if ($(id).value !== '') profile[key] = Number($(id).value);
  }
  if ($('website').value.trim()) profile.website_url = $('website').value.trim();
  if ($('official').value.trim()) profile.official_domain = $('official').value.trim();
  if (Object.keys(profile).length) result.profile = profile;
  return result;
}

function syncConversationFields(input = {}) {
  const structured = Boolean(input.conversation_kind);
  $('message').readOnly = structured;
  $('conversation').disabled = structured;
  if (structured) $('message').value = input.conversation_turns.find(turn => turn.turn_id === input.target_turn_id)?.text || '';
}

function invalidateEditedInput(input) {
  analysisVersion += 1;
  clearResult();
  setAnalyzing(false);
  $('form-message').textContent = '';
  if (input) syncConversationFields(input);
}

const conversationEditor = globalThis.SentinelConversation.createEditor($('conversation-editor'), input => invalidateEditedInput(input));
for (const id of ['message', 'url', 'conversation', 'username', 'age', 'posts', 'followers', 'following', 'website', 'official']) {
  $(id).addEventListener('input', () => invalidateEditedInput());
}

function node(tag, className, text) {
  const element = document.createElement(tag);
  if (className) element.className = className;
  if (text !== undefined) element.textContent = text;
  return element;
}

function assessment(title, item, isProfile = false, isPaired = false) {
  const card = node('section', 'assessment');
  const head = node('div', 'assessment-head');
  head.append(node('h4', '', title));
  const level = isPaired ? (item.state === 'available' ? item.category : item.state)
    : isProfile ? item.status : item.level;
  head.append(node('span', `badge ${level}`, level.replaceAll('_', ' ')));
  card.append(head);
  if (item.evidence?.length) {
    const list = node('ul');
    for (const evidence of item.evidence) list.append(node('li', '', evidence));
    card.append(list);
  } else {
    card.append(node('p', '', isPaired ? 'No additional observed warning signs to display.'
      : 'No warning signs were identified from the available information.'));
  }
  if (item.unavailable_checks?.length) {
    for (const missing of item.unavailable_checks) card.append(node('p', '', `Could not check: ${missing}`));
  }
  if (item.uncertainty) card.append(node('p', '', item.uncertainty));
  if (item.model_votes) {
    const votes = Object.entries(item.model_votes).map(([mode, vote]) => `${mode}: ${vote.replaceAll('_', ' ')}`).join(' · ');
    card.append(node('p', '', `Research model votes — ${votes}. ${item.model_note}`));
  }
  card.append(node('p', 'action', item.action));
  return card;
}

function harmAssessment(item) {
  const card = assessment('English directed-abuse model', item, false, true);
  card.append(node('p', '', `Learned category: ${String(item.category).replaceAll('_', ' ')}.`));
  const coverage = item.coverage || {};
  if (coverage.used_context_turns) {
    card.append(node('p', '', `Context: ${coverage.used_context_turns} preceding turns used of ${coverage.available_context_turns}; ${coverage.omitted_context_turns || 0} older turns omitted.`));
    if (coverage.context_missing) card.append(node('p', '', 'Some preceding context is unavailable.'));
  } else card.append(node('p', '', 'Context unavailable: target-only assessment.'));
  if (coverage.language_assumed) card.append(node('p', '', 'Language: English is assumed.'));
  else if (coverage.language) card.append(node('p', '', `Declared language: ${coverage.language}.`));
  if (item.branch) card.append(node('p', '', `Branch: ${item.branch.replaceAll('_', ' ')}.`));
  if (Array.isArray(item.model_contributions)) {
    for (const contribution of item.model_contributions) card.append(node('p', '', `Model contribution: ${typeof contribution === 'string' ? contribution : JSON.stringify(contribution)}`));
  }
  const probability = item.calibrated_probability;
  if (['complete', 'degraded'].includes(item.state) && typeof probability === 'number' && Number.isFinite(probability) && probability >= 0 && probability <= 1) {
    card.append(node('p', '', `Calibrated probability: ${(probability * 100).toFixed(1)}% on the evaluated distribution.`));
  }
  return card;
}

function renderResult(result) {
  const target = $('result-content');
  const cards = [
    assessment('Message & link', result.fraud),
    assessment('Harmful content observations', result.harmful_content),
    assessment('Profile indicators', result.profile, true),
  ];
  if (result.paired_assessment) cards.push(assessment('Paired message–link model', result.paired_assessment, false, true));
  if (result.harm_assessment) cards.push(harmAssessment(result.harm_assessment));
  target.replaceChildren(...cards);
  target.hidden = false;
  $('result-empty').hidden = true;
  $('result-actions').hidden = false;
}

function clearResult() {
  currentInput = null;
  currentResult = null;
  currentReceipt = null;
  currentCaseId = null;
  $('result-content').replaceChildren();
  $('result-content').hidden = true;
  $('result-empty').hidden = false;
  $('result-actions').hidden = true;
  $('save-button').disabled = true;
  $('save-status').textContent = '';
}

function setAnalyzing(busy) {
  $('check-button').disabled = busy;
  $('check-button').textContent = busy ? 'Analyzing…' : 'Analyze content →';
}

function populate(input) {
  conversationEditor.populate(input);
  for (const id of ['message', 'url', 'conversation']) $(id).value = input[id] || '';
  const p = input.profile || {};
  $('username').value = p.username || '';
  $('age').value = p.account_age_days ?? '';
  $('posts').value = p.posts_last_24h ?? '';
  $('followers').value = p.followers_count ?? '';
  $('following').value = p.following_count ?? '';
  $('website').value = p.website_url || '';
  $('official').value = p.official_domain || '';
  syncConversationFields(input);
}

async function refreshCases() {
  const cases = await api('/api/cases');
  const list = $('case-list');
  list.replaceChildren();
  if (!cases.length) {
    list.append(node('p', 'muted', 'No saved cases yet. Analysis stays private until you choose to save it.'));
    return;
  }
  for (const item of cases) {
    const row = node('div', 'case-row');
    const main = node('div', 'case-main');
    main.append(node('strong', '', item.input.message || item.input.conversation_turns?.find(turn => turn.turn_id === item.input.target_turn_id)?.text || item.input.url || item.input.profile?.username || 'Profile assessment'));
    main.append(node('small', '', `${new Date(item.created_at).toLocaleString()} · ${item.feedback ? `Feedback: ${item.feedback}` : 'No feedback'}`));
    const controls = node('div', 'case-controls');
    const open = node('button', '', 'Open');
    open.onclick = () => {
      analysisVersion += 1;
      setAnalyzing(false);
      $('form-message').textContent = '';
      currentInput = item.input;
      currentResult = item.result;
      currentReceipt = null;
      currentCaseId = item.id;
      populate(item.input);
      renderResult(item.result);
      $('save-button').disabled = true;
      $('save-status').textContent = 'Saved case';
      $('check').scrollIntoView({ behavior: 'smooth' });
    };
    const report = node('button', '', 'Export JSON');
    report.onclick = async () => {
      try {
        const value = await api(`/api/cases/${item.id}/report`);
        const objectUrl = URL.createObjectURL(new Blob([JSON.stringify(value, null, 2)], { type: 'application/json' }));
        const link = document.createElement('a');
        link.href = objectUrl;
        link.download = `sentinel-case-${item.id.slice(0, 8)}.json`;
        link.click();
        setTimeout(() => URL.revokeObjectURL(objectUrl), 1000);
      } catch (error) { alert(error.message); }
    };
    const feedback = node('button', '', 'Mark incorrect');
    feedback.onclick = async () => {
      try { await api(`/api/cases/${item.id}/feedback`, { method: 'POST', body: JSON.stringify({ verdict: 'incorrect' }) }); await refreshCases(); }
      catch (error) { alert(error.message); }
    };
    const remove = node('button', 'danger', 'Delete');
    remove.onclick = async () => {
      if (!confirm('Delete this saved case from this device?')) return;
      try { await api(`/api/cases/${item.id}`, { method: 'DELETE' }); if (currentCaseId === item.id) currentCaseId = null; await refreshCases(); }
      catch (error) { alert(error.message); }
    };
    controls.append(open, report, feedback, remove);
    row.append(main, controls);
    list.append(row);
  }
}

$('check-form').addEventListener('submit', async (event) => {
  event.preventDefault();
  const requestVersion = ++analysisVersion;
  clearResult();
  $('form-message').textContent = '';
  setAnalyzing(true);
  try {
    const submittedInput = inputData();
    const response = await api('/api/analyze', { method: 'POST', body: JSON.stringify(submittedInput) });
    const { assessment_receipt, ...result } = response;
    if (requestVersion !== analysisVersion) return;
    renderResult(result);
    currentInput = submittedInput;
    currentResult = result;
    currentReceipt = typeof assessment_receipt === 'string' && assessment_receipt ? assessment_receipt : null;
    $('save-button').disabled = !currentReceipt;
    if (!currentReceipt) $('save-status').textContent = 'Restart the local Sentinel service and recheck to save this assessment.';
  } catch (error) {
    if (requestVersion === analysisVersion) $('form-message').textContent = error.message;
  } finally {
    if (requestVersion === analysisVersion) setAnalyzing(false);
  }
});

$('save-button').onclick = async () => {
  const saveVersion = analysisVersion;
  const inputToSave = currentInput;
  const resultToSave = currentResult;
  const receiptToSave = currentReceipt;
  if (!inputToSave || !resultToSave || !receiptToSave || currentCaseId || pendingSaves.has(saveVersion)) return;
  pendingSaves.add(saveVersion);
  $('save-button').disabled = true;
  $('save-status').textContent = 'Saving…';
  try {
    const saved = await api('/api/cases', { method: 'POST', body: JSON.stringify({ input: inputToSave, result: resultToSave, assessment_receipt: receiptToSave }) });
    if (saveVersion === analysisVersion) {
      currentCaseId = saved.id;
      $('save-status').textContent = 'Saved locally';
    }
    await refreshCases();
  } catch (error) {
    if (saveVersion === analysisVersion) {
      if (/recheck|expired|restart|receipt/i.test(error.message)) currentReceipt = null;
      $('save-button').disabled = Boolean(currentCaseId) || !currentReceipt;
      $('save-status').textContent = currentCaseId ? `Saved locally; history could not refresh. ${error.message}` : error.message;
    }
  } finally {
    pendingSaves.delete(saveVersion);
  }
};

$('clear-button').onclick = () => {
  analysisVersion += 1;
  $('check-form').reset();
  conversationEditor.clear();
  syncConversationFields();
  clearResult();
  setAnalyzing(false);
  $('form-message').textContent = '';
};

(async () => {
  try {
    const health = await api('/api/health');
    $('service-status').textContent = health.reputation_loaded ? 'Local service · reputation loaded' : 'Local service · no reputation feed';
    await refreshCases();
  } catch (error) {
    $('service-status').textContent = 'Local service unavailable';
    $('service-status').classList.add('error');
    $('case-list').textContent = error.message;
  }
})();
