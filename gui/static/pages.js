// Pages: Home, Library (Pieces, Plans) and Retarget.
'use strict';

// ---------------------------------------------------------------- shared bits
function planSelect(filter, onchange) {
  const sel = h('select', {onchange: () => onchange && onchange(sel.value)});
  sel.fill = keep => {
    const cur = keep || sel.value;
    clear(sel);
    const ps = ((App.lib && App.lib.plans) || []).filter(p => !p.error && filter(p));
    for (const [label, shared] of [['Shared with the team (plans/)', true], ['This computer only (out/)', false]]) {
      const g = h('optgroup', {label});
      for (const p of ps.filter(p => p.shared === shared)) g.append(h('option', {value: p.id, text: p.name + (p.score ? '  ·  ' + p.score.matched + '/' + p.n_notes : '')}));
      if (g.children.length) sel.append(g);
    }
    if (cur && [...sel.options].some(o => o.value === cur)) sel.value = cur;
    else if (App.lib && [...sel.options].some(o => o.value === App.lib.ref_plan)) sel.value = App.lib.ref_plan;
  };
  sel.fill();
  return sel;
}
function scoreText(p) { return p.score ? p.score.matched + ' / ' + p.n_notes : '–'; }
function rangeText(r, n) { return !r ? '–' : (r.lo === r.hi ? r.lo : r.lo + ' to ' + r.hi) + ' / ' + n; }
function planChips(p) {
  const c = [];
  c.push(h('span', {class: 'chip plain', text: p.side === 'left' ? 'left hand' : 'right hand'}));
  c.push(h('span', {class: 'chip ' + (p.playable ? 'plain' : 'warn'), text: p.playable ? 'wrist fixed' : 'needs an arm'}));
  if (p.playable) c.push(h('span', {class: 'chip plain', text: p.level ? 'level mount' : 'first mount, tilted'}));
  if (p.cem) c.push(h('span', {class: 'chip plain', text: p.optimised ? 'searched ' + p.cem.samples + ' × ' + p.cem.iters : 'reused, no search'}));
  if (p.hw_runs) c.push(h('span', {class: 'chip ok', text: p.hw_runs + ' real run' + (p.hw_runs > 1 ? 's' : '') + ' logged here'}));
  return c;
}
function pieceFacts(p) {
  return `${p.n_notes} notes · ${Math.round(p.duration)} s · ${noteName(p.lo)} to ${noteName(p.hi)} · ${p.keys.length} keys` + (p.n_black ? ` (${p.n_black} black)` : '');
}
function jobCard(j, extra) {
  const bar = progressBar(j);
  const stop = (j.state === 'running' || j.state === 'queued') ? h('button', {class: 'pill', text: j.stopping ? 'Stopping …' : 'Stop', disabled: j.stopping,
    onclick: () => act(() => api('/api/stop', {id: j.id}))}) : null;
  return h('div', {class: 'jobcard'},
    h('div', {class: 'top'}, h('b', {text: j.title}), stateChip(j), h('span', {class: 'grow'}), h('a', {text: 'Log', onclick: () => openLog(j.id)}), stop),
    bar,
    h('div', {class: 'phase'}, h('span', {text: j.state === 'queued' ? 'Waiting for the run before it' : (j.phase || '')}),
      h('span', {class: 'grow'}), j.eta ? h('span', {class: 'num', text: 'about ' + dur(j.eta) + ' left'}) : (j.started && j.ended ? h('span', {class: 'num', text: 'took ' + dur(j.ended - j.started)}) : null)),
    extra || null);
}

// the pipeline in four steps; shown on the pages that are part of it
function flowBar(step) {
  const steps = [['pieces', 'Pick a piece'], ['pieces', 'Listen'], ['retarget', 'Retarget'], ['play', 'Play on the hand']];
  return h('div', {class: 'flow'}, steps.map(([key, label], i) => [i ? h('span', {class: 'arrow', text: '›'}) : null,
    h('a', {class: 'fstep' + (i + 1 === step || (step === 1 && i === 1) ? ' on' : ''), onclick: () => show(key)}, h('i', {text: String(i + 1)}), label)]));
}

// ---------------------------------------------------------------- Home
App.pages.home = {
  build(el) {
    const tile = (key, letter, color, title, text) => h('a', {class: 'card tile', onclick: () => show(key)},
      h('div', {class: 'ico', style: {background: color}, text: letter}), h('h4', {text: title}), h('p', {text: text}), h('a', {text: 'Open ›'}));
    this.checks = h('div', {});
    this.recent = h('div', {class: 'list'});
    el.append(...pageHead('Home', 'Pick a task. The bar at the bottom always shows what is running; Log ▴ opens the output of every run.'),
      h('div', {class: 'cols c4 stack'},
        tile('play', 'P', '#0a84ff', 'Play a piece', 'A finished plan on one hand or two. Fake hand first, then the real one.'),
        tile('retarget', 'R', '#34c759', 'Retarget a piece', 'Notes in, finger plan out: the SBTO search, as detailed as you have time for.'),
        tile('teach', 'T', '#ff9f0a', 'Teach me', 'Your hand under the robot hand: it presses your fingers through the piece.'),
        tile('camera', 'C', '#af52de', 'Camera', 'The hand follows your hand in front of the webcam.')),
      card('From a piece to the hand', flowBar(0), h('p', {class: 'note', text: 'Pick a piece in the library and listen to it, let the search make a plan (with a time estimate before you start), then play it: on the fake hand first, on the real hand with one more click.'})),
      h('div', {class: 'cols main-side'}, card('Ready to go?', this.checks), card('Latest runs', this.recent)));
  },
  update() {
    const s = App.state, e = s.env, t = targetInfo();
    const go = (key, label) => h('button', {class: 'pill', text: label, onclick: () => show(key)});
    const lib = App.lib || {pieces: [], plans: []};
    clear(this.checks).append(
      checkrow(e.mujoco ? 'ok' : 'warn', 'Simulation', e.mujoco ? `MuJoCo is installed · ${e.cores} processor threads · Python ${e.python}` : 'MuJoCo is not installed here: playing works, optimising and videos do not. pip install -r requirements.txt, or ./wq gui', go('retarget', 'Retarget')),
      checkrow('ok', 'Library', `${lib.pieces.length} pieces · ${lib.plans.filter(p => p.shared).length} shared plans · ${lib.plans.filter(p => !p.shared).length} on this computer only`, go('plans', 'Plans')),
      checkrow(s.hand.state === 'not_confirmed' ? 'bad' : (t.real ? 'warn' : 'ok'), 'Hand',
        (t.real ? `Real hand selected: ${t.label}.` : 'Fake hand selected: nothing moves.') + (s.hand.state === 'confirmed' ? ' Last run ended with the hand switched off.' : s.hand.state === 'not_confirmed' ? ' The last switch-off was NOT confirmed: Settings › Switch the hand off.' : ''), go('settings', 'Settings')),
      checkrow(e.cv2 && e.mediapipe && e.hand_model ? 'ok' : 'off', 'Camera', e.cv2 && e.mediapipe ? (e.hand_model ? 'MediaPipe and the hand model are here.' : 'MediaPipe is installed; the hand model (8 MB) is not downloaded yet.') : 'Optional: pip install -r requirements-camera.txt', go('camera', 'Camera')),
      checkrow(e.ffmpeg ? 'ok' : 'off', 'Videos', e.ffmpeg ? 'ffmpeg is installed: plans can be filmed in simulation.' : 'ffmpeg is not installed: no new videos.'));
    const jobs = s.jobs.slice(0, 7);
    clear(this.recent);
    if (!jobs.length) this.recent.append(h('div', {class: 'subtle small', text: 'Nothing has run yet.'}));
    for (const j of jobs) this.recent.append(h('div', {class: 'recent'}, stateChip(j), h('a', {text: j.title, title: j.title, onclick: () => openLog(j.id)}), h('span', {class: 'subtle small', text: j.ended ? ago(j.ended) : ''})));
  },
};

// ---------------------------------------------------------------- Library › Pieces
App.pages.pieces = {
  playing: null,
  build(el) {
    const file = h('input', {type: 'file', accept: '.mid,.midi', hidden: true, onchange: async () => {
      const f = file.files[0]; if (!f) return;
      await act(async () => {
        const r = await fetch('/api/import?name=' + encodeURIComponent(f.name), {method: 'POST', headers: {'X-WQ': '1', 'Content-Type': 'application/octet-stream'}, body: await f.arrayBuffer()});
        const d = await r.json(); if (!r.ok) throw new Error(d.error);
        await loadLibrary(); flash('Imported: ' + f.name);
      });
      file.value = '';
    }});
    this.body = h('div', {});
    el.append(flowBar(1), ...pageHead('Pieces', 'The human side: which note, when. Each piece is a MIDI file; one of them was played by a pianist whose wrist path is known. Retarget turns a piece into a plan for the robot hand.',
      [file, h('button', {class: 'pill', text: 'Import a MIDI file', onclick: () => file.click()})]), this.body);
    this.onLibrary();
    const tick = () => { if (this.playing && this.playing.h.time() == null) this.stop(); if (this.playing) this.playing.cv.draw(); requestAnimationFrame(tick); };
    requestAnimationFrame(tick);
  },
  stop() { if (this.playing) { this.playing.h.stop(); const b = this.playing.btn; this.playing = null; b.textContent = '▶ Listen'; } },
  hide() { this.stop(); },
  listenBtn(notes, cvRef) {
    const btn = h('button', {class: 'pill', text: '▶ Listen', onclick: () => {
      const mine = this.playing && this.playing.btn === btn;
      this.stop();
      if (mine) return;
      const hd = listen(notes); if (!hd) return flash('This browser has no sound output.', true);
      this.playing = {h: hd, btn, cv: cvRef()}; btn.textContent = '■ Stop';
    }});
    return btn;
  },
  pieceCard(p) {
    const cv = roll(p.notes, {cursor: () => (this.playing && this.playing.cv === cv ? this.playing.h.time() : null)});
    return h('section', {class: 'card piece'},
      h('h4', {text: (p.composer ? p.composer + ' · ' : '') + p.title}),
      h('div', {class: 'row tight'}, h('span', {class: 'chip ' + (p.origin === 'human' ? 'ok' : 'plain'), text: p.origin === 'human' ? 'played by a pianist' : p.origin === 'imported' ? 'imported' : 'from the score'}),
        p.plans.length ? h('span', {class: 'chip plain', text: p.plans.length + ' plan' + (p.plans.length > 1 ? 's' : '')}) : h('span', {class: 'chip warn', text: 'no plan yet'})),
      cv, h('div', {class: 'facts', text: pieceFacts(p)}),
      h('div', {class: 'row'}, this.listenBtn(p.notes, () => cv), h('button', {class: 'pill primary', text: 'Retarget ›', onclick: () => show('retarget', {piece: p.id})})));
  },
  duetCard(stem, parts) {
    const both = [].concat(...parts.map(p => p.notes)), cvs = [];
    const group = {draw() { cvs.forEach(c => c.draw()); }};
    const cursor = () => (this.playing && this.playing.cv === group ? this.playing.h.time() : null);
    parts.forEach(p => cvs.push(roll(p.notes, {color: p.part === 'left' ? '#7d92a5' : '#0a84ff', cursor})));
    return h('section', {class: 'card piece'}, h('h4', {text: parts[0].duet_title}),
      parts.map((p, i) => [h('div', {class: 'row'}, h('span', {class: 'chip plain', text: p.part === 'right' ? 'melody' : 'accompaniment'}), h('span', {class: 'facts', text: pieceFacts(p)}),
        h('span', {class: 'grow'}), h('a', {text: 'Retarget ›', onclick: () => show('retarget', {piece: p.id, side: p.part === 'left' ? 'left' : 'right'})})), cvs[i]]),
      h('div', {class: 'row'}, this.listenBtn(both, () => group), h('button', {class: 'pill', text: 'Play both ›', onclick: () => show('duet')})));
  },
  onLibrary() {
    if (!this.body || !App.lib) return;
    this.stop();
    const ps = App.lib.pieces, one = ps.filter(p => p.group === 'one'), imp = ps.filter(p => p.group === 'imported'), two = ps.filter(p => p.group === 'two');
    clear(this.body);
    this.body.append(h('h3', {text: 'One hand', style: {margin: '4px 0 8px'}}), h('div', {class: 'cols c3 stack'}, one.map(p => this.pieceCard(p))));
    const stems = [...new Set(two.map(p => p.duet))];
    this.body.append(h('h3', {text: 'Two hands', style: {margin: '14px 0 8px'}}), h('div', {class: 'cols c2 stack'}, stems.map(s => this.duetCard(s, two.filter(p => p.duet === s)))));
    if (imp.length) this.body.append(h('h3', {text: 'Imported', style: {margin: '14px 0 8px'}}), h('div', {class: 'cols c3 stack'}, imp.map(p => this.pieceCard(p))));
    const rec = App.lib.recordings || [];
    this.body.append(h('h3', {text: 'Camera recordings', style: {margin: '14px 0 8px'}}),
      card(null, rec.length ? h('table', {class: 't'}, h('tr', {}, h('th', {text: 'Session'}), h('th', {text: 'Length'}), h('th', {text: 'Frames with a hand'}), h('th', {text: 'Folder'})),
        rec.slice(0, 8).map(r => h('tr', {}, h('td', {text: r.date}), h('td', {text: r.seconds + ' s'}), h('td', {class: 'num', text: r.frames}), h('td', {class: 'mono', text: r.id}))))
        : h('div', {class: 'subtle', text: 'None yet. Every Camera session saves the tracked hand next to the joint targets it produced.'})));
  },
};

// ---------------------------------------------------------------- Library › Plans
App.pages.plans = {
  filter: 'shared', sel: null,
  build(el) {
    this.listEl = h('div', {class: 'list scroll-list'});
    this.detail = h('div', {});
    this.seg = seg([['shared', 'Shared with the team'], ['local', 'This computer only'], ['all', 'All']], this.filter, v => { this.filter = v; this.paintList(); });
    el.append(...pageHead('Plans', 'The robot side: joint commands for one hand, 1000 per second, made from a piece. Scores are from simulation, on ten slightly different setups.'),
      h('div', {class: 'cols side-main'}, h('div', {}, h('div', {class: 'stack'}, this.seg), this.listEl), this.detail));
    this.onLibrary();
  },
  show(arg) { if (arg && arg.plan) { this.sel = arg.plan; const p = planById(arg.plan); if (p && !p.shared && this.filter === 'shared') { this.filter = 'all'; this.seg.set('all'); } this.paintList(); this.paintDetail(); } },
  onLibrary() { if (this.listEl) { this.paintList(); this.paintDetail(); } },
  paintList() {
    const ps = ((App.lib && App.lib.plans) || []).filter(p => this.filter === 'all' || (this.filter === 'shared') === p.shared);
    if (!this.sel || !ps.some(p => p.id === this.sel)) this.sel = ps.length ? (ps.find(p => p.id === App.lib.ref_plan) || ps[0]).id : null;
    clear(this.listEl);
    if (!ps.length) this.listEl.append(h('div', {class: 'subtle', text: this.filter === 'local' ? 'No runs on this computer yet. Retarget makes them.' : 'No plans.'}));
    for (const p of ps) {
      this.listEl.append(h('div', {class: 'planrow' + (p.id === this.sel ? ' on' : ''), onclick: () => { this.sel = p.id; this.paintList(); this.paintDetail(); }},
        h('span', {class: 'nm', text: p.name}), h('span', {class: 'sc', text: p.error ? 'unreadable' : scoreText(p)}),
        h('div', {class: 'meta'}, p.error ? h('span', {class: 'chip bad', text: p.error.slice(0, 60)}) : [h('span', {class: 'subtle small', text: p.title}), ...planChips(p).slice(0, 2)])));
    }
  },
  paintDetail() {
    const p = planById(this.sel);
    clear(this.detail);
    if (!p || p.error) return;
    const fing = planTrack(p).fing;
    const sc = p.score || {};
    const mountText = `flange ${Math.round(p.mount.z * 1000) / 10} cm above the white keys, ${Math.round((p.mount.x - 0.15) * 1000) / 10} cm in front of the key fronts, ` +
      (Math.abs(p.mount.theta) < 0.5 ? 'level' : `fingertips ${p.mount.theta}° down`) + (Math.abs(p.mount.dy) < 0.0005 ? `, centred on ${noteName(p.center)}` : `, ${Math.round(Math.abs(p.mount.dy) * 1000) / 10} cm ${(p.mount.dy > 0) === (p.side !== 'left') ? 'right' : 'left'} of ${noteName(p.center)}`);
    const keys = {};
    for (const [pitch, f] of p.fing) (keys[f] = keys[f] || []).push(noteName(pitch));
    const video = h('div', {});
    const paintVideo = () => {
      clear(video);
      const job = (App.state ? App.state.jobs : []).find(j => j.kind === 'render' && j.meta.plan === p.id && !j.meta.plan_b && (j.state === 'running' || j.state === 'queued'));
      if (job) video.append(jobCard(job));
      else if (p.video) video.append(h('video', {class: 'preview', controls: true, preload: 'metadata', src: '/media/' + p.video + '?v=' + Math.round(p.mtime)}),
        h('p', {class: 'note', text: 'Simulation, real time, then 4x slow motion. The sound is made from the keys the simulation pressed.'}));
      else video.append(h('div', {class: 'row'}, h('button', {class: 'pill', text: 'Film it in simulation', disabled: !(App.state && App.state.env.mujoco && App.state.env.ffmpeg),
        onclick: () => act(async () => { await api('/api/render', {plan: p.id}); flash('Video queued.'); })}),
        h('span', {class: 'subtle small', text: `about ${dur(Math.max(15, p.length_s + 8))}`})));
    };
    this.paintVideo = paintVideo;
    paintVideo();
    const before = p.before || {};
    this.detail.append(card(p.name,
      h('div', {class: 'row tight', style: {marginBottom: '8px'}}, h('span', {class: 'subtle', text: p.title}), ...planChips(p)),
      roll(p.notes, {fing}), fingerLegend(),
      h('div', {class: 'kpis'},
        h('div', {class: 'kpi'}, h('b', {text: scoreText(p)}), h('span', {text: 'notes hit, our best guess of the setup'})),
        h('div', {class: 'kpi'}, h('b', {text: sc.wrong != null ? sc.wrong : '–'}), h('span', {text: 'wrong notes'})),
        h('div', {class: 'kpi'}, h('b', {text: sc.timing_ms != null ? Math.round(sc.timing_ms) + ' ms' : '–'}), h('span', {text: '90 % of the notes are this close in time'}))),
      h('div', {class: 'row', style: {marginTop: '12px'}},
        h('button', {class: 'pill primary', text: 'Play ›', disabled: !p.playable, onclick: () => show('play', {plan: p.id})}),
        h('button', {class: 'pill', text: 'Teach ›', disabled: !p.playable, onclick: () => show('teach', {plan: p.id})}),
        h('button', {class: 'pill', text: '3D viewer', disabled: !(App.state && App.state.env.mujoco && App.state.env.display && !App.state.env.docker),
          onclick: () => act(async () => { await api('/api/viewer', {plan: p.id}); flash('The viewer opens in its own window.'); })}),
        !p.shared ? h('button', {class: 'pill', text: 'Share with the team', title: 'Moves the folder from out/ to plans/. Commit and push it afterwards.',
          onclick: () => act(async () => { const r = await api('/api/share', {plan: p.id}); await loadLibrary(); show('plans', {plan: r.plan}); flash('Moved to ' + r.plan + '. Commit and push it to share it.'); })}) : null,
        !p.playable ? h('span', {class: 'subtle small', text: 'This plan moves the wrist: it needs an arm.'}) : null)),
      card('In simulation', video),
      h('div', {class: 'cols c2'},
        card('Ten setups', h('table', {class: 't'},
          h('tr', {}, h('th', {text: 'Setup'}), h('th', {class: 'n', text: 'Before the search'}), h('th', {class: 'n', text: 'This plan'})),
          h('tr', {}, h('td', {text: 'Our best guess'}), h('td', {class: 'n', text: before.nominal != null ? before.nominal + ' / ' + p.n_notes : '–'}), h('td', {class: 'n', text: scoreText(p)})),
          h('tr', {}, h('td', {text: '5 training setups'}), h('td', {class: 'n', text: rangeText(before.train, p.n_notes)}), h('td', {class: 'n', text: rangeText(p.train, p.n_notes)})),
          h('tr', {}, h('td', {text: '5 unseen setups'}), h('td', {class: 'n', text: rangeText(before.test, p.n_notes)}), h('td', {class: 'n', text: rangeText(p.test, p.n_notes)}))),
          h('p', {class: 'note', text: 'Setups differ in servo stiffness and in the mount (millimetres, degrees). Unseen ones were never shown to the search.'})),
        card('How it was made', h('table', {class: 't'},
          h('tr', {}, h('td', {class: 'subtle', text: 'Piece'}), h('td', {text: p.piece || '–'})),
          h('tr', {}, h('td', {class: 'subtle', text: 'Mount'}), h('td', {text: p.playable ? mountText : 'the wrist moves along the keys (an ideal arm in simulation)'})),
          h('tr', {}, h('td', {class: 'subtle', text: 'Fingers'}), h('td', {text: FINGERS.map((f, i) => keys[i] ? f + ' ' + keys[i].join(' ') : null).filter(Boolean).join(' · ')})),
          h('tr', {}, h('td', {class: 'subtle', text: 'Key stroke'}), h('td', {text: p.stroke_ms + ' ms down, ' + p.stroke_ms + ' ms up'})),
          h('tr', {}, h('td', {class: 'subtle', text: 'Search'}), h('td', {text: p.cem ? (p.optimised ? `${p.cem.samples} tries × ${p.cem.iters} rounds, ${p.cem.windows} half-second steps, ${dur(p.wall_s)}` : 'none: stroke parameters taken over from another plan') : 'none (first plan from finger poses)'})),
          h('tr', {}, h('td', {class: 'subtle', text: 'Folder'}), h('td', {class: 'mono', text: p.id}))))));
  },
  update() { if (this.paintVideo && this.sel) { const j = App.state.jobs.find(j => j.kind === 'render' && j.meta.plan === this.sel); const sig = j ? j.id + j.state + Math.round((j.progress || 0) * 50) : ''; if (sig !== this.vsig) { this.vsig = sig; this.paintVideo(); } } },
};

// ---------------------------------------------------------------- Retarget (the SBTO search)
App.pages.retarget = {
  f: {piece: 'ode', side: 'right', wrist: 'fixed', detail: 'reuse', samples: 48, iters: 6, elites: 8, commit: 0.5, knot_dt: 0.2, dr: '', seed: 0, workers: 0, warm: true, position: null, name: '', nameEdited: false},
  build(el) {
    const f = this.f, self = this;
    f.workers = App.state.settings.workers || 8;
    const change = () => this.refresh();
    this.pieceSel = h('select', {onchange: () => { f.piece = this.pieceSel.value; f.nameEdited = false; this.pieceChanged(); }});
    this.pieceRoll = h('div', {});
    this.listenBtn = h('button', {class: 'pill', text: '▶ Listen', onclick: () => {
      if (this.heard) { this.heard.stop(); this.heard = null; this.listenBtn.textContent = '▶ Listen'; return; }
      const p = pieceById(f.piece); if (!p) return;
      this.heard = listen(p.notes); if (!this.heard) return flash('This browser has no sound output.', true);
      this.listenBtn.textContent = '■ Stop';
    }});
    setInterval(() => { if (this.heard) { if (this.heard.time() == null) { this.heard = null; this.listenBtn.textContent = '▶ Listen'; } if (this.rollCv) this.rollCv.draw(); } }, 60);
    this.pieceFacts = h('div', {class: 'hint'});
    this.sideSeg = seg([['right', 'Right hand'], ['left', 'Left hand']], f.side, v => { f.side = v; this.loadPositions(); });
    this.wristSeg = h('span', {});
    this.posEl = h('div', {class: 'list'});
    this.detailSeg = h('span', {});
    this.detailHelp = h('div', {class: 'hint', style: {marginTop: '6px'}});
    const custom = () => { if (f.detail !== 'custom') { f.detail = 'custom'; this.paintDetail(); } change(); };
    this.sSamples = slider(8, 192, 8, f.samples, v => v + ' tries', v => { f.samples = v; if (f.elites >= v) { f.elites = Math.max(2, v / 4 | 0); this.sElites.value = f.elites; } custom(); });
    this.sIters = slider(1, 12, 1, f.iters, v => v + (v === 1 ? ' round' : ' rounds'), v => { f.iters = v; custom(); });
    this.sElites = slider(2, 32, 1, f.elites, v => 'best ' + v, v => { f.elites = Math.min(v, f.samples - 1); custom(); });
    this.sCommit = slider(0.25, 1.0, 0.25, f.commit, v => v + ' s', v => { f.commit = v; change(); });
    this.sKnot = slider(0.1, 0.5, 0.05, f.knot_dt, v => 'every ' + v + ' s', v => { f.knot_dt = v; change(); });
    this.knotHint = h('div', {class: 'hint'});
    this.sWorkers = slider(1, App.state.env.cores, 1, f.workers, v => v + ' of ' + App.state.env.cores, v => { f.workers = v; change(); });
    this.drSeg = seg([['', 'Automatic'], ['wide', 'Wide'], ['mild', 'Mild']], f.dr, v => { f.dr = v; change(); });
    this.seedIn = h('input', {type: 'number', min: 0, max: 9999, value: f.seed, onchange: () => { f.seed = parseInt(this.seedIn.value || '0', 10); change(); }});
    this.warmBox = h('input', {type: 'checkbox', checked: f.warm, onchange: () => { f.warm = this.warmBox.checked; change(); }});
    this.warmRow = h('label', {class: 'check'}, this.warmBox, h('span', {}, 'Start the search from what Ode to Joy learned', h('div', {class: 'hint', text: 'Per finger: when to press early, how deep. Off = start from the plain finger poses.'})));
    this.nameIn = h('input', {type: 'text', style: {width: '100%'}, oninput: () => { f.name = this.nameIn.value; f.nameEdited = true; change(); }});
    this.estBig = h('div', {class: 'big-number', text: '–'});
    this.estSub = h('div', {class: 'subtle small'});
    this.estKpis = h('div', {class: 'kpis'});
    this.estWhy = h('div', {});
    this.cmd = h('pre', {class: 'mono', style: {whiteSpace: 'pre-wrap', wordBreak: 'break-all', margin: 0, color: '#445'}});
    this.startBtn = h('button', {class: 'pill primary big wide', text: 'Start', onclick: () => this.start()});
    this.runs = h('div', {class: 'list'});
    el.append(flowBar(3), ...pageHead('Retarget', 'Turns a piece into a plan for the robot hand. The search (SBTO) tries variations of each half second of music on five simulated setups, keeps the best and repeats. More tries and rounds: a better plan, a longer wait.'),
      h('div', {class: 'cols main-side'},
        h('div', {},
          card('1 · Piece', h('div', {class: 'form'}, ...field('Piece', h('div', {class: 'row'}, this.pieceSel, this.listenBtn)), ...field('', h('div', {}, this.pieceRoll, this.pieceFacts)))),
          card('2 · Hand', h('div', {class: 'form'}, ...field('Hand', this.sideSeg), ...field('Wrist', this.wristSeg), ...field('Where it sits', this.posEl))),
          card('3 · How detailed', this.detailSeg, this.detailHelp,
            h('div', {class: 'form', style: {marginTop: '12px'}},
              ...field('Tries per round', this.sSamples, 'How many variations of each half second are played per round.'),
              ...field('Rounds', this.sIters, 'Each round starts from the best tries of the round before.'),
              ...field('Wrist knots', h('div', {}, this.sKnot, this.knotHint))),
            h('details', {class: 'disclosure'}, h('summary', {text: 'More options'}),
              h('div', {class: 'form'},
                ...field('Kept per round', this.sElites, 'The best tries that shape the next round.'),
                ...field('Step length', this.sCommit, 'How much music one step of the search fixes. 0.5 s is the tested value.'),
                ...field('Test setups', this.drSeg, 'How different the five simulated setups are. Automatic: wide for a fixed wrist (mount ±2 mm, stiffness 2.5 to 10 times), mild otherwise.'),
                ...field('Processor', this.sWorkers, 'Processes used. One fewer than the cores keeps the computer usable.'),
                ...field('Seed', this.seedIn, 'Another seed gives another search of the same size.'),
                ...field('', this.warmRow))))),
        h('div', {},
          card('Estimated time', this.estBig, this.estSub, this.estKpis, this.estWhy,
            h('div', {class: 'form', style: {gridTemplateColumns: '70px minmax(0,1fr)', marginTop: '12px'}}, ...field('Name', this.nameIn, 'The run lands in out/<name>.')),
            h('div', {style: {marginTop: '12px'}}, this.startBtn),
            h('details', {class: 'disclosure'}, h('summary', {text: 'Show the command'}), h('div', {}, this.cmd))),
          card('Runs', this.runs))));
    this.onLibrary();
  },
  hide() { if (this.heard) { this.heard.stop(); this.heard = null; this.listenBtn.textContent = '▶ Listen'; } },
  show(arg) {
    if (arg && arg.piece) { this.f.piece = arg.piece; this.f.nameEdited = false; if (arg.side) { this.f.side = arg.side; this.sideSeg.set(arg.side); } if (this.pieceSel) { this.pieceSel.value = arg.piece; this.pieceChanged(); } }
  },
  onLibrary() {
    if (!this.pieceSel || !App.lib) return;
    const ps = App.lib.pieces;
    clear(this.pieceSel);
    for (const [label, grp] of [['One hand', 'one'], ['Two hands', 'two'], ['Imported', 'imported']]) {
      const g = h('optgroup', {label});
      for (const p of ps.filter(p => p.group === grp)) g.append(h('option', {value: p.id, text: (p.composer ? p.composer + ' · ' : '') + p.title}));
      if (g.children.length) this.pieceSel.append(g);
    }
    if (!ps.some(p => p.id === this.f.piece)) this.f.piece = ps[0] ? ps[0].id : null;
    this.pieceSel.value = this.f.piece;
    if (!this.positions) this.pieceChanged();
  },
  pieceChanged() {
    const f = this.f, p = pieceById(f.piece);
    if (!p) return;
    if (this.heard) { this.heard.stop(); this.heard = null; this.listenBtn.textContent = '▶ Listen'; }
    this.rollCv = roll(p.notes, {cursor: () => (this.heard ? this.heard.time() : null)});
    clear(this.pieceRoll).append(this.rollCv);
    this.pieceFacts.textContent = pieceFacts(p) + (p.note ? ' · ' + p.note : '');
    if (p.part === 'left' && f.side !== 'left' && !this.sideTouched) { /* keep the user's choice; the accompaniment works for either hand */ }
    if (f.wrist === 'human' && !p.human_wrist) f.wrist = 'fixed';
    clear(this.wristSeg).append(seg([['fixed', 'Stays in place'], ['plan', 'Moves, planned from the notes'], ['human', 'Follows the pianist', !p.human_wrist, p.human_wrist ? '' : 'Only K.265 has a recorded wrist path']],
      f.wrist, v => { f.wrist = v; if (v !== 'fixed' && f.detail === 'reuse') f.detail = 'standard'; this.paintPositions(); this.paintDetail(); this.refresh(); }));
    this.loadPositions();
  },
  async loadPositions() {
    const f = this.f, key = f.piece + '|' + f.side;
    this.posKey = key;
    const r = await act(() => api('/api/positions?piece=' + encodeURIComponent(f.piece) + '&side=' + f.side)) || {positions: [], why: ''};
    if (this.posKey !== key) return;          // an answer for a piece that is no longer selected
    this.positions = r;
    f.position = this.positions.positions.find(o => !o.legacy) || this.positions.positions[0] || null;
    if (!f.position && f.wrist === 'fixed') { /* no fixed position: the page says why */ }
    if (f.detail === 'reuse' && !(f.position && f.position.reuse_from)) f.detail = 'standard';
    this.paintPositions(); this.paintDetail(); this.refresh();
  },
  paintPositions() {
    const f = this.f, el = clear(this.posEl);
    if (f.wrist !== 'fixed') {
      el.append(h('div', {class: 'banner warn', text: 'A moving wrist needs an arm. Today the arm is three ideal sliding axes in simulation: these plans can be watched, not played on the hand alone.'}));
      return;
    }
    const ps = (this.positions && this.positions.positions) || [];
    if (this.positions && this.positions.why) el.append(h('div', {class: 'banner warn', text: this.positions.why}));
    for (const o of ps.slice(0, 5)) {
      el.append(h('div', {class: 'opt' + (f.position && f.position.id === o.id ? ' on' : ''), onclick: () => { f.position = o; if (f.detail === 'reuse' && !o.reuse_from) f.detail = 'standard'; this.paintPositions(); this.paintDetail(); this.refresh(); }},
        h('span', {class: 'radio'}),
        h('div', {style: {flex: 1}}, h('div', {class: 't', text: o.text}),
          h('div', {class: 'd', text: `${o.source} · flange ${Math.round(o.mount.z * 1000) / 10} cm above the keys, ${Math.round((o.mount.x - 0.15) * 1000) / 10} cm in front, ${Math.abs(o.mount.theta) < 0.5 ? 'level' : o.mount.theta + '° down'}, ${Math.abs(o.mount.dy) < 0.0005 ? 'centred on' : Math.round(Math.abs(o.mount.dy) * 1000) / 10 + ' cm from'} ${noteName(o.center)}`}),
          o.note ? h('div', {class: 'd', style: {color: '#a35f00'}, text: o.note}) : null),
        h('span', {class: 'chip ' + (o.legacy ? 'warn' : o.proven ? 'ok' : 'plain'), text: o.legacy ? 'old mount' : o.proven ? 'used by a shared plan' : 'simulation only'})));
    }
  },
  paintDetail() {
    const f = this.f, D = App.lib.detail, moving = f.wrist !== 'fixed';
    const canReuse = !moving && f.position && f.position.reuse_from;
    clear(this.detailSeg).append(seg([['reuse', 'Reuse', !canReuse, canReuse ? '' : 'Needs a level-mount position with a plan to start from'], ['draft', 'Draft'], ['standard', 'Standard'], ['fine', 'Fine'], ['custom', 'Custom']],
      f.detail, v => { f.detail = v; this.paintDetail(); this.refresh(); }));
    const d = D[f.detail];
    if (d && f.detail !== 'reuse') { f.samples = d.samples; f.iters = d.iters; f.elites = d.elites; }
    this.sSamples.value = f.samples; this.sIters.value = f.iters; this.sElites.value = f.elites;
    const off = f.detail === 'reuse';
    for (const s of [this.sSamples, this.sIters, this.sElites, this.sCommit]) s.setDisabled(off);
    this.sKnot.setDisabled(off || !moving);
    this.knotHint.textContent = moving ? 'The wrist path gets one sideways and one height correction per knot. Closer knots: finer wrist motion, more numbers to search.'
      : 'Only for a moving wrist. With a fixed wrist every note has its own five numbers: when down, when up, how deep, sideways, forward.';
    this.detailHelp.textContent = f.detail === 'custom' ? 'Your own numbers.' : d.help + (f.detail === 'reuse' ? ' Say so when you show the plan: it is not a fresh optimisation.' : '');
    this.warmRow.style.display = (!moving && f.position && f.position.reuse_from && f.detail !== 'reuse') ? '' : 'none';
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
      this.est = e;
      this.estBig.textContent = '≈ ' + dur(e.seconds);
      this.estSub.textContent = e.windows ? `${dur(e.low)} to ${dur(e.high)} on this computer with ${e.workers} processes` + (e.calibrated_runs ? ` · timed on ${e.calibrated_runs} earlier run${e.calibrated_runs > 1 ? 's' : ''} here` : ' · from the reference computer, gets exact after the first run here')
        : 'No search: finger poses, servo delay, then the score on ten setups.';
      clear(this.estKpis);
      if (e.windows) this.estKpis.append(
        h('div', {class: 'kpi'}, h('b', {text: e.windows}), h('span', {text: 'half-second steps with notes'})),
        h('div', {class: 'kpi'}, h('b', {text: e.rollouts.toLocaleString('en')}), h('span', {text: 'simulated plays'})),
        h('div', {class: 'kpi'}, h('b', {text: e.numbers}), h('span', {text: 'numbers searched'})));
      clear(this.estWhy);
      if (!App.state.env.mujoco) this.estWhy.append(h('div', {class: 'banner warn', style: {marginTop: '10px'}, text: 'MuJoCo is not installed on this computer: start the studio with ./wq gui or install requirements.txt.'}));
      else if (!e.ok) this.estWhy.append(h('div', {class: 'banner warn', style: {marginTop: '10px'}, text: e.why.charAt(0).toUpperCase() + e.why.slice(1) + '.'}));
      if (!this.f.nameEdited) { this.f.name = e.name || ''; this.nameIn.value = this.f.name; }
      this.cmd.textContent = e.command || '';
      this.startBtn.disabled = !e.ok || !App.state.env.mujoco;
      this.startBtn.textContent = this.f.detail === 'reuse' ? 'Make the plan' : 'Start the search';
    }, 120);
  },
  async start() {
    const r = await act(() => api('/api/retarget', this.req()));
    if (!r) return;
    flash('Queued: ' + r.job.title);
    this.f.nameEdited = false;
    this.refresh();
  },
  runCard(j) {
    const m = j.meta, n = m.n_notes, extra = h('div', {});
    const span = rows => { const a = Math.min(...rows.map(x => x[0])), b = Math.max(...rows.map(x => x[0])); return a === b ? String(a) : a + ' to ' + b; };
    const line = (label, d) => d ? `${label}: best guess ${d.train[0][0]} of ${n} notes · 5 training setups ${span(d.train)} · 5 unseen setups ${span(d.test)}` : null;
    if (m.windows && m.windows.length) {
      const cv = h('canvas', {class: 'cost'});
      extra.append(cv, h('div', {class: 'subtle small', text: 'Cost of each half-second step: grey before, blue after its rounds. Lower is better.'}));
      requestAnimationFrame(() => {
        if (!cv.isConnected) return;
        const [g, W, H] = fitCanvas(cv), w = m.windows, mx = Math.max(...w.map(x => x[1]), 1e-6), total = Math.max(w.length, (m.estimate && m.estimate.windows) || w.length), bw = Math.max(2, (W - 4) / total);
        g.clearRect(0, 0, W, H);
        w.forEach((x, i) => {
          g.fillStyle = '#c9d6e2'; g.fillRect(2 + i * bw, H - 2 - (H - 6) * x[1] / mx, Math.max(1, bw - 1.5), (H - 6) * x[1] / mx);
          g.fillStyle = '#0a84ff'; g.fillRect(2 + i * bw, H - 2 - (H - 6) * x[2] / mx, Math.max(1, bw - 1.5), (H - 6) * x[2] / mx);
        });
      });
    }
    const res = [line('Before', m.baseline), m.used && m.used.start_from ? line('Start', m.start) : null, line('Result', m.result)].filter(Boolean);
    if (res.length) extra.append(h('div', {class: 'small', style: {marginTop: '8px'}}, res.map((t, i) => h('div', {style: {fontWeight: i === res.length - 1 && m.result ? 600 : 400}, text: t}))));
    if (j.state === 'done') extra.append(h('div', {class: 'row', style: {marginTop: '8px'}},
      h('button', {class: 'pill', text: 'Open the plan', onclick: () => show('plans', {plan: m.plan})}),
      h('button', {class: 'pill primary', text: 'Play ›', onclick: () => show('play', {plan: m.plan})}),
      m.estimate && m.wall_s ? h('span', {class: 'subtle small', text: `took ${dur(m.wall_s)}, estimate was ${dur(m.estimate.seconds)}`}) : null));
    return jobCard(j, extra);
  },
  update() {
    const jobs = App.state.jobs.filter(j => j.kind === 'retarget').slice(0, 6);
    const sig = jobs.map(j => j.id + j.state + j.phase + Math.round((j.progress || 0) * 200) + (j.meta.windows || []).length + (j.stopping ? 's' : '')).join();
    if (sig === this.sig) return;
    this.sig = sig;
    clear(this.runs);
    if (!jobs.length) this.runs.append(h('div', {class: 'subtle small', text: 'No runs yet. One run at a time: the next one waits.'}));
    for (const j of jobs) this.runs.append(this.runCard(j));
  },
};
