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
    this.importIn = h('input', {type: 'file', accept: '.mid,.midi,audio/midi', style: {display: 'none'}, onchange: () => this.importFile()});
    el.append(h('div', {class: 'split'}, h('div', {class: 'pane'}, this.groupEl, this.search, this.list,
      h('a', {class: 'oneline', text: '+ Import a MIDI file', title: 'Saved to assets/library/ on this computer', onclick: () => this.importIn.click()}), this.importIn), this.detail));
    this.onLibrary();
  },
  hide() { stopListening(); },
  show(arg) { if (arg && arg.piece) this.pick(arg.piece); },
  onLibrary() {
    if (!this.list || !App.lib) return;
    const n = g => App.lib.pieces.filter(p => p.group === g).length;
    const songs = App.lib.pieces.filter(p => p.group === 'songs'), xmas = songs.length && songs.every(p => p.kind === 'christmas');
    const tabs = [['one', 'Ours'], ['two', 'Duets'], ['songs', xmas ? 'Christmas' : 'Sing-along'], ['dataset', 'Pianists'], ['imported', 'Mine']].filter(([g]) => n(g) || g === 'one');
    clear(this.groupEl).append(seg(tabs.map(([g, label]) => [g, label + (g === 'dataset' ? ' ' + n(g) : '')]), this.group, v => { this.group = v; this.paintList(); }));
    this.paintList(); this.paintDetail();
  },
  pick(id) {
    const p = pieceById(id); if (!p) return;
    this.sel = id;
    if (this.q && !(p.title + ' ' + (p.composer || '')).toLowerCase().includes(this.q)) { this.q = ''; this.search.value = ''; }
    if (p.group !== this.group) { this.group = p.group; this.onLibrary(); } else { this.paintList(); this.paintDetail(); }
  },
  paintList() {
    const q = this.q, ps = App.lib.pieces.filter(p => p.group === this.group && (!q || (p.title + ' ' + (p.composer || '')).toLowerCase().includes(q)));
    clear(this.list);
    for (const p of ps) this.list.append(h('div', {class: 'lrow' + (p.id === this.sel ? ' on' : ''), onclick: () => { this.sel = p.id; this.paintList(); this.paintDetail(); }},
      h('div', {class: 't', text: p.title}),
      h('div', {class: 'd', text: [p.version || p.composer, mmss(p.duration), p.plans.length ? p.plans.length + (p.plans.length > 1 ? ' plans' : ' plan') : null].filter(Boolean).join(' · ')})));
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
    const facts = [p.version, p.composer, p.n_notes + ' notes', mmss(p.duration), noteName(p.lo) + '–' + noteName(p.hi), p.licence ? p.licence.split(':')[0] : null].filter(Boolean).join(' · ');
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
      h('div', {class: 'page-head'}, h('div', {}, h('h2', {class: 'pt', text: p.title}), h('div', {class: 'facts', text: facts + (p.human_wrist ? ' · pianist\'s wrist path known' : '')}),
        p.lyrics ? h('div', {class: 'facts', style: {fontStyle: 'italic'}, text: '“' + p.lyrics + ' …”'}) : null),
        h('div', {class: 'actions'}, listenButton(async () => p.notes, t => { cursor = t; rl.draw(); }), h('button', {class: 'pill primary', text: 'Retarget ›', onclick: () => show('retarget', {piece: p.id})}))),
      rl, h('h3', {text: 'Plans', style: {margin: '16px 0 0', fontSize: '15px'}}), list,
      p.fits === false ? h('details', {class: 'disclosure', open: !plans.some(x => x.playable)},
        h('summary', {text: 'Too wide for one hand in place: simplify it for one hand'}), h('div', {}, ...this.cutPanel(p, false))) : null));
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
    // a recorded performance: minutes long, two hands. The robot learns a part of it.
    this.detail.append(card(null,
      h('div', {class: 'page-head'}, h('div', {}, h('h2', {class: 'pt', text: p.title}), h('div', {class: 'facts', text: facts + ' · FürElise piece ' + p.dataset_id}))),
      ...this.cutPanel(p, true)));
  },
  cutPanel(p, withRoll) {
    // a part of a piece, in one of three versions. "One hand" fits it into the keys the real hand reaches without an arm.
    const short = p.duration <= 75;
    const ex = this.ex && this.ex.id === p.id ? this.ex : (this.ex = {id: p.id, start: 0, length: short ? 0 : 20, mode: 'onehand', tempo: 1, at_once: 1, part: p.tune || '', hand: ''});
    const len = () => ex.length || Math.min(180, p.duration - ex.start + 0.5);      // 0 = to the end (at most 3 minutes)
    const sel = [0, 0];
    let cursor = null, prev = null, token = 0;
    const rl = withRoll ? roll(p.notes, {select: sel, cursor: () => (cursor == null ? null : ex.start + cursor * (ex.mode === 'onehand' ? ex.tempo : 1))}) : null;
    const outEl = h('div', {style: {marginTop: '10px'}});
    const info = h('div', {class: 'oneline'});
    const tempoRow = h('div', {class: 'form', style: {marginTop: '8px', gridTemplateColumns: '70px minmax(0,1fr)'}});
    const go = h('button', {class: 'pill primary', text: 'Make it › Retarget', disabled: true, onclick: () => act(async () => {
      const r = await api('/api/excerpt', {piece: p.id, start: ex.start, length: len(), mode: ex.mode, tempo: ex.tempo, at_once: ex.at_once, part: ex.mode === 'all' ? null : ex.part || null, hand: ex.hand || null});
      await loadLibrary(); show('retarget', {piece: r.piece});
    })});
    const listenB = listenButton(async () => prev && prev.notes, t => { cursor = t; if (rl) rl.draw(); if (outEl.rl) outEl.rl.draw(); });
    const whiteIdx = m => { let n = 0; for (let k = 21; k < m; k++) if (![1, 3, 6, 8, 10].includes(k % 12)) n++; return n; };
    const describe = r => {
      const i = r.info, k = i.keys, lo = noteName(k[0]), hi = noteName(k[k.length - 1]);
      if (i.mode === 'onehand') {
        return `${i.n_notes} notes on ${lo}–${hi}` + (i.chords ? ` · ${i.chords} chords` : '') + ` · ${Math.round(i.steps * 100)} % of the steps exact` +
          (i.jumps ? ` · the tune moves key ${i.jumps}×` : '') + (i.dropped ? ` · ${i.dropped} too fast, left out` : '') +
          (i.hand.proven ? ` · hand where it sits for ${i.hand.source}` : ' · a new hand position: simulation first');
      }
      const five = k.every(m => ![1, 3, 6, 8, 10].includes(m % 12)) && whiteIdx(k[k.length - 1]) - whiteIdx(k[0]) <= 4;
      return `${i.n_notes} notes on ${lo}–${hi}` + (five ? ' · fits one hand' : ' · wider than one hand: the wrist has to move (simulation only, needs an arm)');
    };
    const refresh = () => {
      stopListening();
      sel[0] = ex.start; sel[1] = ex.start + len();
      if (rl) rl.draw();
      clear(tempoRow).append(...(ex.mode === 'onehand' ? [
        ...field('At once', seg([[1, 'One key'], [2, 'Up to 2'], [3, 'Up to 3']], ex.at_once, v => { ex.at_once = v; refresh(); })),
        ...field('Hand', seg([['', 'Best fit', false, 'The hand position where most of the tune keeps its pitch: the hand may have to be moved'],
          [App.lib.ref_plan, 'Like Ode (real hand)', false, 'C5–G5: where the real hand already played Ode to Joy, Jingle Bells and Saints']], ex.hand, v => { ex.hand = v; refresh(); })),
        ...field('Tempo', seg([[1, 'As played'], [0.75, '75 %'], [0.5, '50 %']], ex.tempo, v => { ex.tempo = v; refresh(); }))] : []));
      const my = ++token;
      go.disabled = true; info.textContent = '…';
      clearTimeout(this.cutT);
      this.cutT = setTimeout(async () => {
        let r;
        try { r = await api('/api/excerpt', {piece: p.id, start: ex.start, length: len(), mode: ex.mode, tempo: ex.tempo, at_once: ex.at_once, part: ex.mode === 'all' ? null : ex.part || null, hand: ex.hand || null, preview: true}); }
        catch (e) { if (my === token) { prev = null; info.textContent = e.message; clear(outEl); } return; }
        if (my !== token) return;
        prev = r; go.disabled = false;
        info.textContent = describe(r);
        outEl.rl = roll(r.notes, {cursor: () => cursor, color: ex.mode === 'onehand' ? '#30a46c' : undefined});
        clear(outEl).append(outEl.rl);
      }, 150);
    };
    const start = slider(0, Math.max(0, Math.floor(p.duration - 2)), 1, ex.start, v => mmss(v), v => { ex.start = v; refresh(); });
    const lseg = seg([[10, '10 s'], [20, '20 s'], [40, '40 s'], [0, 'To the end']], ex.length, v => { ex.length = v; refresh(); });
    const mseg = seg([['onehand', 'One hand, simplified', false, 'Fitted into the keys one hand reaches with the wrist in place: plays on the real hand'],
      ['melody', 'Melody', false, 'The top line as played: usually needs a moving wrist'], ['all', 'All notes', false, 'Both hands: needs a moving wrist']], ex.mode, v => { ex.mode = v; refresh(); });
    // a band arrangement: which instrument plays the tune (the guess is marked; Listen tells)
    const tune = p.parts ? h('select', {onchange: () => { ex.part = tune.value; refresh(); }},
      h('option', {value: '', text: 'All instruments: the highest line'}),
      p.parts.map(t => h('option', {value: t.part, text: (t.part === p.tune ? '♪ ' : '') + t.instrument + (t.name && t.name.toLowerCase() !== t.instrument ? ' "' + t.name + '"' : '') +
        ` · ${t.n} notes · ${noteName(t.lo)}–${noteName(t.hi)}` + (t.part === p.tune ? ' · probably the tune' : '')}))) : null;
    if (tune) tune.value = ex.part;
    refresh();
    return [rl, h('div', {class: 'form', style: {marginTop: '12px', gridTemplateColumns: '70px minmax(0,1fr)'}},
      ...field('From', start), ...field('Length', lseg), ...(tune ? field('Tune', tune) : []), ...field('Version', mseg)), tempoRow,
      outEl, info, h('div', {class: 'bar-row', style: {marginTop: '12px'}}, listenB, go)].filter(Boolean);
  },
  async importFile() {
    const f = this.importIn.files[0];
    this.importIn.value = '';
    if (!f) return;
    const r = await act(async () => {
      const res = await fetch('/api/import?name=' + encodeURIComponent(f.name), {method: 'POST', headers: {'X-WQ': '1', 'Content-Type': 'audio/midi'}, body: await f.arrayBuffer()});
      const d = await res.json().catch(() => null);
      if (!res.ok) throw new Error((d && d.error) || 'Import failed: ' + res.status);
      return d;
    });
    if (r) { await loadLibrary(); this.pick(r.piece); flash('Imported ' + f.name); }
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
    for (const [label, grp] of [['Ours', 'one'], ['Two hands', 'two'], ['Christmas and sing-along', 'songs'], ['Mine', 'imported']]) {
      const g = h('optgroup', {label});
      for (const p of ps.filter(p => p.group === grp)) g.append(h('option', {value: p.id, text: p.title + (p.version ? ' · ' + p.version : '')}));
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
    const sig = jobs.map(j => j.id + j.state + j.phase + Math.round((j.progress || 0) * 200) + (j.stopping ? 's' : '') + (planById(j.meta.plan) ? 'p' : '')).join();
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
            : j.state === 'done' && planById(m.plan) && planById(m.plan).playable ? h('button', {class: 'pill primary', text: '▶ Play', onclick: () => show('play', {plan: m.plan})}) : null)));
    }
    this.runs.append(c);
  },
};
