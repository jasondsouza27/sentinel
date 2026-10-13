import assert from 'node:assert/strict';
import { readFileSync, existsSync } from 'node:fs';
import test from 'node:test';
import { createContext, runInContext } from 'node:vm';

const script = readFileSync(new URL('../web/app.js', import.meta.url), 'utf8');
const editorPath = new URL('../web/conversation.js', import.meta.url);
const editorScript = existsSync(editorPath) ? readFileSync(editorPath, 'utf8') : '';
const html = readFileSync(new URL('../web/index.html', import.meta.url), 'utf8');

// A small DOM boundary for the real client script; browser checks cover layout,
// native validation and downloads. Fetch is controlled to exercise late replies.
class Element {
  constructor(tag = 'div') { this.tagName = tag.toUpperCase(); }
  dataset = {};
  attributes = {};
  checked = false;
  readOnly = false;
  setAttribute(name, value) { this.attributes[name] = String(value); }
  getAttribute(name) { return this.attributes[name]; }
  set innerHTML(value) { throw new Error('Unsafe HTML rendering'); }
  focus() {}

  value = '';
  hidden = false;
  disabled = false;
  children = [];
  listeners = {};
  classList = { add() {} };
  _text = '';
  get textContent() { return this._text + this.children.map(child => child.textContent).join(' '); }
  set textContent(value) { this._text = value; this.children = []; }
  append(...children) { this.children.push(...children); }
  replaceChildren(...children) { this._text = ''; this.children = children; }
  addEventListener(type, handler) { this.listeners[type] = handler; }
  scrollIntoView() {}
}

function result(evidence) {
  const assessment = { level: 'review', evidence: [evidence], unavailable_checks: [], action: 'Verify through an official channel.' };
  return {
    assessment_receipt: 'receipt-' + evidence,
    fraud: assessment,
    harmful_content: { ...assessment, level: 'not_assessed', evidence: [] },
    profile: { ...assessment, status: 'insufficient_evidence', evidence: [] },
  };
}

function deferred() {
  let resolve, reject;
  const promise = new Promise((yes, no) => { resolve = yes; reject = no; });
  return { promise, resolve, reject };
}

async function client({ cases = [] } = {}) {
  const elements = new Map();
  for (const match of html.matchAll(/<([a-z][\w-]*)\b([^>]*)>/gi)) {
    const id = /\bid="([^"]+)"/.exec(match[2])?.[1];
    if (!id) continue;
    const element = new Element(match[1]);
    element.hidden = /\bhidden\b/.test(match[2]);
    element.disabled = /\bdisabled\b/.test(match[2]);
    elements.set(id, element);
  }
  const get = id => elements.get(id);
  get('check-form').reset = () => {
    for (const element of elements.values()) element.value = '';
  };
  const savedInputs = [];
  const savedPayloads = [];
  let analyze = async () => new Response(JSON.stringify(result('First assessment')));
  let save = async () => ({ id: 'new-case' });
  const fetch = async (path, options = {}) => {
    let data;
    if (path === '/api/health') data = { reputation_loaded: false };
    else if (path === '/api/analyze') return analyze(JSON.parse(options.body));
    else if (path === '/api/cases' && options.method === 'POST') {
      const payload = JSON.parse(options.body);
      savedPayloads.push(payload);
      savedInputs.push(payload.input);
      data = await save(payload.input, payload);
    } else if (path === '/api/cases') data = cases;
    else throw new Error(`Unexpected request: ${options.method || 'GET'} ${path}`);
    return data instanceof Response ? data : new Response(JSON.stringify(data));
  };
  const context = createContext({
    document: { getElementById: get, createElement: tag => new Element(tag) }, fetch,
  });
  runInContext(editorScript, context, { filename: 'web/conversation.js' });
  runInContext(script, context, { filename: 'web/app.js' });
  await new Promise(resolve => setImmediate(resolve));
  return {
    get, savedInputs, savedPayloads,
    populate(input) { runInContext('populate(' + JSON.stringify(input) + ')', context); },
    readEditor() { return JSON.parse(runInContext('JSON.stringify(conversationEditor.read())', context)); },
    replyWith(handler) { analyze = async input => new Response(JSON.stringify(await handler(input))); },
    replyError(message) { analyze = async () => new Response(JSON.stringify({ error: message }), { status: 400 }); },
    replyToSaveWith(handler) { save = handler; },
    submit() { return get('check-form').listeners.submit({ preventDefault() {} }); },
    clear() { get('clear-button').onclick(); },
    save() { return get('save-button').onclick(); },
    open() { get('case-list').children[0].children[1].children[0].onclick(); },
  };
}

async function assessedClient(options) {
  const app = await client(options);
  app.get('message').value = 'Original message';
  app.replyWith(async () => result('Original evidence'));
  await app.submit();
  assert.equal(app.get('result-content').hidden, false);
  return app;
}

test('a pending new check hides the old assessment and cannot save unchecked input', async () => {
  const app = await assessedClient();
  const reply = deferred();
  app.replyWith(() => reply.promise);
  app.get('message').value = 'New fee request';
  const pending = app.submit();
  try {
    assert.equal(app.get('result-content').hidden, true);
    assert.equal(app.get('result-actions').hidden, true);
    assert.equal(app.get('save-button').disabled, true);
    await app.save();
    assert.deepEqual(app.savedInputs, []);
  } finally {
    reply.resolve(result('New evidence'));
    await pending;
  }
});

test('an offline check leaves no stale assessment and gives a recovery action', async () => {
  const app = await assessedClient();
  app.replyWith(async () => { throw new TypeError('Failed to fetch'); });
  app.get('message').value = 'Pay the registration fee now';
  await app.submit();
  assert.equal(app.get('result-content').hidden, true);
  assert.equal(app.get('result-actions').hidden, true);
  assert.equal(app.get('save-button').disabled, true);
  assert.equal(app.get('check-button').disabled, false);
  assert.match(app.get('form-message').textContent, /start sentinel.*try again/i);
});

test('server validation errors remain visible without retaining an older result', async () => {
  const app = await assessedClient();
  app.replyError('Supply a message, URL, conversation, or profile details');
  await app.submit();
  assert.equal(app.get('result-content').hidden, true);
  assert.equal(app.get('form-message').textContent, 'Supply a message, URL, conversation, or profile details');
});

test('clearing a pending check discards its late result', async () => {
  const app = await client();
  const reply = deferred();
  app.replyWith(() => reply.promise);
  app.get('message').value = 'Request to cancel';
  const pending = app.submit();
  app.clear();
  reply.resolve(result('Cancelled evidence'));
  await pending;
  assert.equal(app.get('message').value, '');
  assert.equal(app.get('result-content').hidden, true);
  assert.equal(app.get('result-actions').hidden, true);
  assert.equal(app.get('check-button').disabled, false);
});

test('an older failed check cannot interrupt a newer check after clearing', async () => {
  const app = await client();
  const older = deferred();
  app.replyWith(() => older.promise);
  app.get('message').value = 'Old request';
  const oldPending = app.submit();
  app.clear();
  const newer = deferred();
  app.replyWith(() => newer.promise);
  app.get('message').value = 'New request';
  const newPending = app.submit();
  try {
    older.reject(new TypeError('Failed to fetch'));
    await oldPending;
    assert.equal(app.get('form-message').textContent, '');
    assert.equal(app.get('check-button').disabled, true);
  } finally {
    newer.resolve(result('Current evidence'));
    await newPending;
  }
  assert.match(app.get('result-content').textContent, /Current evidence/);
});

test('opening a saved case discards an outstanding analysis reply', async () => {
  const saved = { id: 'stored', created_at: '2026-10-05T12:00:00Z', input: { message: 'Saved message' }, result: result('Saved evidence') };
  const app = await client({ cases: [saved] });
  const reply = deferred();
  app.replyWith(() => reply.promise);
  app.get('message').value = 'Unfinished request';
  const pending = app.submit();
  app.open();
  reply.resolve(result('Unfinished evidence'));
  await pending;
  assert.equal(app.get('message').value, 'Saved message');
  assert.match(app.get('result-content').textContent, /Saved evidence/);
  assert.doesNotMatch(app.get('result-content').textContent, /Unfinished evidence/);
  assert.equal(app.get('save-button').disabled, true);
  assert.equal(app.get('save-status').textContent, 'Saved case');
});

test('a successful check saves the analyzed input snapshot', async () => {
  const app = await assessedClient();
  app.get('message').value = 'Edited after analysis';
  await app.save();
  assert.deepEqual(app.savedInputs, [{ message: 'Original message' }]);
  assert.equal(app.get('save-button').disabled, true);
  assert.equal(app.get('save-status').textContent, 'Saved locally');
});

test('a late save cannot mark a newer assessment as saved', async () => {
  const app = await assessedClient();
  const reply = deferred();
  app.replyToSaveWith(() => reply.promise);
  const pending = app.save();
  app.clear();
  app.get('message').value = 'New message';
  app.replyWith(async () => result('New evidence'));
  await app.submit();
  reply.resolve({ id: 'original-case' });
  await pending;
  assert.match(app.get('result-content').textContent, /New evidence/);
  assert.equal(app.get('save-button').disabled, false);
  assert.equal(app.get('save-status').textContent, '');
  app.replyToSaveWith(async () => ({ id: 'second-case' }));
  await app.save();
  assert.deepEqual(app.savedInputs, [{ message: 'Original message' }, { message: 'New message' }]);
});

test('an older failed save cannot put its error on a newer assessment', async () => {
  const app = await assessedClient();
  const reply = deferred();
  app.replyToSaveWith(() => reply.promise);
  const pending = app.save();
  app.clear();
  app.get('message').value = 'New message';
  await app.submit();
  reply.reject(new TypeError('Failed to fetch'));
  await pending;
  assert.equal(app.get('save-status').textContent, '');
  assert.equal(app.get('save-button').disabled, false);
});

test('opening a saved case is not overwritten by an earlier save reply', async () => {
  const saved = { id: 'stored', created_at: '2026-10-05T12:00:00Z', input: { message: 'Saved message' }, result: result('Saved evidence') };
  const app = await assessedClient({ cases: [saved] });
  const reply = deferred();
  app.replyToSaveWith(() => reply.promise);
  const pending = app.save();
  app.open();
  reply.resolve({ id: 'original-case' });
  await pending;
  assert.equal(app.get('save-status').textContent, 'Saved case');
  assert.match(app.get('result-content').textContent, /Saved evidence/);
});

test('repeated save clicks persist a pending assessment once', async () => {
  const app = await assessedClient();
  const reply = deferred();
  app.replyToSaveWith(() => reply.promise);
  const first = app.save();
  const second = app.save();
  try {
    assert.equal(app.get('save-button').disabled, true);
    assert.deepEqual(app.savedInputs, [{ message: 'Original message' }]);
  } finally {
    reply.resolve({ id: 'original-case' });
    await Promise.all([first, second]);
  }
});

test('a failed save can be retried for the current assessment', async () => {
  const app = await assessedClient();
  app.replyToSaveWith(async () => { throw new TypeError('Failed to fetch'); });
  await app.save();
  assert.equal(app.get('save-button').disabled, false);
  assert.match(app.get('save-status').textContent, /start sentinel.*try again/i);
  app.replyToSaveWith(async () => ({ id: 'retried-case' }));
  await app.save();
  assert.equal(app.get('save-button').disabled, true);
  assert.equal(app.get('save-status').textContent, 'Saved locally');
});

test('optional paired state and category render as text without changing rule cards', async () => {
  const app = await client();
  app.get('message').value = 'Fee request';
  app.replyWith(async () => ({
    ...result('Rule evidence'),
    paired_assessment: {
      state: 'unavailable', category: 'not_assessed', evidence: ['<img src=x onerror=alert(1)>'],
      unavailable_checks: ['Research artifact only'], uncertainty: 'No live model claim',
      action: 'Verify independently', model_version: null,
    },
  }));
  await app.submit();
  const rendered = app.get('result-content').textContent;
  assert.match(rendered, /Rule evidence/);
  assert.match(rendered, /Paired message.*link/i);
  assert.match(rendered, /Research artifact only/);
  assert.match(rendered, /<img src=x onerror=alert\(1\)>/);
  assert.doesNotMatch(rendered, /undefined/);
});

function orderedInput(message = 'Original message') {
  return { message, conversation_kind: 'linear', target_turn_id: 't2', conversation_turns: [
    { turn_id: 't1', speaker_id: 'local_a', text: 'Earlier words' },
    { turn_id: 't2', speaker_id: 'local_b', text: message },
    { turn_id: 't3', speaker_id: null, text: 'Later words' },
  ] };
}

async function structuredClient(options) {
  const app = await client(options);
  assert.ok(app.get('conversation-editor'), 'Conversation editor must be in the actual page');
  app.setTarget = message => app.populate(orderedInput(message));
  app.setTarget('Original message');
  return app;
}

async function assessedStructuredClient(options) {
  const app = await structuredClient(options);
  app.replyWith(async () => result('Original evidence'));
  await app.submit();
  assert.equal(app.get('result-content').hidden, false);
  return app;
}

function descendants(element) {
  return [element, ...element.children.flatMap(descendants)];
}

function editorFields(app, role) {
  return descendants(app.get('conversation-editor')).filter(element => element.dataset.role === role);
}

function edit(element, value, type = 'input') {
  element.value = value;
  return element.listeners[type]?.({ target: element });
}

test('web saves exactly the analyzed turns, reviewed result and receipt together', async () => {
  const app = await structuredClient();
  const reviewed = { ...result('literal <img src=x onerror=alert(1)>'), harm_assessment: {
    state: 'unavailable', category: 'not_assessed', branch: 'context_cpu', target_id: 't2',
    coverage: { used_context_turns: 1, available_context_turns: 1, omitted_context_turns: 0,
      context_missing: false, language: 'en', language_assumed: true },
    evidence: ['Only preceding context is supplied.'], unavailable_checks: ['Research only'],
    uncertainty: 'Model unavailable', action: 'Review the target', model_version: null,
  } };
  app.replyWith(async () => reviewed);
  await app.submit();
  const analyzed = orderedInput();
  app.setTarget('programmatic newer form value');
  await app.save();
  const { assessment_receipt, ...expectedResult } = reviewed;
  assert.deepEqual(app.savedPayloads, [{ input: analyzed, result: expectedResult, assessment_receipt }]);
  const rendered = app.get('result-content').textContent;
  assert.match(rendered, /English.*assum/i);
  assert.match(rendered, /Research only/);
  assert.match(rendered, /<img src=x onerror=alert\(1\)>/);
  assert.doesNotMatch(rendered, /calibrated probability:/i);
  assert.equal(descendants(app.get('result-content')).some(item => ['IMG', 'SCRIPT'].includes(item.tagName)), false);
});

test('a user turn or target edit invalidates the result and late reply', async () => {
  const app = await assessedStructuredClient();
  const reply = deferred();
  app.replyWith(() => reply.promise);
  const pending = app.submit();
  edit(editorFields(app, 'text')[1], 'changed target');
  reply.resolve(result('outdated result'));
  await pending;
  assert.equal(app.get('result-content').hidden, true);
  assert.equal(app.get('save-button').disabled, true);
  assert.equal(app.get('message').value, 'changed target');
  await app.save();
  assert.deepEqual(app.savedPayloads, []);
  const target = editorFields(app, 'target')[0];
  target.checked = true;
  target.listeners.change({ target });
  assert.equal(app.get('message').value, 'Earlier words');
  assert.equal(app.get('message').readOnly, true);
});

test('structured submissions omit flat legacy conversation and mirror selected message', async () => {
  const app = await structuredClient();
  app.get('conversation').value = 'arbitrary legacy future threat';
  let supplied;
  app.replyWith(async input => { supplied = input; return result('checked'); });
  await app.submit();
  assert.deepEqual(supplied, orderedInput());
  assert.equal(app.get('message').value, 'Original message');
  assert.equal(app.get('message').readOnly, true);
  assert.equal(app.get('conversation').disabled, true);
});

test('an older server result remains readable but cannot be saved unsigned', async () => {
  const app = await client();
  app.get('message').value = 'message';
  app.replyWith(async () => { const value = result('Old server result'); delete value.assessment_receipt; return value; });
  await app.submit();
  assert.match(app.get('result-content').textContent, /Old server result/);
  assert.equal(app.get('save-button').disabled, true);
  assert.match(app.get('save-status').textContent, /restart.*recheck/i);
  await app.save();
  assert.deepEqual(app.savedPayloads, []);
});

test('an expired receipt requires recheck and preserves the reviewed result', async () => {
  const app = await assessedStructuredClient();
  app.replyToSaveWith(async () => new Response(JSON.stringify({ error: 'Assessment receipt expired. Recheck this content.' }), { status: 400 }));
  await app.save();
  assert.equal(app.get('save-button').disabled, true);
  assert.match(app.get('save-status').textContent, /recheck/i);
  assert.match(app.get('result-content').textContent, /Original evidence/);
  await app.save();
  assert.equal(app.savedPayloads.length, 1);
});

test('saved structured cases reopen exact turns and clearing restores legacy mode', async () => {
  const saved = { id: 'stored', created_at: '2026-10-13T12:00:00Z', input: orderedInput('Saved target'), result: result('Saved observations') };
  const app = await structuredClient({ cases: [saved] });
  app.open();
  const { message, ...expected } = saved.input;
  assert.deepEqual(app.readEditor(), expected);
  assert.equal(app.get('message').value, message);
  assert.equal(app.get('message').readOnly, true);
  app.clear();
  assert.deepEqual(app.readEditor(), {});
  assert.equal(app.get('message').readOnly, false);
  assert.equal(app.get('conversation').disabled, false);
});

test('structured: a pending new check hides the old assessment and cannot save unchecked input', async () => {
  const app = await assessedStructuredClient();
  const reply = deferred();
  app.replyWith(() => reply.promise);
  app.setTarget('New fee request');
  const pending = app.submit();
  try {
    assert.equal(app.get('result-content').hidden, true);
    assert.equal(app.get('result-actions').hidden, true);
    assert.equal(app.get('save-button').disabled, true);
    await app.save();
    assert.deepEqual(app.savedInputs, []);
  } finally {
    reply.resolve(result('New evidence'));
    await pending;
  }
});

test('structured: an offline check leaves no stale assessment and gives a recovery action', async () => {
  const app = await assessedStructuredClient();
  app.replyWith(async () => { throw new TypeError('Failed to fetch'); });
  app.setTarget('Pay the registration fee now');
  await app.submit();
  assert.equal(app.get('result-content').hidden, true);
  assert.equal(app.get('result-actions').hidden, true);
  assert.equal(app.get('save-button').disabled, true);
  assert.equal(app.get('check-button').disabled, false);
  assert.match(app.get('form-message').textContent, /start sentinel.*try again/i);
});

test('structured: server validation errors remain visible without retaining an older result', async () => {
  const app = await assessedStructuredClient();
  app.replyError('Supply a message, URL, conversation, or profile details');
  await app.submit();
  assert.equal(app.get('result-content').hidden, true);
  assert.equal(app.get('form-message').textContent, 'Supply a message, URL, conversation, or profile details');
});

test('structured: clearing a pending check discards its late result', async () => {
  const app = await structuredClient();
  const reply = deferred();
  app.replyWith(() => reply.promise);
  app.setTarget('Request to cancel');
  const pending = app.submit();
  app.clear();
  reply.resolve(result('Cancelled evidence'));
  await pending;
  assert.equal(app.get('message').value, '');
  assert.equal(app.get('result-content').hidden, true);
  assert.equal(app.get('result-actions').hidden, true);
  assert.equal(app.get('check-button').disabled, false);
});

test('structured: an older failed check cannot interrupt a newer check after clearing', async () => {
  const app = await structuredClient();
  const older = deferred();
  app.replyWith(() => older.promise);
  app.setTarget('Old request');
  const oldPending = app.submit();
  app.clear();
  const newer = deferred();
  app.replyWith(() => newer.promise);
  app.setTarget('New request');
  const newPending = app.submit();
  try {
    older.reject(new TypeError('Failed to fetch'));
    await oldPending;
    assert.equal(app.get('form-message').textContent, '');
    assert.equal(app.get('check-button').disabled, true);
  } finally {
    newer.resolve(result('Current evidence'));
    await newPending;
  }
  assert.match(app.get('result-content').textContent, /Current evidence/);
});

test('structured: opening a saved case discards an outstanding analysis reply', async () => {
  const saved = { id: 'stored', created_at: '2026-10-05T12:00:00Z', input: orderedInput('Saved message'), result: result('Saved evidence') };
  const app = await structuredClient({ cases: [saved] });
  const reply = deferred();
  app.replyWith(() => reply.promise);
  app.setTarget('Unfinished request');
  const pending = app.submit();
  app.open();
  reply.resolve(result('Unfinished evidence'));
  await pending;
  assert.equal(app.get('message').value, 'Saved message');
  assert.match(app.get('result-content').textContent, /Saved evidence/);
  assert.doesNotMatch(app.get('result-content').textContent, /Unfinished evidence/);
  assert.equal(app.get('save-button').disabled, true);
  assert.equal(app.get('save-status').textContent, 'Saved case');
});

test('structured: a successful check saves the analyzed input snapshot', async () => {
  const app = await assessedStructuredClient();
  app.setTarget('Edited after analysis');
  await app.save();
  assert.deepEqual(app.savedInputs, [orderedInput('Original message')]);
  assert.equal(app.get('save-button').disabled, true);
  assert.equal(app.get('save-status').textContent, 'Saved locally');
});

test('structured: a late save cannot mark a newer assessment as saved', async () => {
  const app = await assessedStructuredClient();
  const reply = deferred();
  app.replyToSaveWith(() => reply.promise);
  const pending = app.save();
  app.clear();
  app.setTarget('New message');
  app.replyWith(async () => result('New evidence'));
  await app.submit();
  reply.resolve({ id: 'original-case' });
  await pending;
  assert.match(app.get('result-content').textContent, /New evidence/);
  assert.equal(app.get('save-button').disabled, false);
  assert.equal(app.get('save-status').textContent, '');
  app.replyToSaveWith(async () => ({ id: 'second-case' }));
  await app.save();
  assert.deepEqual(app.savedInputs, [orderedInput('Original message'), orderedInput('New message')]);
});

test('structured: an older failed save cannot put its error on a newer assessment', async () => {
  const app = await assessedStructuredClient();
  const reply = deferred();
  app.replyToSaveWith(() => reply.promise);
  const pending = app.save();
  app.clear();
  app.setTarget('New message');
  await app.submit();
  reply.reject(new TypeError('Failed to fetch'));
  await pending;
  assert.equal(app.get('save-status').textContent, '');
  assert.equal(app.get('save-button').disabled, false);
});

test('structured: opening a saved case is not overwritten by an earlier save reply', async () => {
  const saved = { id: 'stored', created_at: '2026-10-05T12:00:00Z', input: orderedInput('Saved message'), result: result('Saved evidence') };
  const app = await assessedStructuredClient({ cases: [saved] });
  const reply = deferred();
  app.replyToSaveWith(() => reply.promise);
  const pending = app.save();
  app.open();
  reply.resolve({ id: 'original-case' });
  await pending;
  assert.equal(app.get('save-status').textContent, 'Saved case');
  assert.match(app.get('result-content').textContent, /Saved evidence/);
});

test('structured: repeated save clicks persist a pending assessment once', async () => {
  const app = await assessedStructuredClient();
  const reply = deferred();
  app.replyToSaveWith(() => reply.promise);
  const first = app.save();
  const second = app.save();
  try {
    assert.equal(app.get('save-button').disabled, true);
    assert.deepEqual(app.savedInputs, [orderedInput('Original message')]);
  } finally {
    reply.resolve({ id: 'original-case' });
    await Promise.all([first, second]);
  }
});

test('structured: a failed save can be retried for the current assessment', async () => {
  const app = await assessedStructuredClient();
  app.replyToSaveWith(async () => { throw new TypeError('Failed to fetch'); });
  await app.save();
  assert.equal(app.get('save-button').disabled, false);
  assert.match(app.get('save-status').textContent, /start sentinel.*try again/i);
  app.replyToSaveWith(async () => ({ id: 'retried-case' }));
  await app.save();
  assert.equal(app.get('save-button').disabled, true);
  assert.equal(app.get('save-status').textContent, 'Saved locally');
});

test('structured: optional paired state and category render as text without changing rule cards', async () => {
  const app = await structuredClient();
  app.setTarget('Fee request');
  app.replyWith(async () => ({
    ...result('Rule evidence'),
    paired_assessment: {
      state: 'unavailable', category: 'not_assessed', evidence: ['<img src=x onerror=alert(1)>'],
      unavailable_checks: ['Research artifact only'], uncertainty: 'No live model claim',
      action: 'Verify independently', model_version: null,
    },
  }));
  await app.submit();
  const rendered = app.get('result-content').textContent;
  assert.match(rendered, /Rule evidence/);
  assert.match(rendered, /Paired message.*link/i);
  assert.match(rendered, /Research artifact only/);
  assert.match(rendered, /<img src=x onerror=alert\(1\)>/);
  assert.doesNotMatch(rendered, /undefined/);
});
