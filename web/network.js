// Live dashboard for the community hub. Polls /v1/stats and /v1/campaigns.
const $ = id => document.getElementById(id);
const SVG = 'http://www.w3.org/2000/svg';
const pct = value => value == null ? '–' : `${(value * 100).toFixed(1)}%`;

function cell(row, text, className) {
  const td = document.createElement('td');
  td.textContent = text;
  if (className) td.className = className;
  row.append(td);
}

function drawChart(series) {
  const svg = $('chart');
  const w = 720, h = 240, pad = 36;
  const points = series.filter(p => p.scam_exposures > 0);
  svg.replaceChildren();
  const maxHour = Math.max(1, ...series.map(p => p.hour));
  for (const v of [0, 0.25, 0.5, 0.75, 1]) {
    const y = h - pad - (h - 2 * pad) * v;
    const line = document.createElementNS(SVG, 'line');
    Object.entries({ x1: pad, x2: w - 8, y1: y, y2: y, class: 'grid' }).forEach(([k, val]) => line.setAttribute(k, val));
    const label = document.createElementNS(SVG, 'text');
    Object.entries({ x: pad - 6, y: y + 4, 'text-anchor': 'end', class: 'axis' }).forEach(([k, val]) => label.setAttribute(k, val));
    label.textContent = `${v * 100}%`;
    svg.append(line, label);
  }
  if (points.length > 1) {
    // Soft fill under the combined line.
    const xy = p => [pad + (w - pad - 8) * p.hour / maxHour, h - pad - (h - 2 * pad) * p.combined / p.scam_exposures];
    const area = document.createElementNS(SVG, 'polygon');
    const first = xy(points[0]), last = xy(points[points.length - 1]);
    area.setAttribute('class', 'area');
    area.setAttribute('points', [`${first[0]},${h - pad}`, ...points.map(p => xy(p).join(',')), `${last[0]},${h - pad}`].join(' '));
    svg.append(area);
  }
  for (const [key, cls] of [['model', 'model'], ['combined', 'combined']]) {
    const path = document.createElementNS(SVG, 'polyline');
    path.setAttribute('class', `series ${cls}`);
    path.setAttribute('points', points.map(p => `${pad + (w - pad - 8) * p.hour / maxHour},${h - pad - (h - 2 * pad) * p[key] / p.scam_exposures}`).join(' '));
    svg.append(path);
  }
  const axis = document.createElementNS(SVG, 'text');
  Object.entries({ x: w - 8, y: h - 8, 'text-anchor': 'end', class: 'axis' }).forEach(([k, val]) => axis.setAttribute(k, val));
  axis.textContent = `simulated hours (0–${Math.round(maxHour)})`;
  svg.append(axis);
}

// Simulations count hours from 0; a live hub counts hours since 1970, shown as a local date and time.
function when(hours, simulated) {
  if (simulated) return `hour ${hours.toFixed(1)}`;
  return new Date(hours * 3600 * 1000).toLocaleString([], { dateStyle: 'medium', timeStyle: 'short' });
}

async function refresh() {
  try {
    const [stats, feed] = await Promise.all([fetch('/v1/stats').then(r => r.json()), fetch('/v1/campaigns').then(r => r.json())]);
    $('t-clients').textContent = stats.clients.toLocaleString();
    $('t-reports').textContent = stats.reports.toLocaleString();
    $('t-published').textContent = (stats.clusters.published || 0).toLocaleString();
    $('t-held').textContent = (stats.clusters.held_for_review || 0).toLocaleString();
    const sim = stats.simulation;
    $('clock').textContent = sim ? `Simulated hour ${stats.clock_hour.toFixed(1)} of ${sim.hours}${sim.finished ? ' · finished' : ''} · k = ${stats.k}`
      : `Live hub · k = ${stats.k}`;
    if (sim) {
      $('sim-panel').hidden = false;
      $('sim-meta').textContent = `${sim.detector === 'model' ? 'text-ml-v1 on each device' : 'rates detector'} · ${sim.users.toLocaleString()} simulated users · ${sim.scam_exposures.toLocaleString()} scam messages delivered · ${sim.campaigns_published}/${sim.campaigns_total} campaigns published`;
      $('s-model').textContent = pct(sim.scam_exposures && sim.model_protected / sim.scam_exposures);
      $('s-combined').textContent = pct(sim.scam_exposures && sim.combined_protected / sim.scam_exposures);
      $('s-saves').textContent = sim.network_only_saves.toLocaleString();
      drawChart(sim.series || []);
    }
    const rows = feed.campaigns.slice(0, 40).map(c => {
      const row = document.createElement('tr');
      cell(row, c.id);
      cell(row, c.topics.join(', ') || '—');
      cell(row, c.category || '—');
      cell(row, c.reporters.toLocaleString(), 'num');
      cell(row, c.confidence.toFixed(1), 'num');
      cell(row, when(c.first_hour, sim));
      cell(row, c.published_hour == null ? '—' : when(c.published_hour, sim));
      return row;
    });
    if (rows.length) $('campaigns').replaceChildren(...rows);
  } catch (error) {
    $('clock').textContent = 'Hub unavailable; retrying…';
  }
}

// When this page is served by the hub itself (not by the Sentinel app at /network),
// point the page links at the local Sentinel app instead of the hub.
if (location.pathname === '/' && location.port !== '8787') {
  document.querySelectorAll('[data-app-link]').forEach(link => { link.href = `http://127.0.0.1:8787${link.getAttribute('href')}`; });
}

refresh();
setInterval(refresh, 1500);
