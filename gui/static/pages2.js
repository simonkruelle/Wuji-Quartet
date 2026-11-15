// Pages: Play (one hand, two hands, teach), Camera, Settings.
'use strict';

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
      card(null, h('div', {class: 'bar-row'}, this.modeSeg, this.plan, this.pair, this.tempoSeg, h('span', {class: 'grow'}), this.btn), this.teachRow, this.more),
      card(null, this.view.stage.el, fingerLegend()), this.view.status);
    this.onLibrary(); this.setMode(this.mode);
  },
  show(arg) {
    if (arg && arg.plan) { if (this.mode === 'two') this.setMode('one'); this.fill(arg.plan); this.changed(); }
    this.view.stage.redraw();
  },
  duet() { return (App.lib.duets || []).find(d => d.id === this.pair.value); },
  fill(keep) {
    const cur = keep || this.plan.value;
    clear(this.plan);
    const ps = App.lib.plans.filter(p => !p.error && p.playable);
    for (const [label, sh] of [['Shared', true], ['This computer', false]]) {
      const g = h('optgroup', {label});
      for (const p of ps.filter(p => p.shared === sh)) g.append(h('option', {value: p.id, text: p.name + ' · ' + scoreText(p)}));
      if (g.children.length) this.plan.append(g);
    }
    this.plan.value = ps.some(p => p.id === cur) ? cur : (ps.some(p => p.id === App.lib.ref_plan) ? App.lib.ref_plan : (ps[0] || {}).id);
    const pk = this.pair.value;
    clear(this.pair);
    for (const d of App.lib.duets || []) this.pair.append(h('option', {value: d.id, text: `${d.title} · ${d.sides[0]} + ${d.sides[1]}` + (d.gentle ? '' : ' · fast strokes') + (d.shared ? '' : ' · this computer')}));
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
      this.csig = null; this.update();
      return;
    }
    const p = planById(this.plan.value); if (!p) return;
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
    this.view.sync();
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
App.pages.camera = {
  build(el) {
    this.img = h('img', {class: 'cam', alt: 'Camera picture with the tracked hand'});
    this.need = h('div', {});
    this.chips = h('div', {class: 'row tight', style: {marginTop: '8px'}});
    this.camBtn = h('button', {class: 'pill primary', onclick: () => this.toggleCamera()});
    this.calBtn = h('button', {class: 'pill', text: 'Calibrate', title: 'Hold your hand flat and open, then press', onclick: () => this.cmd({calibrate: true}, 'Calibrated: this pose is "open".')});
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
        card(null, this.img, this.chips),
        h('div', {},
          card(null, h('div', {class: 'ctrl-col'}, h('div', {class: 'row'}, this.camBtn, this.calBtn), this.driveBtn, this.status),
            h('details', {class: 'disclosure'}, h('summary', {text: 'More'}), h('div', {class: 'form', style: {gridTemplateColumns: '96px minmax(0,1fr)'}},
              ...field('Camera', this.camNo), ...field('File', this.source), ...field('Smoothing', this.alpha),
              ...field('Current limit', this.effort), ...field('Fastest', this.vmax),
              ...field('', h('label', {class: 'check'}, this.thumb, h('span', {text: 'thumb follows'}))), ...field('', h('label', {class: 'check'}, this.flip, h('span', {text: 'mirror finger spread'})))))),
          card(null, this.joints))));
    this.timer = setInterval(() => this.tick(), 250);
  },
  onTarget() { if (this.effort) this.effort.setDisabled(!targetInfo().real); },
  async cmd(c, msg) { const r = await act(() => api('/api/camera/cmd', c)); if (r && msg) flash(msg); },
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
      h('span', {class: 'chip ' + (c.calibrated ? 'ok' : 'plain'), text: c.calibrated ? 'calibrated' : 'not calibrated'}));
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
    this.calBtn.disabled = !running;
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
    this.found = h('div', {});
    this.envEl = h('div', {});
    el.append(...pageHead('Settings'),
      h('div', {class: 'cols c2'},
        h('div', {},
          card('Hand', this.targets,
            h('div', {class: 'row', style: {marginTop: '10px'}},
              h('button', {class: 'pill', text: 'Find the hand', title: 'Reads only, never moves', onclick: () => act(async () => { const r = await api('/api/hand/info', {target: App.target}); openLog(r.job.id); })}),
              h('button', {class: 'pill danger', text: 'Switch the hand off', onclick: () => act(async () => { const r = await api('/api/hand/off', {target: App.target}); openLog(r.job.id); })})),
            this.found),
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
    for (const t of App.state.targets) this.targets.append(h('div', {class: 'opt' + (t.id === App.target ? ' on' : ''), onclick: () => { if (t.real && t.ok === false) return flash(t.help, true); setTarget(t.id); }},
      h('span', {class: 'radio'}), h('div', {style: {flex: 1}}, h('div', {class: 't', text: t.label}), h('div', {class: 'd', text: t.help}))));
  },
  onTarget() { if (this.targets) this.paintTargets(); },
  update() {
    const e = App.state.env, yes = (b, y, n) => h('span', {class: 'chip ' + (b ? 'ok' : 'plain'), text: b ? y : n});
    const sig = JSON.stringify(e) + App.state.jobs.filter(j => j.kind === 'hand_info').map(j => j.id + j.state).join();
    if (sig === this.sig) return;
    this.sig = sig;
    clear(this.envEl).append(h('div', {class: 'row tight'}, yes(e.mujoco, 'MuJoCo', 'no MuJoCo'), yes(e.sdk, 'wuji-sdk', 'no wuji-sdk'), yes(e.cv2 && e.mediapipe, 'MediaPipe', 'no MediaPipe'),
      yes(e.ffmpeg, 'ffmpeg', 'no ffmpeg'), h('span', {class: 'chip plain', text: `Python ${e.python} · ${e.cores} threads${e.docker ? ' · Docker' : ''} · ${e.rev || ''}`})));
    const j = App.state.jobs.find(j => j.kind === 'hand_info' && j.state === 'done');
    clear(this.found);
    if (j && j.meta.hands.length) this.found.append(h('table', {class: 't', style: {marginTop: '10px'}}, h('tr', {}, h('th', {text: 'Serial number'}), h('th', {text: 'Side'}), h('th', {text: 'Address'}), h('th', {text: 'Firmware'}), h('th', {class: 'n', text: 'Joints'})),
      j.meta.hands.map(x => h('tr', {}, h('td', {class: 'mono', text: x.sn}), h('td', {text: x.side}), h('td', {class: 'mono', text: x.ip}), h('td', {text: x.firmware}), h('td', {class: 'n', text: (x.joints != null ? x.joints : '?') + '/20'})))));
  },
};
