(() => {
  let editorCounter = 0;
  let turnCounter = 0;
  const idPattern = /^[A-Za-z0-9_-]{1,64}$/;
  const copy = value => JSON.parse(JSON.stringify(value));
  const newId = () => `t_${Date.now().toString(36)}_${(++turnCounter).toString(36)}`;

  function createEditor(rootElement, onChange = () => {}) {
    const prefix = `conversation_${++editorCounter}`;
    let enabled = false, kind = 'linear', turns = [], target = null, language = '';
    let errorText = '', coverageNode, errorNode;
    let controls = [];

    function element(tag, text, className) {
      const value = document.createElement(tag);
      if (text !== undefined) value.textContent = text;
      if (className) value.className = className;
      return value;
    }
    function field(role, labelText, control, suffix = '') {
      control.dataset.role = role;
      const id = `${prefix}_${role}_${suffix}`;
      control.setAttribute('id', id);
      control.setAttribute('aria-label', labelText);
      const label = element('label', labelText);
      label.setAttribute('for', id);
      controls.push(control);
      return [label, control];
    }
    function snapshot() {
      if (!enabled) return {};
      const value = { conversation_kind: kind, conversation_turns: copy(turns), target_turn_id: target };
      if (typeof language === 'string' && language.trim()) value.language = language;
      return value;
    }
    function relationships(candidate = turns) {
      if (!candidate.some(turn => turn.turn_id === target)) return 'Choose another target before removing the selected target turn.';
      const seen = new Set();
      let lastTime;
      for (const turn of candidate) {
        if (typeof turn.turn_id !== 'string' || !idPattern.test(turn.turn_id) || seen.has(turn.turn_id)) return 'Every turn needs a unique opaque ID.';
        if (kind === 'reply_thread' && (turn.reply_to !== null && !seen.has(turn.reply_to))) return 'A reply must refer to an earlier turn. Change the reply before moving or removing its parent.';
        if (Object.hasOwn(turn, 'relative_time_seconds')) {
          const value = turn.relative_time_seconds;
          if (typeof value !== 'number' || !Number.isFinite(value) || value < 0 || (lastTime !== undefined && value < lastTime)) return 'Relative times must be finite, nonnegative and preserve turn order.';
          lastTime = value;
        }
        seen.add(turn.turn_id);
      }
      return '';
    }
    function validation() {
      if (!['linear', 'reply_thread'].includes(kind)) return 'Choose linear or reply thread conversation.';
      if (!turns.length || turns.length > 50) return 'Supply between 1 and 50 turns.';
      const problem = relationships();
      if (problem) return problem;
      let total = 0;
      const required = ['turn_id', 'speaker_id', 'text'];
      const allowed = new Set([...required, 'relative_time_seconds', ...(kind === 'reply_thread' ? ['reply_to'] : [])]);
      for (const turn of turns) {
        if (!required.every(key => Object.hasOwn(turn, key)) || Object.keys(turn).some(key => !allowed.has(key))) return 'The turn has incomplete or unsupported fields.';
        if (turn.speaker_id !== null && (typeof turn.speaker_id !== 'string' || !idPattern.test(turn.speaker_id))) return 'Use a local speaker label with up to 64 letters, numbers, underscores or hyphens.';
        if (typeof turn.text !== 'string' || !turn.text.trim()) return 'Every turn needs nonempty text.';
        total += turn.text.length;
      }
      if (total > 20000) return 'The conversation exceeds 20,000 characters.';
      if (turns.find(turn => turn.turn_id === target).text.length > 10000) return 'The target exceeds 10,000 characters.';
      return '';
    }
    function updateCoverage() {
      if (!coverageNode) return;
      const index = turns.findIndex(turn => turn.turn_id === target);
      let ancestors = [];
      if (index >= 0 && kind === 'linear') ancestors = turns.slice(0, index);
      else if (index >= 0) {
        const seen = new Set([target]);
        let parent = turns[index].reply_to;
        while (parent !== null && parent !== undefined && !seen.has(parent)) {
          seen.add(parent);
          const value = turns.find(turn => turn.turn_id === parent);
          if (!value) break;
          ancestors.push(value); parent = value.reply_to;
        }
      }
      const count = Math.min(4, ancestors.length);
      const context = count ? `${count} preceding turns used${ancestors.length > 4 ? `; ${ancestors.length - 4} older turns omitted` : ''}.` : 'No preceding turns: missing context.';
      coverageNode.textContent = `Target: turn ${index + 1}. ${context} ${Math.max(0, turns.length - index - 1)} later turns excluded. ${language.trim() ? `Declared language: ${language}.` : 'English is assumed unless you declare a language.'}`;
      errorNode.textContent = errorText;
    }
    function notify() { errorText = ''; updateCoverage(); onChange(snapshot()); }
    function changeTurns(candidate, focusIndex = 0) {
      const problem = relationships(candidate);
      if (problem) { errorText = problem; updateCoverage(); return; }
      turns = candidate; errorText = ''; render('text', focusIndex); onChange(snapshot());
    }
    function button(role, text, callback, disabled = false) {
      const value = element('button', text);
      value.type = 'button'; value.dataset.role = role; value.disabled = disabled;
      value.addEventListener('click', callback);
      controls.push(value);
      return value;
    }
    function render(focusRole, focusIndex = 0) {
      controls = [];
      const toggle = element('input'); toggle.type = 'checkbox'; toggle.checked = enabled;
      const header = element('div', undefined, 'conversation-heading');
      header.append(...field('enabled', 'Use ordered conversation turns', toggle));
      toggle.addEventListener('change', () => {
        enabled = toggle.checked;
        if (enabled && !turns.length) { const turn = { turn_id: newId(), speaker_id: null, text: '' }; turns = [turn]; target = turn.turn_id; }
        errorText = ''; render('enabled'); onChange(snapshot());
      });
      const body = element('div', undefined, 'conversation-body'); body.hidden = !enabled;
      const kindControl = element('select');
      for (const [value, text] of [['linear', 'Linear conversation'], ['reply_thread', 'Reply thread']]) {
        const option = element('option', text); option.value = value; kindControl.append(option);
      }
      kindControl.value = kind;
      kindControl.addEventListener('change', () => {
        kind = kindControl.value;
        turns = turns.map(turn => { const value = { ...turn }; if (kind === 'reply_thread') value.reply_to = null; else delete value.reply_to; return value; });
        errorText = ''; render('kind'); onChange(snapshot());
      });
      body.append(...field('kind', 'Conversation order', kindControl));
      const languageControl = element('input'); languageControl.value = language;
      languageControl.placeholder = 'Leave blank to assume English; en to declare English';
      languageControl.maxLength = 64;
      languageControl.addEventListener('input', () => { language = languageControl.value; notify(); });
      body.append(...field('language', 'Language declaration (optional)', languageControl));
      const list = element('div', undefined, 'conversation-turns'); list.dataset.role = 'turns';
      turns.forEach((turn, index) => {
        const item = element('fieldset', undefined, 'conversation-turn');
        item.append(element('legend', `Turn ${index + 1}`));
        const radio = element('input'); radio.type = 'radio'; radio.name = `${prefix}_target`;
        radio.checked = turn.turn_id === target; radio.dataset.turnId = turn.turn_id;
        radio.addEventListener('change', () => {
          if (!radio.checked) return; target = turn.turn_id;
          controls.filter(value => value.dataset.role === 'target').forEach(value => { value.checked = value.dataset.turnId === target; });
          notify();
        });
        const targetRow = element('div', undefined, 'turn-target'); targetRow.append(...field('target', 'Assess this turn', radio, index)); item.append(targetRow);
        const text = element('textarea'); text.rows = 3; text.value = turn.text ?? ''; text.maxLength = 20000;
        text.addEventListener('input', () => { turn.text = text.value; notify(); });
        item.append(...field('text', `Text for turn ${index + 1}`, text, index));
        const speaker = element('input'); speaker.value = turn.speaker_id ?? ''; speaker.maxLength = 64;
        speaker.placeholder = 'Optional local label, e.g. speaker_a';
        speaker.addEventListener('input', () => { turn.speaker_id = speaker.value || null; notify(); });
        item.append(...field('speaker', `Local speaker for turn ${index + 1}`, speaker, index));
        const time = element('input'); time.type = 'number'; time.min = '0'; time.step = 'any'; time.value = turn.relative_time_seconds ?? '';
        time.addEventListener('input', () => { if (time.value === '') delete turn.relative_time_seconds; else turn.relative_time_seconds = Number(time.value); notify(); });
        item.append(...field('time', `Relative seconds for turn ${index + 1} (optional)`, time, index));
        if (kind === 'reply_thread') {
          const reply = element('select'); const option = element('option', 'No parent'); option.value = ''; reply.append(option);
          turns.slice(0, index).forEach((earlier, parentIndex) => { const value = element('option', `Turn ${parentIndex + 1}`); value.value = earlier.turn_id; reply.append(value); });
          reply.value = turn.reply_to ?? '';
          reply.addEventListener('change', () => { turn.reply_to = reply.value || null; notify(); });
          item.append(...field('reply', `Reply parent for turn ${index + 1}`, reply, index));
        }
        const actions = element('div', undefined, 'turn-actions');
        actions.append(button('up', 'Move up', () => {
          if (!index) return; const values = turns.slice(); [values[index - 1], values[index]] = [values[index], values[index - 1]]; changeTurns(values, index - 1);
        }, index === 0), button('down', 'Move down', () => {
          if (index === turns.length - 1) return; const values = turns.slice(); [values[index], values[index + 1]] = [values[index + 1], values[index]]; changeTurns(values, index + 1);
        }, index === turns.length - 1), button('remove', 'Remove turn', () => changeTurns(turns.filter(value => value.turn_id !== turn.turn_id), Math.max(0, index - 1))));
        item.append(actions); list.append(item);
      });
      body.append(list, button('add', 'Add turn', () => {
        if (turns.length >= 50) { errorText = 'A conversation can contain at most 50 turns.'; updateCoverage(); return; }
        const turn = { turn_id: newId(), speaker_id: null, text: '' };
        if (kind === 'reply_thread') turn.reply_to = null;
        turns.push(turn); errorText = ''; render('text', turns.length - 1); onChange(snapshot());
      }));
      coverageNode = element('p', undefined, 'field-help'); coverageNode.dataset.role = 'coverage'; coverageNode.setAttribute('aria-live', 'polite');
      errorNode = element('p', undefined, 'form-message'); errorNode.dataset.role = 'error'; errorNode.setAttribute('role', 'alert');
      body.append(coverageNode, errorNode); rootElement.replaceChildren(header, body); updateCoverage();
      if (focusRole) controls.filter(value => value.dataset.role === focusRole)[focusIndex]?.focus();
    }
    render();
    return {
      read() { if (!enabled) return {}; const problem = validation(); if (problem) { errorText = problem; updateCoverage(); throw new Error(problem); } return snapshot(); },
      populate(input = {}) {
        enabled = Object.hasOwn(input, 'conversation_kind') || Object.hasOwn(input, 'conversation_turns') || Object.hasOwn(input, 'target_turn_id');
        kind = input.conversation_kind || 'linear'; turns = Array.isArray(input.conversation_turns) ? copy(input.conversation_turns) : [];
        target = input.target_turn_id ?? null; language = typeof input.language === 'string' ? input.language : ''; errorText = ''; render();
      },
      clear() { enabled = false; kind = 'linear'; turns = []; target = null; language = ''; errorText = ''; render(); },
    };
  }
  globalThis.SentinelConversation = { createEditor };
})();
