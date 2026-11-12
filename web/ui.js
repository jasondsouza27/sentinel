// Presentation layer for the Sentinel web client.
// It never calls the API or changes what app.js submits. If it fails to load,
// every field is still shown (tabs only collapse once the `js` class is set).
(() => {
  const $ = id => document.getElementById(id);
  const svgNS = 'http://www.w3.org/2000/svg';
  const root = document.documentElement;
  root.classList.add('js');
  const reduceMotion = matchMedia('(prefers-reduced-motion: reduce)').matches;
  const el = (tag, className, text) => {
    const node = document.createElement(tag);
    if (className) node.className = className;
    if (text !== undefined) node.textContent = text;
    return node;
  };

  /* ---------- header ---------- */
  const header = document.querySelector('.site-header');
  const onScroll = () => header?.classList.toggle('scrolled', scrollY > 8);
  addEventListener('scroll', onScroll, { passive: true });
  onScroll();

  const navLinks = new Map([...document.querySelectorAll('.site-header nav a[href^="#"]')]
    .map(link => [link.getAttribute('href').slice(1), link]));
  if ('IntersectionObserver' in window && navLinks.size) {
    const spy = new IntersectionObserver(entries => {
      for (const entry of entries) {
        if (entry.isIntersecting) navLinks.forEach((link, id) => link.classList.toggle('active', id === entry.target.id));
      }
    }, { rootMargin: '-45% 0px -50% 0px' });
    navLinks.forEach((_, id) => { const section = $(id); if (section) spy.observe(section); });
  }

  // Mirror the service status into a tooltip (the pill shows only its dot on mid-size screens).
  const status = $('service-status');
  if (status) {
    const syncTitle = () => { status.title = status.textContent.trim(); };
    new MutationObserver(syncTitle).observe(status, { childList: true, characterData: true, subtree: true });
    syncTitle();
  }

  /* ---------- community hub link ---------- */
  // If Sentinel was started with --network-hub, point the nav link at that hub.
  fetch('/api/health').then(r => r.json()).then(health => {
    const url = health?.community_network?.hub_url;
    if (typeof url !== 'string') return;
    try {
      const parsed = new URL(url);
      if (!['http:', 'https:'].includes(parsed.protocol) || !['127.0.0.1', 'localhost'].includes(parsed.hostname)) return;
      document.querySelectorAll('[data-hub-link]').forEach(link => { link.href = `${parsed.origin}/`; });
    } catch { /* keep the default address */ }
  }).catch(() => {});

  /* ---------- scroll reveal ---------- */
  if ('IntersectionObserver' in window && !reduceMotion) {
    const reveal = new IntersectionObserver(entries => {
      for (const entry of entries) {
        if (!entry.isIntersecting) continue;
        entry.target.classList.add('in');
        reveal.unobserve(entry.target);
      }
    }, { threshold: 0.06 });
    const groups = ['.principles li', '.notice', '.section-heading', '.work-grid > .panel', '.history-panel', '.how-card'];
    for (const selector of groups) {
      document.querySelectorAll(selector).forEach((node, index) => {
        node.classList.add('reveal');
        node.style.transitionDelay = `${Math.min(index, 3) * 90}ms`;
        reveal.observe(node);
      });
    }
  }

  /* ---------- hero example card ---------- */
  const examples = [
    { from: 'Parcel Desk', score: 92, tone: 'high', label: 'High concern',
      note: 'Urgency, a payment request and an unfamiliar link.',
      parts: [['Your parcel is on hold. Pay the '], ['customs fee', 'mark'], [' '], ['within 2 hours', 'mark'], [' at '], ['parcel-release.example', 'link'], [' to avoid return.']],
      signals: ['Urgency pressure', 'Payment request', 'Unknown domain'] },
    { from: 'Campus Jobs', score: 61, tone: 'review', label: 'Review carefully',
      note: 'An offer that asks for money before any work.',
      parts: [['Congratulations, you were selected for a remote role. Send the '], ['registration fee', 'mark'], [' today to '], ['confirm your seat', 'mark'], ['.']],
      signals: ['Upfront fee', 'Unsolicited offer'] },
    { from: 'Study group', score: 6, tone: 'low', label: 'Low observed concern',
      note: 'No pressure, payment or link. Still verify anything unexpected.',
      parts: [["Notes from today's lab are in the shared folder. The quiz moved to Thursday afternoon."]],
      signals: ['No request', 'No link'] },
  ];
  const specimen = document.querySelector('.specimen');
  if (specimen) {
    const from = specimen.querySelector('.specimen-from b');
    const message = specimen.querySelector('.specimen-msg');
    const arc = specimen.querySelector('.specimen-ring .arc');
    const score = specimen.querySelector('.specimen-ring b');
    const badge = specimen.querySelector('.specimen-verdict .badge');
    const note = specimen.querySelector('.specimen-note');
    const signals = specimen.querySelector('.specimen-signals');
    const steps = [...specimen.querySelectorAll('.specimen-step i')];
    const toneColor = { high: 'var(--high)', review: 'var(--review)', low: 'var(--low)' };
    let index = 0;
    const show = example => {
      from.textContent = example.from;
      message.replaceChildren(...example.parts.map(([text, kind]) => kind === 'mark' ? el('mark', '', text) : kind === 'link' ? el('u', '', text) : document.createTextNode(text)));
      score.textContent = example.score;
      arc.style.strokeDashoffset = (169.6 * (1 - example.score / 100)).toFixed(1);
      arc.style.stroke = toneColor[example.tone];
      badge.className = `badge ${example.tone}`;
      badge.textContent = example.label;
      note.textContent = example.note;
      signals.replaceChildren(...example.signals.map(text => el('li', '', text)));
      steps.forEach((step, i) => step.classList.toggle('on', i === index));
    };
    show(examples[0]);
    if (!reduceMotion) {
      let paused = false;
      specimen.addEventListener('pointerenter', () => { paused = true; });
      specimen.addEventListener('pointerleave', () => { paused = false; });
      setInterval(() => {
        if (paused || document.hidden) return;
        specimen.classList.add('swap');
        setTimeout(() => {
          index = (index + 1) % examples.length;
          show(examples[index]);
          specimen.classList.remove('swap');
        }, 380);
      }, 4800);
    }
  }

  /* ---------- input tabs ---------- */
  const form = $('check-form');
  const tabs = [...document.querySelectorAll('.segmented [role="tab"]')];
  const panels = new Map([...document.querySelectorAll('.tab-panel')].map(panel => [panel.dataset.panel, panel]));
  const thumb = document.querySelector('.segmented-thumb');
  const filled = {
    basics: () => ['message', 'url'].some(id => $(id)?.value.trim()),
    thread: () => Boolean($('conversation')?.value.trim()) || Boolean(document.querySelector('#conversation-editor .conversation-heading input:checked')),
    profile: () => ['username', 'age', 'posts', 'followers', 'following', 'website', 'official'].some(id => $(id)?.value.trim()),
  };
  let current = 'basics';
  const selectTab = (name, focus = false) => {
    current = name;
    tabs.forEach((tab, i) => {
      const on = tab.dataset.tab === name;
      tab.setAttribute('aria-selected', String(on));
      tab.tabIndex = on ? 0 : -1;
      if (on) {
        if (thumb) thumb.style.transform = `translateX(${i * 100}%)`;
        if (focus) tab.focus();
      }
    });
    panels.forEach((panel, key) => { panel.hidden = key !== name; });
  };
  const refreshFilled = () => tabs.forEach(tab => tab.classList.toggle('has-value', filled[tab.dataset.tab]?.() || false));
  if (tabs.length && panels.size) {
    tabs.forEach((tab, i) => {
      const panel = panels.get(tab.dataset.tab);
      tab.id = `tab-${tab.dataset.tab}`;
      panel?.setAttribute('aria-labelledby', tab.id);
      tab.addEventListener('click', () => selectTab(tab.dataset.tab));
      tab.addEventListener('keydown', event => {
        const step = event.key === 'ArrowRight' ? 1 : event.key === 'ArrowLeft' ? -1 : 0;
        if (!step) return;
        event.preventDefault();
        selectTab(tabs[(i + step + tabs.length) % tabs.length].dataset.tab, true);
      });
    });
    selectTab('basics');
    form?.addEventListener('input', refreshFilled);
    form?.addEventListener('change', refreshFilled);
    // A field that fails native validation inside a hidden tab: open that tab first.
    form?.addEventListener('invalid', event => {
      const panel = event.target.closest?.('.tab-panel');
      if (panel?.hidden) {
        selectTab(panel.dataset.panel);
        setTimeout(() => event.target.reportValidity());
      }
    }, true);
  }

  /* ---------- character counters ---------- */
  const counters = [];
  for (const id of ['message', 'conversation']) {
    const field = $(id);
    if (!field) continue;
    const counter = el('span', 'char-count');
    counter.setAttribute('aria-hidden', 'true');
    const help = field.nextElementSibling?.classList.contains('field-help') ? field.nextElementSibling : null;
    if (help) {
      const row = el('div', 'field-meta');
      help.replaceWith(row);
      row.append(help, counter);
    } else {
      const row = el('div', 'field-meta');
      field.after(row);
      row.append(el('span'), counter);
    }
    const max = Number(field.maxLength) || 0;
    const update = () => {
      const length = field.value.length;
      counter.textContent = max ? `${length.toLocaleString()} / ${max.toLocaleString()}` : length.toLocaleString();
      counter.classList.toggle('near', max > 0 && length > max * 0.9);
    };
    field.addEventListener('input', update);
    counters.push(update);
    update();
  }
  const refreshFields = () => { counters.forEach(update => update()); refreshFilled(); };

  /* ---------- analyzing state ---------- */
  const button = $('check-button');
  const empty = $('result-empty');
  if (empty) {
    const skeleton = el('div', 'skeleton');
    skeleton.setAttribute('aria-hidden', 'true');
    skeleton.append(el('i'), el('i'), el('i'));
    empty.append(skeleton);
  }
  if (button) {
    new MutationObserver(() => document.body.classList.toggle('is-analyzing', button.disabled))
      .observe(button, { attributes: true, attributeFilter: ['disabled'] });
  }

  /* ---------- overall verdict ---------- */
  const results = $('result-content');
  const toneOf = badge => {
    const c = badge.classList;
    if (c.contains('high') || c.contains('smishing')) return 'high';
    if (c.contains('review') || c.contains('indicators_for_review') || c.contains('spam')) return 'review';
    if (c.contains('low_observed_concern') || c.contains('not_flagged') || c.contains('ham')) return 'low';
    return 'neutral';
  };
  const copy = {
    high: ['Strong warning signs', 'Do not pay, reply or sign in until you verify the sender through an official channel.'],
    review: ['Some signs to review', 'Read the observations below before you act on this.'],
    low: ['No warning signs observed', 'This does not prove it is safe. Stay careful with unexpected requests.'],
    neutral: ['Not enough to assess', 'Add more context, such as the full message or the link, and check again.'],
  };
  let verdict;
  const buildVerdict = () => {
    const node = el('div', 'verdict-summary');
    const ring = el('div', 'verdict-ring');
    const svg = document.createElementNS(svgNS, 'svg');
    svg.setAttribute('viewBox', '0 0 72 72');
    for (const cls of ['track', 'arc']) {
      const circle = document.createElementNS(svgNS, 'circle');
      for (const [k, v] of Object.entries({ cx: 36, cy: 36, r: 32, class: cls })) circle.setAttribute(k, v);
      svg.append(circle);
    }
    ring.append(svg, el('b'), el('small'));
    const text = el('div', 'verdict-text');
    text.append(el('span', 'mono', 'Overall'), el('strong'), el('p'));
    node.append(ring, text);
    results.before(node);
    return node;
  };
  const renderVerdict = () => {
    if (!results) return;
    const badges = [...results.querySelectorAll('.assessment-head .badge')];
    if (results.hidden || !badges.length) { if (verdict) verdict.hidden = true; return; }
    verdict ??= buildVerdict();
    const tones = badges.map(toneOf);
    const tone = ['high', 'review', 'low'].find(t => tones.includes(t)) || 'neutral';
    const flagged = tones.filter(t => t === 'high' || t === 'review').length;
    const assessed = tones.filter(t => t !== 'neutral').length;
    verdict.className = `verdict-summary tone-${tone}`;
    verdict.hidden = false;
    verdict.querySelector('b').textContent = String(flagged);
    verdict.querySelector('small').textContent = `OF ${assessed || badges.length}`;
    verdict.querySelector('strong').textContent = copy[tone][0];
    verdict.querySelector('p').textContent = copy[tone][1];
    const arc = verdict.querySelector('.arc');
    const ratio = assessed ? flagged / assessed : 0;
    arc.style.strokeDashoffset = '201';
    requestAnimationFrame(() => requestAnimationFrame(() => {
      arc.style.strokeDashoffset = (201 * (1 - (tone === 'low' ? 1 : ratio))).toFixed(1);
    }));
    // restart the entrance animation
    verdict.style.animation = 'none';
    void verdict.offsetWidth;
    verdict.style.animation = '';
  };

  if (results) {
    new MutationObserver(() => {
      renderVerdict();
      refreshFields();
      const shown = !results.hidden && results.childElementCount > 0;
      // Opening a saved case may fill a tab other than the one in view.
      if (shown && !filled[current]?.()) {
        const first = tabs.find(tab => filled[tab.dataset.tab]?.());
        if (first) selectTab(first.dataset.tab);
      }
      if (shown && matchMedia('(max-width: 1040px)').matches) {
        $('result-panel')?.scrollIntoView({ behavior: reduceMotion ? 'auto' : 'smooth', block: 'start' });
      }
    }).observe(results, { childList: true, attributes: true, attributeFilter: ['hidden'] });
  }

  form?.addEventListener('reset', () => setTimeout(() => { refreshFields(); selectTab('basics'); }));

  /* ---------- keyboard ---------- */
  form?.addEventListener('keydown', event => {
    if (event.key !== 'Enter' || !(event.metaKey || event.ctrlKey)) return;
    event.preventDefault();
    if (!button?.disabled) form.requestSubmit(button);
  });
  const hint = document.querySelector('.kbd-hint kbd');
  if (hint && /Mac|iPhone|iPad/.test(navigator.platform || navigator.userAgent)) hint.textContent = '⌘';
})();
