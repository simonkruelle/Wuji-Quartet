// Pages: Play (one hand, two hands, arm and hand), Teach, Camera, Settings.
'use strict';

// ---------------------------------------------------------------- one view of a hand run: stage + status + result
function runView(match) {
  const V = {stage: Stage(), status: h('div', {}), result: h('div', {}), shown: null, rest: []};
  V.setRest = tracks => { V.rest = tracks; if (!V.stage.timeline) V.stage.set(tracks); };
  V.job = () => {
    const js = (App.state ? App.state.jobs : []).filter(j => j.group === 'hand' && match(j));
    return js.find(j => j.state === 'running' || j.state === 'queued') || js[0] || null;
  };
  V.sync = () => {
    const j = V.job(), running = j && (j.state === 'running' || j.state === 'queued');
    if (running && j.meta.timeline) {
      const tl = j.meta.timeline, key = j.id + ':' + tl.start_at + ':' + (tl.next_in || 0);
      if (key !== V.shown) {
        V.shown = key;
        const tracks = [planById(j.meta.plan), j.meta.plan_b ? planById(j.meta.plan_b) : null].filter(Boolean).map(p => planTrack(p, j.meta.fingers));
        V.stage.set(tracks);
        V.stage.play(tl, {sound: !j.meta.real && App.state.settings.sound && !tl.next_in});
      }
    } else if (V.stage.timeline) { V.stage.stop(); V.stage.set(V.rest); V.shown = null; }
    const sig = j ? j.id + j.state + j.phase + (j.stopping ? 's' : '') + Math.round((j.progress || 0) * 100) + JSON.stringify(j.meta.summary || []) + App.state.hand.state : '';
    if (sig === V.sig) return;
    V.sig = sig;
    clear(V.status); clear(V.result);
    if (!j) return;
    V.status.append(jobCard(j));
    if (running) return;
    const m = j.meta, kids = [];
    if (j.state === 'done') kids.push(h('div', {class: 'banner ok', text: `Played ${m.played} of ${m.repeats} round${m.repeats > 1 ? 's' : ''}. Hand switched off: confirmed.` + (m.skipped ? ` ${m.skipped} of the 1000-per-second commands were sent late and skipped.` : '')}));
    else if (m.late) kids.push(h('div', {class: 'banner warn', text: 'The hand was ready after the start time, so nothing was played. Raise the lead time (More options) and start again.'}));
    else if (j.state === 'stopped') kids.push(h('div', {class: 'banner info', text: 'Stopped.' + (App.state.hand.state === 'confirmed' ? ' Hand switched off: confirmed.' : '')}));
    else kids.push(h('div', {class: 'banner bad', text: 'The run did not finish. Open the log for the reason.'}));
    if (App.state.hand.state === 'not_confirmed' && m.real) kids.push(h('div', {class: 'banner bad'}, 'The switch-off was NOT confirmed. The hand may still hold its pose. ',
      h('button', {class: 'pill danger', text: 'Switch the hand off', onclick: () => act(() => api('/api/hand/off', {target: m.target}))})));
    if (m.summary && m.summary.length) kids.push(h('table', {class: 't'},
      h('tr', {}, h('th', {text: 'Finger'}), h('th', {class: 'n', text: 'Furthest from its command'}), h('th', {class: 'n', text: 'Peak current'}), h('th', {class: 'n', text: 'Time at the current limit'})),
      FINGERS.map(f => m.summary.find(r => r.finger === f)).filter(Boolean).map(r => h('tr', {}, h('td', {text: r.finger}), h('td', {class: 'n', text: r.err_deg.toFixed(1) + '°'}),
        h('td', {class: 'n', text: m.real ? r.peak.toFixed(2) + ' A' : '–'}), h('td', {class: 'n', text: m.real ? r.at_limit.toFixed(1) + ' %' : '–'})))),
      m.real ? null : h('p', {class: 'note', text: 'Fake hand: every joint follows its command with a 30 ms delay. No currents.'}));
    V.result.append(card('Last run', ...kids));
  };
  return V;
}
function effortSlider(value) { return slider(0.3, 1.5, 0.1, value, v => v.toFixed(1) + ' A'); }
function tempoSeg(value, onchange) { return seg([[0.5, '50 %'], [0.75, '75 %'], [1, '100 %']], value, v => onchange(parseFloat(v))); }
function fingerToggles(onchange) {
  const el = h('div', {class: 'fingers'}); el.value = FINGERS.slice();
  FINGERS.forEach((f, i) => el.append(h('button', {type: 'button', text: String(i + 1), title: f, class: 'on', style: {background: FCOL[i]}, onclick: e => {
    const on = !el.value.includes(f);
    if (!on && el.value.length === 1) return;
    el.value = FINGERS.filter(x => x === f ? on : el.value.includes(x));
    e.target.classList.toggle('on', on); e.target.style.background = on ? FCOL[i] : '#fff';
    onchange && onchange(el.value);
  }})));
  return el;
}
function startButton(labelFake, labelReal, onclick) {
  const b = h('button', {class: 'pill primary big wide', onclick});
  b.paint = (disabledWhy) => {
    const t = targetInfo(), busy = handBusy();
    b.textContent = busy ? 'A hand run is going on' : (t.real ? labelReal : labelFake);
    b.className = 'pill big wide ' + (t.real ? 'real' : 'primary');
    b.disabled = !!busy || !!disabledWhy;
    b.title = disabledWhy || '';
  };
  b.paint();
  return b;
}
async function launch(body, what) {
  const t = targetInfo();
  body.target = t.id;
  if (t.real) {
    const ok = await confirmReal(what + ' on the real hand?', [
      `Hand: ${t.label}. Current limit ${body.effort.toFixed(1)} A` + (body.tempo && body.tempo < 1 ? `, ${Math.round(body.tempo * 100)} % speed.` : '.'),
      'The hand first moves to its start pose, then plays.',
      'Nothing is in the way of the fingers; the strap is attached.'].concat(body.mode === 'teach' ? ['Your hand lies relaxed under the robot hand, and you can pull it out sideways.'] : []), 'Start');
    if (!ok) return null;
    body.confirm = true;
  }
  Sound.ensure();
  const r = await act(() => api('/api/play', body));
  if (r) flash('Started: ' + r.job.title);
  return r;
}
function handTools() {
  return h('div', {class: 'row', style: {marginTop: '10px'}},
    h('button', {class: 'pill', text: 'Find the hand (reads only)', onclick: () => act(async () => { const r = await api('/api/hand/info', {target: App.target}); openLog(r.job.id); })}),
    h('button', {class: 'pill', text: 'Switch the hand off', onclick: () => act(async () => { const r = await api('/api/hand/off', {target: App.target}); openLog(r.job.id); })}));
}

// ---------------------------------------------------------------- Play › One hand
App.pages.play = {
  build(el) {
    const s = App.state.settings;
    this.view = runView(j => j.kind === 'play' && !j.meta.plan_b);
    this.plan = planSelect(p => p.playable, () => this.planChanged());
    this.planInfo = h('div', {class: 'hint'});
    this.target = targetSeg();
    this.tempo = 1; this.tempoSeg = tempoSeg(1, v => { this.tempo = v; });
    this.effort = effortSlider(s.effort);
    this.fingers = fingerToggles(() => this.planChanged());
    this.lead = slider(3, 30, 1, 4, v => v + ' s');
    this.btn = startButton('Play on the fake hand', 'Play on the REAL hand', () => this.start());
    this.tools = handTools();
    el.append(flowBar(4), ...pageHead('One hand', 'Plays a finished plan. The fake hand runs the same playback at 1000 commands per second without hardware, with sound from the browser. Try a plan there first.'),
      h('div', {class: 'cols side-main'},
        h('div', {}, card('What and where',
          h('div', {class: 'form'},
            ...field('Plan', this.plan, null), ...field('', this.planInfo),
            ...fieldWide('Hand', this.target),
            ...field('Speed', this.tempoSeg, 'Slower stretches the whole motion.'),
            ...field('Current limit', this.effort, 'How hard the fingers may push. 0.5 A for anything new, 1.0 A to play, never above 1.5 A.'),
            ...field('Fingers', this.fingers, 'Switch fingers off to try one at a time. They wait above their keys.')),
          h('details', {class: 'disclosure'}, h('summary', {text: 'More options'}), h('div', {class: 'form'},
            ...field('Lead time', this.lead, 'From Start to the first command of the piece: connecting, switching on, moving to the start pose.'))),
          h('div', {style: {marginTop: '14px'}}, this.btn), this.tools)),
        h('div', {}, card(null, this.view.stage.el, fingerLegend('numbers = fingers, 1 is the thumb')), this.view.status, this.view.result)));
    this.planChanged(); this.onTarget();
  },
  show(arg) { if (arg && arg.plan) { this.plan.fill(arg.plan); this.planChanged(); } this.view.stage.redraw(); },
  onLibrary() { if (this.plan) { this.plan.fill(); this.planChanged(); } },
  onTarget() {
    if (!this.target) return;
    this.target.paint();
    const t = targetInfo();
    this.effort.setDisabled(!t.real);
    this.lead.value = t.id === 'fake' ? 4 : t.id === 'local' ? 9 : 13;
    this.tools.style.display = t.real ? '' : 'none';
    this.btn.paint();
  },
  planChanged() {
    const p = planById(this.plan.value);
    if (!p) { this.planInfo.textContent = 'No playable plan yet.'; return; }
    this.planInfo.textContent = `${p.title} · ${p.n_notes} notes · ${Math.round(p.duration)} s · ${p.side} hand · in simulation ${scoreText(p)}`;
    this.view.setRest([planTrack(p, this.fingers.value)]);
  },
  start() {
    const p = planById(this.plan.value); if (!p) return;
    launch({plan: p.id, tempo: this.tempo, effort: this.effort.value, fingers: this.fingers.value, countdown: this.lead.value}, 'Play ' + p.name);
  },
  update() { this.view.sync(); this.btn.paint(planById(this.plan.value) ? '' : 'Choose a plan'); },
};

// ---------------------------------------------------------------- Play › Two hands
App.pages.duet = {
  build(el) {
    const s = App.state.settings;
    this.view = runView(j => j.kind === 'play' && j.meta.plan_b);
    this.pair = h('select', {onchange: () => { const d = (App.lib.duets || []).find(x => x.id === this.pair.value); if (d) { this.a.fill(d.a); this.b.fill(d.b); this.changed(); } }});
    this.a = planSelect(p => p.playable, () => { this.pair.value = ''; this.changed(); });
    this.b = planSelect(p => p.playable, () => { this.pair.value = ''; this.changed(); });
    this.info = h('div', {});
    this.target = targetSeg();
    this.tempo = 1; this.tempoSeg = tempoSeg(1, v => { this.tempo = v; });
    this.effort = effortSlider(s.effort);
    this.lead = slider(5, 40, 1, 6, v => v + ' s');
    this.snA = h('input', {type: 'text', placeholder: 'serial number, hand A', style: {width: '100%'}});
    this.snB = h('input', {type: 'text', placeholder: 'serial number, hand B', style: {width: '100%', marginTop: '5px'}});
    this.snRow = h('div', {}, this.snA, this.snB, h('div', {class: 'hint', text: 'Both plans are for the same side: name the two hands. "Find the hand" lists the serial numbers.'}));
    this.btn = startButton('Play on two fake hands', 'Play on the REAL hands', () => this.start());
    this.checkEl = h('div', {});
    this.videoEl = h('div', {});
    this.tools = handTools();
    el.append(...pageHead('Two hands', 'Two plans, two hands, one start. Each hand keeps its own fixed position; if one hand stops, the other is stopped too.'),
      h('div', {class: 'cols side-main'},
        h('div', {}, card('What and where',
          h('div', {class: 'form'},
            ...field('Piece', this.pair, 'Pairs that belong together. Or choose the two plans yourself.'),
            ...field('Hand A', this.a), ...field('Hand B', this.b), ...field('', this.info),
            ...fieldWide('Hands', this.target), ...field('Speed', this.tempoSeg), ...field('Current limit', this.effort, 'For both hands.')),
          h('details', {class: 'disclosure'}, h('summary', {text: 'More options'}), h('div', {class: 'form'},
            ...field('Lead time', this.lead, 'From Start to the first command. Two real hands need 15 s.'), ...field('Serial numbers', this.snRow))),
          h('div', {style: {marginTop: '14px'}}, this.btn), this.tools),
          card('Together in one simulation', this.checkEl)),
        h('div', {}, card(null, this.view.stage.el, fingerLegend('hollow notes = left hand')), this.view.status, this.view.result, card('In simulation', this.videoEl))));
    this.onLibrary(); this.onTarget();
  },
  show() { this.view.stage.redraw(); },
  onLibrary() {
    if (!this.pair) return;
    const ds = App.lib.duets || [];
    const keep = this.pair.value;
    clear(this.pair).append(h('option', {value: '', text: 'Your own choice'}));
    for (const d of ds) this.pair.append(h('option', {value: d.id, text: `${d.title} · ${d.sides[0]} + ${d.sides[1]} hand` + (d.gentle ? '' : ' · fast strokes') + (d.shared ? '' : ' · this computer only')}));
    this.a.fill(); this.b.fill();
    if (keep && ds.some(d => d.id === keep)) this.pair.value = keep;
    else if (!this.started && ds.length) { const d = ds.find(x => x.title.startsWith('Ode')) || ds[0]; this.pair.value = d.id; this.a.fill(d.a); this.b.fill(d.b); this.started = true; }
    this.changed();
  },
  onTarget() {
    if (!this.target) return;
    this.target.paint();
    const t = targetInfo();
    this.effort.setDisabled(!t.real);
    this.lead.value = t.id === 'fake' ? 6 : 16;
    this.tools.style.display = t.real ? '' : 'none';
    this.btn.paint();
  },
  changed() {
    const a = planById(this.a.value), b = planById(this.b.value);
    clear(this.info); clear(this.videoEl); this.csig = null;
    if (!a || !b) return;
    this.view.setRest([planTrack(a), planTrack(b)]);
    const kids = [h('div', {class: 'hint', text: `A: ${a.side} hand, ${a.n_notes} notes · B: ${b.side} hand, ${b.n_notes} notes`})];
    if (a.id === b.id) kids.push(h('div', {class: 'banner warn', text: 'Hand A and hand B have the same plan.'}));
    else if (a.side === b.side) kids.push(h('div', {class: 'banner info', style: {marginTop: '6px'}, text: `Both plans are for a ${a.side} hand: on real hands this needs two ${a.side} hands and their serial numbers.`}));
    this.info.append(...kids);
    this.snRow.parentElement.previousElementSibling.style.display = this.snRow.parentElement.style.display = a.side === b.side ? '' : 'none';
    const d = (App.lib.duets || []).find(x => x.a === a.id && x.b === b.id);
    if (d && d.video) this.videoEl.append(h('video', {class: 'preview', controls: true, preload: 'metadata', src: '/media/' + d.video}));
    else this.videoEl.append(h('div', {class: 'row'}, h('button', {class: 'pill', text: 'Film both hands in simulation', disabled: !(App.state.env.mujoco && App.state.env.ffmpeg) || a.id === b.id,
      onclick: () => act(async () => { await api('/api/render', {plan: a.id, plan_b: b.id}); flash('Video queued.'); })}), h('span', {class: 'subtle small', text: 'a few minutes'})));
    this.paintCheck();
  },
  paintCheck() {
    const a = this.a.value, b = this.b.value;
    const j = App.state.jobs.find(j => j.kind === 'check' && j.meta.plan === a && j.meta.plan_b === b);
    const vj = App.state.jobs.find(j => j.kind === 'render' && j.meta.plan === a && j.meta.plan_b === b && (j.state === 'running' || j.state === 'queued'));
    const sig = a + b + (j ? j.id + j.state : '') + (vj ? vj.id + vj.state + Math.round((vj.progress || 0) * 40) : '');
    if (sig === this.csig) return;
    this.csig = sig;
    clear(this.checkEl);
    const btn = h('button', {class: 'pill', text: 'Check the pair (10 s)', disabled: !App.state.env.mujoco || a === b, onclick: () => act(() => api('/api/check', {plan: a, plan_b: b}))});
    if (!j) this.checkEl.append(h('div', {class: 'row'}, btn, h('span', {class: 'subtle small', text: 'Notes per hand, and whether the hands touch.'})));
    else if (j.state === 'running' || j.state === 'queued') this.checkEl.append(jobCard(j));
    else if (j.state === 'done' && j.meta.hands.length) {
      const ok = j.meta.hands.every(x => x.matched === x.total && !x.wrong) && !j.meta.touching && !j.meta.stray;
      this.checkEl.append(h('div', {class: 'banner ' + (ok ? 'ok' : 'warn'), text: j.meta.hands.map(x => `${x.side} hand ${x.matched}/${x.total}` + (x.wrong ? `, ${x.wrong} wrong` : '')).join(' · ') +
        ` · hands ${j.meta.apart_cm} cm apart, ${j.meta.touching ? 'touching in ' + j.meta.touching + ' simulation steps' : 'never touching'}` + (j.meta.stray ? ` · ${j.meta.stray} keys outside both parts` : '')}),
        h('div', {class: 'row'}, btn));
    } else this.checkEl.append(h('div', {class: 'banner bad', text: 'The check did not finish. '}, h('a', {text: 'Log', onclick: () => openLog(j.id)})), h('div', {class: 'row'}, btn));
    if (vj) this.checkEl.append(h('div', {style: {marginTop: '8px'}}, jobCard(vj)));
  },
  start() {
    const a = planById(this.a.value), b = planById(this.b.value); if (!a || !b || a.id === b.id) return;
    launch({plan: a.id, plan_b: b.id, tempo: this.tempo, effort: this.effort.value, countdown: this.lead.value, sn_a: this.snA.value.trim() || null, sn_b: this.snB.value.trim() || null}, 'Play ' + a.name + ' + ' + b.name);
  },
  update() { this.view.sync(); this.paintCheck(); const a = this.a.value, b = this.b.value; this.btn.paint(!a || !b ? 'Choose two plans' : a === b ? 'Choose two different plans' : ''); },
};

// ---------------------------------------------------------------- Play › Arm and hand (not built)
App.pages.arm = {
  build(el) {
    this.list = h('div', {class: 'cols c2'});
    el.append(...pageHead('Arm and hand', 'Pieces wider than five keys need a wrist that moves along the keyboard: an arm. That part is not built yet. What exists today is below.'),
      card('Where this stands',
        checkrow('ok', 'Planning', 'Retarget already plans a moving wrist: "Moves, planned from the notes" for any melody, "Follows the pianist" for K.265.'),
        checkrow('ok', 'Simulation', 'The arm is three ideal sliding axes (sideways, forward, height). Plans can be filmed and scored.'),
        checkrow('off', 'A real arm', 'Not built. No arm driver, no arm model, no calibration between arm and keyboard.'),
        checkrow('off', 'What a driver needs', 'A plan with a moving wrist has 23 columns at 1000 per second: 20 finger joints, then the wrist sideways, forward and up in metres from the mount. The arm follows the last three; the hand plays the first twenty with --fingers-only.')),
      h('h3', {text: 'Plans with a moving wrist', style: {margin: '14px 0 8px'}}), this.list);
    this.onLibrary();
  },
  onLibrary() {
    if (!this.list) return;
    const ps = ((App.lib && App.lib.plans) || []).filter(p => !p.error && !p.playable);
    clear(this.list);
    if (!ps.length) this.list.append(h('div', {class: 'subtle', text: 'None yet.'}));
    for (const p of ps) this.list.append(card(p.name, h('div', {class: 'row tight', style: {marginBottom: '8px'}}, h('span', {class: 'subtle', text: p.title}), h('span', {class: 'chip plain', text: scoreText(p) + ' notes in simulation'})),
      p.video ? h('video', {class: 'preview', controls: true, preload: 'metadata', src: '/media/' + p.video}) : roll(p.notes, {fing: planTrack(p).fing}),
      h('div', {class: 'row', style: {marginTop: '8px'}}, h('button', {class: 'pill', text: 'Open the plan', onclick: () => show('plans', {plan: p.id})}))));
  },
};

// ---------------------------------------------------------------- Teach
function phrases(notes, size) {
  // cut the piece every `size` notes, moved to the longest silence nearby
  const out = []; let i0 = 0;
  while (i0 < notes.length) {
    let i1 = Math.min(notes.length - 1, i0 + size - 1);
    if (i1 < notes.length - 1) {
      let best = i1, gap = -1;
      for (let k = Math.max(i0 + 2, i1 - 2); k <= Math.min(notes.length - 2, i1 + 2); k++) { const g = notes[k + 1][0] - notes[k][1]; if (g > gap + 1e-6) { gap = g; best = k; } }
      i1 = best;
      if (notes.length - 1 - i1 < 3) i1 = notes.length - 1;
    }
    out.push({i0, i1, start: notes[i0][0], end: notes[i1][1]});
    i0 = i1 + 1;
  }
  return out;
}
App.pages.teach = {
  build(el) {
    const s = App.state.settings;
    this.view = runView(j => j.kind === 'teach');
    this.view.stage.look = 4.0;
    this.plan = planSelect(p => p.playable, () => this.planChanged());
    this.target = targetSeg();
    this.tempo = s.teach_tempo; this.tempoSeg = tempoSeg(s.teach_tempo, v => { this.tempo = v; });
    this.effort = effortSlider(s.teach_effort);
    this.mode = 'whole';
    this.modeSeg = seg([['whole', 'Whole piece'], ['phrase', 'Phrase by phrase']], 'whole', v => { this.mode = v; this.paintPhrases(); });
    this.phraseEl = h('div', {class: 'row tight', style: {marginTop: '8px'}});
    this.rollEl = h('div', {style: {marginTop: '8px'}});
    this.rounds = slider(1, 10, 1, 3, v => v + (v === 1 ? ' time' : ' times'));
    this.pause = slider(2, 20, 1, 5, v => v + ' s');
    this.lead = slider(3, 30, 1, 4, v => v + ' s');
    this.checks = ['The hand is mounted higher than for playing: my fingers fit between its fingertips and the keys.',
      'The strap is attached, and I know where Stop is.', 'My hand lies relaxed under the robot hand and I can pull it out sideways.'].map(t => {
      const b = h('input', {type: 'checkbox', onchange: () => this.update()}); return {b, el: h('label', {class: 'check'}, b, h('span', {text: t}))};
    });
    this.checkBox = h('div', {}, this.checks.map(c => c.el));
    this.btn = startButton('Start the lesson on the fake hand', 'Start the lesson on the REAL hand', () => this.start());
    el.append(...pageHead('Teach', 'The robot hand sits a little higher, your hand lies under it, and its fingers press yours through the piece. Start slowly and one phrase at a time.'),
      h('div', {class: 'cols side-main'},
        h('div', {}, card('The lesson', h('div', {class: 'steps'},
          h('div', {class: 'step'}, h('div', {}, h('h4', {text: 'Piece'}), this.plan)),
          h('div', {class: 'step'}, h('div', {}, h('h4', {text: 'What to practise'}), this.modeSeg, this.phraseEl, this.rollEl)),
          h('div', {class: 'step'}, h('div', {}, h('h4', {text: 'How'}), h('div', {class: 'form', style: {gridTemplateColumns: '104px minmax(0,1fr)'}},
            ...field('Speed', this.tempoSeg), ...field('Repeat', this.rounds), ...field('Pause between', this.pause, 'The hand is switched off in the pause: its fingers rest on yours.'),
            ...fieldWide('Hand', this.target), ...field('Current limit', this.effort, 'How hard the fingers press on yours. Start low; never above 1.5 A.'), ...field('Lead time', this.lead)))),
          h('div', {class: 'step'}, h('div', {}, h('h4', {text: 'Before you start'}), this.checkBox))),
          h('div', {style: {marginTop: '10px'}}, this.btn))),
        h('div', {}, card(null, this.view.stage.el, fingerLegend('numbers = your fingers, 1 is the thumb')), this.view.status, this.view.result)));
    this.planChanged(); this.onTarget();
  },
  show(arg) { if (arg && arg.plan) { this.plan.fill(arg.plan); this.planChanged(); } this.view.stage.redraw(); },
  onLibrary() { if (this.plan) { this.plan.fill(); this.planChanged(); } },
  onTarget() {
    if (!this.target) return;
    this.target.paint();
    const t = targetInfo();
    this.effort.setDisabled(!t.real);
    this.lead.value = t.id === 'fake' ? 4 : t.id === 'local' ? 9 : 13;
    this.checkBox.style.display = t.real ? '' : 'none';
    this.checkBox.previousElementSibling.textContent = t.real ? 'Before you start' : 'Fake hand: nothing to check';
    this.update();
  },
  planChanged() { this.sel = 0; this.paintPhrases(); },
  section() {
    const p = planById(this.plan.value);
    if (!p || this.mode === 'whole') return null;
    return (this.phr || [])[this.sel] || null;
  },
  paintPhrases() {
    const p = planById(this.plan.value);
    clear(this.phraseEl); clear(this.rollEl);
    if (!p) return;
    this.phr = phrases(p.notes, 8);
    if (this.mode === 'phrase') this.phr.forEach((ph, i) => this.phraseEl.append(h('button', {class: 'pill' + (i === this.sel ? ' primary' : ''), text: String(i + 1), title: `notes ${ph.i0 + 1} to ${ph.i1 + 1}`,
      onclick: () => { this.sel = i; this.paintPhrases(); }})));
    const sec = this.section();
    this.rollEl.append(roll(p.notes, {fing: planTrack(p).fing, select: sec ? [sec.start, sec.end] : null}),
      h('div', {class: 'hint', text: sec ? `Phrase ${this.sel + 1} of ${this.phr.length}: notes ${sec.i0 + 1} to ${sec.i1 + 1}, ${(sec.end - sec.start).toFixed(1)} s at full speed` : `${p.title}: ${p.n_notes} notes, ${Math.round(p.duration)} s at full speed`}));
    this.view.stage.select = sec ? [sec.start, sec.end] : null;
    this.view.stage.idle = sec ? sec.start + 0.6 : 0;
    this.view.setRest([planTrack(p)]);
    this.view.stage.redraw();
  },
  start() {
    const p = planById(this.plan.value); if (!p) return;
    const sec = this.section();
    launch({plan: p.id, mode: 'teach', tempo: this.tempo, effort: this.effort.value, repeats: this.rounds.value, pause: this.pause.value, countdown: this.lead.value,
      start: sec ? sec.start : null, end: sec ? sec.end : null}, 'Teach ' + p.name);
  },
  update() {
    if (!this.view) return;
    this.view.sync();
    const t = targetInfo();
    this.btn.paint(!planById(this.plan.value) ? 'Choose a piece' : (t.real && !this.checks.every(c => c.b.checked)) ? 'Tick the three points first' : '');
  },
};

// ---------------------------------------------------------------- Camera (Sebas's webcam teleop)
App.pages.camera = {
  build(el) {
    this.img = h('img', {class: 'cam', alt: 'Camera picture with the tracked hand'});
    this.need = h('div', {});
    this.stateEl = h('div', {class: 'row tight', style: {marginTop: '8px'}});
    this.camNo = h('input', {type: 'number', min: 0, max: 9, value: App.state.settings.camera});
    this.source = h('input', {type: 'text', placeholder: 'optional: a video or picture file instead of the camera', style: {width: '100%'}});
    this.camBtn = h('button', {class: 'pill primary', onclick: () => this.toggleCamera()});
    this.calBtn = h('button', {class: 'pill', text: 'Calibrate: flat, open hand', onclick: () => this.cmd({calibrate: true}, 'Hold your hand flat and open: that pose is now "open".')});
    this.pauseBtn = h('button', {class: 'pill', text: 'Pause', onclick: () => this.cmd({pause: !(this.cs && this.cs.paused)})});
    this.thumb = h('input', {type: 'checkbox', checked: true, onchange: () => this.cmd({thumb: this.thumb.checked})});
    this.flip = h('input', {type: 'checkbox', onchange: () => this.cmd({flip_spread: this.flip.checked})});
    this.alpha = slider(0.1, 1, 0.05, 0.4, v => v.toFixed(2), v => this.cmd({alpha: v}));
    this.target = targetSeg();
    this.effort = effortSlider(0.5);
    this.vmax = slider(0.5, 6, 0.5, 3, v => v.toFixed(1) + ' rad/s');
    this.driveBtn = h('button', {class: 'pill big wide', onclick: () => this.toggleDrive()});
    this.joints = h('div', {class: 'joints'});
    this.status = h('div', {});
    el.append(...pageHead('Camera', 'The hand follows your hand in front of the webcam. Tracking and the angle mapping are Sebas\'s (scripts/teleop.py); the hand is driven with the same limits and the same confirmed switch-off as every other page.'),
      this.need,
      h('div', {class: 'cols main-side'},
        h('div', {}, card('Picture', this.img, this.stateEl,
          h('p', {class: 'note', text: 'Use the hand of the same side as the robot hand, palm towards the camera. The picture is mirrored.'})),
          card('Joint angles', this.joints, h('p', {class: 'note', text: 'Blue: what the camera asks for. Black line: where the hand is. Rows are fingers; columns are their four joints, from the base to the tip.'}))),
        h('div', {},
          card('1 · Camera', h('div', {class: 'form', style: {gridTemplateColumns: '104px minmax(0,1fr)'}}, ...field('Camera', this.camNo, 'Number of the camera: 0 is the built-in one.'), ...field('File', this.source)),
            h('div', {class: 'row', style: {marginTop: '10px'}}, this.camBtn, this.calBtn, this.pauseBtn),
            h('details', {class: 'disclosure'}, h('summary', {text: 'More options'}), h('div', {},
              h('label', {class: 'check'}, this.thumb, h('span', {text: 'The thumb follows too'})),
              h('label', {class: 'check'}, this.flip, h('span', {text: 'Mirror the sideways spread of the fingers'})),
              h('div', {class: 'form', style: {gridTemplateColumns: '104px minmax(0,1fr)'}}, ...field('Smoothing', this.alpha, '1 = none. Lower is calmer and slower.'))))),
          card('2 · Hand', h('div', {class: 'form', style: {gridTemplateColumns: '104px minmax(0,1fr)'}},
            ...fieldWide('Hand', this.target), ...field('Current limit', this.effort, 'Sebas\'s default is not known here: this page starts at 0.5 A.'),
            ...field('Fastest motion', this.vmax, 'The hand moves toward the camera\'s pose no faster than this, so it never jumps.')),
            h('div', {style: {marginTop: '12px'}}, this.driveBtn), this.status),
          card('What is saved', h('p', {class: 'note', style: {margin: 0}, text: 'Every session writes the tracked hand (21 points per frame) next to the 20 joint targets to out/teleop/. With many sessions of people playing library pieces, these pairs are what a learned mapping would be trained on.'})))));
    this.timer = setInterval(() => this.tick(), 250);
    this.onTarget();
  },
  onTarget() { if (this.target) { this.target.paint(); this.effort.setDisabled(!targetInfo().real); } },
  async cmd(c, msg) { const r = await act(() => api('/api/camera/cmd', c)); if (r && msg) flash(msg); },
  async toggleCamera() {
    const job = App.state.jobs.find(j => j.kind === 'camera' && j.state === 'running');
    if (job) return act(() => api('/api/stop', {id: job.id}));
    await act(async () => { await api('/api/settings', {camera: parseInt(this.camNo.value || '0', 10)}); await api('/api/camera/start', {camera: parseInt(this.camNo.value || '0', 10), source: this.source.value.trim()}); flash('Camera starting.'); });
  },
  async toggleDrive() {
    const job = App.state.jobs.find(j => j.kind === 'follow' && (j.state === 'running' || j.state === 'queued'));
    if (job) return act(async () => { await api('/api/stop', {id: job.id}); flash('Released: the hand switches off.'); });
    const t = targetInfo(), body = {target: t.id, effort: this.effort.value, vmax: this.vmax.value};
    if (t.real) {
      const ok = await confirmReal('Let the real hand follow the camera?', [`Hand: ${t.label}. Current limit ${body.effort.toFixed(1)} A, at most ${body.vmax.toFixed(1)} rad/s.`,
        'The hand moves from its pose to yours as soon as it is switched on.', 'Nothing is in the way of the fingers; the strap is attached.'], 'Start');
      if (!ok) return;
      body.confirm = true;
    }
    await act(() => api('/api/camera/drive', body));
  },
  async tick() {
    if (App.page !== 'camera' || !App.state || !App.state.camera.running) { this.cs = null; return; }
    try { this.cs = await api('/api/camera/state'); } catch (e) { return; }
    this.paintLive();
  },
  paintLive() {
    const c = this.cs; if (!c) return;
    clear(this.stateEl).append(
      h('span', {class: 'chip ' + (c.starting ? 'warn' : c.tracked ? 'ok' : 'bad'), text: c.starting ? 'starting' : c.paused ? 'paused' : c.tracked ? 'hand seen' : 'no hand in the picture'}),
      c.fps != null ? h('span', {class: 'chip plain', text: c.fps + ' pictures per second'}) : null,
      c.seen != null ? h('span', {class: 'chip plain', text: 'a hand in ' + Math.round(c.seen * 100) + ' % of the pictures'}) : null,
      h('span', {class: 'chip ' + (c.calibrated ? 'ok' : 'plain'), text: c.calibrated ? 'calibrated to your hand' : 'default hand shape'}),
      c.record ? h('span', {class: 'subtle small mono', text: c.record}) : null);
    this.pauseBtn.textContent = c.paused ? 'Resume' : 'Pause';
    // joints: a bar per joint, scaled to the range of that joint's clamp
    const lo = [0, -1.0, 0, 0], hi = [1.3, 0.3, 1.4, 1.4];
    const q = c.q || [], a = c.actual;
    clear(this.joints).append(h('span'), ...['base bend', 'sideways', 'middle joint', 'tip joint'].map(t => h('span', {class: 'hd', text: t})));
    FINGERS.forEach((f, i) => {
      this.joints.append(h('span', {text: f, style: {color: FCOL[i], fontWeight: 700}}));
      for (let k = 0; k < 4; k++) {
        const v = q[4 * i + k] || 0, x = clamp((v - lo[k]) / (hi[k] - lo[k]), 0, 1), zero = clamp((0 - lo[k]) / (hi[k] - lo[k]), 0, 1);
        const bar = h('div', {class: 'jb', title: v.toFixed(2) + ' rad'}, h('i', {style: {left: Math.min(x, zero) * 100 + '%', width: Math.abs(x - zero) * 100 + '%', background: FCOL[i]}}));
        if (a) bar.append(h('u', {style: {left: clamp((a[4 * i + k] - lo[k]) / (hi[k] - lo[k]), 0, 1) * 100 + '%'}}));
        this.joints.append(bar);
      }
    });
  },
  update() {
    const e = App.state.env, running = App.state.camera.running;
    const need = [];
    if (!(e.cv2 && e.mediapipe)) need.push(h('div', {class: 'banner warn'}, 'The camera needs MediaPipe and OpenCV on this computer: ', h('span', {class: 'mono', text: 'pip install -r requirements-camera.txt'}), ', then restart the studio. Inside Docker the camera is not reachable: start the studio with python gui/app.py.'));
    else if (!e.hand_model) {
      const j = App.state.jobs.find(j => j.kind === 'model' && j.state === 'running');
      need.push(h('div', {class: 'banner info'}, 'The hand model (8 MB, from Google\'s MediaPipe) is not on this computer yet. ',
        h('button', {class: 'pill', text: j ? 'Downloading …' : 'Download the hand model', disabled: !!j, onclick: () => act(() => api('/api/camera/model', {}))})));
    }
    const sig = need.length + String(e.hand_model) + String(e.cv2) + App.state.jobs.filter(j => j.kind === 'model').map(j => j.state).join();
    if (sig !== this.nsig) { this.nsig = sig; clear(this.need).append(...need); }
    const ready = e.cv2 && e.mediapipe && e.hand_model;
    this.camBtn.textContent = running ? 'Stop the camera' : 'Start the camera';
    this.camBtn.className = 'pill ' + (running ? '' : 'primary');
    this.camBtn.disabled = !ready && !running;
    this.calBtn.disabled = this.pauseBtn.disabled = !running;
    if (running && !this.img.dataset.on) { setTimeout(() => { if (App.state.camera.running) { this.img.src = '/api/camera/stream?t=' + Date.now(); } }, 1500); this.img.dataset.on = '1'; }
    if (!running && this.img.dataset.on) { this.img.removeAttribute('src'); delete this.img.dataset.on; clear(this.stateEl); clear(this.joints); }
    const fj = App.state.jobs.find(j => j.kind === 'follow');
    const driving = fj && (fj.state === 'running' || fj.state === 'queued');
    const t = targetInfo(), busy = handBusy();
    this.driveBtn.textContent = driving ? 'Release the hand' : (t.real ? 'Let the REAL hand follow' : 'Let the fake hand follow');
    this.driveBtn.className = 'pill big wide ' + (driving ? 'danger' : t.real ? 'real' : 'primary');
    this.driveBtn.disabled = driving ? false : (!running || !!busy);
    const ssig = fj ? fj.id + fj.state + fj.phase + App.state.hand.state : '';
    if (ssig !== this.ssig) {
      this.ssig = ssig;
      clear(this.status);
      if (fj) this.status.append(h('div', {style: {marginTop: '10px'}}, jobCard(fj)));
      if (fj && !driving && fj.meta.real && App.state.hand.state === 'not_confirmed') this.status.append(h('div', {class: 'banner bad', style: {marginTop: '8px'}}, 'The switch-off was NOT confirmed. ',
        h('button', {class: 'pill danger', text: 'Switch the hand off', onclick: () => act(() => api('/api/hand/off', {target: fj.meta.target}))})));
    }
  },
};

// ---------------------------------------------------------------- Settings
App.pages.settings = {
  build(el) {
    const s = App.state.settings;
    const save = (k, v) => act(async () => { const r = await api('/api/settings', {[k]: v}); App.state.settings = r.settings; App.state.targets = r.targets; this.paintTargets(); paintHeader(); flash('Saved.'); });
    const text = (k, ph) => h('input', {type: 'text', value: s[k] || '', placeholder: ph, style: {width: '100%'}, onchange: e => save(k, e.target.value.trim())});
    this.targets = h('div', {class: 'list'});
    this.effort = effortSlider(s.effort); this.effort.input.addEventListener('change', () => save('effort', this.effort.value));
    this.teffort = effortSlider(s.teach_effort); this.teffort.input.addEventListener('change', () => save('teach_effort', this.teffort.value));
    this.workers = slider(1, App.state.env.cores, 1, s.workers, v => v + ' of ' + App.state.env.cores); this.workers.input.addEventListener('change', () => save('workers', this.workers.value));
    this.sound = h('input', {type: 'checkbox', checked: s.sound, onchange: () => save('sound', this.sound.checked)});
    this.found = h('div', {});
    this.envEl = h('div', {});
    el.append(...pageHead('Settings', 'Which hand the studio drives, and how. Saved on this computer only (gui/settings.local.json, not in git).'),
      h('div', {class: 'cols c2'},
        h('div', {},
          card('Hand', this.targets, h('p', {class: 'note', text: 'Play, Teach and Camera all use this hand. With a real hand the top bar turns red and every start asks first.'}),
            h('div', {class: 'row', style: {marginTop: '10px'}},
              h('button', {class: 'pill', text: 'Find the hand (reads only)', onclick: () => act(async () => { const r = await api('/api/hand/info', {target: App.target}); this.infoJob = r.job.id; openLog(r.job.id); })}),
              h('button', {class: 'pill danger', text: 'Switch the hand off', onclick: () => act(async () => { const r = await api('/api/hand/off', {target: App.target}); openLog(r.job.id); })})),
            this.found),
          card('Robot computer', h('div', {class: 'form'},
            ...field('SSH address', text('ssh_host', 'user@address'), 'The computer the hand is plugged into, when it is not this one. Key login must work without a password.'),
            ...field('Folder', text('ssh_repo', '~/Wuji-Quartet'), 'Where this repository lies there.'),
            ...field('Python', text('ssh_python', '~/wq-venv/bin/python'), 'The interpreter with wuji-sdk there.')),
            h('div', {class: 'row', style: {marginTop: '10px'}}, h('button', {class: 'pill', text: 'Copy scripts and plans there', onclick: () => act(async () => { const r = await api('/api/sync', {}); openLog(r.job.id); })}),
              h('span', {class: 'subtle small', text: 'scripts/ and every plan file in plans/, with rsync'})))),
        h('div', {},
          card('Defaults', h('div', {class: 'form'},
            ...field('Current, playing', this.effort, 'Hard limit 1.5 A.'), ...field('Current, teaching', this.teffort, 'The fingers press on a person\'s fingers.'),
            ...field('Processor', this.workers, 'Processes for the search.'),
            ...field('Sound', h('label', {class: 'check'}, this.sound, h('span', {text: 'The fake hand plays the notes through the browser'})))),
          ),
          card('This computer', this.envEl))));
    this.paintTargets();
  },
  paintTargets() {
    clear(this.targets);
    for (const t of App.state.targets) this.targets.append(h('div', {class: 'opt' + (t.id === App.target ? ' on' : ''), onclick: () => { if (t.real && t.ok === false) return flash(t.help, true); setTarget(t.id); this.paintTargets(); }},
      h('span', {class: 'radio'}), h('div', {style: {flex: 1}}, h('div', {class: 't', text: t.label}), h('div', {class: 'd', text: t.help})),
      h('span', {class: 'chip ' + (t.real ? (t.ok === false ? 'plain' : 'bad') : 'ok'), text: t.real ? (t.ok === false ? 'not available' : 'moves a real hand') : 'safe'})));
  },
  onTarget() { if (this.targets) this.paintTargets(); },
  update() {
    const e = App.state.env, yes = (b, y, n) => h('span', {class: 'chip ' + (b ? 'ok' : 'plain'), text: b ? y : n});
    const sig = JSON.stringify(e) + App.state.jobs.filter(j => j.kind === 'hand_info').map(j => j.id + j.state).join();
    if (sig === this.sig) return;
    this.sig = sig;
    clear(this.envEl).append(h('table', {class: 't'},
      h('tr', {}, h('td', {class: 'subtle', text: 'Python'}), h('td', {text: e.python + ' · ' + e.platform + (e.docker ? ' · inside Docker' : '') + ' · ' + e.cores + ' threads'})),
      h('tr', {}, h('td', {class: 'subtle', text: 'Optimise and simulate'}), h('td', {}, yes(e.mujoco, 'MuJoCo + mink', 'not installed'))),
      h('tr', {}, h('td', {class: 'subtle', text: 'Drive a hand from here'}), h('td', {}, yes(e.sdk, 'wuji-sdk', 'not installed'))),
      h('tr', {}, h('td', {class: 'subtle', text: 'Camera'}), h('td', {}, yes(e.cv2 && e.mediapipe, 'MediaPipe + OpenCV', 'not installed'), ' ', yes(e.hand_model, 'hand model', 'no hand model'))),
      h('tr', {}, h('td', {class: 'subtle', text: 'Videos'}), h('td', {}, yes(e.ffmpeg, 'ffmpeg', 'not installed'))),
      h('tr', {}, h('td', {class: 'subtle', text: 'Code'}), h('td', {class: 'mono', text: e.rev || '–'}))));
    const j = App.state.jobs.find(j => j.kind === 'hand_info' && j.state === 'done');
    clear(this.found);
    if (j && j.meta.hands.length) this.found.append(h('table', {class: 't', style: {marginTop: '10px'}}, h('tr', {}, h('th', {text: 'Serial number'}), h('th', {text: 'Side'}), h('th', {text: 'Address'}), h('th', {text: 'Firmware'}), h('th', {class: 'n', text: 'Joints'})),
      j.meta.hands.map(x => h('tr', {}, h('td', {class: 'mono', text: x.sn}), h('td', {text: x.side}), h('td', {class: 'mono', text: x.ip}), h('td', {text: x.firmware}), h('td', {class: 'n', text: (x.joints != null ? x.joints : '?') + ' / 20'})))));
  },
};
