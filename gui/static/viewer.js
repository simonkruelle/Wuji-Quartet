// The 3D view of any plan (or two plans for two hands): the robot hand(s) in simulation over the keyboard, the SBTO search that
// made the plan, and the recorded pianist's hands when the piece comes from a FürElise performance. Data: /api/view, built by
// scripts/plan_view.py (piano frame of piano_core.build_scene, in mm: +x toward the player, key fronts at 150, +y toward the
// treble, z = white key top). Used by the 3D view page and by Play (Notes | 3D).
'use strict';

const KB = {W: 22.5, L: 150, H: 22.5, PITCH: 23.5, BW: 10, BL: 90, BH: 18, BOFF: 12.5, TRAVEL: 10, BTRAVEL: 8};   // piano_core.py, mm
const keyY = m => (isBlack(m) ? whiteIndex(m) - 0.5 : whiteIndex(m)) * KB.PITCH;
const COL = {skin: '#eab89b', skinLine: '#9c6a52', robot: '#a9bfd4', robotLine: '#24313d', palm: '#3a4652', human: '#f39c4a', robotKey: '#0a84ff'};
const V3 = {
  sub: (a, b) => [a[0] - b[0], a[1] - b[1], a[2] - b[2]],
  dot: (a, b) => a[0] * b[0] + a[1] * b[1] + a[2] * b[2],
  cross: (a, b) => [a[1] * b[2] - a[2] * b[1], a[2] * b[0] - a[0] * b[2], a[0] * b[1] - a[1] * b[0]],
  norm: a => { const n = Math.hypot(a[0], a[1], a[2]) || 1; return [a[0] / n, a[1] / n, a[2] / n]; },
};
const FINGER_OF = j => j === 0 ? -1 : Math.floor((j - 1) / 4);      // joints: wrist, then 4 per finger thumb..pinky, tip last
const TIPS = [4, 8, 12, 16, 20];
const add = (el, ...kids) => { el.append(...kids.flat(Infinity).filter(k => k != null && k !== false)); return el; };   // append, skipping nulls
const tsec = t => (t < 0 ? '−' : '') + mmss(Math.abs(t));

// plans made from the recorded pianist (FürElise piece 15 = K.265, the one recording with prepared hands): the 3D view shows the pianist too
const PIANIST_PIECES = /^(k265|assets\/furelise\/(midi\/)?15(\/midi)?\.mid)$/;
function hasPianist(p) {
  if (!p) return false;
  if (PIANIST_PIECES.test(p.piece || '') || /k265/.test(p.id)) return true;
  const pc = pieceById(p.piece);
  return !!(pc && PIANIST_PIECES.test(pc.source || ''));
}

const VIEW_CACHE = {};
function getView(ids) {
  const key = ids.map(i => i + '@' + ((planById(i) || {}).mtime || 0)).join('+');
  if (!VIEW_CACHE[key]) VIEW_CACHE[key] = api('/api/view?' + ids.map(i => 'plan=' + encodeURIComponent(i)).join('&')).catch(e => { delete VIEW_CACHE[key]; throw e; });
  return VIEW_CACHE[key];
}

// the 21 points at time t, linear between the 30 fps frames
function poseAt(frames, t, D) {
  const x = clamp((t - D.start) * D.fps, 0, frames.length - 1), i = Math.floor(x), j = Math.min(i + 1, frames.length - 1), a = x - i;
  const A = frames[i], B = frames[j], out = [];
  for (let k = 0; k < A.length; k += 3) out.push([A[k] + (B[k] - A[k]) * a, A[k + 1] + (B[k + 1] - A[k + 1]) * a, A[k + 2] + (B[k + 2] - A[k + 2]) * a]);
  return out;
}
const frameAt = (t, D) => clamp(Math.round((t - D.start) * D.fps), 0, D.hands[0].down.length - 1);

// which target notes the simulated hand played (same pitch within 50 ms, one-to-one, like piano_core.score)
function matchNotes(hand) {
  const used = new Set();
  return hand.notes.map(([on, off, p]) => {
    let best = -1, bd = 0.05;
    hand.onsets.forEach(([t, q], i) => { if (q === p && !used.has(i) && Math.abs(t - on) <= bd) { best = i; bd = Math.abs(t - on); } });
    if (best >= 0) used.add(best);
    return [on, off, p, best >= 0];
  });
}

// ---------------------------------------------------------------- the scene: keyboard + hands, drawn on a 2D canvas
function HandScene(D) {
  const cv = h('canvas', {class: 'scene3d'});
  const hud = h('div', {class: 'hud'});
  const S = {el: h('div', {class: 'stagewrap'}, cv, hud), view: D.human ? 'both' : 'robot', t: D.start, trails: true};
  const pitchesOf = view => {
    const ps = [];
    if (view !== 'robot' && D.human) for (const n of D.human.notes) ps.push(n[2]);
    if (view !== 'pianist') for (const hd of D.hands) { for (const n of hd.notes) ps.push(n[2]); for (const o of hd.onsets) ps.push(o[1]); }
    return ps.length ? ps : [60, 72];
  };
  let lo, hi;
  {
    const ps = pitchesOf('both');
    lo = Math.min(...ps) - 3; hi = Math.max(...ps) + 3;
    while (isBlack(lo)) lo--;
    while (isBlack(hi)) hi++;
  }
  S.home = () => {
    const ps = pitchesOf(S.view), y0 = keyY(Math.min(...ps)), y1 = keyY(Math.max(...ps));
    S.az = -0.5; S.elev = 0.6; S.target = [95, (y0 + y1) / 2, 30]; S.dist = clamp((y1 - y0) * 1.3 + 330, 700, 2200);
    S.draw();
  };
  // the sound of the simulation: every key a hand pressed, held as long as it stayed down
  S.robotNotes = [];
  for (const hd of D.hands) for (const [t, p] of hd.onsets) {
    let f = frameAt(t, D) + 1;
    while (f < hd.down.length && hd.down[f].includes(p)) f++;
    S.robotNotes.push([t, Math.max(t + 0.08, D.start + f / D.fps), p, 1]);
  }

  function camera(W, H) {
    const ce = Math.cos(S.elev);
    const C = [S.target[0] + S.dist * ce * Math.cos(S.az), S.target[1] + S.dist * ce * Math.sin(S.az), S.target[2] + S.dist * Math.sin(S.elev)];
    const f = V3.norm(V3.sub(S.target, C)), r = V3.norm(V3.cross(f, [0, 0, 1])), u = V3.cross(r, f);
    const foc = 0.5 * W / Math.tan(0.4);
    return P => {
      const v = V3.sub(P, C), z = Math.max(20, V3.dot(v, f)), s = foc / z;
      return [W / 2 + V3.dot(v, r) * s, H * 0.56 - V3.dot(v, u) * s, z, s];
    };
  }
  function poly(g, pr, pts, fill, line) {
    g.beginPath();
    pts.forEach((p, i) => { const q = pr(p); if (i) g.lineTo(q[0], q[1]); else g.moveTo(q[0], q[1]); });
    g.closePath();
    if (fill) { g.fillStyle = fill; g.fill(); }
    if (line) { g.strokeStyle = line; g.lineWidth = 1; g.stroke(); }
  }
  function pressed(t) {
    const hum = new Map(), rob = new Set();
    if (S.view !== 'robot' && D.human) for (const n of D.human.notes) if (t >= n[0] && t < n[1]) hum.set(n[2], n[3]);
    if (S.view !== 'pianist') { const f = frameAt(t, D); for (const hd of D.hands) for (const p of hd.down[f]) rob.add(p); }
    return [hum, rob];
  }
  function drawKeys(g, pr, t) {
    const [hum, rob] = pressed(t);
    const tint = (m, base) => rob.has(m) ? COL.robotKey : hum.has(m) ? (hum.get(m) ? COL.human : '#f6c999') : base;
    poly(g, pr, [[-70, keyY(lo) - 12, 0], [0, keyY(lo) - 12, 0], [0, keyY(hi) + 12, 0], [-70, keyY(hi) + 12, 0]], '#0b0d10');
    poly(g, pr, [[-70, keyY(lo) - 12, 0], [-70, keyY(hi) + 12, 0], [-70, keyY(hi) + 12, 60], [-70, keyY(lo) - 12, 60]], '#191d23');
    for (let m = lo; m <= hi; m++) {
      if (isBlack(m)) continue;
      const y = keyY(m), w = KB.W / 2 - 0.3, down = rob.has(m) || hum.has(m), zf = down ? -KB.TRAVEL : 0, c = tint(m, '#eef1f4');
      poly(g, pr, [[0, y - w, 0], [KB.L, y - w, zf], [KB.L, y + w, zf], [0, y + w, 0]], c, 'rgba(0,0,0,.25)');
      if (rob.has(m) && hum.has(m)) poly(g, pr, [[0, y - w, 0], [KB.L * 0.5, y - w, zf * 0.5], [KB.L * 0.5, y + w, zf * 0.5], [0, y + w, 0]], COL.human);
      poly(g, pr, [[KB.L, y - w, zf], [KB.L, y + w, zf], [KB.L, y + w, zf - KB.H], [KB.L, y - w, zf - KB.H]], down ? c : '#b9c2cb', 'rgba(0,0,0,.3)');
      if (m % 12 === 0) { const q = pr([KB.L + 14, y, -KB.H]); g.fillStyle = '#7f8e9c'; g.font = '11px sans-serif'; g.textAlign = 'center'; g.fillText(noteName(m), q[0], q[1] + 4); }
    }
    for (let m = lo; m <= hi; m++) {
      if (!isBlack(m)) continue;
      const y = keyY(m), w = KB.BW / 2, down = rob.has(m) || hum.has(m), zt = KB.BOFF, zf = zt - (down ? KB.BTRAVEL : 0), zb = zt - KB.BH, c = tint(m, '#1c2128');
      for (const s of [-w, w]) poly(g, pr, [[0, y + s, zt], [KB.BL, y + s, zf], [KB.BL, y + s, zb], [0, y + s, zb]], '#0d1014');
      poly(g, pr, [[KB.BL, y - w, zf], [KB.BL, y + w, zf], [KB.BL, y + w, zb], [KB.BL, y - w, zb]], down ? c : '#0d1014');
      poly(g, pr, [[0, y - w, zt], [KB.BL, y - w, zf], [KB.BL, y + w, zf], [0, y + w, zt]], c, 'rgba(255,255,255,.08)');
    }
  }
  // one hand as depth-sorted pieces: shadow on the keys, palm, bones, knuckles, fingertips in the finger colours
  function handPieces(J, robot, alpha, out, pr) {
    const P = J.map(pr), wid = j => robot ? 14 : (FINGER_OF(j) === 0 ? 19 : 16) - (j % 4 === 0 ? 2 : 0), palm = [0, 1, 5, 9, 13, 17];
    out.push({z: 1e9, draw: g => {
      g.globalAlpha = 0.13 * alpha; g.strokeStyle = '#000'; g.lineCap = 'round';
      for (const [a, b] of D.bones) {
        const A = pr([J[a][0], J[a][1], 0]), B = pr([J[b][0], J[b][1], 0]);
        g.lineWidth = wid(b) * A[3]; g.beginPath(); g.moveTo(A[0], A[1]); g.lineTo(B[0], B[1]); g.stroke();
      }
      g.globalAlpha = 1;
    }});
    out.push({z: palm.reduce((s, j) => s + P[j][2], 0) / palm.length + 6, draw: g => {
      g.globalAlpha = alpha; g.beginPath();
      palm.forEach((j, i) => (i ? g.lineTo(P[j][0], P[j][1]) : g.moveTo(P[j][0], P[j][1])));
      g.closePath(); g.fillStyle = robot ? COL.palm : COL.skin; g.strokeStyle = robot ? COL.robotLine : COL.skinLine;
      g.lineJoin = 'round'; g.lineWidth = 14 * P[0][3]; g.stroke(); g.fill(); g.globalAlpha = 1;
    }});
    for (const [a, b] of D.bones) {
      const A = P[a], B = P[b], w = wid(b) * (A[3] + B[3]) / 2, f = FINGER_OF(b);
      out.push({z: (A[2] + B[2]) / 2, draw: g => {
        g.globalAlpha = alpha; g.lineCap = 'round';
        g.strokeStyle = robot ? COL.robotLine : COL.skinLine; g.lineWidth = w + 2.2;
        g.beginPath(); g.moveTo(A[0], A[1]); g.lineTo(B[0], B[1]); g.stroke();
        g.strokeStyle = robot ? COL.robot : COL.skin; g.lineWidth = w;
        g.beginPath(); g.moveTo(A[0], A[1]); g.lineTo(B[0], B[1]); g.stroke();
        if (robot) { g.fillStyle = COL.robotLine; g.beginPath(); g.arc(B[0], B[1], w * 0.32, 0, 7); g.fill(); }
        if (b % 4 === 0) { g.fillStyle = FCOL[f]; g.beginPath(); g.arc(B[0], B[1], w * (robot ? 0.42 : 0.3), 0, 7); g.fill(); }
        g.globalAlpha = 1;
      }});
    }
  }
  // where the fingertips were in the last 0.7 s
  function trail(g, pr, frames, t, alpha) {
    const f1 = (t - D.start) * D.fps, f0 = Math.max(0, f1 - 0.7 * D.fps);
    g.lineCap = 'round'; g.lineJoin = 'round'; g.lineWidth = 2.6;
    TIPS.forEach((j, fi) => {
      let prev = null;
      for (let f = Math.ceil(f0); f <= Math.min(f1, frames.length - 1); f++) {
        const F = frames[f], q = pr([F[3 * j], F[3 * j + 1], F[3 * j + 2]]);
        if (prev) {
          g.globalAlpha = alpha * (0.15 + 0.85 * (f - f0) / (f1 - f0 + 1e-6)); g.strokeStyle = FCOL[fi];
          g.beginPath(); g.moveTo(prev[0], prev[1]); g.lineTo(q[0], q[1]); g.stroke();
        }
        prev = q;
      }
    });
    g.globalAlpha = 1;
  }
  S.draw = () => {
    if (!cv.isConnected || cv.offsetParent === null) return;
    const [g, W, H] = fitCanvas(cv);
    const grd = g.createLinearGradient(0, 0, 0, H); grd.addColorStop(0, '#20262e'); grd.addColorStop(1, '#12161c');
    g.fillStyle = grd; g.fillRect(0, 0, W, H);
    const pr = camera(W, H), t = S.t, showH = S.view !== 'robot' && D.human, showR = S.view !== 'pianist', both = S.view === 'both';
    drawKeys(g, pr, t);
    const pieces = [];
    if (showH) {
      handPieces(poseAt(D.human.left, t, D), false, both ? 0.35 : 0.6, pieces, pr);
      handPieces(poseAt(D.human.right, t, D), false, both ? 0.55 : 1, pieces, pr);
    }
    if (showR) for (const hd of D.hands) handPieces(poseAt(hd.points, t, D), true, 1, pieces, pr);
    if (S.trails) {
      if (showH) trail(g, pr, D.human.right, t, both ? 0.45 : 0.9);
      if (showR) for (const hd of D.hands) trail(g, pr, hd.points, t, 0.9);
    }
    pieces.sort((a, b) => b.z - a.z);
    for (const p of pieces) p.draw(g);
    const who = {pianist: 'Pianist · motion capture', robot: 'Wuji Hand 2 · simulation' + (D.hands.length > 1 ? ' · two hands' : ''), both: 'Pianist (faint) and robot'}[S.view];
    hud.textContent = who + ' · ' + (t < 0 ? 'starts in ' + (-t).toFixed(1) + ' s' : mmss(t)) + (S.live ? ' · live' : '');
  };
  let drag = null;
  cv.addEventListener('pointerdown', e => { drag = [e.clientX, e.clientY]; cv.setPointerCapture(e.pointerId); });
  cv.addEventListener('pointermove', e => {
    if (!drag) return;
    S.az -= (e.clientX - drag[0]) * 0.008; S.elev = clamp(S.elev + (e.clientY - drag[1]) * 0.006, 0.08, 1.5);
    drag = [e.clientX, e.clientY]; S.draw();
  });
  cv.addEventListener('pointerup', () => { drag = null; });
  cv.addEventListener('wheel', e => { e.preventDefault(); S.dist = clamp(S.dist * Math.exp(e.deltaY * 0.001), 250, 3000); S.draw(); }, {passive: false});
  cv.addEventListener('dblclick', () => S.home());
  S.home();
  return S;
}

// ---------------------------------------------------------------- the viewer: scene + its own clock (or a run's clock on Play)
function PlanViewer(opts) {
  opts = opts || {};
  const V = {el: h('div', {class: 'viewer'}), D: null, ids: null, scene: null, live: null,
    clock: {playing: false, t: 0, speed: 1, t0: 0, w0: 0}, view: null, listeners: []};
  const box = h('div', {}), msg = h('div', {class: 'viewmsg'});
  const playBtn = h('button', {class: 'pill primary', text: '▶ Play', onclick: () => (V.clock.playing ? V.pause() : V.play())});
  const slider = h('input', {type: 'range', min: 0, max: 1, step: 0.01, value: 0, style: {flex: 1}, oninput: () => V.seek(parseFloat(slider.value))});
  const tlabel = h('span', {class: 'num subtle', style: {minWidth: '84px', textAlign: 'right'}});
  const viewEl = h('span', {});
  const speedSeg = seg([[1, '100 %'], [0.5, '50 %'], [0.25, '25 %']], 1, v => { const run = V.clock.playing; if (run) V.pause(); V.clock.speed = v; if (run) V.play(); });
  const legend = h('span', {class: 'legend', style: {marginTop: 0}});
  const transport = h('div', {class: 'bar-row', style: {marginTop: '10px'}}, playBtn, slider, tlabel);
  const options = h('div', {class: 'bar-row', style: {marginTop: '8px'}}, viewEl, opts.compact ? null : speedSeg, h('span', {class: 'grow'}), legend);
  V.el.append(box, msg, transport, options);
  const audioNow = () => (Sound.ctx ? Sound.ctx.currentTime : performance.now() / 1000);     // the sound's clock, for our own playback

  V.load = async ids => {
    const key = ids.join('+');
    if (V.ids && V.ids.join('+') === key && (V.D || V.loading)) return V.D;
    V.pause(); V.ids = ids; V.D = null; V.loading = true;
    clear(box); transport.hidden = options.hidden = true;
    msg.hidden = false; msg.textContent = 'Simulating the plan … (once per plan, a few seconds)';
    let D;
    try { D = await getView(ids); } catch (e) { if (V.ids === ids) { V.loading = false; msg.textContent = e.message; } return null; }
    if (V.ids !== ids) return null;
    V.loading = false; V.D = D; msg.hidden = true; transport.hidden = !!V.live; options.hidden = false;
    V.scene = HandScene(D); V.scene.live = !!V.live;
    clear(box).append(V.scene.el);
    slider.min = D.start; slider.max = D.t_end; V.clock.t = D.start;
    clear(viewEl).append(D.human ? seg([['pianist', 'Pianist'], ['robot', 'Robot'], ['both', 'Both']], V.scene.view, v => { V.scene.view = v; V.scene.home(); if (V.clock.playing) { V.pause(); V.play(); } })
      : h('span', {class: 'subtle small', text: 'No recording of a pianist for this piece: the robot only'}));
    add(clear(legend), D.human ? h('span', {}, h('i', {style: {background: COL.human}}), 'pianist presses') : null,
      h('span', {}, h('i', {style: {background: COL.robotKey}}), 'robot presses'), h('span', {class: 'subtle', text: 'drag to turn · scroll to zoom'}));
    V.tick();
    for (const f of V.listeners) f(D);
    return D;
  };
  V.seek = t => { const run = V.clock.playing; if (run) V.pause(); V.clock.t = t; V.tick(); if (run) V.play(); };
  V.play = () => {
    const P = V.clock, D = V.D; if (!D || V.live) return;
    stopListening();
    if (P.t >= D.t_end - 0.05) P.t = D.start;
    Sound.ensure();
    P.w0 = audioNow() + 0.08; P.t0 = P.t; P.playing = true;
    const notes = V.scene.view === 'robot' || !D.human ? V.scene.robotNotes : D.human.notes;   // the pianist's notes, or the keys the simulation pressed
    Sound.silence();
    for (const n of notes) if (n[0] >= P.t) Sound.note(n[2], P.w0 + (n[0] - P.t) / P.speed, (n[1] - n[0]) / P.speed, V.scene.view === 'both' && !n[3] ? 0.08 : 0.15);
    playBtn.textContent = '❚❚ Pause';
    for (const f of V.listeners) f(D, 'play');
    const loop = () => { if (!P.playing) return; V.tick(); requestAnimationFrame(loop); };
    requestAnimationFrame(loop);
  };
  V.pause = () => {
    const P = V.clock; if (!P.playing) return;
    P.playing = false; Sound.silence(); playBtn.textContent = '▶ Play';
    for (const f of V.listeners) f(V.D, 'pause');
  };
  // follow a run on the hand: tl = the Play timeline {start_at (server clock), tempo, tracks: [{shift, offset}]}
  V.follow = tl => {
    V.live = tl; if (V.scene) V.scene.live = !!tl;
    transport.hidden = !!tl || !V.D;
    if (tl) { V.pause(); const loop = () => { if (V.live !== tl) return; V.tick(); requestAnimationFrame(loop); }; requestAnimationFrame(loop); }
    else if (V.D) { V.clock.t = V.D.start; V.tick(); }
  };
  V.time = () => {
    const P = V.clock, D = V.D, tl = V.live;
    if (tl && tl.tracks && tl.tracks[0]) return (now() - tl.start_at - tl.tracks[0].shift) * tl.tempo - tl.tracks[0].offset + D.hands[0].shift;   // now(): the server's clock (core.js)
    if (P.playing) { P.t = P.t0 + (audioNow() - P.w0) * P.speed; if (P.t >= D.t_end) { P.t = D.t_end; V.pause(); } }
    return P.t;
  };
  V.tick = () => {
    if (!V.D || !V.scene) return;
    const t = clamp(V.time(), V.D.start, V.D.t_end);
    V.scene.t = t; V.scene.draw();
    slider.value = t; tlabel.textContent = tsec(t) + ' / ' + mmss(V.D.t_end);
    for (const f of V.listeners) f(V.D, 'tick', t);
  };
  V.redraw = () => { if (V.scene) requestAnimationFrame(() => { V.scene.draw(); V.tick(); }); };
  window.addEventListener('resize', () => V.redraw());
  return V;
}

// ---------------------------------------------------------------- charts on the music clock, click to seek
function timeChart(D, paint, onSeek) {
  const cv = h('canvas', {class: 'tchart'});
  const T0 = D.start, T1 = D.t_end, L = 34, R = 8;
  cv.draw = t => {
    if (!cv.isConnected || cv.offsetParent === null) return;
    const [g, W, H] = fitCanvas(cv);
    g.clearRect(0, 0, W, H);
    const x = s => L + (W - L - R) * (s - T0) / (T1 - T0);
    paint(g, x, W, H, L);
    if (t != null) { g.fillStyle = '#1d1d1f'; g.fillRect(x(t) - 0.75, 0, 1.5, H); }
  };
  cv.addEventListener('click', e => { const r = cv.getBoundingClientRect(); onSeek(clamp(T0 + (T1 - T0) * (e.clientX - r.left - L) / (r.width - L - R), T0, T1)); });
  return cv;
}
// SBTO: the cost of every step before and after its tries; the target notes below (red = the simulated robot missed it)
function sbtoChart(D, hand, onSeek) {
  const S = hand.sbto || {windows: [], cem: {}}, step = S.cem.commit_s || 0.5, hits = matchNotes(hand);
  const top = Math.max(1, ...S.windows.map(w => w[1])), ly = c => Math.log10(1 + c) / Math.log10(1 + top);
  const cv = timeChart(D, (g, x, W, H, L) => {
    const base = H - 22, hgt = base - 6;
    if (S.windows.length) {
      g.strokeStyle = '#e6eef5'; g.lineWidth = 1; g.font = '10.5px sans-serif'; g.textAlign = 'right';
      for (const c of [1, 10]) { if (c > top) continue; const y = base - hgt * ly(c); g.beginPath(); g.moveTo(L, y); g.lineTo(W, y); g.stroke(); g.fillStyle = '#8796a5'; g.fillText(String(c), L - 5, y + 3); }
      for (const [t, before, after] of S.windows) {
        const x0 = x(t + hand.shift) + 0.5, w = Math.max(2, x(t + step) - x(t) - 1);
        g.fillStyle = '#cfd9e3'; g.fillRect(x0, base - hgt * ly(before), w, hgt * ly(before));
        g.fillStyle = '#0a84ff'; g.fillRect(x0 + w * 0.2, base - hgt * ly(after), w * 0.6, hgt * ly(after));
      }
    }
    g.fillStyle = '#c6d3df'; g.fillRect(L, base, W - L, 1);
    for (const [on, , , hit] of hits) { g.fillStyle = hit ? '#30a46c' : '#ff3b30'; g.fillRect(x(on) - 1, base + 6, 2.2, hit ? 8 : 13); }
  }, onSeek);
  if (!S.windows.length) cv.classList.add('short');
  return cv;
}
// the wrist along the keyboard: the pianist's (recorded) and the robot's; the notes as dots
function wristChart(D, onSeek) {
  const lines = [];
  if (D.human) lines.push([D.human.right.map(F => F[1] / KB.PITCH), COL.human, 2.4]);
  for (const hd of D.hands) lines.push([hd.points.map(F => F[1] / KB.PITCH), COL.robotKey, 2]);
  const mel = [].concat(...D.hands.map(hd => hd.notes.map(n => [n[0], keyY(n[2]) / KB.PITCH])));
  const all = [].concat(...lines.map(l => l[0]), mel.map(m => m[1]));
  const lo = Math.floor(Math.min(...all)) - 1, hi = Math.ceil(Math.max(...all)) + 1;
  return timeChart(D, (g, x, W, H, L) => {
    const y = u => H - 6 - (H - 12) * (u - lo) / (hi - lo);
    g.font = '10.5px sans-serif'; g.textAlign = 'right';
    for (let m = 21; m <= 108; m++) {
      if (isBlack(m)) continue;
      const u = whiteIndex(m); if (u < lo || u > hi) continue;
      g.fillStyle = m % 12 === 0 ? '#e1e9f1' : '#f3f7fa'; g.fillRect(L, y(u) - 0.5, W - L, 1);
      if (m % 12 === 0 || (m % 12 === 7 && hi - lo < 30)) { g.fillStyle = '#8796a5'; g.fillText(noteName(m), L - 5, y(u) + 3); }
    }
    g.fillStyle = 'rgba(80,96,112,.35)';
    for (const [t, u] of mel) { g.beginPath(); g.arc(x(t), y(u), 2.2, 0, 7); g.fill(); }
    for (const [arr, col, w] of lines) {
      g.strokeStyle = col; g.lineWidth = w; g.lineJoin = 'round'; g.beginPath();
      arr.forEach((u, f) => { const X = x(D.start + f / D.fps), Y = y(u); if (f) g.lineTo(X, Y); else g.moveTo(X, Y); });
      g.stroke();
    }
  }, onSeek);
}

// ---------------------------------------------------------------- the page: any plan, or two plans for two hands
App.pages.view = {
  build(el) {
    this.picker = h('select', {class: 'viewpick', onchange: () => this.pick(this.picker.value)});
    this.facts = h('div', {class: 'facts', style: {marginTop: '-6px'}});
    this.flow = h('div', {class: 'hflow'});
    this.viewer = PlanViewer();
    this.cards = h('div', {});
    this.viewer.listeners.push((D, what, t) => this.onViewer(D, what, t));
    el.append(...pageHead('3D view', [this.picker]), this.facts, this.flow, card(null, this.viewer.el), this.cards);
    this.onLibrary();
  },
  show(arg) {
    if (arg && (arg.plan || arg.duet)) this.pick(arg.duet ? 'duet:' + arg.duet : arg.plan);
    else if (!this.cur) {
      const human = App.lib.plans.filter(p => !p.error && hasPianist(p)), first = human.find(p => p.id === 'plans/k265_human') || human[0];
      this.pick(first ? first.id : App.lib.ref_plan && planById(App.lib.ref_plan) ? App.lib.ref_plan : (App.lib.plans[0] || {}).id);
    }
    this.viewer.redraw();
  },
  hide() { this.viewer.pause(); },
  onLibrary() {
    if (!this.picker || !App.lib) return;
    const keep = this.cur;
    clear(this.picker);
    const duets = App.lib.duets || [];
    const plans = App.lib.plans.filter(p => !p.error), byPiece = {};
    const human = plans.filter(hasPianist).sort((a, b) => (a.id !== 'plans/k265_human') - (b.id !== 'plans/k265_human') || (b.shared - a.shared) || a.name.localeCompare(b.name));
    if (human.length) this.picker.append(h('optgroup', {label: 'With the recorded pianist'},
      human.map(p => h('option', {value: p.id, text: p.name + ' · ' + scoreText(p) + ' · pianist' + (!p.playable ? ' · needs an arm' : '')}))));
    for (const p of plans) if (!hasPianist(p)) (byPiece[p.piece || ''] = byPiece[p.piece || ''] || []).push(p);
    if (duets.length) this.picker.append(h('optgroup', {label: 'Two hands'}, duets.map(d => h('option', {value: 'duet:' + d.id, text: duetLabel(d)}))));
    const order = ['one', 'two', 'songs', 'imported', 'dataset'];
    const pieces = Object.keys(byPiece).map(id => [id, pieceById(id)]).sort((a, b) =>
      (a[1] ? order.indexOf(a[1].group) : 9) - (b[1] ? order.indexOf(b[1].group) : 9) || String(a[1] ? a[1].title : a[0]).localeCompare(String(b[1] ? b[1].title : b[0])));
    for (const [id, pc] of pieces) {
      const ps = byPiece[id].sort((a, b) => (b.hw_runs || 0) - (a.hw_runs || 0) || (b.shared - a.shared) || a.name.localeCompare(b.name));
      this.picker.append(h('optgroup', {label: pc ? pc.title + (pc.version ? ' · ' + pc.version : '') : (ps[0].title || id || 'Other')},
        ps.map(p => h('option', {value: p.id, text: p.name + ' · ' + scoreText(p) + (p.hw_runs ? ` · real hand ×${p.hw_runs}` : '') + (!p.playable ? ' · needs an arm' : '')}))));
    }
    if (keep) this.picker.value = keep;
  },
  ids(v) {
    if (!v) return null;
    if (v.startsWith('duet:')) { const d = (App.lib.duets || []).find(x => x.id === v.slice(5)); return d ? [d.a, d.b] : null; }
    return planById(v) ? [v] : null;
  },
  pick(v) {
    const ids = this.ids(v); if (!ids) return;
    this.cur = v; this.picker.value = v;
    const p = planById(ids[0]), pc = p && pieceById(p.piece);
    this.facts.textContent = [pc ? (pc.composer ? pc.composer + ' · ' : '') + pc.title + (pc.version ? ' · ' + pc.version : '') : p.title, ids.map(i => i.split('/').pop()).join(' + ')].join(' · ');
    clear(this.flow); clear(this.cards);
    this.viewer.load(ids);
  },
  onViewer(D, what, t) {
    if (!D) return;
    if (what === 'tick') { for (const c of this.charts || []) c.draw(t); this.syncVideo(t, false); return; }
    if (what === 'play' || what === 'pause') { this.syncVideo(this.viewer.clock.t, true); return; }
    this.paint(D);
  },
  paint(D) {
    const seek = t => this.viewer.seek(t);
    const hands = D.hands, plans = hands.map(hd => planById(hd.plan) || {});
    const N = hands.reduce((s, hd) => s + hd.notes.length, 0), played = hands.reduce((s, hd) => s + matchNotes(hd).filter(x => x[3]).length, 0);
    const sbs = hands.map(hd => hd.sbto || {windows: [], cem: {}, before: {}, after: {}});
    const searched = sbs.filter(s => s.windows.length).length;
    const reuse = sbs.find(s => s.reuse_from), earlier = sbs.find(s => s.earlier_search);
    const base = path => (path || '').split('/').pop();
    const hw = plans.reduce((s, p) => s + (p.hw_runs || 0), 0);
    const step = (n, title, sub, cls) => h('div', {class: 'hstep ' + (cls || '')}, h('i', {text: n}), h('div', {}, h('b', {text: title}), h('span', {text: sub})));
    const arrow = () => h('span', {class: 'arrow', text: '→'});
    const hm = D.human, moving = hands.some(hd => hd.wrist !== 'fixed');
    const s0 = sbs.find(s => s.windows.length) || sbs[0];
    clear(this.flow).append(
      hm ? step('1', 'Pianist', `recorded hands · FürElise ${hm.furelise_id}`, 'human') : step('1', 'Score', 'MIDI notes, no hand recording', 'score'), arrow(),
      step('2', 'Taken from it', 'notes, timing' + (hm && hands.some(hd => hd.wrist === 'human') ? ', wrist path' : '') + (hm && hm.tempo < 1 ? ` · at ${Math.round(hm.tempo * 100)} %` : '')), arrow(),
      searched ? step('3', 'SBTO', `${s0.cem.samples} tries × ${s0.cem.iters} rounds per ${s0.cem.commit_s} s` + (s0.derived_from ? ' · on ' + base(s0.derived_from) : '') + (searched < hands.length ? ' · one hand' : ''), 'sbto')
        : reuse ? step('3', 'SBTO, reused', 'found on ' + base(reuse.searched_on || reuse.reuse_from), 'sbto')
          : earlier ? step('3', 'SBTO', 'an earlier search of this plan', 'sbto') : step('3', 'No search', 'finger poses only'), arrow(),
      step('4', hands.length > 1 ? 'Two robot hands' : 'Robot hand', `simulation · ${played}/${N} notes` + (hw ? ` · real hand ×${hw}` : ''), 'robot'));
    // SBTO per hand
    const rng = rows => { if (!rows || !rows.length) return '–'; const v = rows.map(r => r[0]); return Math.min(...v) === Math.max(...v) ? String(v[0]) : Math.min(...v) + '–' + Math.max(...v); };
    const kpi = (label, a, b) => h('div', {class: 'kpi'}, h('b', {}, a != null ? [a, h('span', {class: 'arrow', text: ' → '})] : null, h('span', {style: {color: 'var(--blue)'}, text: b})), h('span', {text: label}));
    this.charts = [];
    const sbCard = card(h('span', {}, 'SBTO search'));
    hands.forEach((hd, i) => {
      const s = sbs[i], n = hd.notes.length, ch = sbtoChart(D, hd, seek), did = s.windows.length > 0;
      this.charts.push(ch);
      const nominal = s.after.train && s.after.train[0] ? s.after.train[0][0] + '/' + n : '–';
      add(sbCard, hands.length > 1 ? h('div', {class: 'handlbl', text: `${hd.side === 'left' ? 'Left' : 'Right'} hand · ${hd.plan.split('/').pop()}`}) : null, ch,
        h('div', {class: 'kpis'}, kpi('notes, nominal hand', did && s.before.train[0] ? s.before.train[0][0] : null, nominal),
          kpi('5 training setups', did ? rng(s.before.train) : null, rng(s.after.train)), kpi('5 unseen setups', did ? rng(s.before.test) : null, rng(s.after.test))),
        h('div', {class: 'oneline', text: did ? `Every try is played in simulation on 5 hands (servo stiffness, ±1–2 mm, ±0.5–1.5°); the best ${s.cem.elites} steer the next round.` + (s.search_s ? ` ${dur(s.search_s)} of search.` : '') +
            (s.derived_from ? ` The search ran on ${base(s.derived_from)}; this plan keeps its result` + (plans[i].stroke_ms ? ` with ${plans[i].stroke_ms} ms strokes.` : '.') : '') +
            (s.warm_from ? ` It started from the parameters of ${base(s.warm_from)}.` : '')
          : s.reuse_from ? `No new search: it reuses the per-finger timing and depth of ${base(s.reuse_from)}` + (s.searched_on && s.searched_on !== s.reuse_from ? `, found by the search on ${base(s.searched_on)}` : '') + '. Retarget › Standard runs one for this piece.'
            : s.earlier_search ? 'Parameters from an earlier search of this plan; that run\'s steps are not in its log.' : 'No search for this plan.'}));
    });
    add(sbCard, h('div', {class: 'legend'}, searched ? [h('span', {}, h('i', {style: {background: '#cfd9e3'}}), 'cost before'), h('span', {}, h('i', {style: {background: '#0a84ff'}}), 'after search')] : null,
      h('span', {}, h('i', {style: {background: '#30a46c'}}), 'note played'), h('span', {}, h('i', {style: {background: '#ff3b30'}}), 'missed (simulation)')));
    // the wrist when it moves or a pianist is there; otherwise where the hand sits and which finger plays which key
    let side;
    if (hm || moving) {
      const wc = wristChart(D, seek); this.charts.push(wc);
      const wi = (sbs[0].wrist_info || {});
      side = card(h('span', {}, hm ? 'Wrist: pianist → robot' : 'Wrist path'), wc,
        h('div', {class: 'legend'}, hm ? h('span', {}, h('i', {style: {background: COL.human}}), 'pianist') : null, h('span', {}, h('i', {style: {background: COL.robotKey}}), 'robot'),
          h('span', {}, h('i', {style: {background: 'rgba(80,96,112,.45)'}}), 'notes')),
        h('div', {class: 'oneline', text: hands[0].wrist === 'human' ? `The robot's wrist follows the pianist's, shifted ${Math.abs(wi.offset_keys || 0).toFixed(1)} keys for the Wuji fingers; moves under 0.3 key are held. Ideal arm: simulation only.`
          : moving ? 'Wrist positions planned from the notes. Ideal arm: simulation only.' : 'The robot\'s wrist stays in place; the pianist moves along the keys.'}));
    } else {
      side = card(h('span', {}, hands.length > 1 ? 'Hands' : 'Hand'), ...hands.map((hd, i) => {
        const p = plans[i], keys = {};
        for (const [pitch, f] of p.fing || []) (keys[f] = keys[f] || new Set()).add(pitch);
        return h('div', {class: 'handinfo'},
          h('div', {class: 'oneline', style: {marginTop: 0}, text: `${hd.side} hand` + (p.center ? `, middle finger over ${noteName(p.center)}` : '') + (p.level ? ', level, 6 cm above the keys' : '') +
            (p.hw_runs ? ` · ${p.hw_runs} real run${p.hw_runs > 1 ? 's' : ''} logged here` : '')}),
          h('div', {class: 'fingkeys'}, FINGERS.map((f, k) => h('span', {}, h('i', {style: {background: FCOL[k]}}), f + ' ',
            h('b', {text: keys[k] ? [...keys[k]].sort((a, b) => a - b).map(noteName).join(' ') : '–'})))));
      }));
    }
    const p0 = plans[0], vid = hands.length === 1 && p0.video;
    this.video = vid ? h('video', {class: 'preview', muted: true, playsInline: true, preload: 'metadata', src: '/media/' + vid + '?v=' + Math.round(p0.mtime || 0)}) : null;
    this.videoPre = hands[0].pre;
    add(clear(this.cards), h('div', {class: 'cols c2'}, sbCard, side),
      this.video ? h('details', {class: 'disclosure', ontoggle: () => this.syncVideo(this.viewer.clock.t, true)}, h('summary', {text: 'MuJoCo video, same clock'}), h('div', {}, this.video)) : null);
    requestAnimationFrame(() => this.viewer.tick());
  },
  syncVideo(t, force) {
    const v = this.video;
    if (!v || !v.closest('details') || !v.closest('details').open) return;
    const want = t + this.videoPre;                     // render_theme: real time from the plan's start, slow motion after
    if (force || Math.abs(v.currentTime - want) > 0.25) v.currentTime = Math.max(0, want);
    v.playbackRate = this.viewer.clock.speed;
    if (this.viewer.clock.playing) v.play().catch(() => {}); else v.pause();
  },
};
