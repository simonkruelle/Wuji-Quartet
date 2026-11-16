// "Where the hand goes": for a plan (or two for two hands), the keyboard seen from above as you stand in front of it (bass left,
// key fronts at the bottom, the hand coming from your side), the flange centre with its numbers, and the fingertips at the plan's
// first frame, the start pose the hand moves to before it plays. Data: /api/startpose (gui/startpose.py).
'use strict';

(() => {                                                          // one global, startPoseView: the other names stay inside
const SVGNS = 'http://www.w3.org/2000/svg';
function sv(tag, attrs, ...kids) {
  const el = document.createElementNS(SVGNS, tag);
  for (const [k, v] of Object.entries(attrs || {})) if (v != null) el.setAttribute(k, v);
  for (const k of kids.flat()) if (k != null) el.append(k.nodeType ? k : document.createTextNode(String(k)));
  return el;
}
const KW = 23.5, KL = 150, BWID = 10, BLEN = 90;                 // mm, as in piano_core
const isBlk = m => [1, 3, 6, 8, 10].includes(m % 12);
const keyY = m => isBlk(m) ? (whiteIdx(m) - 0.5) * KW : whiteIdx(m) * KW;
const cm = mm => (Math.round(mm / 10 * 10) / 10).toFixed(1).replace(/\.0$/, '') + ' cm';
function hull(pts) {                                              // convex hull, monotone chain
  const p = pts.slice().sort((a, b) => a[0] - b[0] || a[1] - b[1]), cr = (o, a, b) => (a[0] - o[0]) * (b[1] - o[1]) - (a[1] - o[1]) * (b[0] - o[0]);
  const lo = [], up = [];
  for (const q of p) { while (lo.length > 1 && cr(lo[lo.length - 2], lo[lo.length - 1], q) <= 0) lo.pop(); lo.push(q); }
  for (const q of p.reverse()) { while (up.length > 1 && cr(up[up.length - 2], up[up.length - 1], q) <= 0) up.pop(); up.push(q); }
  return lo.slice(0, -1).concat(up.slice(0, -1));
}

// in words: where the flange centre goes ('over the middle of E5', or so many cm right of it)
function flangeWords(s) {
  const m = s.mount, side = Math.abs(m.side_mm) < 1 ? `over the middle of ${noteName(s.center)}` : `${cm(Math.abs(m.side_mm))} ${m.side_mm > 0 ? 'right' : 'left'} of the middle of ${noteName(s.center)}`;
  return [side, `${cm(m.front_mm)} in front of the key fronts`, `${cm(m.height_mm)} above the white keys`, Math.abs(m.pitch_deg) < 0.5 ? 'level' : `tilted ${m.pitch_deg}° down`];
}

// one keyboard, one or two hands where they really are (bass on the left): with two hands the left hand is drawn on the left
function poseDrawing(hs) {
  const two = hs.length > 1, tipsOf = s => s.fingers.filter(f => f.x_mm != null);
  const ys = hs.flatMap(s => [...tipsOf(s).map(f => f.y_mm), ...s.fingers.flatMap(f => [f.home, ...(f.plays || [])]).filter(k => k != null).map(keyY), s.mount.y_mm]);
  const w0 = Math.floor(Math.min(...ys) / KW) - 1, w1 = Math.ceil(Math.max(...ys) / KW) + 1;
  const y0 = (w0 - 0.5) * KW, y1 = (w1 + 0.5) * KW, xTop = 40, fx = KL + Math.max(...hs.map(s => s.mount.front_mm)), xBot = fx + (two ? 26 : 22);
  const svg = sv('svg', {viewBox: `${y0 - 4} ${xTop} ${y1 - y0 + 8} ${xBot - xTop}`, class: 'posefig', role: 'img'});
  const home = {}, plays = {}, centers = new Set(hs.map(s => s.center));
  for (const s of hs) s.fingers.forEach((f, k) => { if (f.home != null) home[f.home] = k; for (const m of f.plays || []) if (m !== f.home) plays[m] = k; });
  const midis = [];
  for (let m = 21; m <= 108; m++) { const y = keyY(m); if (y >= y0 - KW && y <= y1 + KW) midis.push(m); }
  for (const m of midis.filter(m => !isBlk(m))) {
    const y = keyY(m) - KW / 2 + 0.5, k = home[m] != null ? home[m] : plays[m];
    svg.append(sv('rect', {x: y, y: 0, width: KW - 1, height: KL, rx: 1.5, fill: home[m] != null ? FCOL[home[m]] + '40' : '#fff',
      stroke: k != null ? FCOL[k] : '#c3d0dc', 'stroke-width': k != null ? 1.4 : 0.6, 'stroke-dasharray': home[m] == null && plays[m] != null ? '3 2' : null}));
    const named = home[m] != null || plays[m] != null || m % 12 === 0 || centers.has(m);
    if (named) svg.append(sv('text', {x: keyY(m), y: KL + 9, 'text-anchor': 'middle', class: 'kname' + (home[m] != null || centers.has(m) ? ' on' : '')}, noteName(m)));
  }
  for (const m of midis.filter(isBlk)) {
    const k = home[m] != null ? home[m] : plays[m];
    svg.append(sv('rect', {x: keyY(m) - BWID / 2, y: 0, width: BWID, height: BLEN, rx: 1, fill: home[m] != null ? FCOL[home[m]] : '#2c3138',
      stroke: k != null ? FCOL[k] : 'none', 'stroke-width': 1.6, 'stroke-dasharray': home[m] == null && plays[m] != null ? '3 2' : null}));
  }
  svg.append(sv('line', {x1: y0, x2: y1, y1: KL, y2: KL, class: 'front'}));
  const lo = Math.min(...hs.map(s => s.mount.y_mm));
  for (const s of hs) {
    // the hand: a light outline from the flange to the fingertips; then the flange centre and its distance to the key fronts
    const tips = tipsOf(s), my = s.mount.y_mm, f2 = KL + s.mount.front_mm, out = two && my > lo ? 1 : -1;   // labels on the hand's outer side
    if (tips.length) {
      const pts = hull([[my - 38, f2], [my + 38, f2], ...tips.map(f => [f.y_mm, f.x_mm])]);
      svg.append(sv('polygon', {points: pts.map(p => p.join(',')).join(' '), class: 'handshape'}));
    }
    svg.append(sv('line', {x1: my, x2: my, y1: KL - 30, y2: f2, class: 'axis'}));
    svg.append(sv('circle', {cx: my, cy: f2, r: 4.2, class: 'flange'}));
    const name = two ? (s.side === 'left' ? 'left hand' : 'right hand') : 'flange centre';
    svg.append(sv('text', {x: my + (two ? out * 7 : 7), y: f2 + (two ? 14 : 4), 'text-anchor': two && out < 0 ? 'end' : 'start', class: 'flabel'}, name));
    const bx = my + out * 14;
    svg.append(sv('path', {d: `M${bx - 3},${KL} h6 M${bx},${KL} V${f2} M${bx - 3},${f2} h6`, class: 'dim'}));
    svg.append(sv('text', {x: bx + out * 5, y: (KL + f2) / 2 + 3, 'text-anchor': out < 0 ? 'end' : 'start', class: 'dimt'}, cm(s.mount.front_mm)));
    tips.forEach(f => {
      const k = s.fingers.indexOf(f);
      svg.append(sv('circle', {cx: f.y_mm, cy: f.x_mm, r: 5, fill: FCOL[k], class: 'tip'},
        sv('title', {}, `${s.side} ${f.finger}: ${f.above_mm} mm above ${noteName(f.over)}, ${f.behind_front_mm} mm behind its front edge`)));
      svg.append(sv('text', {x: f.y_mm, y: f.x_mm + 2.6, 'text-anchor': 'middle', class: 'tipl'}, f.finger[0].toUpperCase()));
    });
  }
  return svg;
}

function poseText(s) {
  const tips = s.fingers.filter(f => f.x_mm != null), r = a => Math.round(a);
  const lines = [h('div', {class: 'poseline'}, h('b', {text: 'Flange centre '}), flangeWords(s).join(' · '))];
  if (tips.length) {
    const off = tips.filter(f => f.home != null && f.over !== f.home);
    const ab = tips.map(f => f.above_mm), bh = tips.map(f => f.behind_front_mm);
    lines.push(h('div', {class: 'poseline'}, h('b', {text: 'At the start '}),
      s.start_hover ? `fingertips ${r(Math.min(...ab))}–${r(Math.max(...ab))} mm above their keys, ${r(Math.min(...bh))}–${r(Math.max(...bh))} mm behind the key fronts`
        : 'fingers curled up until their first note (not over their keys yet)'));
    if (s.start_hover && off.length) lines.push(h('div', {class: 'banner warn', style: {margin: '6px 0 0'},
      text: off.map(f => `${f.finger} starts over ${noteName(f.over)}, not its key ${noteName(f.home)}`).join('; ')}));
  }
  lines.push(h('div', {class: 'fingkeys'}, s.fingers.map((f, k) => h('span', {}, h('i', {style: {background: FCOL[k]}}), f.finger + ' ',
    h('b', {text: f.home != null ? noteName(f.home) : '—'}), (f.plays || []).filter(m => m !== f.home).length ? ' + ' + f.plays.filter(m => m !== f.home).map(noteName).join(' ') : ''))));
  return lines;
}

// the Ode to Joy plan for this side (the position everyone sets up first): the reference plan, or its partner in the Ode pair
function odeRef(side) {
  const ref = planById(App.lib && App.lib.ref_plan); if (!ref) return null;
  if (ref.side === side) return ref;
  const d = (App.lib.duets || []).find(d => d.a === ref.id || d.b === ref.id), o = d && planById(d.a === ref.id ? d.b : d.a);
  return o && o.side === side ? o : null;
}
// how far a plan's hand sits from the Ode to Joy position, in words ('2.4 cm (1 white key) right of the Ode to Joy position')
function fromOde(p) {
  const ref = odeRef(p.side); if (!ref || !p.mount || !ref.mount) return '';
  if (samePlace(p, ref)) return 'same';
  const a = p.mount, b = ref.mount, parts = [];
  const dy = keyY(p.center) + a.dy * 1000 - (keyY(ref.center) + b.dy * 1000), wk = dy / KW;
  if (Math.abs(dy) > 1) parts.push(`${cm(Math.abs(dy))}` + (Math.abs(wk - Math.round(wk)) < 0.02 ? ` (${Math.abs(Math.round(wk))} white key${Math.abs(Math.round(wk)) > 1 ? 's' : ''})` : '') + ` further ${dy > 0 ? 'right' : 'left'}`);
  const dx = (a.x - b.x) * 1000, dz = (a.z - b.z) * 1000, dt = a.theta - b.theta;
  if (Math.abs(dx) > 1) parts.push(`${cm(Math.abs(dx))} ${dx > 0 ? 'further from' : 'closer to'} the keys`);
  if (Math.abs(dz) > 1) parts.push(`${cm(Math.abs(dz))} ${dz > 0 ? 'higher' : 'lower'}`);
  if (Math.abs(dt) > 0.5) parts.push(`tilted ${Math.abs(dt)}° more ${dt > 0 ? 'down' : 'up'}`);
  return parts.join(', ') + ' than for Ode to Joy';
}
// the middle finger's key of a library plan (the mount is measured from p.center, which is not always that key: D major sits 3 cm right of E5)
function midKey(p) {
  const mid = (p.fing || []).filter(([m, f]) => f === 2).map(([m]) => m);
  return mid.includes(p.center) || !mid.length ? p.center : mid[0];
}
// every playable plan, grouped by where its hand sits: songs in one group need no move between them
function positionGroups() {
  const g = new Map();
  for (const p of (App.lib && App.lib.plans) || []) {
    if (!p.playable || !p.mount || p.error) continue;
    const m = p.mount, k = [p.side, p.center, m.x.toFixed(3), m.z.toFixed(3), m.theta.toFixed(1), m.dy.toFixed(3)].join('|');
    if (!g.has(k)) g.set(k, {plan: p, songs: new Map()});
    const e = g.get(k), old = e.songs.get(p.title);
    if (!old || (p.shared && !old.shared)) e.songs.set(p.title, p);
    if (p.shared && !e.plan.shared) e.plan = p;
  }
  return [...g.values()].map(e => Object.assign(e, {songs: [...e.songs.values()]}))
    .sort((a, b) => (a.plan.side === b.plan.side ? 0 : a.plan.side === 'right' ? -1 : 1) || (b.plan.level - a.plan.level) || keyY(a.plan.center) - keyY(b.plan.center));
}

// plans in the library that sit exactly here: no need to move the hand between them
function samePosition(id) {
  const me = planById(id); if (!me) return [];
  const titles = new Set();
  for (const p of (App.lib && App.lib.plans) || []) if (p.id !== id && p.shared && p.playable && samePlace(p, me)) titles.add(p.title);
  return [...titles];
}

function startPoseView() {
  const body = h('div', {}), sum = h('summary', {text: 'Where the hand goes'});
  const V = {el: h('details', {class: 'disclosure posebox', open: true}, sum, body), key: null};
  V.show = async ids => {
    ids = (ids || []).filter(Boolean);
    const key = ids.join('+');
    if (key === V.key) return;
    V.key = key;
    clear(body);
    if (!ids.length) { sum.textContent = 'Where the hand goes'; return; }
    const ps = ids.map(planById);
    sum.textContent = ids.length > 1 ? 'Where the hands go' : 'Where the hand goes';
    let r;
    try { r = await api('/api/startpose?' + ids.map(i => 'plan=' + encodeURIComponent(i)).join('&')); }
    catch (e) { if (V.key === key) body.append(h('div', {class: 'oneline', text: e.message})); return; }
    if (V.key !== key) return;
    const order = r.hands.map((s, i) => i).sort((i, j) => r.hands[i].mount.y_mm - r.hands[j].mount.y_mm);   // bass side first, as on the piano
    const hs = order.map(i => r.hands[i]);
    sum.textContent = (ids.length > 1 ? 'Where the hands go · ' : 'Where the hand goes · ') +
      hs.map(s => `${s.side} hand, middle finger ${noteName(s.fingers[2].home != null ? s.fingers[2].home : s.center)}`).join(' · ');
    const panes = order.map(i => {
      const s = r.hands[i], same = samePosition(ids[i]), p = ps[i];
      const ode = p ? fromOde(p) : '';
      return h('div', {class: 'posepane'},
        h('div', {class: 'handlbl', text: (s.side === 'left' ? 'Left hand' : 'Right hand') + (p ? ' · ' + p.name : '')}),
        ...poseText(s),
        ode ? h('div', {class: 'poseline'}, h('b', {text: 'From the Ode to Joy position '}), ode === 'same' ? 'no move: this is the Ode to Joy position' : ode) : null,
        same.length ? h('div', {class: 'oneline', text: 'Same place, no move: ' + same.slice(0, 8).join(', ') + (same.length > 8 ? ` and ${same.length - 8} more` : '')}) : null);
    });
    body.append(poseDrawing(hs), h('div', {class: hs.length > 1 ? 'cols c2' : ''}, ...panes));
    if (hs.length > 1) {
      const d = Math.abs(hs[0].mount.y_mm - hs[1].mount.y_mm);
      body.append(h('div', {class: 'oneline', text: `Between the two flange centres: ${cm(d)} (${Math.round(d / KW * 10) / 10} white keys).`}));
    }
    body.append(h('div', {class: 'oneline', text: 'Seen from above, standing in front of the piano: bass on the left, key fronts at the bottom; the left hand is on the left, as on the piano. Filled key = the finger\'s key at the start; dashed = a key it also reaches during the piece. Letters = the fingertips at the start pose (hover for the numbers).'}));
  };
  return V;
}
Object.assign(window, {startPoseView, positionGroups, fromOde, midKey});
})();
