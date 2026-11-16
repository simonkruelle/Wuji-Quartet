// Page: Hands. Both real hands side by side (right, left): does each answer, through which port, serial number, firmware, joints;
// the USB adapter the second hand needs (the robot computer has one Ethernet port); a first motion per hand; ready for two hands?
'use strict';

const SIDE_TITLE = {right: 'Right hand', left: 'Left hand'};
function portName(dev) {
  if (!dev) return '';
  if (dev.startsWith('wl')) return 'Wi-Fi';
  if (dev === 'eth0') return 'the Ethernet port';
  if (/^(enx|eth[1-9])/.test(dev)) return 'the USB adapter';
  return dev;
}
const isAdapter = dev => !!dev && /^(enx|eth[1-9])/.test(dev);

App.pages.hands = {
  build(el) {
    this.where = h('div', {});
    this.cards = h('div', {class: 'cols c2', style: {alignItems: 'stretch', marginBottom: '12px'}});
    this.ready = h('div', {});
    this.places = h('div', {});
    el.append(...pageHead('Hands', [
      h('button', {class: 'pill', text: 'Check now', title: 'Pings both hands from the robot computer. Reads only, never moves', onclick: () => checkHand(this.tid())}),
      h('button', {class: 'pill', text: 'Read serial numbers and joints', title: 'scripts/hand_info.py: reads only, never moves', onclick: () => this.info()}),
      h('button', {class: 'pill danger', text: 'Switch both off', onclick: () => act(async () => { const r = await api('/api/hand/off', {target: this.tid()}); openLog(r.job.id); })})]),
      this.where, this.cards, card('Ready for two hands?', this.ready),
      card('Where the hands go, song by song', h('p', {class: 'note', style: {margin: '0 0 8px'}, text: 'Songs on one line share the hand\'s place: no move between them. Click a song for its start pose on Play.'}), this.places));
    this.onLibrary();
  },
  onLibrary() {
    if (!this.places) return;
    clear(this.places).append(h('table', {class: 't'}, positionGroups().map(g => {
      const p = g.plan, ode = fromOde(p);
      return h('tr', {},
        h('td', {style: {width: '34%'}}, h('b', {text: `${p.side === 'left' ? 'Left' : 'Right'} hand, middle finger ${noteName(midKey(p))}`}),
          h('div', {class: 'subtle small', text: (ode === 'same' ? 'the Ode to Joy position' : ode || '') +
            (p.level ? '' : ` · old mount: ${Math.round((p.mount.x - 0.15) * 100)} cm in front, ${Math.round(p.mount.z * 100)} cm up, ${p.mount.theta}° down`)})),
        h('td', {}, h('div', {class: 'row tight', style: {flexWrap: 'wrap'}}, g.songs.map(x => h('a', {class: 'chip plain', style: {cursor: 'pointer'}, text: x.title + (x.shared ? '' : ' · this computer'),
          title: x.id, onclick: () => show('play', {plan: x.id})})))));
    })));
  },
  // the real hands are on the robot computer (or this one); with the fake hand chosen, the page still shows the robot computer's
  tid() {
    if (App.target !== 'fake') return App.target;
    return (App.state.targets || []).some(t => t.id === 'board') ? 'board' : 'local';
  },
  info() { act(async () => { const r = await api('/api/hand/info', {target: this.tid()}); openLog(r.job.id); flash('Reading both hands (reads only) …'); }); },
  update() {
    const tid = this.tid(), l = linkOf(tid), busy = handBusy();
    const jobs = App.state.jobs.filter(j => ['hello', 'hand_adapter', 'hand_info', 'hand_off'].includes(j.kind)).map(j => j.id + j.state).join();
    const sig = JSON.stringify([App.target, tid, l, jobs, busy && busy.id, Math.floor(now() / 30)]);
    if (sig === this.sig) return;
    this.sig = sig;
    this.paint(tid, l, busy);
  },
  paint(tid, l, busy) {
    const t = targetInfo(tid), hs = l.hands || {}, board = tid === 'board';
    clear(this.where);
    if (App.target === 'fake') this.where.append(h('div', {class: 'banner info'}, 'Play uses the fake hand now. ',
      h('a', {text: 'Use these hands for Play', onclick: () => setTarget(tid)})));
    if (l.state === 'down') this.where.append(h('div', {class: 'banner bad', text: l.text}));
    this.where.append(h('p', {class: 'page-sub', text: `${t.label} · ` + (l.checking ? 'checking …' : l.time ? 'checked ' + ago(l.time) : 'not checked yet') +
      (board ? ' · it pings both hands every 10 s while Play uses it, every minute otherwise' : ' · this computer is not pinged: Read serial numbers and joints to see the hands')}));
    clear(this.cards).append(...['right', 'left'].map(s => this.handCard(s, hs, l, board, busy)));
    this.paintReady(hs, l, busy);
  },
  handCard(s, hs, l, board, busy) {
    const x = hs[s] || {}, other = hs[s === 'right' ? 'left' : 'right'] || {};
    const chip = l.state === 'down' ? h('span', {class: 'chip plain', text: 'unknown'})
      : x.up ? h('span', {class: 'chip ok', text: 'answers'}) : x.up === false ? h('span', {class: 'chip bad', text: 'no answer'}) : h('span', {class: 'chip plain', text: 'not checked'});
    const c = card(SIDE_TITLE[s]);
    c.right.append(chip);
    const old = x.up ? '' : ' (last seen)';
    const rows = [['Address', x.ip + (x.up && x.dev ? ' · through ' + portName(x.dev) : '')]];
    if (x.sn) rows.push(['Serial number', x.sn + old], ['Firmware', x.firmware + old],
      ['Joints online', (x.joints != null ? x.joints + ' of 20' : 'not read') + (x.read ? ' · read ' + ago(x.read) : '')]);
    else rows.push(['Serial number', x.up ? 'not read yet' : '—']);
    c.append(h('table', {class: 't'}, rows.map(([k, v]) => h('tr', {}, h('td', {class: 'subtle', style: {width: '120px'}, text: k}), h('td', {text: v})))));
    if (x.up && isAdapter(x.dev)) c.append(h('p', {class: 'note', text: 'Through the USB adapter: set up until the robot computer restarts or the adapter is replugged; then press Set up the adapter again.'}));
    if (x.up === false && l.state !== 'down') c.append(this.hint(s, x, other, l, board));
    const real = targetInfo(this.tid()).real;
    c.append(h('div', {class: 'row', style: {marginTop: '10px'}},
      h('button', {class: 'pill real', text: 'Move one finger', disabled: !real || !!busy || x.up === false || l.state === 'down',
        title: 'The first motion: index finger base joint 9° and back, twice, at 0.5 A (scripts/hand_hello.py). Hand in the air.', onclick: () => this.hello(s)}),
      x.up && !x.sn ? h('button', {class: 'pill', text: 'Read serial number and joints', onclick: () => this.info()}) : null));
    return c;
  },
  hint(s, x, other, l, board) {
    // why this hand does not answer, and the one thing to do about it
    const free = (l.adapters || []).filter(a => a.name !== other.dev);
    const setup = h('button', {class: 'pill primary', text: 'Set up the adapter', disabled: !!handBusy(), onclick: () => this.adapter()});
    if (!board) return h('div', {class: 'banner warn', style: {marginTop: '10px'}, text: 'Not found by the last read. Hand powered (light on its back)? Cable in this computer\'s network port?'});
    if (x.wifi) return h('div', {class: 'banner warn', style: {marginTop: '10px'}, text: 'The robot computer sends ' + x.ip + ' through Wi-Fi, not through a cable to the hand: is the cable in?'});
    if (free.some(a => a.link)) return h('div', {class: 'banner warn', style: {marginTop: '10px'}},
      h('div', {text: `A USB adapter with a cable is plugged in (${free.find(a => a.link).name}) but not set up for this hand.`}), h('div', {style: {marginTop: '6px'}}, setup));
    if (free.length) return h('div', {class: 'banner warn', style: {marginTop: '10px'}},
      h('div', {text: 'The USB adapter has no link: is the cable from this hand in it, and the hand powered?'}), h('div', {style: {marginTop: '6px'}}, setup));
    if (other.up && other.dev === 'eth0') return h('div', {class: 'banner warn', style: {marginTop: '10px'},
      text: `The Ethernet port holds the ${s === 'right' ? 'left' : 'right'} hand. Connect this hand through a USB-Ethernet adapter in a USB-A port (not USB-C: it gives no power), then Set up the adapter.`});
    return h('div', {class: 'banner warn', style: {marginTop: '10px'}, text: 'Hand powered (light on its back)? Cable in the robot computer\'s Ethernet port, or in a USB adapter?'});
  },
  adapter() { act(async () => { const r = await api('/api/hand/adapter', {target: this.tid()}); openLog(r.job.id); flash('Setting up the USB adapter …'); }); },
  async hello(s) {
    const t = targetInfo(this.tid());
    const ok = await confirmReal(`Move the ${s} hand?`, [`${t.label} · ${SIDE_TITLE[s].toLowerCase()} · index finger base joint 9° and back, twice · 0.5 A`,
      'The hand in the air or on its back, fingers free, someone watching it.'], 'Move it');
    if (ok) act(async () => { const r = await api('/api/hand/hello', {target: t.id, side: s, confirm: true}); openLog(r.job.id); });
  },
  paintReady(hs, l, busy) {
    const R = hs.right || {}, L = hs.left || {}, both = R.up && L.up;
    const waved = s => App.state.jobs.find(j => j.kind === 'hello' && j.meta.side === s && j.state === 'done');
    const joints = [R, L].map(x => x.joints);
    const fw = [R.firmware, L.firmware];
    clear(this.ready).append(
      checkrow(both ? 'ok' : (R.up || L.up) ? 'warn' : 'off', 'Both hands answer',
        ['right', 'left'].map(s => s + ': ' + (hs[s] && hs[s].up ? 'yes' + (hs[s].dev ? ', ' + portName(hs[s].dev) : '') : hs[s] && hs[s].up === false ? 'no' : 'not checked')).join(' · ')),
      checkrow(joints.every(j => j === 20) ? 'ok' : joints.some(j => j != null && j < 20) ? 'bad' : 'off', '20 of 20 joints online on each',
        joints.map((j, i) => ['right', 'left'][i] + ': ' + (j != null ? j + '/20' : 'not read')).join(' · '),
        both && joints.some(j => j == null) ? h('button', {class: 'pill', text: 'Read', onclick: () => this.info()}) : null),
      checkrow(fw[0] && fw[1] ? (fw[0] === fw[1] ? 'ok' : 'warn') : 'off', 'Same firmware', fw[0] && fw[1] ? (fw[0] === fw[1] ? fw[0] : `right ${fw[0]}, left ${fw[1]}`) : 'not read'),
      checkrow(waved('right') && waved('left') ? 'ok' : 'off', 'Each hand moved one finger, in the air',
        ['right', 'left'].map(s => s + ': ' + (waved(s) ? 'done ' + ago(waved(s).ended) : 'not yet')).join(' · ')),
      h('div', {class: 'row', style: {marginTop: '8px'}},
        h('button', {class: 'pill primary', text: 'Play › Two hands', disabled: !both, onclick: () => { show('play'); App.pages.play.setMode('two'); }}),
        h('span', {class: 'subtle small', text: 'Two hands start together on one clock; each plays its own plan.'})));
  },
};
