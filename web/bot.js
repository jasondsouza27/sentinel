// Social media bot account detection page. All text is inserted with textContent.
const $ = id => document.getElementById(id);
const SVG = 'http://www.w3.org/2000/svg';
const MAX_UPLOAD_BYTES = 2_500_000;
let platforms = [];
let busy = false;

function el(tag, className, text) {
  const node = document.createElement(tag);
  if (className) node.className = className;
  if (text !== undefined && text !== null) node.textContent = text;
  return node;
}
function svg(tag, attrs, text) {
  const node = document.createElementNS(SVG, tag);
  for (const [k, v] of Object.entries(attrs)) node.setAttribute(k, v);
  if (text !== undefined) node.textContent = text;
  return node;
}
const pct = v => (v === null || v === undefined) ? '—' : `${Math.round(v * 100)}%`;
const num = v => (v === null || v === undefined) ? '—' : Number(v).toLocaleString();

async function api(path, options = {}) {
  let response;
  try {
    response = await fetch(path, { ...options, headers: options.body ? { 'Content-Type': 'application/json' } : undefined });
  } catch {
    throw new Error('Cannot reach the local Sentinel service. Start Sentinel and try again.');
  }
  let data = {};
  try { data = await response.json(); } catch { /* non-JSON error page */ }
  if (!response.ok) {
    const error = new Error(data.error || `Request failed (${response.status})`);
    error.code = data.code;
    throw error;
  }
  return data;
}

// ---------- form state ----------
function selectedSource() { return document.querySelector('input[name="source"]:checked')?.value; }

function updateSourceFields() {
  const source = selectedSource();
  $('upload-fields').hidden = source !== 'upload';
  $('manual-fields').hidden = source !== 'manual';
}

function updatePlatform() {
  const platform = platforms.find(p => p.id === $('platform').value);
  const apiRadio = $('source-api');
  if (!platform) { $('platform-note').textContent = ''; apiRadio.disabled = true; return; }
  apiRadio.disabled = !platform.api_configured;
  $('api-help').textContent = platform.api_configured ? 'Public data from the platform\'s official API.' : platform.api_note;
  $('platform-note').textContent = platform.api_configured
    ? `${platform.name}: official API available, or upload data or enter details.`
    : `${platform.name}: ${platform.api_note}`;
  if (apiRadio.checked && apiRadio.disabled) $('source-upload').checked = true;
  $('account').placeholder = {
    x: 'https://x.com/username or @username', instagram: 'https://instagram.com/username or username',
    facebook: 'https://facebook.com/pagename or pagename', reddit: 'https://reddit.com/user/name or u/name',
    youtube: 'https://youtube.com/@handle or channel ID',
  }[platform.id] || 'username';
  updateSourceFields();
}

async function loadPlatforms() {
  try {
    const reply = await api('/api/bot/platforms');
    platforms = reply.platforms;
    const options = [el('option', '', 'Choose a platform')];
    options[0].value = '';
    for (const p of platforms) {
      const option = el('option', '', p.name);
      option.value = p.id;
      options.push(option);
    }
    $('platform').replaceChildren(...options);
    $('service-status').textContent = 'Local service ready';
    $('service-status').classList.remove('error');
  } catch (error) {
    $('service-status').textContent = 'Service unavailable';
    $('service-status').classList.add('error');
    $('form-message').textContent = error.message;
  }
  updatePlatform();
}

function readFile(file) {
  return new Promise((resolve, reject) => {
    if (file.size > MAX_UPLOAD_BYTES) { reject(new Error('That file is larger than 2.5 MB. Upload at most 3,000 recent posts.')); return; }
    const reader = new FileReader();
    reader.onload = () => resolve(String(reader.result));
    reader.onerror = () => reject(new Error('The file could not be read.'));
    reader.readAsText(file);
  });
}

async function buildUpload() {
  const file = $('upload-file').files[0];
  if (!file) throw new Error('Choose a JSON or CSV file of the account\'s posts, or pick another data source.');
  const text = await readFile(file);
  if (/\.csv$/i.test(file.name) || file.type === 'text/csv') return { format: 'csv', content: text };
  let parsed;
  try { parsed = JSON.parse(text); } catch { throw new Error('The JSON file is not valid JSON.'); }
  if (Array.isArray(parsed)) return { format: 'json', posts: parsed };
  if (!parsed || typeof parsed !== 'object') throw new Error('The JSON file must contain an object or a list of posts.');
  return { format: 'json', profile: parsed.profile, posts: parsed.posts || [] };
}

function buildManual() {
  const profile = {};
  const numberField = (id, key) => { if ($(id).value !== '') profile[key] = Number($(id).value); };
  numberField('m-age', 'account_age_days'); numberField('m-posts', 'total_posts');
  numberField('m-followers', 'followers'); numberField('m-following', 'following');
  if ($('m-image').value) { profile.has_profile_image = $('m-image').value === 'custom'; profile.default_profile_image = $('m-image').value === 'default'; }
  if ($('m-verified').value) profile.verified = $('m-verified').value === 'true';
  if ($('m-name').value.trim()) profile.display_name = $('m-name').value.trim();
  if ($('m-bio').value.trim()) profile.bio = $('m-bio').value.trim();
  if (!Object.keys(profile).length) throw new Error('Enter at least one profile detail, or pick another data source.');
  return profile;
}

// ---------- progress ----------
let progressTimer = 0;
function setProgress(active) {
  const steps = [...$('progress').children];
  const index = steps.findIndex(li => li.dataset.step === active);
  steps.forEach((li, i) => { li.classList.toggle('done', index === -1 ? active === 'done' : i < index); li.classList.toggle('active', i === index); });
}
function startProgress() {
  $('progress').hidden = false;
  const order = ['validate', 'collect', 'features', 'score'];
  let i = 0;
  setProgress(order[0]);
  // The request is a single call; advance the visible steps while it runs.
  progressTimer = setInterval(() => { i = Math.min(i + 1, order.length - 1); setProgress(order[i]); }, 450);
}
function stopProgress(ok) {
  clearInterval(progressTimer);
  if (ok) setProgress('done'); else $('progress').hidden = true;
}

// ---------- rendering ----------
function drawGauge(score, risk) {
  const g = $('gauge');
  g.replaceChildren();
  const arc = 'M 20 100 A 80 80 0 0 1 180 100';
  g.append(svg('path', { d: arc, class: 'track' }));
  const length = Math.PI * 80;
  const riskClass = { Low: 'low', Moderate: 'moderate', High: 'high', 'Very high': 'very-high' }[risk] || 'unknown';
  const value = svg('path', { d: arc, class: `value ${riskClass}`, 'stroke-dasharray': `${length}`, 'stroke-dashoffset': `${length * (1 - (score ?? 0) / 100)}` });
  g.append(value);
  g.append(svg('text', { x: 100, y: 92, 'text-anchor': 'middle', class: 'num' }, score === null ? '—' : String(score)));
  g.append(svg('text', { x: 100, y: 112, 'text-anchor': 'middle', class: 'unit' }, score === null ? 'insufficient data' : 'bot-likeness / 100'));
}

function list(target, items, emptyText, withContribution) {
  const nodes = items.map(item => {
    const li = el('li', '', item.text);
    if (withContribution && item.contribution) li.append(' ', el('small', '', `(+${item.contribution} pts)`));
    return li;
  });
  target.replaceChildren(...(nodes.length ? nodes : [el('li', 'empty', emptyText)]));
}

function facts(target, rows) {
  const nodes = [];
  for (const [label, value] of rows) {
    if (value === undefined) continue;
    nodes.push(el('dt', '', label), el('dd', '', value === null ? '—' : String(value)));
  }
  target.replaceChildren(...nodes);
}

function barChart(target, values, labels, emptyText) {
  target.replaceChildren();
  const w = 480, h = 160, pad = 26;
  if (!values || !values.length || !values.some(v => v > 0)) {
    target.append(svg('text', { x: w / 2, y: h / 2, 'text-anchor': 'middle', class: 'none' }, emptyText));
    return;
  }
  const max = Math.max(...values);
  const step = (w - pad * 2) / values.length;
  target.append(svg('line', { x1: pad, x2: w - 6, y1: h - pad, y2: h - pad, class: 'grid' }));
  values.forEach((v, i) => {
    const height = (h - pad * 2) * v / max;
    const bar = svg('rect', { x: pad + i * step + 1, y: h - pad - height, width: Math.max(step - 2, 1), height, class: 'bar' });
    bar.append(svg('title', {}, `${labels[i]}: ${v}`));
    target.append(bar);
  });
  const every = Math.ceil(values.length / 8);
  labels.forEach((label, i) => {
    if (i % every === 0) target.append(svg('text', { x: pad + i * step + step / 2, y: h - 8, 'text-anchor': 'middle', class: 'axis' }, label));
  });
  target.append(svg('text', { x: pad - 4, y: pad + 4, 'text-anchor': 'end', class: 'axis' }, String(max)));
}

function breakdown(signals) {
  const label = id => id.replaceAll('_', ' ');
  const rows = signals.map(s => {
    const row = el('div', `bar-row ${s.state === 'unavailable' ? 'unavailable' : s.state === 'human_like' ? 'human' : ''}`);
    row.title = s.state === 'unavailable' ? `Not assessed: ${s.reason}` : (s.text || '');
    const track = el('span', 'track');
    const fill = el('span', 'fill');
    const share = s.state === 'unavailable' ? 0 : s.state === 'human_like' ? 4 : Math.min(100, s.contribution * 8);
    fill.style.width = `${share}%`;
    track.append(fill);
    row.append(el('span', '', `${label(s.id)} · ${s.category}`), track,
      el('span', 'num', s.state === 'unavailable' ? 'n/a' : s.state === 'human_like' ? 'human' : `+${s.contribution}`));
    return row;
  });
  $('breakdown').replaceChildren(...rows);
}

function render(report) {
  $('summary-empty').hidden = true;
  $('summary').hidden = false;
  $('report').hidden = false;
  drawGauge(report.score, report.risk_level);
  const badge = $('classification');
  badge.className = `badge ${report.classification.id}`;
  badge.textContent = report.classification.label;
  $('confidence').textContent = report.confidence.level;
  $('confidence').title = `${report.confidence.reason} ${report.confidence.signal_coverage}.`;
  $('risk').textContent = report.risk_level;
  $('coverage').textContent = pct(report.coverage);
  $('score-label').textContent = report.score === null
    ? `${report.score_label}. Withheld: indicative value ${report.indicative_score ?? '—'} from too little data.`
    : report.score_label + (report.coordination_flag ? ` · Coordination signals: ${report.coordination_score}/100.` : '');
  $('explanation').textContent = report.explanation;
  list($('suspicious'), report.suspicious_indicators, 'None found in the available data.', true);
  list($('human'), report.human_indicators, 'None identified from the available data.');
  const describeModel = (ml, label) => {
    const states = {
      released: () => `${label} estimates a ${Math.round(ml.bot_probability * 100)}% bot probability. ${ml.note}`,
      research_only: () => ml.bot_probability === undefined
        ? `${label}: research only. ${ml.reason}`
        : `${label}: research estimate ${Math.round(ml.bot_probability * 100)}% (not used in the classification). ${ml.note}`,
      not_applicable: () => `${label}: not applied. ${ml.reason}`,
      insufficient_data: () => `${label}: not applied. ${ml.reason}`,
      unavailable: () => `${label} is unavailable; the heuristic result stands on its own.`,
    };
    return (states[ml.state] || states.unavailable)();
  };
  const ml = report.ml_model;
  const activityMl = report.ml_activity_model;
  $('ml-card').hidden = !ml && !activityMl;
  $('ml-state').textContent = ml ? describeModel(ml, 'Trained profile model') : '';
  $('ml-validation').textContent = ml?.validation || '';
  // Activity model: a second line in the same card (created here so the page markup stays unchanged).
  let activityState = $('ml-activity-state');
  if (!activityState) {
    activityState = el('p', '');
    activityState.id = 'ml-activity-state';
    const activityValidation = el('p', 'caption');
    activityValidation.id = 'ml-activity-validation';
    $('ml-card').append(activityState, activityValidation);
  }
  activityState.textContent = activityMl ? describeModel(activityMl, 'Trained activity model') : '';
  $('ml-activity-validation').textContent = activityMl?.validation || '';

  const a = report.account;
  facts($('overview'), [
    ['Platform', a.platform_name], ['Account', a.username], ['Display name', a.display_name],
    ['Data source', { youtube_api: 'YouTube Data API', reddit_api: 'Reddit API', upload: 'Uploaded data', manual: 'Entered details' }[a.source] || a.source],
    ['Account age', a.account_age_days === null ? null : `${num(a.account_age_days)} days`],
    ['Followers', num(a.followers)], ['Following', num(a.following)], ['Total posts', num(a.total_posts)],
    ['Posts analysed', num(a.posts_analysed)], ['Verified', a.verified === null ? null : a.verified ? 'Yes' : 'No'],
  ]);
  breakdown(report.signals);
  const act = report.activity;
  barChart($('hours-chart'), act.hour_histogram, Array.from({ length: 24 }, (_, h) => String(h)), 'Not enough timed posts');
  const days = act.daily_counts || [];
  barChart($('days-chart'), days.map(d => d[1]), days.map(d => d[0].slice(5)), 'Not enough timed posts');
  facts($('activity'), [
    ['Posts per day', act.posts_per_day], ['Span analysed', act.span_days === null ? null : `${act.span_days} days`],
    ['Interval variation', act.interval_cv], ['Repeated-interval share', pct(act.regular_interval_share)],
    ['Active hours', act.active_hours === null ? null : `${act.active_hours} of 24`], ['Quietest 6 hours', pct(act.night_gap_share)],
    ['Reposts', pct(act.repost_ratio)],
  ]);
  const c = report.content;
  facts($('content'), [
    ['Near-identical posts', pct(c.near_duplicate_share)], ['Exact repeats', pct(c.exact_duplicate_share)],
    ['Hashtags per post', c.hashtags_per_post], ['Links per post', c.urls_per_post], ['Top link domain share', pct(c.top_domain_share)],
    ['Vocabulary diversity', c.vocabulary_diversity], ['Spam-like language', pct(c.spam_language_share)],
  ]);
  $('limitations').replaceChildren(...report.limitations.map(text => el('li', '', text)), el('li', '', report.data_retention));
  $('analysed-at').textContent = `Analysed ${new Date(report.analysed_at).toLocaleString()} · ${report.model.type.replaceAll('_', ' ')} ${report.model.version}`;
}

function clearResult() {
  $('summary').hidden = true;
  $('summary-empty').hidden = false;
  $('report').hidden = true;
}

// ---------- events ----------
$('platform').addEventListener('change', () => { updatePlatform(); clearResult(); });
for (const radio of document.querySelectorAll('input[name="source"]')) radio.addEventListener('change', updateSourceFields);

$('bot-form').addEventListener('submit', async event => {
  event.preventDefault();
  if (busy) return;
  $('form-message').textContent = '';
  const platform = $('platform').value;
  const account = $('account').value.trim();
  const source = selectedSource();
  if (!platform) { $('form-message').textContent = 'Choose a platform.'; return; }
  if (!account) { $('form-message').textContent = 'Enter a profile URL or username.'; return; }
  const body = { platform, account, source };
  try {
    if (source === 'upload') body.upload = await buildUpload();
    if (source === 'manual') body.profile = buildManual();
  } catch (error) { $('form-message').textContent = error.message; return; }
  busy = true;
  $('analyze-button').disabled = true;
  clearResult();
  startProgress();
  try {
    const report = await api('/api/bot/analyze', { method: 'POST', body: JSON.stringify(body) });
    stopProgress(true);
    render(report);
  } catch (error) {
    stopProgress(false);
    $('form-message').textContent = error.code === 'rate_limited' ? `${error.message}` : error.message;
  } finally {
    busy = false;
    $('analyze-button').disabled = false;
  }
});

$('reset-button').addEventListener('click', () => {
  $('bot-form').reset();
  $('form-message').textContent = '';
  $('progress').hidden = true;
  clearResult();
  updatePlatform();
});

loadPlatforms();
