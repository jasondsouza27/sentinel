import assert from 'node:assert/strict';
import { readFileSync } from 'node:fs';
import test from 'node:test';
import { runInNewContext } from 'node:vm';

const script = readFileSync(new URL('../extension/popup.js', import.meta.url), 'utf8');
class Element {
  constructor(tag = 'div') { this.tagName = tag.toUpperCase(); }
  value = ''; hidden = false; disabled = false; children = []; listeners = {}; _text = '';
  get textContent() { return this._text + this.children.map(child => child.textContent).join(' '); }
  set textContent(value) { this._text = String(value); this.children = []; }
  set innerHTML(value) { throw new Error('Unsafe HTML rendering'); }
  append(...items) { this.children.push(...items); }
  replaceChildren(...items) { this._text = ''; this.children = items; }
  addEventListener(type, handler) { this.listeners[type] = handler; }
}
function result(evidence = 'Rule evidence') {
  const item = { level: 'review', evidence: [evidence], action: 'Verify independently' };
  return { assessment_receipt: 'popup-receipt-' + evidence, fraud: item, harmful_content: item,
    profile: { status: 'insufficient_evidence', evidence: [], action: 'Review' } };
}
function deferred() {
  let resolve, reject;
  const promise = new Promise((yes, no) => { resolve = yes; reject = no; });
  return { promise, resolve, reject };
}
function setup(assessment) {
  const ids = ['selection', 'message', 'url', 'check', 'open', 'error', 'result', 'findings', 'save', 'save-status'];
  const elements = new Map(ids.map(id => [id, new Element()]));
  elements.get('result').hidden = true;
  const response = result();
  if (assessment) response.paired_assessment = assessment;
  const savedPayloads = [], analyzedInputs = [];
  let analyze = async () => response;
  let save = async () => ({ id: 'stored' });
  let selection = async () => [{ result: 'explicit selected text' }];
  const fetch = async (url, options) => {
    const payload = JSON.parse(options.body);
    let data;
    if (url.endsWith('/api/analyze')) { analyzedInputs.push(payload); data = await analyze(payload); }
    else if (url.endsWith('/api/cases')) { savedPayloads.push(payload); data = await save(payload); }
    else throw new Error('Unexpected endpoint');
    return data instanceof Response ? data : new Response(JSON.stringify(data));
  };
  runInNewContext(script, {
    document: { getElementById: id => elements.get(id), createElement: tag => new Element(tag) }, fetch,
    chrome: { storage: { session: { get: async () => ({}), remove: async () => {} } },
      tabs: { query: async () => [{ id: 1 }], create: () => {} },
      scripting: { executeScript: async () => selection() } },
  });
  Object.assign(elements, { savedPayloads, analyzedInputs,
    replyWith(handler) { analyze = handler; }, replyToSaveWith(handler) { save = handler; },
    replySelectionWith(handler) { selection = handler; },
    edit(value) { this.get('message').value = value; this.get('message').listeners.input({ target: this.get('message') }); },
    check() { return this.get('check').onclick(); }, save() { return this.get('save').onclick(); },
  });
  return elements;
}
async function assessed() {
  const app = setup(); app.get('message').value = 'selected target';
  await app.check(); return app;
}
function descendants(element) { return [element, ...element.children.flatMap(descendants)]; }

test('popup shows only configured optional paired card as escaped text', async () => {
  const empty = setup();
  empty.get('message').value = 'A message';
  await empty.get('check').onclick();
  assert.equal(empty.get('findings').children.length, 3);

  const withPaired = setup({ state: 'unavailable', category: 'not_assessed',
    evidence: ['<script>alert(1)</script>'], unavailable_checks: ['Research only'],
    uncertainty: 'No confidence', action: 'Check official channel', model_version: null });
  withPaired.get('message').value = 'A message';
  await withPaired.get('check').onclick();
  const content = withPaired.get('findings').textContent;
  assert.equal(withPaired.get('findings').children.length, 4);
  assert.match(content, /paired/i);
  assert.match(content, /<script>alert\(1\)<\/script>/);
  assert.doesNotMatch(content, /undefined/);
});


test('popup sends only an explicit target check and saves exact result plus receipt', async () => {
  const app = setup();
  assert.equal(app.analyzedInputs.length, 0);
  app.get('message').value = 'selected target';
  const reviewed = result('reviewed observation');
  app.replyWith(async () => reviewed); await app.check();
  app.get('message').value = 'programmatic later form value'; await app.save();
  const { assessment_receipt, ...expected } = reviewed;
  assert.deepEqual(app.savedPayloads, [{ input: { message: 'selected target', url: '' }, result: expected, assessment_receipt }]);
  assert.equal(app.get('save').disabled, true);
});

test('pending popup check hides the older result and cannot save unreviewed content', async () => {
  const app = await assessed(); const reply = deferred();
  app.replyWith(() => reply.promise); app.get('message').value = 'next target'; const pending = app.check();
  assert.equal(app.get('result').hidden, true); assert.equal(app.get('save').disabled, true);
  await app.save(); assert.deepEqual(app.savedPayloads, []);
  reply.resolve(result('next evidence')); await pending;
});

test('popup edits discard a pending late result and restore ability to recheck', async () => {
  const app = setup(); const reply = deferred(); app.replyWith(() => reply.promise);
  app.get('message').value = 'old target'; const pending = app.check(); app.edit('new target');
  reply.resolve(result('outdated evidence')); await pending;
  assert.equal(app.get('result').hidden, true); assert.equal(app.get('save').disabled, true);
  assert.equal(app.get('check').disabled, false); await app.save(); assert.deepEqual(app.savedPayloads, []);
});

test('older popup success cannot overwrite a newer assessment', async () => {
  const app = setup(); const old = deferred(); app.replyWith(() => old.promise);
  app.get('message').value = 'old'; const pending = app.check(); app.edit('new');
  app.replyWith(async () => result('new evidence')); await app.check();
  old.resolve(result('old evidence')); await pending;
  assert.match(app.get('findings').textContent, /new evidence/);
  assert.doesNotMatch(app.get('findings').textContent, /old evidence/);
});

test('older popup failure cannot put an error on a newer pending check', async () => {
  const app = setup(); const old = deferred(); app.replyWith(() => old.promise);
  app.get('message').value = 'old'; const pending = app.check(); app.edit('new');
  const next = deferred(); app.replyWith(() => next.promise); const newer = app.check();
  old.reject(new TypeError('Failed to fetch')); await pending;
  assert.equal(app.get('error').textContent, ''); assert.equal(app.get('check').disabled, true);
  next.resolve(result('new evidence')); await newer;
});

test('late popup save cannot mark a newer reviewed result as saved', async () => {
  const app = await assessed(); const reply = deferred(); app.replyToSaveWith(() => reply.promise);
  const pending = app.save(); app.edit('new target'); app.replyWith(async () => result('new evidence')); await app.check();
  reply.resolve({ id: 'old case' }); await pending;
  assert.equal(app.get('save').disabled, false); assert.equal(app.get('save-status').textContent, '');
  app.replyToSaveWith(async () => ({ id: 'new case' })); await app.save(); assert.equal(app.savedPayloads.length, 2);
});

test('repeated popup save clicks persist the reviewed snapshot once', async () => {
  const app = await assessed(); const reply = deferred(); app.replyToSaveWith(() => reply.promise);
  const first = app.save(), second = app.save(); assert.equal(app.savedPayloads.length, 1);
  reply.resolve({ id: 'stored' }); await Promise.all([first, second]);
});

test('offline popup check has no stale result and gives a recovery action', async () => {
  const app = await assessed(); app.replyWith(async () => { throw new TypeError('Failed to fetch'); }); await app.check();
  assert.equal(app.get('result').hidden, true); assert.equal(app.get('save').disabled, true);
  assert.match(app.get('error').textContent, /start.*local.*retry/i);
});

test('popup reads older unsigned server results but asks to restart before saving', async () => {
  const app = setup(); app.get('message').value = 'target';
  app.replyWith(async () => { const value = result('readable old result'); delete value.assessment_receipt; return value; });
  await app.check(); assert.match(app.get('findings').textContent, /readable old result/);
  assert.equal(app.get('save').disabled, true); assert.match(app.get('save-status').textContent, /restart.*recheck/i);
  await app.save(); assert.deepEqual(app.savedPayloads, []);
});

test('popup expired receipt leaves observations readable and requires another check', async () => {
  const app = await assessed(); app.replyToSaveWith(async () => new Response(JSON.stringify({ error: 'Receipt expired. Recheck content.' }), { status: 400 }));
  await app.save(); assert.equal(app.get('save').disabled, true);
  assert.match(app.get('save-status').textContent, /recheck/i);
  assert.equal(app.get('result').hidden, false); await app.save(); assert.equal(app.savedPayloads.length, 1);
});

test('popup harm facts and missing confidence render safely as text', async () => {
  const app = setup(); app.get('message').value = 'target'; app.replyWith(async () => ({ ...result(), harm_assessment: {
    state: 'unavailable', category: 'not_assessed', branch: 'target_cpu',
    coverage: { used_context_turns: 0, available_context_turns: 0, context_missing: true, language_assumed: true },
    evidence: ['<img src=x onerror=alert(1)>'], unavailable_checks: ['Missing artifact'],
    uncertainty: 'No learned result', action: 'Review', model_version: null,
  } }));
  await app.check(); const text = app.get('findings').textContent;
  assert.match(text, /missing.*context|context.*unavailable/i); assert.match(text, /English.*assum/i);
  assert.match(text, /<img src=x onerror=alert\(1\)>/); assert.doesNotMatch(text, /calibrated probability:/i);
  assert.equal(descendants(app.get('findings')).some(item => ['IMG', 'SCRIPT'].includes(item.tagName)), false);
});

test('late selected-text read cannot overwrite a newer explicit popup check', async () => {
  const app = setup(); const selection = deferred(); app.replySelectionWith(() => selection.promise);
  const pending = app.get('selection').onclick(); app.edit('user typed target'); await app.check();
  selection.resolve([{ result: 'old selected text' }]); await pending;
  assert.equal(app.get('message').value, 'user typed target');
});
