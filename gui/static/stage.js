// Pictures of music: the small piano roll, the falling-notes stage over a keyboard, and a simple piano-like sound.
'use strict';

function fitCanvas(cv) {
  const r = cv.getBoundingClientRect(), d = window.devicePixelRatio || 1;
  const w = Math.max(10, Math.round(r.width * d)), hgt = Math.max(10, Math.round(r.height * d));
  if (cv.width !== w || cv.height !== hgt) { cv.width = w; cv.height = hgt; }
  const g = cv.getContext('2d');
  g.setTransform(d, 0, 0, d, 0, 0);
  return [g, r.width, r.height];
}
const whiteIndex = m => { let n = 0; for (let k = 21; k < m; k++) if (!isBlack(k)) n++; return n; };

// ---------------------------------------------------------------- small piano roll (time left to right)
function roll(notes, opts) {
  // notes: [[on, off, pitch], ...]; opts.fing: {pitch: finger}; opts.cursor(): seconds or null; opts.select: [t0, t1]
  opts = opts || {};
  const cv = h('canvas', {class: 'roll'});
  cv.draw = () => {
    if (!cv.isConnected) return;
    const [g, W, H] = fitCanvas(cv);
    g.clearRect(0, 0, W, H);
    if (!notes || !notes.length) return;
    const T = Math.max(...notes.map(n => n[1])), lo = Math.min(...notes.map(n => n[2])), hi = Math.max(...notes.map(n => n[2]));
    const span = Math.max(4, hi - lo + 1), rh = Math.max(2, Math.min(7, (H - 8) / span));
    const x = t => 4 + (W - 8) * t / T, y = p => H - 5 - (p - lo + 0.5) * (H - 10) / span;
    if (opts.select) { g.fillStyle = 'rgba(10,132,255,.12)'; g.fillRect(x(opts.select[0]), 0, Math.max(2, x(opts.select[1]) - x(opts.select[0])), H); }
    for (const [on, off, p] of notes) {
      const f = opts.fing ? opts.fing[p] : null;
      g.fillStyle = f != null ? FCOL[f] : (opts.color || '#0a84ff');
      g.fillRect(x(on), y(p) - rh / 2, Math.max(1.5, x(off) - x(on) - 0.5), rh);
    }
    const c = opts.cursor ? opts.cursor() : null;
    if (c != null && c >= 0 && c <= T) { g.fillStyle = '#1d1d1f'; g.fillRect(x(c), 0, 1.5, H); }
  };
  requestAnimationFrame(cv.draw);
  return cv;
}

// ---------------------------------------------------------------- sound
const Sound = {
  ctx: null, nodes: [],
  ensure() {
    if (!this.ctx) { const C = window.AudioContext || window.webkitAudioContext; if (C) this.ctx = new C(); }
    if (this.ctx && this.ctx.state === 'suspended') this.ctx.resume();
    return this.ctx;
  },
  note(pitch, when, length, gainv) {
    const c = this.ctx; if (!c) return;
    const t = Math.max(c.currentTime, when), f0 = 440 * Math.pow(2, (pitch - 69) / 12);
    const out = c.createGain();
    out.gain.setValueAtTime(0, t);
    out.gain.linearRampToValueAtTime(gainv || 0.16, t + 0.006);
    out.gain.exponentialRampToValueAtTime(0.0008, t + Math.max(0.5, Math.min(2.2, length + 0.9)));
    out.connect(c.destination);
    for (const [hn, a] of [[1, 1], [2, 0.35], [3, 0.15], [4, 0.06]]) {
      const o = c.createOscillator(), g = c.createGain();
      o.type = 'sine'; o.frequency.value = f0 * hn; g.gain.value = a;
      o.connect(g); g.connect(out); o.start(t); o.stop(t + 2.4);
      this.nodes.push(o);
    }
    if (this.nodes.length > 4000) this.nodes.splice(0, 2000);
  },
  silence() { for (const o of this.nodes) { try { o.stop(); } catch (e) { /* already ended */ } } this.nodes = []; },
};
// plays notes by the browser's clock; returns a handle with stop() and time() (seconds into the piece, null when over)
function listen(notes, tempo) {
  const c = Sound.ensure(); if (!c) return null;
  Sound.silence();
  tempo = tempo || 1;
  const t0 = c.currentTime + 0.15, T = Math.max(...notes.map(n => n[1]));
  for (const [on, off, p] of notes) Sound.note(p, t0 + on / tempo, (off - on) / tempo);
  let stopped = false;
  return {stop() { stopped = true; Sound.silence(); }, time() { const t = (c.currentTime - t0) * tempo; return stopped || t > T + 0.6 ? null : t; }};
}

// ---------------------------------------------------------------- the stage: notes fall onto a keyboard
function Stage() {
  const cv = h('canvas', {class: 'stage'});
  const hud = h('div', {class: 'hud'});
  const wrap = h('div', {class: 'stagewrap'}, cv, hud);
  const S = {el: wrap, tracks: [], timeline: null, sound: false, look: 3.2, idle: 0, numbers: true, select: null, scheduled: null};
  let raf = null;

  S.set = (tracks) => { S.tracks = tracks || []; S.range = keyRange(S.tracks); kick(); };
  // timeline: {start_at, tempo, tracks:[{shift, offset}], ...} in the server's clock; null = at rest
  S.play = (timeline, opts) => {
    S.timeline = timeline; S.sound = !!(opts && opts.sound);
    if (timeline && S.sound) schedule();
    kick();
  };
  S.stop = () => { S.timeline = null; if (S.scheduled) { Sound.silence(); S.scheduled = null; } kick(); };
  S.destroy = () => { cancelAnimationFrame(raf); raf = null; };

  function keyRange(tracks) {
    let lo = 127, hi = 0;
    for (const t of tracks) for (const n of t.notes) { lo = Math.min(lo, n[2]); hi = Math.max(hi, n[2]); }
    if (lo > hi) { lo = 60; hi = 72; }
    lo -= 3; hi += 3;
    while (whiteIndex(hi + 1) - whiteIndex(lo) < 14) { lo -= 1; hi += 1; }
    while (isBlack(lo)) lo--;
    while (isBlack(hi)) hi++;
    return [Math.max(21, lo), Math.min(108, hi)];
  }
  // when a note sounds, in seconds from the start of the run (wall clock)
  const at = (tr, i, on) => (S.timeline ? (S.timeline.tracks[i].shift + (on + S.timeline.tracks[i].offset) / S.timeline.tempo) : on + 1.2);
  function inWindow(n) {
    const tl = S.timeline; if (!tl) return !S.select || (n[0] >= S.select[0] - 1e-6 && n[0] <= S.select[1] + 1e-6);
    if (tl.start != null && n[0] < tl.start - 1.0) return false;
    if (tl.end != null && n[0] > tl.end + 0.6) return false;
    return true;
  }
  function schedule() {
    const c = Sound.ensure(); if (!c) return;
    Sound.silence();
    const tl = S.timeline, base = c.currentTime + (tl.start_at - now());
    S.tracks.forEach((tr, i) => {
      for (const n of tr.notes) {
        if (!inWindow(n) || (tr.fingers && tr.fing && !tr.fingers.includes(tr.fing[n[2]]))) continue;
        const w = base + at(tr, i, n[0]);
        if (w > c.currentTime - 0.05) Sound.note(n[2], w, (n[1] - n[0]) / tl.tempo, i ? 0.11 : 0.16);
      }
    });
    S.scheduled = tl.start_at;
  }
  function kick() { if (raf == null) raf = requestAnimationFrame(frame); }

  function frame() {
    raf = null;
    if (!cv.isConnected) return;
    if (cv.offsetParent === null) { raf = requestAnimationFrame(frame); return; }      // page hidden: keep waiting cheaply
    const [g, W, H] = fitCanvas(cv);
    const tl = S.timeline;
    const t = tl ? now() - tl.start_at : S.idle;                 // seconds since the first command
    const [lo, hi] = S.range || [60, 72];
    const w0 = whiteIndex(lo), nW = whiteIndex(hi) - w0 + 1, kw = W / nW, kbH = Math.min(120, Math.max(64, H * 0.2)), hitY = H - kbH;
    const pps = (hitY - 8) / S.look;
    const kx = m => isBlack(m) ? (whiteIndex(m) - w0) * kw - kw * 0.3 : (whiteIndex(m) - w0) * kw;
    const kwid = m => isBlack(m) ? kw * 0.6 : kw;
    g.fillStyle = '#12161c'; g.fillRect(0, 0, W, H);
    g.strokeStyle = 'rgba(255,255,255,.045)'; g.lineWidth = 1;
    for (let m = lo; m <= hi; m++) if (!isBlack(m)) { const x = Math.round(kx(m)) + 0.5; g.beginPath(); g.moveTo(x, 0); g.lineTo(x, hitY); g.stroke(); }
    for (let m = lo; m <= hi; m++) if (m % 12 === 0) { g.fillStyle = 'rgba(255,255,255,.035)'; g.fillRect(kx(m), 0, kw * 7, hitY); m += 11; }
    const down = {};
    S.tracks.forEach((tr, i) => {
      for (const n of tr.notes) {
        const f = tr.fing ? tr.fing[n[2]] : null;
        const muted = !inWindow(n) || (tr.fingers && f != null && !tr.fingers.includes(f));
        const tOn = at(tr, i, n[0]), tOff = at(tr, i, n[1]);
        if (tOff < t - 0.4 || tOn > t + S.look + 0.2) continue;
        if (!muted && t >= tOn && t <= tOff) down[n[2]] = [f, i];
        const yB = hitY - (tOn - t) * pps, yT = hitY - (tOff - t) * pps;
        const x = kx(n[2]) + 1.5, w = kwid(n[2]) - 3, top = Math.max(-20, yT), bot = Math.min(hitY, yB);
        if (bot <= top) continue;
        const col = f != null ? FCOL[f] : (i ? '#8fa3b5' : '#0a84ff');
        g.globalAlpha = muted ? 0.16 : 1;
        g.fillStyle = col;
        rr(g, x, top, w, Math.max(3, bot - top), 4); g.fill();
        if (tr.side === 'left' && S.tracks.length > 1) { g.fillStyle = 'rgba(18,22,28,.38)'; rr(g, x + 3, top + 3, w - 6, Math.max(0, bot - top - 6), 2); g.fill(); }
        if (S.numbers && f != null && bot - top > 15 && !muted) {
          g.fillStyle = '#fff'; g.font = '700 ' + Math.min(14, Math.max(10, w * 0.5)) + 'px sans-serif'; g.textAlign = 'center'; g.textBaseline = 'alphabetic';
          g.fillText(String(tr.side === 'left' ? f + 1 : f + 1), x + w / 2, Math.min(bot - 5, hitY - 5));
        }
        g.globalAlpha = 1;
      }
    });
    // keyboard
    g.fillStyle = '#0c0f13'; g.fillRect(0, hitY - 2, W, 2);
    for (let m = lo; m <= hi; m++) if (!isBlack(m)) {
      const d = down[m];
      g.fillStyle = d ? (d[0] != null ? FCOL[d[0]] : '#0a84ff') : '#f4f6f8';
      g.fillRect(kx(m) + 0.5, hitY, kw - 1, kbH - 1);
      if (m % 12 === 0 || nW <= 16) { g.fillStyle = d ? '#fff' : '#8494a3'; g.font = '11px sans-serif'; g.textAlign = 'center'; g.fillText(noteName(m), kx(m) + kw / 2, H - 7); }
    }
    for (let m = lo; m <= hi; m++) if (isBlack(m)) {
      const d = down[m];
      g.fillStyle = d ? (d[0] != null ? FCOL[d[0]] : '#0a84ff') : '#1b2027';
      g.fillRect(kx(m), hitY, kwid(m), kbH * 0.62);
    }
    // countdown and text
    let text = '';
    if (tl) {
      const first = Math.min(...S.tracks.map((tr, i) => Math.min(...tr.notes.filter(inWindow).map(n => at(tr, i, n[0])))));
      const last = Math.max(...S.tracks.map((tr, i) => Math.max(...tr.notes.filter(inWindow).map(n => at(tr, i, n[1])))));
      if (t < 0) {
        g.fillStyle = 'rgba(18,22,28,.55)'; g.fillRect(0, 0, W, hitY);
        g.fillStyle = '#fff'; g.textAlign = 'center'; g.font = '700 84px sans-serif'; g.fillText(String(Math.ceil(-t)), W / 2, hitY / 2 + 20);
        g.font = '15px sans-serif'; g.fillStyle = '#b9c7d4'; g.fillText('the hand moves to its start pose', W / 2, hitY / 2 + 52);
        text = 'starts in ' + Math.ceil(-t) + ' s';
      } else if (t < last + 0.5) text = 'playing' + (tl.repeats > 1 ? ' · round ' + tl.rep + ' of ' + tl.repeats : '') + (tl.tempo < 1 ? ' · ' + Math.round(tl.tempo * 100) + ' % speed' : '');
      else text = tl.next_in ? 'next round in ' + Math.max(0, Math.ceil(tl.next_in - (now() - tl.paused_at))) + ' s' : 'finished';
      S.over = t > last + 0.8; S.first = first;
    }
    hud.textContent = text;
    if (tl || S.anim) raf = requestAnimationFrame(frame);
  }
  function rr(g, x, y, w, hgt, r) {
    r = Math.min(r, w / 2, hgt / 2);
    g.beginPath(); g.moveTo(x + r, y); g.lineTo(x + w - r, y); g.quadraticCurveTo(x + w, y, x + w, y + r); g.lineTo(x + w, y + hgt - r);
    g.quadraticCurveTo(x + w, y + hgt, x + w - r, y + hgt); g.lineTo(x + r, y + hgt); g.quadraticCurveTo(x, y + hgt, x, y + hgt - r); g.lineTo(x, y + r); g.quadraticCurveTo(x, y, x + r, y); g.closePath();
  }
  window.addEventListener('resize', kick);
  S.redraw = kick;
  return S;
}

// a plan as a stage track; fingers: the fingers that play (others are shown faint)
function planTrack(p, fingers) {
  const fing = {};
  for (const [pitch, f] of (p.fing || [])) if (!(pitch in fing)) fing[pitch] = f;
  return {notes: p.notes, fing, side: p.side, fingers: fingers && fingers.length < 5 ? fingers.map(f => FINGERS.indexOf(f)) : null};
}
function fingerLegend(sideNote) {
  return h('div', {class: 'legend'}, FINGERS.map((f, i) => h('span', {}, h('i', {style: {background: FCOL[i]}}), (i + 1) + ' ' + f)), sideNote ? h('span', {text: sideNote}) : null);
}
