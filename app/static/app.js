/* mlev local UI.
   Talks to the Flask app in app/server.py. Long jobs run on the server and are
   polled, because a backfill takes minutes and a fetch cannot wait that long. */

const state = {
  sport: 'nfl',
  tab: 'data',
  status: null,
  polls: {},
};

const $ = (sel, root = document) => root.querySelector(sel);
const $$ = (sel, root = document) => [...root.querySelectorAll(sel)];

const fmt = (v, digits = 3) =>
  v === null || v === undefined || v === '' ? '—'
  : typeof v === 'number' ? (Number.isInteger(v) ? v.toLocaleString() : v.toFixed(digits))
  : v;

/* Table cells: a season is 2026, not "2,026". Only genuine counts get grouped,
   and in a data table almost no integer is a count. */
const fmtCell = (v, digits = 3) =>
  v === null || v === undefined || v === '' ? '—'
  : typeof v === 'number' ? (Number.isInteger(v) ? String(v) : v.toFixed(digits))
  : v;

async function api(path, options) {
  const res = await fetch(path, {
    headers: { 'Content-Type': 'application/json' },
    ...options,
  });
  const body = await res.json().catch(() => ({ error: `HTTP ${res.status}` }));
  if (!res.ok) throw new Error(body.error || `HTTP ${res.status}`);
  return body;
}

/* ---------------- theme ---------------- */
const savedTheme = (() => { try { return localStorage.getItem('mlev-theme'); } catch { return null; } })();
if (savedTheme) document.documentElement.setAttribute('data-theme', savedTheme);
$('#themeToggle').addEventListener('click', () => {
  const now = document.documentElement.getAttribute('data-theme');
  const isDark = now === 'dark' || (!now && matchMedia('(prefers-color-scheme: dark)').matches);
  const next = isDark ? 'light' : 'dark';
  document.documentElement.setAttribute('data-theme', next);
  try { localStorage.setItem('mlev-theme', next); } catch { /* private mode */ }
});

/* ---------------- navigation ---------------- */
$$('.sportswitch button').forEach(btn => btn.addEventListener('click', () => {
  state.sport = btn.dataset.sport;
  $$('.sportswitch button').forEach(b => b.setAttribute('aria-selected', String(b === btn)));
  render();
  loadBacktest();
}));

$$('nav.tabs button').forEach(btn => btn.addEventListener('click', () => {
  state.tab = btn.dataset.tab;
  $$('nav.tabs button').forEach(b => b.setAttribute('aria-selected', String(b === btn)));
  $$('section[data-panel]').forEach(s => { s.hidden = s.dataset.panel !== state.tab; });
  if (state.tab === 'backtest') loadBacktest();
  if (state.tab === 'predict') loadFixtureHelp();
}));

/* ---------------- status ---------------- */
async function refreshStatus() {
  try {
    state.status = await api('/api/status');
    render();
  } catch (err) {
    console.error(err);
  }
}

function sportStatus() {
  return state.status ? state.status[state.sport] : null;
}

function fileRow(f) {
  const cls = f.exists ? 'ok' : 'missing';
  const label = f.exists ? `${f.rows.toLocaleString()} rows` : 'not downloaded';
  return `<li>
      <span class="pill ${cls}"><span class="dot"></span>${f.exists ? 'ready' : 'missing'}</span>
      <span class="name">${f.name.replace(/_/g, ' ')}</span>
      <span class="meta">${label}${f.updated ? ' · ' + f.updated : ''}</span>
    </li>`;
}

function render() {
  const st = sportStatus();
  if (!st) return;

  $('#playersField').hidden = state.sport !== 'epl';
  $('#seasonField').hidden = state.sport === 'epl';
  $('#weekField').hidden = state.sport === 'epl';
  $('#eplFixtures').hidden = !(state.sport === 'epl' && $('#scLevel').value === 'game');

  $('#dataIntro').innerHTML = st.ready
    ? `<strong>${st.label} data is ready.</strong> Seasons ${st.seasons}, plus the
       ${st.upcoming_season}/${String(st.upcoming_season + 1).slice(2)} season for predicting.
       Run this again any time to pick up newly played fixtures.`
    : `<strong>No ${st.label} data yet.</strong> Press the button below — it downloads
       roughly ${state.sport === 'nfl' ? '100 MB and takes a few minutes' : '15 MB and takes about a minute'}.
       You only need to do this once.`;

  $('#rawList').innerHTML = st.raw.map(fileRow).join('');
  $('#cleanList').innerHTML = [...st.clean, ...st.features].map(fileRow).join('');

  const level = $('#btLevel').value;
  const bt = st.backtests.find(b => b.level === level);
  $('#btFreshness').className = 'pill ' + (bt ? 'ok' : 'missing');
  $('#btFreshness').innerHTML = `<span class="dot"></span>${bt ? 'last run ' + bt.updated : 'never run'}`;

  $('#predList').innerHTML = st.predictions.length
    ? st.predictions.map(p => `<li>
        <span class="name"><a href="#" data-pred="${p.name}">${p.name}</a></span>
        <span class="meta">${p.level} · ${p.updated}</span></li>`).join('')
    : '<li class="empty">No predictions saved yet.</li>';

  $$('#predList a[data-pred]').forEach(a => a.addEventListener('click', async ev => {
    ev.preventDefault();
    const data = await api(`/api/predictions/${state.sport}/${a.dataset.pred}`);
    $('#predictionResults').innerHTML =
      `<div class="card"><h2>${a.dataset.pred}</h2>${renderPredictionTable(data)}</div>`;
  }));

  const busy = (state.status._jobs || []).some(j => j.status === 'running' && j.sport === state.sport);
  ['#btnBackfill', '#btnBacktest', '#btnScore'].forEach(sel => { $(sel).disabled = busy; });
}

/* ---------------- jobs ---------------- */
function jobBox(container, job) {
  const cls = job.status === 'failed' ? 'err' : job.status === 'done' ? '' : 'warn';
  const bar = job.status === 'running' ? '<div class="progressbar"><i></i></div>' : '';
  const head = job.status === 'running' ? `Running — ${job.elapsed}s elapsed`
    : job.status === 'done' ? `Finished in ${job.elapsed}s`
    : `Failed after ${job.elapsed}s`;
  container.innerHTML = `
    <div class="note ${cls}" style="margin-top:14px">
      <strong>${head}</strong>${job.error ? '<br>' + escapeHtml(job.error) : ''}
      ${bar}
      <pre class="log">${escapeHtml((job.lines || []).slice(-40).join('\n'))}</pre>
    </div>`;
  const log = $('pre.log', container);
  if (log) log.scrollTop = log.scrollHeight;
}

function escapeHtml(s) {
  return String(s).replace(/[&<>"']/g, c =>
    ({ '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;', "'": '&#39;' }[c]));
}

function pollJob(jobId, container, onDone) {
  clearInterval(state.polls[container.id]);
  state.polls[container.id] = setInterval(async () => {
    try {
      const job = await api(`/api/job/${jobId}`);
      jobBox(container, job);
      if (job.status !== 'running') {
        clearInterval(state.polls[container.id]);
        await refreshStatus();
        if (job.status === 'done' && onDone) onDone(job);
      }
    } catch (err) {
      clearInterval(state.polls[container.id]);
      container.innerHTML = `<div class="note err">Lost contact with the server: ${escapeHtml(err.message)}</div>`;
    }
  }, 1000);
}

async function startJob(path, body, container, onDone) {
  container.innerHTML = '<div class="note warn"><strong>Starting…</strong></div>';
  try {
    const { job_id } = await api(path, { method: 'POST', body: JSON.stringify(body) });
    render();
    pollJob(job_id, container, onDone);
  } catch (err) {
    container.innerHTML = `<div class="note err">${escapeHtml(err.message)}</div>`;
  }
}

$('#btnBackfill').addEventListener('click', () => startJob('/api/backfill', {
  sport: state.sport,
  with_players: $('#withPlayers').checked,
  force: $('#forceRefetch').checked,
}, $('#backfillJob')));

$('#btnBacktest').addEventListener('click', () => startJob('/api/backtest', {
  sport: state.sport,
  level: $('#btLevel').value,
}, $('#backtestJob'), job => showBacktest(job.result)));

$('#btLevel').addEventListener('change', () => { render(); loadBacktest(); });
$('#scLevel').addEventListener('change', render);

$('#btnScore').addEventListener('click', () => {
  const body = { sport: state.sport, level: $('#scLevel').value };
  if (state.sport === 'nfl') {
    if ($('#scSeason').value) body.season = $('#scSeason').value;
    if ($('#scWeek').value) body.week = $('#scWeek').value;
  } else if ($('#scLevel').value === 'game') {
    const rows = parseFixtures($('#fixtureText').value);
    if (rows.length) body.fixtures = rows;
  }
  startJob('/api/score', body, $('#scoreJob'), job => {
    $('#predictionResults').innerHTML =
      `<div class="card"><h2>Predictions</h2>
       <p class="sub">Saved as <code>${job.result.file}</code> in data/${state.sport}/predictions/</p>
       ${renderPredictionTable(job.result.table)}</div>`;
    $('#predictionResults').scrollIntoView({ behavior: 'smooth', block: 'start' });
  });
});

function parseFixtures(text) {
  return text.split('\n').map(l => l.trim()).filter(Boolean).map(line => {
    const [Date_, HomeTeam, AwayTeam] = line.split(',').map(s => s.trim());
    return { Date: Date_, HomeTeam, AwayTeam };
  }).filter(r => r.Date && r.HomeTeam && r.AwayTeam);
}

async function loadFixtureHelp() {
  if (state.sport !== 'epl') return;
  try {
    const { fixtures, note } = await api('/api/fixtures/epl');
    $('#fixtureNote').innerHTML = fixtures.length
      ? `<strong>${fixtures.length} upcoming fixtures</strong> loaded from football-data.co.uk. Edit the list if you want.`
      : `<strong>No fixtures in the live feed right now.</strong> ${escapeHtml(note || '')}
         Type the matchday you want below — one per line.`;
    if (fixtures.length && !$('#fixtureText').value.trim()) {
      $('#fixtureText').value = fixtures.map(f => `${f.Date}, ${f.HomeTeam}, ${f.AwayTeam}`).join('\n');
    }
    if (!$('#fixtureText').value.trim()) {
      $('#fixtureText').placeholder = '29/08/2026, Liverpool, Arsenal\n29/08/2026, Man United, Brighton';
    }
  } catch { /* the form still works without the feed */ }
}

/* ---------------- backtest rendering ---------------- */
async function loadBacktest() {
  if (state.tab !== 'backtest') return;
  try {
    const data = await api(`/api/backtest/${state.sport}/${$('#btLevel').value}`);
    if (data.overall.rows.length) showBacktest(data);
    else $('#backtestResults').innerHTML =
      '<div class="card"><p class="empty">No backtest yet for this market. Press “Run backtest”.</p></div>';
  } catch { /* nothing saved yet */ }
}

/* Which metric matters for which target, and which direction is good. */
const HEADLINE = [
  { key: 'brier', label: 'Brier score', lower: true, against: 'baseline_brier', againstLabel: 'guessing the base rate' },
  { key: 'log_loss', label: 'Log loss', lower: true, against: 'baseline_log_loss', againstLabel: 'guessing the base rate' },
  { key: 'accuracy', label: 'Accuracy', lower: false, pct: true },
  { key: 'ece', label: 'Calibration error', lower: true, hint: 'how far stated probabilities drift from what happens' },
  { key: 'mae', label: 'Average error', lower: true },
  { key: 'cov80', label: '80% interval hit rate', lower: null, target: 0.8 },
];

function showBacktest(data) {
  const cols = data.overall.columns;
  const rows = data.overall.rows.map(r => Object.fromEntries(cols.map((c, i) => [c, r[i]])));
  const primary = rows[0];

  const isSpread = r => String(r.target).startsWith('spread');
  const mainRows = rows.filter(r => !isSpread(r));
  const spreadRows = rows.filter(isSpread);

  const cards = mainRows.map(row => {
    const metrics = HEADLINE.filter(m => row[m.key] !== null && row[m.key] !== undefined)
      .map(m => {
        const value = m.pct ? (row[m.key] * 100).toFixed(1) + '%' : fmt(row[m.key], 4);
        let against = '';
        if (m.against && row[m.against] != null) {
          const better = m.lower ? row[m.key] < row[m.against] : row[m.key] > row[m.against];
          const gap = Math.abs(row[m.key] - row[m.against]);
          against = `<div class="against ${better ? 'better' : 'worse'}">
            ${better ? 'beats' : 'loses to'} ${m.againstLabel} by <b>${gap.toFixed(4)}</b></div>`;
        } else if (m.target != null) {
          const off = row[m.key] - m.target;
          against = `<div class="against">${Math.abs(off) < 0.03 ? 'about right'
            : off < 0 ? 'slightly overconfident' : 'slightly conservative'}
            (aiming for ${m.target.toFixed(2)})</div>`;
        } else if (m.hint) {
          against = `<div class="against">${m.hint}</div>`;
        }
        return `<div class="metric"><div class="label">${m.label}</div>
                <div class="value">${value}</div>${against}</div>`;
      }).join('');
    return `<div class="card">
      <h2>${prettyTarget(row.target)}</h2>
      <p class="sub">${row.n ? row.n.toLocaleString() + ' out-of-sample rows' : ''}</p>
      <div class="metricgrid">${metrics}</div></div>`;
  }).join('');

  $('#backtestResults').innerHTML =
    cards
    + spreadCard(spreadRows)
    + calibrationCard(data.calibration)
    + `<div class="card">
         <h3>All the raw numbers</h3>
         ${collapsed('Every metric, pooled', tableInner(data.overall))}
         ${collapsed('Season by season', tableInner(data.by_season))}
       </div>`;
}

/* The derived spread lines are secondary to the three headline markets, and
   one card each pushed everything else off the screen. One compact table. */
function spreadCard(rows) {
  if (!rows.length) return '';
  const body = rows.map(r => `<tr>
      <td>${prettyTarget(r.target)}</td>
      <td class="num">${r.n.toLocaleString()}</td>
      <td class="num">${fmt(r.brier, 4)}</td>
      <td class="num">${fmt(r.baseline_brier, 4)}</td>
      <td class="num" style="color:${r.brier < r.baseline_brier ? 'var(--good)' : 'var(--critical)'}">
        ${r.brier < r.baseline_brier ? '−' : '+'}${Math.abs(r.brier - r.baseline_brier).toFixed(4)}</td>
      <td class="num">${(r.accuracy * 100).toFixed(1)}%</td>
      <td class="num">${fmt(r.ece, 4)}</td>
    </tr>`).join('');
  return `<div class="card">
    <h2>Spread lines</h2>
    <p class="sub">Derived from the same margin distribution as the moneyline, so
      they cannot contradict it. Pushes are excluded from the scoring.</p>
    <div class="tablewrap"><table>
      <thead><tr><th>Line</th><th class="num">n</th><th class="num">Brier</th>
        <th class="num">Base rate</th><th class="num">vs base</th>
        <th class="num">Accuracy</th><th class="num">Calib. error</th></tr></thead>
      <tbody>${body}</tbody></table></div>
  </div>`;
}

function prettyTarget(t) {
  const spread = /^spread([+-])(\d+(?:\.\d+)?)$/.exec(String(t));
  if (spread) {
    const n = parseFloat(spread[2]);
    if (n === 0) return 'Pick\u2019em (home to win)';
    return `Home ${spread[1] === '-' ? '\u2212' : '+'}${n}`;
  }
  return String(t)
    .replace(/_/g, ' ')
    .replace('home win', 'Home win probability')
    .replace('home margin', 'Winning margin')
    .replace('total points', 'Total points')
    .replace('match outcome 1x2', 'Match result (home / draw / away)')
    .replace(/^./, c => c.toUpperCase());
}

/* Calibration: predicted probability vs what actually happened.
   One series against a reference diagonal — the single most useful plot here,
   because a model can look accurate and still lie about its own confidence. */
function calibrationCard(calib) {
  if (!calib || !calib.rows.length) return '';
  const cols = calib.columns;
  const rows = calib.rows.map(r => Object.fromEntries(cols.map((c, i) => [c, r[i]])));
  const targets = [...new Set(rows.map(r => r.target))];

  const charts = targets.map(t => {
    // Pool the per-season bins. One dot per probability band across the whole
    // backtest reads far better than ten overlapping dots per band, and the
    // season detail is still one click away in the table below.
    const byBin = new Map();
    for (const r of rows.filter(r => r.target === t)) {
      if (typeof r.mean_predicted !== 'number' || typeof r.observed_rate !== 'number') continue;
      const acc = byBin.get(r.bin) || { n: 0, predSum: 0, obsSum: 0 };
      acc.n += r.n;
      acc.predSum += r.mean_predicted * r.n;
      acc.obsSum += r.observed_rate * r.n;
      byBin.set(r.bin, acc);
    }
    const pts = [...byBin.values()]
      .filter(a => a.n > 0)
      .map(a => ({ x: a.predSum / a.n, y: a.obsSum / a.n, n: a.n }));
    if (!pts.length) return '';
    return `<figure class="chart">
      <h3 style="margin-bottom:8px">${prettyTarget(t)}</h3>
      ${calibrationSvg(pts)}
      <figcaption>Each dot is one probability band, pooled over every test season.
        Dot size is how many predictions landed in it. On the dashed line the
        model's stated probability matched reality; above it the model was too
        cautious, below it too confident.</figcaption>
    </figure>`;
  }).filter(Boolean);

  const layout = charts.length > 1 ? 'grid two' : 'grid';
  return `<div class="card">
    <h2>Calibration</h2>
    <p class="sub">When the model says 70%, does it happen 70% of the time?</p>
    <div class="legend">
      <span><i style="background:var(--series-1)"></i>Observed rate</span>
      <span><i style="background:var(--border-strong)"></i>Perfect calibration</span>
    </div>
    <div class="${layout}">${charts.join('')}</div>
    ${collapsed('Calibration, season by season', tableInner(calib))}
  </div>`;
}

function collapsed(title, inner) {
  return `<details class="help"><summary>${title}</summary><div>${inner}</div></details>`;
}

function calibrationSvg(pts) {
  const W = 380, H = 360, P = 52;
  const sx = v => P + v * (W - P - 10);
  const sy = v => H - P - v * (H - P - 10);
  const maxN = Math.max(...pts.map(p => p.n || 1));

  const ticks = [0, 0.25, 0.5, 0.75, 1];
  const grid = ticks.map(t => `
    <line class="gridline" x1="${sx(t)}" y1="${sy(0)}" x2="${sx(t)}" y2="${sy(1)}"/>
    <line class="gridline" x1="${sx(0)}" y1="${sy(t)}" x2="${sx(1)}" y2="${sy(t)}"/>`).join('');
  const labels = ticks.map(t => `
    <text x="${sx(t)}" y="${H - P + 15}" text-anchor="middle">${(t * 100).toFixed(0)}%</text>
    <text x="${P - 8}" y="${sy(t) + 4}" text-anchor="end">${(t * 100).toFixed(0)}%</text>`).join('');

  const dots = pts.map(p => {
    const r = 4 + 6 * Math.sqrt((p.n || 1) / maxN);
    return `<circle class="dot" cx="${sx(p.x)}" cy="${sy(p.y)}" r="${r.toFixed(1)}">
      <title>predicted ${(p.x * 100).toFixed(1)}% · actual ${(p.y * 100).toFixed(1)}% · ${p.n} rows</title>
    </circle>`;
  }).join('');

  return `<svg viewBox="0 0 ${W} ${H}" width="100%" style="max-width:${W}px" class="axis"
               role="img" aria-label="Calibration plot: predicted probability against observed rate">
    ${grid}
    <line class="reference" x1="${sx(0)}" y1="${sy(0)}" x2="${sx(1)}" y2="${sy(1)}"/>
    ${dots}
    ${labels}
    <text x="${(sx(0) + sx(1)) / 2}" y="${H - 4}" text-anchor="middle">Model said</text>
    <text x="11" y="${(sy(0) + sy(1)) / 2}" text-anchor="middle"
          transform="rotate(-90 11 ${(sy(0) + sy(1)) / 2})">Actually happened</text>
  </svg>`;
}

/* ---------------- tables ---------------- */
function tableCard(title, data) {
  if (!data || !data.rows.length) return '';
  return `<div class="card"><h3>${title}</h3>${tableInner(data)}</div>`;
}

function tableInner(data) {
  if (!data || !data.rows.length) return '<p class="empty">Nothing to show.</p>';
  const head = data.columns.map(c =>
    `<th class="${c === 'target' || c === 'bin' ? '' : 'num'}">${c.replace(/_/g, ' ')}</th>`).join('');
  const body = data.rows.map(r => '<tr>' + r.map((v, i) => {
    const numeric = typeof v === 'number';
    const grouped = data.columns[i] === 'n';   // the one real count column
    return `<td class="${numeric ? 'num' : ''}">${(grouped ? fmt : fmtCell)(v, 4)}</td>`;
  }).join('') + '</tr>').join('');
  return `<div class="tablewrap"><table><thead><tr>${head}</tr></thead><tbody>${body}</tbody></table></div>`;
}

/* Probability columns get a magnitude bar so a table of numbers is scannable. */
const PROB_COL = /(_prob|^p_home$|^p_draw$|^p_away$|^p_btts$|_over_|cover_|push_|^tie_prob$)/;

function renderPredictionTable(data) {
  if (!data || !data.rows.length) return '<p class="empty">No predictions.</p>';
  const head = data.columns.map(c => `<th class="${PROB_COL.test(c) ? '' : 'num'}">${c.replace(/_/g, ' ')}</th>`).join('');
  const body = data.rows.map(row => '<tr>' + row.map((v, i) => {
    const col = data.columns[i];
    if (PROB_COL.test(col) && typeof v === 'number') {
      const pct = Math.max(0, Math.min(1, v));
      return `<td><span class="probcell">
        <span class="track"><span class="fill" style="width:${(pct * 100).toFixed(1)}%"></span></span>
        <span class="val">${(pct * 100).toFixed(1)}%</span></span></td>`;
    }
    return `<td class="${typeof v === 'number' ? 'num' : ''}">${fmtCell(v, 2)}</td>`;
  }).join('') + '</tr>').join('');
  return `<div class="tablewrap"><table><thead><tr>${head}</tr></thead><tbody>${body}</tbody></table></div>`;
}

/* ---------------- boot ---------------- */
refreshStatus();
setInterval(() => { if (!Object.keys(state.polls).length) refreshStatus(); }, 15000);
