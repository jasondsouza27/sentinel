import assert from 'node:assert/strict';
import { readFileSync } from 'node:fs';
import test from 'node:test';
import { runInNewContext } from 'node:vm';

const script = readFileSync(new URL('../extension/popup.js', import.meta.url), 'utf8');

class Element {
  value = '';
  hidden = false;
  disabled = false;
  children = [];
  _text = '';
  get textContent() { return this._text + this.children.map(child => child.textContent).join(' '); }
  set textContent(value) { this._text = value; this.children = []; }
  append(...items) { this.children.push(...items); }
  replaceChildren(...items) { this._text = ''; this.children = items; }
}

function setup(assessment) {
  const ids = ['selection', 'message', 'url', 'check', 'open', 'error', 'result', 'findings', 'save', 'save-status'];
  const elements = new Map(ids.map(id => [id, new Element()]));
  const item = { level: 'review', evidence: ['Rule evidence'], action: 'Verify independently' };
  const response = { fraud: item, harmful_content: item, profile: { status: 'insufficient_evidence', evidence: [], action: 'Review' } };
  if (assessment) response.paired_assessment = assessment;
  runInNewContext(script, {
    document: { getElementById: id => elements.get(id), createElement: () => new Element() },
    fetch: async () => new Response(JSON.stringify(response)),
    chrome: { storage: { session: { get: async () => ({}), remove: async () => {} } }, tabs: { create: () => {} } },
  });
  return elements;
}

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
