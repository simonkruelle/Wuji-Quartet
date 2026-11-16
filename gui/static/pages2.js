// Pages: Play (one hand, two hands, teach), Camera, Settings.
'use strict';

// where a plan's hand sits: its middle finger's key and the mount; two plans with the same of both share the position
const samePlace = (a, b) => a && b && a.side === b.side && a.center === b.center && a.mount && b.mount &&
  ['x', 'z', 'theta', 'dy'].every(k => Math.abs(a.mount[k] - b.mount[k]) < (k === 'theta' ? 0.5 : 0.002));
const whiteIdx = m => { let n = 0; for (let k = 21; k < m; k++) if (![1, 3, 6, 8, 10].includes(k % 12)) n++; return n; };

// ---------------------------------------------------------------- a hand run: stage + one status line + result
function runView(match) {
  const V = {stage: Stage(), status: h('div', {}), rest: [], shown: null};
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
        V.stage.set([planById(j.meta.plan), j.meta.plan_b ? planById(j.meta.plan_b) : null].filter(Boolean).map(p => planTrack(p, j.meta.fingers)));
        V.stage.play(tl, {sound: !j.meta.real && App.state.settings.sound && !tl.next_in});
      }
    } else if (V.stage.timeline) { V.stage.stop(); V.stage.set(V.rest); V.shown = null; }
    const sig = j ? j.id + j.state + j.phase + (j.stopping ? 's' : '') + Math.round((j.progress || 0) * 100) + App.state.hand.state : '';
    if (sig === V.sig) return;
    V.sig = sig;
    clear(V.status);
    if (!j) return;
    if (running) return V.status.append(jobCard(j));
    const m = j.meta;
    let text, cls;
    if (j.state === 'done') { cls = 'ok'; text = `Played ${m.played > 1 ? m.played + ' rounds' : ''}`.trim() + '. Hand off, confirmed.'; }
    else if (m.late) { cls = 'warn'; text = 'The hand was not ready in time: nothing played. Raise the lead time under More.'; }
    else if (j.state === 'stopped') { cls = 'info'; text = 'Stopped.' + (App.state.hand.state === 'confirmed' ? ' Hand off, confirmed.' : ''); }
    else { cls = 'bad'; text = 'Did not finish.'; }
    const kids = [h('div', {class: 'banner ' + cls, style: {marginBottom: 0}}, text, ' ', h('a', {text: 'Log', onclick: () => openLog(j.id)}))];
    if (App.state.hand.state === 'not_confirmed' && m.real) kids.push(h('div', {class: 'banner bad', style: {marginTop: '8px'}}, 'Switch-off NOT confirmed. ',
      h('button', {class: 'pill danger', text: 'Switch the hand off', onclick: () => act(() => api('/api/hand/off', {target: m.target}))})));
    if (m.real && m.summary && m.summary.length) kids.push(h('details', {class: 'disclosure'}, h('summary', {text: 'Per finger'}), h('table', {class: 't'},
      h('tr', {}, h('th', {text: 'Finger'}), h('th', {class: 'n', text: 'Furthest from command'}), h('th', {class: 'n', text: 'Peak current'}), h('th', {class: 'n', text: 'At the limit'})),
      FINGERS.map(f => m.summary.find(r => r.finger === f)).filter(Boolean).map(r => h('tr', {}, h('td', {text: r.finger}), h('td', {class: 'n', text: r.err_deg.toFixed(1) + '°'}),
        h('td', {class: 'n', text: r.peak.toFixed(2) + ' A'}), h('td', {class: 'n', text: r.at_limit.toFixed(1) + ' %'}))))));
    V.status.append(...kids);
  };
  return V;
}
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

// ---------------------------------------------------------------- Play: one hand, two hands, teach
App.pages.play = {
  mode: 'one', tempo: 1, sel: 0,
  build(el) {
    const s = App.state.settings;
    this.view = runView(() => true);
    this.v3 = PlanViewer({compact: true});         // Notes | 3D: the plan's hand in simulation, following the run while it plays
    this.v3.el.hidden = true;
    this.showSeg = seg([['notes', 'Notes'], ['3d', '3D']], 'notes', v => this.setShow(v));
    this.legend = fingerLegend();
    this.modeSeg = seg([['one', 'One hand'], ['two', 'Two hands'], ['teach', 'Teach']], this.mode, v => this.setMode(v));
    this.plan = h('select', {onchange: () => this.changed()});
    this.pair = h('select', {onchange: () => this.changed()});
    this.tempoSeg = seg([[0.5, '50 %'], [0.75, '75 %'], [1, '100 %']], 1, v => { this.tempo = parseFloat(v); });
    this.btn = h('button', {class: 'pill primary big', onclick: () => this.start()});
    this.phr = h('div', {class: 'row tight'});
    this.rounds = slider(1, 10, 1, 3, v => '× ' + v);
    this.pause = slider(2, 20, 1, 5, v => v + ' s pause');
    this.teachRow = h('div', {class: 'bar-row', style: {marginTop: '10px'}}, h('span', {class: 'lbl', text: 'Phrase'}), this.phr,
      h('span', {style: {width: '150px'}}, this.rounds), h('span', {style: {width: '170px'}}, this.pause));
    this.effort = slider(0.3, 1.5, 0.1, s.effort, v => v.toFixed(1) + ' A');
    this.fingers = fingerToggles(() => this.changed());
    this.lead = slider(3, 40, 1, 4, v => v + ' s');
    this.snA = h('input', {type: 'text', placeholder: 'hand A', style: {width: '48%'}});
    this.snB = h('input', {type: 'text', placeholder: 'hand B', style: {width: '48%', marginLeft: '4%'}});
    this.checkEl = h('span', {class: 'oneline', style: {marginTop: 0}});
    this.checkBtn = h('button', {class: 'pill', text: 'Check the pair in simulation', onclick: () => { const d = this.duet(); if (d) act(() => api('/api/check', {plan: d.a, plan_b: d.b})); }});
    this.more = h('details', {class: 'disclosure'}, h('summary', {text: 'More'}), h('div', {class: 'form'},
      ...field('Current limit', this.effort, 'never above 1.5 A'), ...field('Fingers', this.fingers), ...field('Lead time', this.lead, 'from Start to the first note'),
      ...field('Serial numbers', h('div', {}, this.snA, this.snB), 'two hands of the same side only'), ...field('Two hands', h('div', {class: 'row'}, this.checkBtn, this.checkEl))));
    el.append(...pageHead('Play'),
      card(null, h('div', {class: 'bar-row'}, this.modeSeg, this.plan, this.pair, this.tempoSeg, h('span', {class: 'grow'}), this.btn), this.posLine = h('div', {}), this.teachRow, this.more,
        (this.pose = startPoseView()).el),
      card(null, h('div', {class: 'bar-row', style: {marginBottom: '8px'}}, this.showSeg), this.view.stage.el, this.v3.el, this.legend), this.view.status);
    this.onLibrary(); this.setMode(this.mode);
  },
  show(arg) {
    if (arg && arg.pair) {                        // a two-hand pair from the Library
      this.setMode('two');
      if ([...this.pair.options].some(o => o.value === arg.pair)) { this.pair.value = arg.pair; this.changed(); }
    }
    if (arg && arg.plan) {
      if (this.mode === 'two') this.setMode('one');
      this.want = arg.plan;                       // a run that just finished may not be in the library yet: keep asking for it
      this.fill(arg.plan); this.changed();
      if (!planById(arg.plan)) loadLibrary();
    }
    this.view.stage.redraw(); this.v3.redraw();
  },
  hide() { if (this.v3) this.v3.pause(); },
  setShow(v) {
    this.show3d = v === '3d';
    this.view.stage.el.hidden = this.legend.hidden = this.show3d; this.v3.el.hidden = !this.show3d;
    if (this.show3d) { this.k3 = null; this.load3d(); this.sync3d(); } else { this.v3.pause(); this.v3.follow(null); this.k3 = null; this.view.stage.redraw(); }
  },
  ids3d() {
    if (this.mode === 'two') { const d = this.duet(); return d ? [d.a, d.b] : null; }
    return planById(this.plan.value) ? [this.plan.value] : null;
  },
  load3d() { const ids = this.ids3d(); if (this.show3d && ids && !this.k3) this.v3.load(ids); },
  sync3d() {
    // while a run plays (fake or real hand), the 3D view runs on its clock; afterwards it shows the chosen plan again
    if (!this.show3d) return;
    const j = this.view.job(), tl = j && (j.state === 'running' || j.state === 'queued') && j.meta.timeline;
    if (tl && !tl.next_in) {
      const key = j.id + ':' + tl.start_at;
      if (key !== this.k3) { this.k3 = key; this.v3.load([j.meta.plan, j.meta.plan_b].filter(Boolean)); this.v3.follow(tl); }
    } else if (this.k3) { this.k3 = null; this.v3.follow(null); this.load3d(); }
  },
  duet() { return (App.lib.duets || []).find(d => d.id === this.pair.value); },
  fill(keep) {
    const ps = App.lib.plans.filter(p => !p.error && p.playable);
    let cur = keep || this.plan.value;
    if (this.want && ps.some(p => p.id === this.want)) { cur = this.want; this.want = null; }
    clear(this.plan);
    for (const [label, sh] of [['Shared', true], ['This computer', false]]) {
      const g = h('optgroup', {label});
      for (const p of ps.filter(p => p.shared === sh)) g.append(h('option', {value: p.id, text: p.name + ' · ' + scoreText(p) + (p.center ? ' · middle finger ' + noteName(midKey(p)) : '')}));
      if (g.children.length) this.plan.append(g);
    }
    this.plan.value = ps.some(p => p.id === cur) ? cur : (ps.some(p => p.id === App.lib.ref_plan) ? App.lib.ref_plan : (ps[0] || {}).id);
    const pk = this.pair.value;
    clear(this.pair);
    for (const d of App.lib.duets || []) this.pair.append(h('option', {value: d.id, text: duetLabel(d)}));
    if ([...this.pair.options].some(o => o.value === pk)) this.pair.value = pk;
  },
  onLibrary() { if (this.plan) { this.fill(); this.changed(); } },
  onTarget() { if (this.btn) { this.lead.value = App.target === 'fake' ? (this.mode === 'two' ? 6 : 4) : (this.mode === 'two' ? 16 : App.target === 'local' ? 9 : 13); this.effort.setDisabled(!targetInfo().real); this.update(); } },
  setMode(v) {
    this.mode = v; this.modeSeg.set(v);
    this.plan.hidden = v === 'two'; this.pair.hidden = v !== 'two';
    this.teachRow.hidden = v !== 'teach';
    this.tempo = v === 'teach' ? App.state.settings.teach_tempo : 1; this.tempoSeg.set(this.tempo);
    this.effort.value = v === 'teach' ? App.state.settings.teach_effort : App.state.settings.effort;
    this.onTarget(); this.changed();
  },
  changed() {
    if (this.mode === 'two') {
      const d = this.duet();
      this.view.stage.select = null; this.view.stage.idle = 0;
      if (d) this.view.setRest([planTrack(planById(d.a)), planTrack(planById(d.b))]);
      clear(this.posLine); this.pose.show(d ? [d.a, d.b] : []);
      this.csig = null; this.update(); this.load3d();
      return;
    }
    const p = planById(this.plan.value); if (!p) return;
    this.paintPos(p); this.pose.show([p.id]);
    if (this.mode === 'teach') {
      this.ph = phrases(p.notes, 8); if (this.sel >= this.ph.length) this.sel = 0;
      clear(this.phr).append(h('button', {class: 'pill' + (this.sel < 0 ? ' primary' : ''), text: 'All', onclick: () => { this.sel = -1; this.changed(); }}),
        ...this.ph.map((x, i) => h('button', {class: 'pill' + (i === this.sel ? ' primary' : ''), text: String(i + 1), onclick: () => { this.sel = i; this.changed(); }})));
    }
    const sec = this.section();
    this.view.stage.select = sec ? [sec.start, sec.end] : null;
    this.view.stage.idle = sec ? sec.start + 0.6 : 0;
    this.view.setRest([planTrack(p, this.fingers.value)]);
    this.view.stage.redraw();
    this.load3d();
  },
  paintPos(p) {
    // where the hand has to sit for this plan; a warning when that is not where it plays Ode to Joy
    const ref = planById(App.lib.ref_plan);
    clear(this.posLine);
    if (!p.center) return;
    if (!ref || p.side !== ref.side || samePlace(p, ref)) return;           // the 'Where the hand goes' box below says it
    this.posLine.append(h('div', {class: 'banner warn', style: {marginTop: '8px'},
      text: `This plan needs the ${p.side} hand ${fromOde(p)} (middle finger ${noteName(midKey(p))}). Move the hand first: where to, below.`}));
  },
  section() { return this.mode === 'teach' && this.sel >= 0 && this.ph ? this.ph[this.sel] : null; },
  async start() {
    const t = targetInfo(), body = {target: t.id, tempo: this.tempo, effort: this.effort.value, countdown: this.lead.value};
    let what;
    if (this.mode === 'two') {
      const d = this.duet(); if (!d) return;
      Object.assign(body, {plan: d.a, plan_b: d.b, sn_a: this.snA.value.trim() || null, sn_b: this.snB.value.trim() || null}); what = d.title + ', two hands';
    } else {
      const p = planById(this.plan.value); if (!p) return;
      Object.assign(body, {plan: p.id, fingers: this.fingers.value}); what = p.name;
      if (this.mode === 'teach') { const sec = this.section(); Object.assign(body, {mode: 'teach', repeats: this.rounds.value, pause: this.pause.value, start: sec ? sec.start : null, end: sec ? sec.end : null}); }
    }
    if (t.real) {
      const ok = await confirmReal((this.mode === 'teach' ? 'Lesson' : 'Play') + ' on the real hand?', [
        `${what} · ${t.label} · ${body.effort.toFixed(1)} A` + (body.tempo < 1 ? ` · ${Math.round(body.tempo * 100)} % speed` : ''),
        'The hand moves to its start pose first.', 'Nothing in the way; the strap is attached.']
        .concat(this.mode === 'teach' ? ['The hand sits higher; your hand lies relaxed under it and can slide out sideways.'] : []), 'Start');
      if (!ok) return;
      body.confirm = true;
    }
    Sound.ensure();
    await act(() => api('/api/play', body));
  },
  update() {
    if (!this.view) return;
    this.view.sync(); this.sync3d();
    const t = targetInfo(), busy = handBusy();
    this.btn.textContent = busy ? 'Playing …' : (this.mode === 'teach' ? 'Start the lesson' : 'Play') + (t.real ? ' on the real hand' : '');
    this.btn.className = 'pill big ' + (t.real ? 'real' : 'primary');
    this.btn.disabled = !!busy || (this.mode === 'two' ? !this.duet() : !planById(this.plan.value));
    const d = this.mode === 'two' && this.duet();
    const j = d && App.state.jobs.find(j => j.kind === 'check' && j.meta.plan === d.a && j.meta.plan_b === d.b);
    const sig = (d ? d.id : '') + (j ? j.id + j.state : '');
    if (sig !== this.csig) {
      this.csig = sig;
      this.checkBtn.disabled = !d || !App.state.env.mujoco || (j && j.state === 'running');
      this.checkEl.textContent = !j ? '' : j.state === 'running' || j.state === 'queued' ? 'checking …' : j.state === 'done' && j.meta.hands.length
        ? j.meta.hands.map(x => `${x.side} ${x.matched}/${x.total}`).join(' · ') + ` · ${j.meta.touching ? 'hands touch' : 'hands never touch'}` : 'check failed';
    }
  },
};

// ---------------------------------------------------------------- Camera (Sebas's webcam teleop)
// Guided calibration: each pose is shown, then held while the camera collects it (scripts/teleop.py CAL_POSES).
const CAL_STEPS = [
  {pose: 'open', title: 'Open hand', text: 'Hand flat, fingers together, thumb next to the index finger. Palm to the camera.'},
  {pose: 'fist', title: 'Fist', text: 'Curl all four fingers as far as they go. Thumb resting on the side.'},
  {pose: 'spread', title: 'Spread wide', text: 'Fingers and thumb as far apart as they go. Hand flat.'},
  {pose: 'thumb', title: 'Thumb across', text: 'Thumb tip on the base of your little finger. Other fingers straight.'},
];
const CAL_PREP = 1.5, CAL_HOLD = 3.0;        // seconds to get into the pose, seconds it is recorded

function poseSvg(pose) {                      // palm to the camera, mirrored view: index on the left, thumb at the far left
  const NS = 'http://www.w3.org/2000/svg', svg = document.createElementNS(NS, 'svg');
  svg.setAttribute('viewBox', '0 0 120 130'); svg.setAttribute('class', 'pose');
  const el = (tag, a) => { const e = document.createElementNS(NS, tag); for (const k in a) e.setAttribute(k, a[k]); svg.append(e); return e; };
  const base = [[41, 38], [54, 42], [67, 39], [80, 31]];            // x of each finger's base, straight length
  const ang = {open: [0, 0, 0, 0], fist: [0, 0, 0, 0], spread: [-20, -5, 9, 22], thumb: [0, 0, 0, 0]}[pose];
  const thumb = {open: [-22, 32], fist: [-12, 26], spread: [-68, 34], thumb: [98, 40]}[pose];   // angle from up, length
  base.forEach(([x, len], i) => {
    const l = pose === 'fist' ? 11 : len;
    el('rect', {x: x - 5.5, y: 62 - l, width: 11, height: l + 6, rx: 5.5, transform: `rotate(${ang[i]} ${x} 62)`});
  });
  el('rect', {x: 34, y: 58, width: 53, height: 52, rx: 11});
  el('rect', {x: 31, y: 92 - thumb[1], width: 12, height: thumb[1] + 6, rx: 6, transform: `rotate(${thumb[0]} 37 92)`, class: 'th'});
  return svg;
}

App.pages.camera = {
  build(el) {
    this.img = h('img', {class: 'cam', alt: 'Camera picture with the tracked hand'});
    this.need = h('div', {});
    this.chips = h('div', {class: 'row tight', style: {marginTop: '8px'}});
    this.camBtn = h('button', {class: 'pill primary', onclick: () => this.toggleCamera()});
    this.calBtn = h('button', {class: 'pill', text: 'Calibrate', title: 'Four poses, about 5 s each: the camera learns your hand\'s range', onclick: () => this.guided()});
    this.quickCal = h('button', {class: 'pill', text: 'Open hand only', title: 'Hold your hand flat and open, then press: sets only the zero pose', onclick: () => this.cmd({calibrate: true}, 'Calibrated: this pose is "open".')});
    this.guide = h('div', {class: 'cal-guide', hidden: true});
    this.driveBtn = h('button', {class: 'pill big', onclick: () => this.toggleDrive()});
    this.camNo = h('input', {type: 'number', min: 0, max: 9, value: App.state.settings.camera});
    this.source = h('input', {type: 'text', placeholder: 'video or picture file', style: {width: '100%'}});
    this.thumb = h('input', {type: 'checkbox', checked: true, onchange: () => this.cmd({thumb: this.thumb.checked})});
    this.flip = h('input', {type: 'checkbox', onchange: () => this.cmd({flip_spread: this.flip.checked})});
    this.alpha = slider(0.1, 1, 0.05, 0.4, v => v.toFixed(2), v => this.cmd({alpha: v}));
    this.effort = slider(0.3, 1.5, 0.1, 0.5, v => v.toFixed(1) + ' A');
    this.vmax = slider(0.5, 6, 0.5, 3, v => v.toFixed(1) + ' rad/s');
    this.joints = h('div', {class: 'joints'});
    this.status = h('div', {});
    el.append(...pageHead('Camera'), this.need,
      h('div', {class: 'cols main-side'},
        card(null, h('div', {class: 'cam-wrap'}, this.img, this.guide), this.chips),
        h('div', {},
          card(null, h('div', {class: 'ctrl-col'}, h('div', {class: 'row'}, this.camBtn, this.calBtn), this.driveBtn, this.status),
            h('details', {class: 'disclosure'}, h('summary', {text: 'More'}), h('div', {class: 'form', style: {gridTemplateColumns: '96px minmax(0,1fr)'}},
              ...field('Camera', this.camNo), ...field('File', this.source), ...field('Smoothing', this.alpha),
              ...field('Current limit', this.effort), ...field('Fastest', this.vmax),
              ...field('Calibrate', this.quickCal),
              ...field('', h('label', {class: 'check'}, this.thumb, h('span', {text: 'thumb follows'}))), ...field('', h('label', {class: 'check'}, this.flip, h('span', {text: 'mirror finger spread'})))))),
          card(null, this.joints))));
    this.timer = setInterval(() => this.tick(), 250);
  },
  onTarget() { if (this.effort) this.effort.setDisabled(!targetInfo().real); },
  async cmd(c, msg) { const r = await act(() => api('/api/camera/cmd', c)); if (r && msg) flash(msg); },
  async guided() {
    if (this.calRun) return;
    const run = this.calRun = {cancel: false}, sleep = ms => new Promise(r => setTimeout(r, ms));
    const send = c => api('/api/camera/cmd', c);
    const cancelBtn = h('button', {class: 'pill', text: 'Cancel', onclick: () => { run.cancel = true; }});
    this.guide.hidden = false;
    try {
      for (let i = 0; i < CAL_STEPS.length && !run.cancel; i++) {
        const st = CAL_STEPS[i], bar = h('i'), label = h('div', {class: 'cal-phase'}), seen = h('span', {class: 'chip plain'});
        clear(this.guide).append(h('div', {class: 'cal-step', text: `Pose ${i + 1} of ${CAL_STEPS.length}`}), poseSvg(st.pose),
          h('div', {class: 'cal-title', text: st.title}), h('div', {class: 'cal-text', text: st.text}),
          h('div', {class: 'cal-bar'}, bar), h('div', {class: 'row tight'}, label, seen), cancelBtn);
        const t0 = performance.now();
        let capturing = false;
        while (!run.cancel) {
          const t = (performance.now() - t0) / 1000;
          if (t >= CAL_PREP + CAL_HOLD) break;
          if (!capturing && t >= CAL_PREP) { capturing = true; await send({capture: st.pose}); }
          bar.style.width = (capturing ? (t - CAL_PREP) / CAL_HOLD : t / CAL_PREP) * 100 + '%';
          bar.className = capturing ? 'hold' : '';
          label.textContent = capturing ? 'Hold it …' : 'Get into the pose';
          const c = this.cs || {}, n = (c.captured || {})[st.pose];
          seen.className = 'chip ' + (c.tracked ? 'ok' : 'bad');
          seen.textContent = c.tracked ? (capturing && n != null ? `hand seen · ${n} frames` : 'hand seen') : 'no hand';
          await sleep(50);
        }
        await send({capture: null});
      }
      if (run.cancel) { flash('Calibration cancelled: the previous one still applies.'); return; }
      const repOf = () => JSON.stringify(((this.cs || {}).calibration || {}).report || null), before = repOf();
      await send({fit: true});
      clear(this.guide).append(h('div', {class: 'cal-title', text: 'Working it out …'}));
      for (let k = 0; k < 20 && repOf() === before; k++) await sleep(150);     // the state poll brings the new report
      this.showReport(repOf() === before ? null : JSON.parse(repOf()));
    } catch (e) {
      flash(e.message || String(e), true);
      try { await send({capture: null}); } catch (_) {}
    } finally {
      this.calRun = null;
      if (run.cancel) this.guide.hidden = true;
    }
  },
  showReport(rep) {
    const rows = CAL_STEPS.map(st => {
      const r = (rep || {})[st.pose] || {}, few = (r.frames || 0) < 15, weak = r.weak || 0;
      const ok = !few && weak <= (r.joints || 0) / 3;
      return h('div', {class: 'cal-res'}, h('span', {class: 'chip ' + (ok ? 'ok' : 'warn'), text: ok ? 'good' : 'redo'}), h('b', {text: st.title}),
        h('span', {class: 'hint', text: few ? `hand seen in ${r.frames || 0} frames only` : weak ? `${weak} of ${r.joints} joints not fitted (barely moved, or implausible): left as before` : `${r.frames} frames`}));
    });
    const bad = rows.some(r => r.firstChild.textContent === 'redo');
    clear(this.guide).append(h('div', {class: 'cal-title', text: rep ? (bad ? 'Calibrated, with gaps' : 'Calibrated') : 'No answer from the camera'}),
      ...rows, h('div', {class: 'cal-text', text: rep ? 'Saved: the camera starts with it next time.' : 'Try again.'}),
      h('div', {class: 'row tight'}, h('button', {class: 'pill', text: 'Again', onclick: () => this.guided()}),
        h('button', {class: 'pill primary', text: 'Done', onclick: () => { this.guide.hidden = true; }})));
  },
  async toggleCamera() {
    const job = App.state.jobs.find(j => j.kind === 'camera' && j.state === 'running');
    if (job) return act(() => api('/api/stop', {id: job.id}));
    const n = parseInt(this.camNo.value || '0', 10);
    await act(async () => { await api('/api/settings', {camera: n}); await api('/api/camera/start', {camera: n, source: this.source.value.trim()}); });
  },
  async toggleDrive() {
    const job = App.state.jobs.find(j => j.kind === 'follow' && (j.state === 'running' || j.state === 'queued'));
    if (job) return act(() => api('/api/stop', {id: job.id}));
    const t = targetInfo(), body = {target: t.id, effort: this.effort.value, vmax: this.vmax.value};
    if (t.real) {
      const ok = await confirmReal('Let the real hand follow the camera?', [`${t.label} · ${body.effort.toFixed(1)} A · at most ${body.vmax.toFixed(1)} rad/s`,
        'The hand moves to your hand\'s pose as soon as it is on.', 'Nothing in the way; the strap is attached.'], 'Start');
      if (!ok) return;
      body.confirm = true;
    }
    await act(() => api('/api/camera/drive', body));
  },
  async tick() {
    if (App.page !== 'camera' || !App.state || !App.state.camera.running) { this.cs = null; return; }
    try { this.cs = await api('/api/camera/state'); } catch (e) { return; }
    const c = this.cs;
    clear(this.chips).append(
      h('span', {class: 'chip ' + (c.starting ? 'warn' : c.tracked ? 'ok' : 'bad'), text: c.starting ? 'starting' : c.paused ? 'paused' : c.tracked ? 'hand seen' : 'no hand'}),
      c.fps != null ? h('span', {class: 'chip plain', text: c.fps + ' fps'}) : null,
      h('span', {class: 'chip ' + (c.calibrated ? 'ok' : 'plain'), text: c.calibrated ? 'calibrated' + (c.calibration && c.calibration.saved ? ' · ' + c.calibration.saved : '') : 'not calibrated',
        title: c.calibration ? 'guided calibration of ' + c.calibration.saved : null}));
    const lo = [0, -1.0, 0, 0], hi = [1.3, 0.3, 1.4, 1.4], q = c.q || [], a = c.actual;
    clear(this.joints).append(h('span'), ...['base', 'side', 'middle', 'tip'].map(t => h('span', {class: 'hd', text: t})));
    FINGERS.forEach((f, i) => {
      this.joints.append(h('span', {text: f, style: {color: FCOL[i], fontWeight: 700}}));
      for (let k = 0; k < 4; k++) {
        const v = q[4 * i + k] || 0, x = clamp((v - lo[k]) / (hi[k] - lo[k]), 0, 1), z = clamp(-lo[k] / (hi[k] - lo[k]), 0, 1);
        const bar = h('div', {class: 'jb', title: v.toFixed(2) + ' rad'}, h('i', {style: {left: Math.min(x, z) * 100 + '%', width: Math.abs(x - z) * 100 + '%', background: FCOL[i]}}));
        if (a) bar.append(h('u', {style: {left: clamp((a[4 * i + k] - lo[k]) / (hi[k] - lo[k]), 0, 1) * 100 + '%'}}));
        this.joints.append(bar);
      }
    });
  },
  update() {
    const e = App.state.env, running = App.state.camera.running;
    const mj = App.state.jobs.find(j => j.kind === 'model' && j.state === 'running');
    const sig = [e.cv2 && e.mediapipe, e.hand_model, !!mj].join();
    if (sig !== this.nsig) {
      this.nsig = sig;
      clear(this.need);
      if (!(e.cv2 && e.mediapipe)) this.need.append(h('div', {class: 'banner warn'}, 'Needs MediaPipe here: ', h('span', {class: 'mono', text: 'pip install -r requirements-camera.txt'}), ', then restart the studio (not inside Docker).'));
      else if (!e.hand_model) this.need.append(h('div', {class: 'banner info'}, 'The hand model (8 MB) is not here yet. ',
        h('button', {class: 'pill', text: mj ? 'Downloading …' : 'Download', disabled: !!mj, onclick: () => act(() => api('/api/camera/model', {}))})));
    }
    this.camBtn.textContent = running ? 'Stop camera' : 'Start camera';
    this.camBtn.className = 'pill ' + (running ? '' : 'primary');
    this.camBtn.disabled = !(e.cv2 && e.mediapipe && e.hand_model) && !running;
    this.calBtn.disabled = !running; this.quickCal.disabled = !running;
    if (!running && this.calRun) this.calRun.cancel = true;
    if (running && !this.img.dataset.on) { this.img.dataset.on = '1'; setTimeout(() => { if (App.state.camera.running) this.img.src = '/api/camera/stream?t=' + Date.now(); }, 1500); }
    if (!running && this.img.dataset.on) { this.img.removeAttribute('src'); delete this.img.dataset.on; clear(this.chips); clear(this.joints); }
    const fj = App.state.jobs.find(j => j.kind === 'follow'), driving = fj && (fj.state === 'running' || fj.state === 'queued'), t = targetInfo();
    this.driveBtn.textContent = driving ? 'Release the hand' : 'Hand follows' + (t.real ? ' (real hand)' : '');
    this.driveBtn.className = 'pill big ' + (driving ? 'danger' : t.real ? 'real' : 'primary');
    this.driveBtn.disabled = driving ? false : (!running || !!handBusy());
    const ssig = fj ? fj.id + fj.state + fj.phase + App.state.hand.state : '';
    if (ssig !== this.ssig) {
      this.ssig = ssig;
      clear(this.status);
      if (fj && driving) this.status.append(h('div', {class: 'oneline', style: {marginTop: 0}, text: fj.phase}));
      if (fj && !driving && fj.meta.real && App.state.hand.state === 'not_confirmed') this.status.append(h('div', {class: 'banner bad'}, 'Switch-off NOT confirmed. ',
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
    const sl = (k, a, b, st, fmt) => { const x = slider(a, b, st, s[k], fmt); x.input.addEventListener('change', () => save(k, x.value)); return x; };
    this.targets = h('div', {class: 'list'});
    this.envEl = h('div', {});
    el.append(...pageHead('Settings'),
      h('div', {class: 'cols c2'},
        h('div', {},
          card('Hand', this.targets,
            h('div', {class: 'row', style: {marginTop: '10px'}},
              h('button', {class: 'pill', text: 'Hands ›', onclick: () => show('hands')}), h('span', {class: 'subtle small', text: 'both hands: connected?, serial numbers, joints, first motion'}))),
          card('Robot computer', h('div', {class: 'form', style: {gridTemplateColumns: '90px minmax(0,1fr)'}},
            ...field('SSH', text('ssh_host', 'user@address')), ...field('Folder', text('ssh_repo', '~/Wuji-Quartet')), ...field('Python', text('ssh_python', '~/wq-venv/bin/python'))),
            h('div', {class: 'row', style: {marginTop: '10px'}}, h('button', {class: 'pill', text: 'Copy scripts and plans there', onclick: () => act(async () => { const r = await api('/api/sync', {}); openLog(r.job.id); })})))),
        h('div', {},
          card('Defaults', h('div', {class: 'form'},
            ...field('Current, play', sl('effort', 0.3, 1.5, 0.1, v => v.toFixed(1) + ' A')), ...field('Current, teach', sl('teach_effort', 0.3, 1.5, 0.1, v => v.toFixed(1) + ' A')),
            ...field('Speed, teach', sl('teach_tempo', 0.25, 1, 0.25, v => Math.round(v * 100) + ' %')), ...field('Processes', sl('workers', 1, App.state.env.cores, 1, v => v + ' of ' + App.state.env.cores)),
            ...field('Sound', h('label', {class: 'check'}, h('input', {type: 'checkbox', checked: s.sound, onchange: e => save('sound', e.target.checked)}), h('span', {text: 'fake hand plays through the browser'}))))),
          card('This computer', this.envEl))));
    this.paintTargets();
  },
  paintTargets() {
    clear(this.targets);
    for (const t of App.state.targets) {
      const l = linkOf(t.id), k = linkKind(l);
      const chip = t.real && !(t.ok === false) ? h('span', {class: 'chip ' + (k === 'unknown' ? 'plain' : k), text: linkHead(l).toLowerCase(), title: linkDetail(l)}) : null;
      this.targets.append(h('div', {class: 'opt' + (t.id === App.target ? ' on' : ''), onclick: () => { if (t.real && t.ok === false) return flash(t.help, true); setTarget(t.id); }},
        h('span', {class: 'radio'}), h('div', {style: {flex: 1}}, h('div', {class: 't'}, t.label, chip ? ' ' : null, chip), h('div', {class: 'd', text: t.help}))));
    }
    this.linkSig = linkSigOf();
  },
  onTarget() { if (this.targets) this.paintTargets(); },
  update() {
    if (this.targets && linkSigOf() !== this.linkSig) this.paintTargets();
    const e = App.state.env, yes = (b, y, n) => h('span', {class: 'chip ' + (b ? 'ok' : 'plain'), text: b ? y : n});
    const sig = JSON.stringify(e);
    if (sig === this.sig) return;
    this.sig = sig;
    clear(this.envEl).append(h('div', {class: 'row tight'}, yes(e.mujoco, 'MuJoCo', 'no MuJoCo'), yes(e.sdk, 'wuji-sdk', 'no wuji-sdk'), yes(e.cv2 && e.mediapipe, 'MediaPipe', 'no MediaPipe'),
      yes(e.ffmpeg, 'ffmpeg', 'no ffmpeg'), h('span', {class: 'chip plain', text: `Python ${e.python} · ${e.cores} threads${e.docker ? ' · Docker' : ''} · ${e.rev || ''}`})));
  },
};
