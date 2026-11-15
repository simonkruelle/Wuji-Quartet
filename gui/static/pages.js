// Pages: Library (pieces and their plans) and Retarget.
'use strict';

// ---------------------------------------------------------------- shared bits
const PIECES = {};                                     // id -> piece with notes, fetched on demand
async function getPiece(id) {
  if (!PIECES[id]) PIECES[id] = await api('/api/piece?id=' + encodeURIComponent(id));
  return PIECES[id];
}
const mmss = s => Math.floor(s / 60) + ':' + String(Math.round(s % 60) % 60).padStart(2, '0');
function scoreText(p) { return p.score ? p.score.matched + '/' + p.n_notes : '–'; }
function span(r) { return !r ? '–' : r.lo === r.hi ? String(r.lo) : r.lo + '–' + r.hi; }
function jobCard(j, extra) {
  const stop = (j.state === 'running' || j.state === 'queued') ? h('button', {class: 'pill', text: j.stopping ? 'Stopping …' : 'Stop', disabled: j.stopping,
    onclick: () => act(() => api('/api/stop', {id: j.id}))}) : null;
  return h('div', {class: 'jobcard'},
    h('div', {class: 'top'}, h('b', {text: j.title}), stateChip(j), h('span', {class: 'grow'}), h('a', {text: 'Log', onclick: () => openLog(j.id)}), stop),
    progressBar(j),
    h('div', {class: 'phase'}, h('span', {text: j.state === 'queued' ? 'Waiting' : (j.phase || '')}), h('span', {class: 'grow'}),
      j.eta ? h('span', {class: 'num', text: dur(j.eta) + ' left'}) : (j.started && j.ended ? h('span', {class: 'num', text: dur(j.ended - j.started)}) : null)),
    extra || null);
}
function listenButton(getNotes, onTick) {
  // one sound at a time across the studio
  const b = h('button', {class: 'pill', text: '▶ Listen'});
  b.onclick = async () => {
    if (listenButton.cur) { const mine = listenButton.cur.b === b; stopListening(); if (mine) return; }
    const notes = await getNotes(); if (!notes || !notes.length) return;
    const hd = listen(notes); if (!hd) return flash('No sound output in this browser.', true);
    listenButton.cur = {b, h: hd}; b.textContent = '■ Stop';
    const tick = () => {
      if (!listenButton.cur || listenButton.cur.b !== b) { onTick && onTick(null); return; }
      const t = hd.time();
      if (t == null) { b.textContent = '▶ Listen'; listenButton.cur = null; }
      onTick && onTick(t);
      if (t != null) requestAnimationFrame(tick);
    };
    requestAnimationFrame(tick);
  };
  return b;
}
function stopListening() { if (listenButton.cur) { listenButton.cur.h.stop(); listenButton.cur.b.textContent = '▶ Listen'; listenButton.cur = null; } }

// ---------------------------------------------------------------- Library
App.pages.library = {
  group: 'one', sel: 'ode', q: '', open: null,
  build(el) {
    this.search = h('input', {type: 'text', class: 'search', placeholder: 'Search', oninput: () => { this.q = this.search.value.trim().toLowerCase(); this.paintList(); }});
    this.groupEl = h('div', {});
    this.list = h('div', {class: 'rows'});
    this.detail = h('div', {});
    el.append(h('div', {class: 'split'}, h('div', {class: 'pane'}, this.groupEl, this.search, this.list), this.detail));
    this.onLibrary();
  },
  hide() { stopListening(); },
  show(arg) { if (arg && arg.piece) this.pick(arg.piece); },
  onLibrary() {
    if (!this.list || !App.lib) return;
    const n = g => App.lib.pieces.filter(p => p.group === g).length;
    clear(this.groupEl).append(seg([['one', 'Ours'], ['two', 'Duets'], ['dataset', 'Pianists ' + n('dataset')], ...(n('imported') ? [['imported', 'Excerpts ' + n('imported')]] : [])],
      this.group, v => { this.group = v; this.paintList(); }));
    this.paintList(); this.paintDetail();
  },
  pick(id) {
    const p = pieceById(id); if (!p) return;
    this.sel = id;
    if (p.group !== this.group) { this.group = p.group; this.onLibrary(); } else { this.paintList(); this.paintDetail(); }
  },
  paintList() {
    const q = this.q, ps = App.lib.pieces.filter(p => p.group === this.group && (!q || (p.title + ' ' + (p.composer || '')).toLowerCase().includes(q)));
    clear(this.list);
    for (const p of ps) this.list.append(h('div', {class: 'lrow' + (p.id === this.sel ? ' on' : ''), onclick: () => { this.sel = p.id; this.paintList(); this.paintDetail(); }},
      h('div', {class: 't', text: p.title}),
      h('div', {class: 'd', text: [p.composer, mmss(p.duration), p.plans.length ? p.plans.length + (p.plans.length > 1 ? ' plans' : ' plan') : null].filter(Boolean).join(' · ')})));
    this.showLocal = false;
    if (!ps.length) this.list.append(h('div', {class: 'lrow'}, h('div', {class: 'd', text: 'Nothing here.'})));
  },
  async paintDetail() {
    stopListening();
    const id = this.sel;
    if (!pieceById(id)) { clear(this.detail); return; }
    const p = await act(() => getPiece(id));
    if (!p || this.sel !== id) return;
    clear(this.detail);
    let cursor = null;
    const facts = [p.composer, p.n_notes + ' notes', mmss(p.duration), noteName(p.lo) + '–' + noteName(p.hi)].filter(Boolean).join(' · ');
    if (p.group === 'dataset') return this.paintDataset(p, facts);
    const rl = roll(p.notes, {cursor: () => cursor});
    const rank = x => [x.id !== App.lib.ref_plan, !x.playable, !x.level, x.stroke_ms < 60, !x.hw_runs, x.name];
    const plans = App.lib.plans.filter(x => p.plans.includes(x.id)).sort((a, b) => { const ra = rank(a), rb = rank(b); for (let i = 0; i < ra.length; i++) if (ra[i] !== rb[i]) return ra[i] < rb[i] ? -1 : 1; return 0; }), shared = plans.filter(x => x.shared), local = plans.filter(x => !x.shared);
    const list = h('div', {style: {marginTop: '6px'}});
    if (!plans.length) list.append(h('div', {class: 'oneline', text: 'No plan yet.'}));
    for (const x of shared) list.append(this.planRow(x));
    if (local.length && (this.showLocal || !shared.length)) for (const x of local) list.append(this.planRow(x));
    else if (local.length) list.append(h('a', {class: 'oneline', style: {display: 'block'}, text: `+ ${local.length} on this computer only`, onclick: () => { this.showLocal = true; this.paintDetail(); }}));
    this.detail.append(card(null,
      h('div', {class: 'page-head'}, h('div', {}, h('h2', {class: 'pt', text: p.title}), h('div', {class: 'facts', text: facts + (p.human_wrist ? ' · pianist\'s wrist path known' : '')})),
        h('div', {class: 'actions'}, listenButton(async () => p.notes, t => { cursor = t; rl.draw(); }), h('button', {class: 'pill primary', text: 'Retarget ›', onclick: () => show('retarget', {piece: p.id})}))),
      rl, h('h3', {text: 'Plans', style: {margin: '16px 0 0', fontSize: '15px'}}), list));
  },
  planRow(x) {
    const open = this.open === x.id;
    const row = h('div', {class: 'prow'},
      h('span', {class: 'nm', text: (open ? '▾ ' : '▸ ') + x.name, title: x.title, onclick: () => { this.open = open ? null : x.id; this.paintDetail(); }}),
      h('span', {class: 'row tight'}, h('span', {class: 'chip plain', text: x.side}), !x.playable ? h('span', {class: 'chip warn', text: 'needs an arm'}) : null, h('span', {class: 'sc', text: scoreText(x)})),
      h('button', {class: 'pill' + (x.playable ? ' primary' : ''), text: '▶ Play', disabled: !x.playable, onclick: () => show('play', {plan: x.id})}));
    if (open) {
      const v = x.video ? h('video', {class: 'preview', controls: true, preload: 'metadata', src: '/media/' + x.video + '?v=' + Math.round(x.mtime)})
        : h('button', {class: 'pill', text: 'Film it in simulation', disabled: !(App.state.env.mujoco && App.state.env.ffmpeg), onclick: () => act(async () => { await api('/api/render', {plan: x.id}); flash('Filming: the video appears here when done.'); })});
      row.append(h('div', {class: 'pdetail'},
        h('div', {text: `Simulation, ten setups: training ${span(x.train)} · unseen ${span(x.test)} · wrong ${x.score ? x.score.wrong : '–'}`}),
        h('div', {text: (x.cem ? (x.optimised ? `searched ${x.cem.samples}×${x.cem.iters}` : 'no search') : 'first plan') + ` · ${x.stroke_ms} ms strokes · ` + (x.level ? 'level mount' : x.playable ? 'first mount, tilted' : 'moving wrist') + (x.hw_runs ? ` · ${x.hw_runs} real runs logged` : '') + ` · ${x.id}`}),
        h('div', {class: 'row'}, v, !x.shared ? h('button', {class: 'pill', text: 'Share with the team', title: 'Move from out/ to plans/ (then commit and push)',
          onclick: () => act(async () => { const r = await api('/api/share', {plan: x.id}); await loadLibrary(); this.open = r.plan; flash('Moved to ' + r.plan); })}) : null)));
    }
    return row;
  },
  paintDataset(p, facts) {
    // a recorded performance: minutes long, two hands. The robot learns an excerpt of it.
    const ex = this.ex && this.ex.id === p.id ? this.ex : (this.ex = {id: p.id, start: 0, length: 20, mode: 'melody'});
    let cursor = null;
    const sel = () => p.notes.filter(n => n[0] >= ex.start && n[0] < ex.start + ex.length && (ex.mode === 'all' || n[2] >= 60));
    const rl = roll(p.notes, {select: [ex.start, ex.start + ex.length], cursor: () => (cursor == null ? null : ex.start + cursor)});
    const info = h('span', {class: 'oneline', style: {marginTop: 0}});
    const paint = () => { info.textContent = `${sel().length} notes · ${mmss(ex.start)}–${mmss(Math.min(p.duration, ex.start + ex.length))}`; rl.draw(); };
    const start = slider(0, Math.max(0, Math.floor(p.duration - 5)), 1, ex.start, v => mmss(v), v => { stopListening(); ex.start = v; paint(); });
    const lseg = seg([[10, '10 s'], [20, '20 s'], [40, '40 s']], ex.length, v => { stopListening(); ex.length = parseFloat(v); paint(); });
    const mseg = seg([['melody', 'Right-hand melody'], ['all', 'All notes']], ex.mode, v => { stopListening(); ex.mode = v; paint(); });
    const go = h('button', {class: 'pill primary', text: 'Make the excerpt › Retarget', onclick: () => act(async () => {
      const r = await api('/api/excerpt', {piece: p.id, start: ex.start, length: ex.length, mode: ex.mode});
      await loadLibrary(); show('retarget', {piece: r.piece});
    })});
    this.detail.append(card(null,
      h('div', {class: 'page-head'}, h('div', {}, h('h2', {class: 'pt', text: p.title}), h('div', {class: 'facts', text: facts + ' · FürElise piece ' + p.dataset_id})),
        h('div', {class: 'actions'}, listenButton(async () => sel().map(n => [n[0] - ex.start, n[1] - ex.start, n[2]]), t => { cursor = t; rl.draw(); }))),
      rl,
      h('div', {class: 'form', style: {marginTop: '12px', gridTemplateColumns: '70px minmax(0,1fr)'}}, ...field('From', start), ...field('Length', lseg), ...field('Notes', mseg)),
      h('div', {class: 'bar-row', style: {marginTop: '12px'}}, go, info)));
    paint();
  },
};

// ---------------------------------------------------------------- Retarget (the SBTO search)
App.pages.retarget = {
  f: {piece: 'ode', side: 'right', wrist: 'fixed', detail: 'reuse', samples: 48, iters: 6, elites: 8, commit: 0.5, knot_dt: 0.2, dr: '', seed: 0, workers: 0, warm: true, position: null, name: '', nameEdited: false},
  build(el) {
    const f = this.f;
    f.workers = App.state.settings.workers || 8;
    const change = () => this.refresh();
    let cursor = null;
    this.cursor = () => cursor;
    this.pieceSel = h('select', {onchange: () => { f.piece = this.pieceSel.value; f.nameEdited = false; this.userWrist = false; this.pieceChanged(); }});
    this.rollEl = h('div', {style: {marginTop: '10px'}});
    this.listen = listenButton(async () => (await getPiece(f.piece)).notes, t => { cursor = t; if (this.rl) this.rl.draw(); });
    this.sideSeg = seg([['right', 'Right hand'], ['left', 'Left hand']], f.side, v => { f.side = v; this.loadPositions(); });
    this.wristEl = h('span', {});
    this.posEl = h('div', {class: 'oneline'});
    this.detailEl = h('span', {});
    const custom = () => { if (f.detail !== 'custom') { f.detail = 'custom'; this.paintDetail(); } change(); };
    this.sSamples = slider(8, 192, 8, f.samples, v => v + ' tries', v => { f.samples = v; if (f.elites >= v) { f.elites = Math.max(2, v / 4 | 0); this.sElites.value = f.elites; } custom(); });
    this.sIters = slider(1, 12, 1, f.iters, v => v + (v === 1 ? ' round' : ' rounds'), v => { f.iters = v; custom(); });
    this.sKnot = slider(0.1, 0.5, 0.05, f.knot_dt, v => v + ' s', v => { f.knot_dt = v; change(); });
    this.sElites = slider(2, 32, 1, f.elites, v => 'best ' + v, v => { f.elites = Math.min(v, f.samples - 1); custom(); });
    this.sCommit = slider(0.25, 1.0, 0.25, f.commit, v => v + ' s', v => { f.commit = v; change(); });
    this.sWorkers = slider(1, App.state.env.cores, 1, f.workers, v => v + ' of ' + App.state.env.cores, v => { f.workers = v; change(); });
    this.drSeg = seg([['', 'Auto'], ['wide', 'Wide'], ['mild', 'Mild']], f.dr, v => { f.dr = v; change(); });
    this.seedIn = h('input', {type: 'number', min: 0, max: 9999, value: f.seed, onchange: () => { f.seed = parseInt(this.seedIn.value || '0', 10); change(); }});
    this.warmBox = h('input', {type: 'checkbox', checked: f.warm, onchange: () => { f.warm = this.warmBox.checked; change(); }});
    this.nameIn = h('input', {type: 'text', style: {width: '100%'}, oninput: () => { f.name = this.nameIn.value; f.nameEdited = true; change(); }});
    this.estBig = h('div', {class: 'big-number', text: '–'});
    this.estSub = h('div', {class: 'oneline'});
    this.why = h('div', {});
    this.cmd = h('pre', {class: 'mono', style: {whiteSpace: 'pre-wrap', wordBreak: 'break-all', margin: 0, color: '#445'}});
    this.startBtn = h('button', {class: 'pill primary big', text: 'Start', onclick: () => this.start()});
    this.runs = h('div', {});
    el.append(...pageHead('Retarget'),
      card(null, h('div', {class: 'bar-row'}, this.pieceSel, this.listen, this.sideSeg, this.wristEl), this.rollEl, this.posEl),
      card(null,
        h('div', {class: 'bar-row'}, this.detailEl, h('span', {class: 'grow'}), h('div', {class: 'est'}, this.estBig), this.startBtn),
        this.estSub, this.why,
        h('details', {class: 'disclosure'}, h('summary', {text: 'More'}),
          h('div', {class: 'form'},
            ...field('Tries per round', this.sSamples), ...field('Rounds', this.sIters), ...field('Wrist knots every', this.sKnot, 'moving wrist only'),
            ...field('Kept per round', this.sElites), ...field('Step', this.sCommit), ...field('Test setups', this.drSeg),
            ...field('Processes', this.sWorkers), ...field('Seed', this.seedIn),
            ...field('Start from Ode', h('label', {class: 'check'}, this.warmBox, h('span', {class: 'hint', text: 'per-finger timing and depth learned on Ode to Joy'}))),
            ...field('Name', this.nameIn), ...field('Command', this.cmd)))),
      this.runs);
    this.onLibrary();
  },
  hide() { stopListening(); },
  show(arg) {
    if (arg && arg.piece) {
      this.f.piece = arg.piece; this.f.nameEdited = false; this.userWrist = false;
      if (arg.side) { this.f.side = arg.side; this.sideSeg.set(arg.side); }
      this.onLibrary();
    }
  },
  onLibrary() {
    if (!this.pieceSel || !App.lib) return;
    const ps = App.lib.pieces.filter(p => p.group !== 'dataset');
    clear(this.pieceSel);
    for (const [label, grp] of [['Ours', 'one'], ['Two hands', 'two'], ['Excerpts', 'imported']]) {
      const g = h('optgroup', {label});
      for (const p of ps.filter(p => p.group === grp)) g.append(h('option', {value: p.id, text: p.title}));
      if (g.children.length) this.pieceSel.append(g);
    }
    if (!ps.some(p => p.id === this.f.piece)) this.f.piece = ps[0] ? ps[0].id : null;
    this.pieceSel.value = this.f.piece;
    if (this.loaded !== this.f.piece) this.pieceChanged();
  },
  async pieceChanged() {
    const f = this.f; this.loaded = f.piece;
    stopListening();
    const p = await act(() => getPiece(f.piece)); if (!p || this.loaded !== p.id) return;
    this.p = p;
    this.rl = roll(p.notes, {cursor: this.cursor});
    clear(this.rollEl).append(this.rl);
    if (f.wrist === 'human' && !p.human_wrist) f.wrist = 'fixed';
    this.paintWrist();
    this.loadPositions();
  },
  paintWrist() {
    const f = this.f, p = this.p;
    clear(this.wristEl).append(seg([['fixed', 'Wrist fixed'], ['plan', 'Wrist moves'], ...(p && p.human_wrist ? [['human', 'Like the pianist']] : [])],
      f.wrist, v => { f.wrist = v; this.userWrist = true; if (v !== 'fixed' && f.detail === 'reuse') f.detail = 'standard'; this.paintPos(); this.paintDetail(); this.refresh(); }));
  },
  async loadPositions() {
    const f = this.f, key = f.piece + '|' + f.side;
    this.posKey = key;
    const r = await act(() => api('/api/positions?piece=' + encodeURIComponent(f.piece) + '&side=' + f.side)) || {positions: [], why: ''};
    if (this.posKey !== key) return;
    this.positions = r;
    f.position = r.positions[0] || null;
    if (!f.position && f.wrist === 'fixed') { f.wrist = 'plan'; this.paintWrist(); }                 // more than five keys apart: the wrist has to move
    else if (f.position && f.wrist === 'plan' && !this.userWrist) { f.wrist = 'fixed'; this.paintWrist(); }
    if (f.detail === 'reuse' && !(f.wrist === 'fixed' && f.position && f.position.reuse_from)) f.detail = 'standard';
    this.paintPos(); this.paintDetail(); this.refresh();
  },
  paintPos() {
    const f = this.f, ps = (this.positions && this.positions.positions) || [];
    clear(this.posEl);
    if (f.wrist !== 'fixed') return this.posEl.append(ps.length ? 'A moving wrist needs an arm: simulation only.' : 'More than five fingers apart: the wrist has to move. Simulation only, needs an arm.');
    if (!ps.length) return;
    const text = o => o.text + (o.proven ? '' : ' · simulation only');
    if (ps.length === 1) return this.posEl.append(text(ps[0]));
    const sel = h('select', {onchange: () => { f.position = ps[+sel.value]; if (f.detail === 'reuse' && !f.position.reuse_from) f.detail = 'standard'; this.paintDetail(); this.refresh(); }},
      ps.map((o, i) => h('option', {value: i, text: text(o)})));
    sel.value = String(Math.max(0, ps.indexOf(f.position)));
    this.posEl.append(sel);
  },
  paintDetail() {
    const f = this.f, D = App.lib.detail, moving = f.wrist !== 'fixed';
    const canReuse = !moving && f.position && f.position.reuse_from;
    clear(this.detailEl).append(seg([['reuse', 'Reuse', !canReuse, 'No search: what the search learned on Ode to Joy, per finger'], ['draft', 'Draft', false, '24 tries × 3 rounds'],
      ['standard', 'Standard', false, '48 × 6: every optimised plan in this repo'], ['fine', 'Fine', false, '96 × 8'], ['custom', 'Custom', false, 'your numbers, under More']],
      f.detail, v => { f.detail = v; this.paintDetail(); this.refresh(); }));
    const d = D[f.detail];
    if (d && f.detail !== 'reuse') { f.samples = d.samples; f.iters = d.iters; f.elites = d.elites; }
    this.sSamples.value = f.samples; this.sIters.value = f.iters; this.sElites.value = f.elites;
    for (const s of [this.sSamples, this.sIters, this.sElites, this.sCommit]) s.setDisabled(f.detail === 'reuse');
    this.sKnot.setDisabled(f.detail === 'reuse' || !moving);
  },
  req() {
    const f = this.f;
    const r = {piece: f.piece, wrist: f.wrist, detail: f.detail, samples: f.samples, iters: f.iters, elites: f.elites, commit: f.commit, workers: f.workers, seed: f.seed, dr: f.dr || null, warm: f.warm, side: f.side};
    if (f.wrist === 'fixed') r.position = f.position; else r.knot_dt = f.knot_dt;
    if (f.nameEdited && f.name) r.name = f.name;
    return r;
  },
  refresh() {
    clearTimeout(this.rt);
    this.rt = setTimeout(async () => {
      const e = await act(() => api('/api/estimate', this.req()));
      if (!e) return;
      this.estBig.textContent = '≈ ' + dur(e.seconds);
      this.estSub.textContent = e.windows ? `${e.windows} steps · ${e.rollouts.toLocaleString('en')} simulated plays · ${e.workers} processes` + (e.calibrated_runs ? '' : ' · timed on the reference computer until the first run here') : 'No search.';
      clear(this.why);
      const bad = !App.state.env.mujoco ? 'MuJoCo is not installed here: start the studio with ./wq gui.' : !e.ok ? e.why.charAt(0).toUpperCase() + e.why.slice(1) + '.' : '';
      if (bad) this.why.append(h('div', {class: 'banner warn', style: {marginTop: '8px'}, text: bad}));
      if (!this.f.nameEdited) { this.f.name = e.name || ''; this.nameIn.value = this.f.name; }
      this.cmd.textContent = e.command || '';
      this.startBtn.disabled = !e.ok || !App.state.env.mujoco;
    }, 120);
  },
  async start() {
    const r = await act(() => api('/api/retarget', this.req()));
    if (r) { this.f.nameEdited = false; this.refresh(); }
  },
  update() {
    const jobs = App.state.jobs.filter(j => j.kind === 'retarget').slice(0, 5);
    const sig = jobs.map(j => j.id + j.state + j.phase + Math.round((j.progress || 0) * 200) + (j.stopping ? 's' : '')).join();
    if (sig === this.sig) return;
    this.sig = sig;
    clear(this.runs);
    if (!jobs.length) return;
    const c = card(null);
    const rng = rows => span({lo: Math.min(...rows.map(x => x[0])), hi: Math.max(...rows.map(x => x[0]))});
    for (const j of jobs) {
      const m = j.meta, live = j.state === 'running' || j.state === 'queued';
      const res = m.result ? `${m.result.train[0][0]}/${m.n_notes} notes · training ${rng(m.result.train)} · unseen ${rng(m.result.test)}` + (m.wall_s ? ' · ' + dur(m.wall_s) : '') : '';
      c.append(h('div', {class: 'runline'},
        h('div', {}, h('div', {class: 'nm'}, h('b', {text: m.used ? m.used.name : j.title}), ' ', stateChip(j)), h('div', {class: 'ph', text: live ? (j.phase || 'Waiting') + (j.eta ? ' · ' + dur(j.eta) + ' left' : '') : res || j.phase})),
        progressBar(j),
        h('span', {class: 'row tight'}, h('a', {text: 'Log', onclick: () => openLog(j.id)}),
          live ? h('button', {class: 'pill', text: j.stopping ? 'Stopping …' : 'Stop', disabled: j.stopping, onclick: () => act(() => api('/api/stop', {id: j.id}))})
            : j.state === 'done' ? h('button', {class: 'pill primary', text: '▶ Play', onclick: () => show('play', {plan: m.plan})}) : null)));
    }
    this.runs.append(c);
  },
};
