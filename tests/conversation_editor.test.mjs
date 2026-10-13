import assert from 'node:assert/strict';
import { readFileSync, existsSync } from 'node:fs';
import test from 'node:test';
import { createContext, runInContext } from 'node:vm';

const path = new URL('../web/conversation.js', import.meta.url);
const script = existsSync(path) ? readFileSync(path, 'utf8') : '';
class Element {
  constructor(tag = 'div') { this.tagName = tag.toUpperCase(); }
  value = ''; checked = false; hidden = false; disabled = false;
  children = []; listeners = {}; dataset = {}; attributes = {}; _text = '';
  get textContent() { return this._text + this.children.map(item => item.textContent).join(' '); }
  set textContent(value) { this._text = String(value); this.children = []; }
  set innerHTML(value) { throw new Error('Unsafe HTML rendering'); }
  append(...children) { this.children.push(...children); }
  replaceChildren(...children) { this._text = ''; this.children = children; }
  addEventListener(type, callback) { this.listeners[type] = callback; }
  setAttribute(name, value) { this.attributes[name] = String(value); }
  getAttribute(name) { return this.attributes[name]; }
  focus() {}
}
function descendants(element) { return [element, ...element.children.flatMap(descendants)]; }
function setup() {
  const root = new Element('section');
  const changes = [];
  const context = createContext({ document: { createElement: tag => new Element(tag) } });
  runInContext(script, context);
  assert.equal(typeof context.SentinelConversation?.createEditor, 'function', 'Task 11 turn editor is missing');
  const editor = context.SentinelConversation.createEditor(root, input => changes.push(JSON.parse(JSON.stringify(input))));
  return { root, editor, changes,
    fields(role) { return descendants(root).filter(item => item.dataset.role === role); },
    read() { return JSON.parse(JSON.stringify(editor.read())); },
    click(role, index = 0) { const element = this.fields(role)[index]; element.listeners.click({ target: element }); },
    edit(role, value, index = 0, type = 'input') { const element = this.fields(role)[index]; element.value = value; element.listeners[type]({ target: element }); },
    choose(index) { const element = this.fields('target')[index]; element.checked = true; element.listeners.change({ target: element }); },
  };
}
function input(kind = 'linear') {
  const turns = [
    { turn_id: 'a', speaker_id: 'local_a', text: 'earlier' },
    { turn_id: 'b', speaker_id: null, text: 'selected' },
    { turn_id: 'c', speaker_id: null, text: 'later' },
  ];
  if (kind === 'reply_thread') turns.forEach((turn, index) => { turn.reply_to = index === 0 ? null : turns[index - 1].turn_id; });
  return { conversation_kind: kind, conversation_turns: turns, target_turn_id: 'b' };
}

test('legacy editor is empty and programmatic populate or clear sends no user callbacks', () => {
  const app = setup();
  assert.deepEqual(app.read(), {});
  app.editor.populate(input());
  assert.deepEqual(app.read(), input());
  app.editor.clear();
  assert.deepEqual(app.read(), {});
  assert.deepEqual(app.changes, []);
});

test('enabling the editor and adding turns generates distinct opaque IDs', () => {
  const app = setup();
  const enabled = app.fields('enabled')[0]; enabled.checked = true; enabled.listeners.change({ target: enabled });
  app.edit('text', 'first');
  app.click('add');
  app.edit('text', 'second', 1);
  const value = app.read();
  assert.equal(value.conversation_turns.length, 2);
  assert.equal(new Set(value.conversation_turns.map(turn => turn.turn_id)).size, 2);
  assert.ok(value.conversation_turns.every(turn => /^[A-Za-z0-9_-]{1,64}$/.test(turn.turn_id)));
  assert.equal(app.changes.length, 4);
});

test('target radio selection and text edits return exact submitted text', () => {
  const app = setup(); app.editor.populate(input());
  app.choose(2);
  app.edit('text', 'literal <img src=x> "reported abuse"', 2);
  assert.equal(app.read().target_turn_id, 'c');
  assert.equal(app.read().conversation_turns[2].text, 'literal <img src=x> "reported abuse"');
  assert.equal(descendants(app.root).some(item => item.tagName === 'IMG'), false);
  assert.equal(app.fields('text')[2].attributes['aria-label'], 'Text for turn 3');
});

test('linear turn movement preserves target identity and supports removing other turns', () => {
  const app = setup(); app.editor.populate(input());
  app.click('up', 2);
  assert.deepEqual(app.read().conversation_turns.map(turn => turn.turn_id), ['a', 'c', 'b']);
  assert.equal(app.read().target_turn_id, 'b');
  app.click('remove', 1);
  assert.deepEqual(app.read().conversation_turns.map(turn => turn.turn_id), ['a', 'b']);
});

test('removing selected target is rejected until a different target is chosen', () => {
  const app = setup(); app.editor.populate(input());
  app.click('remove', 1);
  assert.deepEqual(app.read(), input());
  assert.match(app.fields('error')[0].textContent, /target/i);
  app.choose(0); app.click('remove', 1);
  assert.deepEqual(app.read().conversation_turns.map(turn => turn.turn_id), ['a', 'c']);
});

test('reply parent controls offer only earlier turns and explicitly preserve null roots', () => {
  const app = setup(); app.editor.populate(input('reply_thread'));
  const reply = app.fields('reply')[1];
  assert.deepEqual(reply.children.map(option => option.value), ['', 'a']);
  app.edit('reply', '', 1, 'change');
  assert.equal(app.read().conversation_turns[1].reply_to, null);
});

test('reply movement or parent deletion cannot invent a replacement relationship', () => {
  const app = setup(); app.editor.populate(input('reply_thread'));
  app.click('up', 2);
  assert.deepEqual(app.read(), input('reply_thread'));
  assert.match(app.fields('error')[0].textContent, /earlier|reply/i);
  app.click('remove', 0);
  assert.deepEqual(app.read(), input('reply_thread'));
  app.edit('reply', '', 1, 'change');
  app.click('remove', 0);
  assert.deepEqual(app.read().conversation_turns.map(turn => turn.turn_id), ['b', 'c']);
});

test('switching to reply mode supplies nullable parents without guessing ancestry', () => {
  const app = setup(); app.editor.populate(input());
  app.edit('kind', 'reply_thread', 0, 'change');
  assert.ok(app.read().conversation_turns.every(turn => turn.reply_to === null));
  app.edit('kind', 'linear', 0, 'change');
  assert.ok(app.read().conversation_turns.every(turn => !Object.hasOwn(turn, 'reply_to')));
});

test('relative times are preserved and contradictory reorder is rejected', () => {
  const value = input(); value.conversation_turns.forEach((turn, index) => { turn.relative_time_seconds = index; });
  const app = setup(); app.editor.populate(value); app.click('up', 2);
  assert.deepEqual(app.read(), value);
  assert.match(app.fields('error')[0].textContent, /time|order/i);
});

test('read rejects empty text, unsupported IDs and oversized conversation', () => {
  const app = setup(); const value = input(); value.conversation_turns[1].text = '';
  app.editor.populate(value); assert.throws(() => app.read(), /text/i);
  value.conversation_turns[1].text = 'selected'; value.conversation_turns[0].speaker_id = 'not an opaque label';
  app.editor.populate(value); assert.throws(() => app.read(), /speaker/i);
  value.conversation_turns[0].speaker_id = null; value.conversation_turns[0].text = 'x'.repeat(20001);
  app.editor.populate(value); assert.throws(() => app.read(), /20,000|characters/i);
});

test('coverage names the target and excludes later turns from the preceding window', () => {
  const app = setup(); app.editor.populate(input());
  assert.match(app.fields('coverage')[0].textContent, /1 preceding/i);
  assert.match(app.fields('coverage')[0].textContent, /1 later/i);
  app.choose(0);
  assert.match(app.fields('coverage')[0].textContent, /no preceding|missing context/i);
});

test('a supplied language is retained and omitted language is explicitly assumed', () => {
  const app = setup(); app.editor.populate({ ...input(), language: 'en' });
  assert.equal(app.read().language, 'en');
  app.edit('language', '');
  assert.equal(Object.hasOwn(app.read(), 'language'), false);
  assert.match(app.fields('coverage')[0].textContent, /English.*assum/i);
});

test('the editor admits fifty turns and refuses a fifty-first addition', () => {
  const app = setup(); const value = input();
  value.conversation_turns = Array.from({ length: 50 }, (_, index) => ({ turn_id: 't' + index, speaker_id: null, text: 'text' }));
  value.target_turn_id = 't0'; app.editor.populate(value); app.click('add');
  assert.equal(app.read().conversation_turns.length, 50);
  assert.match(app.fields('error')[0].textContent, /50/);
});


test('opaque IDs reject numeric values', () => {
  const app = setup(); const numeric = input(); numeric.conversation_turns[1].turn_id = 1; numeric.target_turn_id = 1;
  app.editor.populate(numeric); assert.throws(() => app.read(), /ID|target/i);
});

test('opaque local speaker IDs reject a final newline', () => {
  const app = setup(); const newline = input(); newline.conversation_turns[0].speaker_id = 'speaker' + String.fromCharCode(10);
  app.editor.populate(newline); assert.throws(() => app.read(), /speaker/i);
});

test('target character cap is independent of the complete conversation cap', () => {
  const app = setup(); const value = input(); value.conversation_turns[1].text = 'x'.repeat(10000);
  app.editor.populate(value); assert.equal(app.read().conversation_turns[1].text.length, 10000);
  value.conversation_turns[1].text += 'x'; app.editor.populate(value);
  assert.throws(() => app.read(), /10,000|target/i);
});
