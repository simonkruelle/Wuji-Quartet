// Wuji Quartet Studio: shell (header, sidebar, status bar, log drawer, dialogs) and the link to the server.
'use strict';

const NAV = [
  ['home', 'Home'],
  [null, 'LIBRARY'],
  ['pieces', 'Pieces', 1], ['plans', 'Plans', 1],
  ['retarget', 'Retarget'],
  [null, 'PLAY'],
  ['play', 'One hand', 1], ['duet', 'Two hands', 1], ['arm', 'Arm and hand', 1, 'later'],
  ['teach', 'Teach'],
  ['camera', 'Camera'],
  ['settings', 'Settings'],
];
const PARENT = {pieces: 'Library', plans: 'Library', play: 'Play', duet: 'Play', arm: 'Play'};
const FINGERS = ['thumb', 'index', 'middle', 'ring', 'pinky'];
const FCOL = ['#ff9f0a', '#34c759', '#0a84ff', '#af52de', '#ff375f'];
const NOTE = ['C', 'C♯', 'D', 'D♯', 'E', 'F', 'F♯', 'G', 'G♯', 'A', 'A♯', 'B'];

const App = {state: null, lib: null, page: null, pages: {}, clock: 0, target: null, logOpen: false, logJob: null, logNext: 0, pending: {}};

// ---------------------------------------------------------------- small helpers
function h(tag, attrs, ...kids) {
  const el = document.createElement(tag);
  for (const [k, v] of Object.entries(attrs || {})) {
    if (v == null || v === false) continue;
    if (k === 'class') el.className = v;
    else if (k === 'text') el.textContent = v;
    else if (k.startsWith('on')) el.addEventListener(k.slice(2), v);
    else if (k === 'style' && typeof v === 'object') Object.assign(el.style, v);
    else if (k in el && k !== 'list') { try { el[k] = v; } catch (e) { el.setAttribute(k, v); } }
    else el.setAttribute(k, v === true ? '' : v);
  }
  for (const kid of kids.flat(Infinity)) if (kid != null && kid !== false) el.append(kid.nodeType ? kid : document.createTextNode(String(kid)));
  return el;
}
const $ = (sel, root) => (root || document).querySelector(sel);
const clear = el => { while (el.firstChild) el.removeChild(el.firstChild); return el; };
const noteName = m => NOTE[m % 12] + (Math.floor(m / 12) - 1);
const isBlack = m => [1, 3, 6, 8, 10].includes(m % 12);
const clamp = (v, a, b) => Math.min(b, Math.max(a, v));
function dur(s) {
  if (s == null) return '';
  s = Math.max(0, Math.round(s));
  if (s < 90) return s + ' s';
  if (s < 3600) return Math.round(s / 60) + ' min';
  return Math.floor(s / 3600) + ' h ' + Math.round((s % 3600) / 60) + ' min';
}
const now = () => Date.now() / 1000 + App.clock;          // the server's clock: start times are given in it
function ago(t) {
  const s = now() - t;
  if (s < 60) return 'just now';
  if (s < 3600) return Math.round(s / 60) + ' min ago';
  if (s < 86400) return Math.round(s / 3600) + ' h ago';
  return new Date(t * 1000).toLocaleDateString();
}

async function api(path, body) {
  const opt = body === undefined ? {} : {method: 'POST', headers: {'X-WQ': '1', 'Content-Type': 'application/json'}, body: JSON.stringify(body)};
  let r;
  try { r = await fetch(path, opt); } catch (e) { throw new Error('The studio does not answer. Is python gui/app.py still running?'); }
  let data = null;
  try { data = await r.json(); } catch (e) { /* not JSON */ }
  if (!r.ok) throw new Error((data && data.error) || ('Request failed: ' + r.status));
  return data;
}
function flash(text, bad) {
  const el = $('#flash');
  el.textContent = text || '';
  el.className = bad ? 'bad' : '';
  clearTimeout(flash.t);
  flash.t = setTimeout(() => { el.textContent = ''; }, bad ? 12000 : 7000);
}
async function act(fn) {              // run a button's action; a failure is shown, never thrown at the user
  try { return await fn(); } catch (e) { flash(e.message, true); return null; }
}

// ---------------------------------------------------------------- controls
function seg(options, value, onchange, cls) {
  // options: [[value, label, disabled?, title?, optionClass?]]
  const el = h('div', {class: 'seg ' + (cls || ''), role: 'group'});
  el.value = value;
  el.set = v => { el.value = v; for (const b of el.children) b.classList.toggle('on', b.dataset.v === String(v)); };
  for (const [v, label, disabled, title, oc] of options) {
    el.append(h('button', {type: 'button', 'data-v': v, text: label, disabled: !!disabled, title, class: oc || '',
      onclick: () => { if (String(el.value) !== String(v)) { el.set(v); onchange && onchange(v); } }}));
  }
  el.set(value);
  return el;
}
function slider(min, max, step, value, fmt, onchange) {
  const out = h('output', {});
  const inp = h('input', {type: 'range', min, max, step, value});
  const show = () => { out.textContent = fmt(parseFloat(inp.value)); };
  inp.addEventListener('input', () => { show(); onchange && onchange(parseFloat(inp.value)); });
  show();
  const el = h('div', {class: 'slider'}, inp, out);
  el.input = inp;
  Object.defineProperty(el, 'value', {get: () => parseFloat(inp.value), set: v => { inp.value = v; show(); }});
  el.setDisabled = d => { inp.disabled = d; };
  return el;
}
function card(title, ...kids) {
  const right = h('span', {class: 'right'});
  const c = h('section', {class: 'card'}, title ? h('h3', {}, title, right) : null, ...kids);
  c.right = right;
  return c;
}
function fieldWide(label, control, hint) {     // label above the control, across both columns: for controls that need the width
  return [h('div', {class: 'wide'}, h('label', {text: label}), control, hint ? h('div', {class: 'hint', text: hint}) : null)];
}
function field(label, control, hint) { return [h('label', {text: label}), h('div', {}, control, hint ? h('div', {class: 'hint', text: hint}) : null)]; }
function checkrow(state, title, detail, action) {
  const marks = {ok: '✓', warn: '!', bad: '✕', off: '·'};
  return h('div', {class: 'checkrow'}, h('span', {class: 'mark ' + state, text: marks[state] || '·'}),
    h('div', {class: 'b'}, h('b', {text: title}), h('div', {text: detail || ''})), action || null);
}
function pageHead(title, sub, actions) {
  return [h('div', {class: 'page-head'}, h('div', {}, h('h1', {class: 'page-title', text: title}), h('p', {class: 'page-sub', text: sub || ''})),
    actions ? h('div', {class: 'actions'}, actions) : null)];
}
function progressBar(job) {
  const b = h('div', {class: 'bar'}, h('i'));
  b.set = j => {
    const run = j.state === 'running' || j.state === 'queued';
    b.classList.toggle('busy', run && j.progress == null && j.state === 'running');
    b.classList.toggle('done', j.state === 'done');
    b.firstChild.style.width = (j.state === 'done' ? 100 : Math.round((j.progress || 0) * 100)) + '%';
  };
  if (job) b.set(job);
  return b;
}
function stateChip(j) {
  const m = {queued: ['waiting', 'plain'], running: [j.stopping ? 'stopping' : 'running', 'warn'], done: ['done', 'ok'], failed: ['failed', 'bad'], stopped: ['stopped', 'plain'], lost: ['interrupted', 'plain']};
  const [t, c] = m[j.state] || [j.state, 'plain'];
  return h('span', {class: 'chip ' + c, text: t});
}

// ---------------------------------------------------------------- dialogs
function dialog(build) {
  // build(close) -> element. Buttons react to clicks and to Space/Enter only when they hold the focus; the dialog opens on Cancel.
  return new Promise(resolve => {
    const m = $('#modal'), d = $('.dialog', m);
    const close = v => { m.hidden = true; clear(d); document.removeEventListener('keydown', esc); resolve(v); };
    const esc = e => { if (e.key === 'Escape') close(null); };
    clear(d).append(build(close));
    m.hidden = false;
    document.addEventListener('keydown', esc);
    const c = $('[data-cancel]', d);
    if (c) c.focus();
  });
}
function confirmReal(title, lines, go) {
  return dialog(close => h('div', {},
    h('h3', {text: title}),
    h('ul', {}, lines.map(l => h('li', {text: l}))),
    h('p', {class: 'subtle small', text: 'Stop is the red button in the top bar. It switches the hand off; the fingers go limp.'}),
    h('div', {class: 'row end'},
      h('button', {class: 'pill', 'data-cancel': '1', text: 'Cancel', onclick: () => close(false)}),
      h('button', {class: 'pill real', text: go, onclick: () => close(true)}))));
}

// ---------------------------------------------------------------- hand target (shared by Play, Teach, Camera)
function targetInfo(id) { return ((App.state && App.state.targets) || []).find(t => t.id === (id || App.target)) || {id: 'fake', label: 'Fake hand', real: false}; }
function setTarget(id) {
  App.target = id;
  act(() => api('/api/settings', {target: id}));
  paintHeader();
  for (const p of Object.values(App.pages)) if (p.onTarget) p.onTarget();
}
function targetSeg() {
  const el = h('span', {});
  el.paint = () => {
    const ts = (App.state && App.state.targets) || [];
    clear(el).append(seg(ts.map(t => [t.id, t.short || t.label, t.real && t.ok === false, t.label + '. ' + t.help, t.real ? 'realopt' : '']), App.target, setTarget, 'real'));
  };
  el.paint();
  return el;
}
function handBusy() { return ((App.state && App.state.jobs) || []).find(j => j.group === 'hand' && (j.state === 'running' || j.state === 'queued')); }

// ---------------------------------------------------------------- shell
function buildNav() {
  const nav = clear($('#sidebar'));
  for (const [key, label, sub, soon] of NAV) {
    if (!key) { nav.append(h('div', {class: 'head', text: label})); continue; }
    nav.append(h('a', {class: 'item' + (sub ? ' sub' : ''), 'data-k': key, onclick: () => show(key)}, label, soon ? h('span', {class: 'soon', text: soon}) : null));
  }
}
function show(key, arg) {
  if (!App.pages[key]) key = 'home';
  const prev = App.page;
  if (prev && prev !== key && App.pages[prev].hide) App.pages[prev].hide();
  for (const a of document.querySelectorAll('#sidebar .item')) a.classList.toggle('on', a.dataset.k === key);
  const title = (NAV.find(n => n[0] === key) || [])[1];
  $('#crumb').textContent = PARENT[key] ? PARENT[key] + ' › ' + title : title;
  for (const [k, p] of Object.entries(App.pages)) if (p.el) p.el.hidden = k !== key;
  const p = App.pages[key];
  if (!p.el) { p.el = h('div', {class: 'page'}); $('#content').append(p.el); p.build(p.el); }
  App.page = key;
  if (location.hash.slice(1) !== key) history.replaceState(null, '', '#' + key);
  if (p.show) p.show(arg);
  if (p.update && App.state) p.update();
  $('#content').scrollTop = 0;
}
function paintHeader() {
  const t = targetInfo();
  const chip = $('#modechip');
  chip.textContent = t.real ? 'Real hand' : 'Fake hand';
  chip.classList.toggle('real', !!t.real);
  $('#realbar').hidden = !t.real;
  $('#realbar').textContent = 'REAL HAND · ' + t.label + ' · commands move the physical hand';
  const busy = handBusy();
  const stop = $('#stopall');
  stop.hidden = !busy;
  if (busy) stop.textContent = busy.stopping ? 'Stopping …' : '■ Stop the hand';
}
function paintStatus() {
  const s = App.state; if (!s) return;
  const set = (id, cls, text) => { const el = $(id); el.className = 'st ' + cls; el.querySelector('b').textContent = text; };
  set('#st-sim', s.env.mujoco ? 'ok' : '', s.env.mujoco ? 'Ready' : 'Not installed');
  const busy = handBusy();
  const t = targetInfo();
  if (busy) set('#st-hand', busy.meta.real ? 'rec' : 'busy', (busy.meta.real ? 'Moving' : 'Fake hand moving') + (busy.phase ? ' · ' + busy.phase : ''));
  else if (s.hand.state === 'not_confirmed') set('#st-hand', 'bad', 'Switch-off NOT confirmed');
  else if (s.hand.state === 'confirmed') set('#st-hand', 'ok', 'Off · confirmed ' + ago(s.hand.time));
  else set('#st-hand', '', t.real ? 'Not used yet' : 'Fake hand');
  const comp = s.jobs.filter(j => j.group === 'compute' && (j.state === 'running' || j.state === 'queued'));
  const run = comp.find(j => j.state === 'running');
  if (run) set('#st-compute', 'busy', (run.progress != null ? Math.round(run.progress * 100) + ' %' : 'Running') + (run.eta ? ' · ' + dur(run.eta) + ' left' : '') + (comp.length > 1 ? ' · ' + (comp.length - 1) + ' waiting' : ''));
  else set('#st-compute', '', 'Idle');
  set('#st-camera', s.camera.running ? (s.camera.driving ? 'rec' : 'ok') : '', s.camera.running ? (s.camera.driving ? 'Driving the hand' : 'Tracking') : 'Off');
}

// ---------------------------------------------------------------- log drawer
function toggleLog(open) {
  App.logOpen = open == null ? !App.logOpen : open;
  $('#logdrawer').hidden = !App.logOpen;
  $('#loglink').textContent = App.logOpen ? 'Log ▾' : 'Log ▴';
  if (App.logOpen) { paintLogJobs(); pollLog(true); }
}
function openLog(jobId) { App.logJob = jobId; App.logNext = 0; clear($('#logtext')); toggleLog(true); }
function paintLogJobs() {
  const sel = $('#logjob'); const jobs = (App.state && App.state.jobs) || [];
  if (!App.logJob && jobs.length) App.logJob = jobs[0].id;
  const sig = jobs.map(j => j.id + j.state).join();
  if (sel.dataset.sig !== sig) {
    sel.dataset.sig = sig;
    clear(sel);
    for (const j of jobs) sel.append(h('option', {value: j.id, text: j.title + ' · ' + j.state}));
  }
  sel.value = App.logJob || '';
}
async function pollLog(force) {
  if (!App.logOpen || !App.logJob || pollLog.busy) return;
  pollLog.busy = true;
  try {
    const r = await api('/api/job?id=' + App.logJob + '&from=' + App.logNext);
    const pre = $('#logtext');
    if (r.lines.length) {
      const stick = pre.scrollTop + pre.clientHeight >= pre.scrollHeight - 30;
      pre.append(r.lines.join('\n') + '\n');
      if (stick) pre.scrollTop = pre.scrollHeight;
    }
    App.logNext = r.next;
    $('#logstate').textContent = r.job ? r.job.state + (r.job.phase ? ' · ' + r.job.phase : '') : '';
  } catch (e) { /* the job list repaints on the next poll */ }
  pollLog.busy = false;
}

// ---------------------------------------------------------------- polling
async function poll() {
  try {
    const t0 = Date.now() / 1000;
    const s = await api('/api/state');
    const t1 = Date.now() / 1000;
    if (poll.best == null || t1 - t0 < poll.best + 0.02) { poll.best = t1 - t0; App.clock = s.time - (t0 + t1) / 2; }
    const before = App.state;
    App.state = s;
    if (App.target == null) App.target = s.settings.target;
    if (!targetInfo(App.target) || targetInfo(App.target).id !== App.target) App.target = 'fake';
    // a finished optimiser or video run changes the library
    const done = s.jobs.filter(j => ['done', 'failed', 'stopped'].includes(j.state)).map(j => j.id).join();
    if (before && poll.done !== done && s.jobs.some(j => ['retarget', 'render', 'model'].includes(j.kind) && j.state === 'done' && !(poll.done || '').includes(j.id))) loadLibrary();
    poll.done = done;
    paintHeader(); paintStatus();
    if (App.logOpen) { paintLogJobs(); pollLog(); }
    const p = App.pages[App.page];
    if (p && p.update) p.update();
    if (poll.down) { poll.down = false; flash('Connected again.'); }
  } catch (e) {
    if (!poll.down) flash(e.message, true);
    poll.down = true;
  }
  setTimeout(poll, 800);
}
async function loadLibrary() {
  try {
    App.lib = await api('/api/library');
    for (const p of Object.values(App.pages)) if (p.el && p.onLibrary) p.onLibrary();
  } catch (e) { flash(e.message, true); }
}
const planById = id => ((App.lib && App.lib.plans) || []).find(p => p.id === id);
const pieceById = id => ((App.lib && App.lib.pieces) || []).find(p => p.id === id);

window.addEventListener('DOMContentLoaded', async () => {
  buildNav();
  $('#loglink').addEventListener('click', e => { e.preventDefault(); toggleLog(); });
  $('#logjob').addEventListener('change', e => { App.logJob = e.target.value; App.logNext = 0; clear($('#logtext')); pollLog(true); });
  $('#stopall').addEventListener('click', () => act(async () => { await api('/api/stop', {all: true}); flash('Stop sent: the hand switches off.'); }));
  $('#modechip').addEventListener('click', () => show('settings'));
  await loadLibrary();
  await poll();
  show(location.hash.slice(1) || 'home');
});
