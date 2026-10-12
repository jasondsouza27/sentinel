import assert from 'node:assert/strict';
import { readFileSync } from 'node:fs';
import test from 'node:test';
import { runInNewContext } from 'node:vm';

const script = readFileSync(new URL('../web/app.js', import.meta.url), 'utf8');
const html = readFileSync(new URL('../web/index.html', import.meta.url), 'utf8');

// A small DOM boundary for the real client script; browser checks cover layout,
// native validation and downloads. Fetch is controlled to exercise late replies.
class Element {
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
    const element = new Element();
    element.hidden = /\bhidden\b/.test(match[2]);
    element.disabled = /\bdisabled\b/.test(match[2]);
    elements.set(id, element);
  }
  const get = id => elements.get(id);
  get('check-form').reset = () => {
    for (const element of elements.values()) element.value = '';
  };
  const savedInputs = [];
  let analyze = async () => new Response(JSON.stringify(result('First assessment')));
  let save = async () => ({ id: 'new-case' });
  const fetch = async (path, options = {}) => {
    let data;
    if (path === '/api/health') data = { reputation_loaded: false };
    else if (path === '/api/analyze') return analyze(JSON.parse(options.body));
    else if (path === '/api/cases' && options.method === 'POST') {
      const input = JSON.parse(options.body).input;
      savedInputs.push(input);
      data = await save(input);
    } else if (path === '/api/cases') data = cases;
    else throw new Error(`Unexpected request: ${options.method || 'GET'} ${path}`);
    return new Response(JSON.stringify(data));
  };
  runInNewContext(script, {
    document: { getElementById: get, createElement: () => new Element() },
    fetch,
  }, { filename: 'web/app.js' });
  await new Promise(resolve => setImmediate(resolve));
  return {
    get, savedInputs,
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
