const $ = (id) => document.getElementById(id);
let currentInput = null;
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
  const result = {};
  for (const id of ['message', 'url', 'conversation']) {
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

function node(tag, className, text) {
  const element = document.createElement(tag);
  if (className) element.className = className;
  if (text !== undefined) element.textContent = text;
  return element;
}

function assessment(title, item, isProfile = false) {
  const card = node('section', 'assessment');
  const head = node('div', 'assessment-head');
  head.append(node('h4', '', title));
  const level = isProfile ? item.status : item.level;
  head.append(node('span', `badge ${level}`, level.replaceAll('_', ' ')));
  card.append(head);
  if (item.evidence?.length) {
    const list = node('ul');
    for (const evidence of item.evidence) list.append(node('li', '', evidence));
    card.append(list);
  } else {
    card.append(node('p', '', 'No warning signs were identified from the available information.'));
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

function renderResult(result) {
  const target = $('result-content');
  target.replaceChildren(
    assessment('Message & link', result.fraud),
    assessment('Harmful content', result.harmful_content),
    assessment('Profile indicators', result.profile, true),
  );
  target.hidden = false;
  $('result-empty').hidden = true;
  $('result-actions').hidden = false;
}

function clearResult() {
  currentInput = null;
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
  for (const id of ['message', 'url', 'conversation']) $(id).value = input[id] || '';
  const p = input.profile || {};
  $('username').value = p.username || '';
  $('age').value = p.account_age_days ?? '';
  $('posts').value = p.posts_last_24h ?? '';
  $('followers').value = p.followers_count ?? '';
  $('following').value = p.following_count ?? '';
  $('website').value = p.website_url || '';
  $('official').value = p.official_domain || '';
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
    main.append(node('strong', '', item.input.message || item.input.url || item.input.profile?.username || 'Profile assessment'));
    main.append(node('small', '', `${new Date(item.created_at).toLocaleString()} · ${item.feedback ? `Feedback: ${item.feedback}` : 'No feedback'}`));
    const controls = node('div', 'case-controls');
    const open = node('button', '', 'Open');
    open.onclick = () => {
      analysisVersion += 1;
      setAnalyzing(false);
      $('form-message').textContent = '';
      currentInput = item.input;
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
  const submittedInput = inputData();
  clearResult();
  $('form-message').textContent = '';
  setAnalyzing(true);
  try {
    const result = await api('/api/analyze', { method: 'POST', body: JSON.stringify(submittedInput) });
    if (requestVersion !== analysisVersion) return;
    renderResult(result);
    currentInput = submittedInput;
    $('save-button').disabled = false;
  } catch (error) {
    if (requestVersion === analysisVersion) $('form-message').textContent = error.message;
  } finally {
    if (requestVersion === analysisVersion) setAnalyzing(false);
  }
});

$('save-button').onclick = async () => {
  const saveVersion = analysisVersion;
  const inputToSave = currentInput;
  if (!inputToSave || currentCaseId || pendingSaves.has(saveVersion)) return;
  pendingSaves.add(saveVersion);
  $('save-button').disabled = true;
  $('save-status').textContent = 'Saving…';
  try {
    const saved = await api('/api/cases', { method: 'POST', body: JSON.stringify({ input: inputToSave }) });
    if (saveVersion === analysisVersion) {
      currentCaseId = saved.id;
      $('save-status').textContent = 'Saved locally';
    }
    await refreshCases();
  } catch (error) {
    if (saveVersion === analysisVersion) {
      $('save-button').disabled = Boolean(currentCaseId);
      $('save-status').textContent = currentCaseId ? `Saved locally; history could not refresh. ${error.message}` : error.message;
    }
  } finally {
    pendingSaves.delete(saveVersion);
  }
};

$('clear-button').onclick = () => {
  analysisVersion += 1;
  $('check-form').reset();
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
