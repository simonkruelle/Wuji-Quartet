"""Dependency-free MIDI helpers: parse .mid (note on/off with tempo map), write .mid, raw MIDI byte stream parsing."""
import struct

def _varlen(b, q):
    v = 0
    while True:
        c = b[q]; q += 1; v = (v << 7) | (c & 0x7F)
        if not c & 0x80: return v, q

def read_notes(path):
    """-> list of dict(on, off, pitch, vel) in seconds, sorted by onset (all tracks/channels merged)."""
    b = open(path, "rb").read(); assert b[:4] == b"MThd", "not a MIDI file"
    fmt, ntr, div = struct.unpack(">HHH", b[8:14]); p = 14; ev = []; tempos = []
    for trk in range(ntr):
        assert b[p:p + 4] == b"MTrk"; ln = struct.unpack(">I", b[p + 4:p + 8])[0]; q = p + 8; end = q + ln; tick = 0; status = 0
        while q < end:
            dt, q = _varlen(b, q); tick += dt; c = b[q]
            if c & 0x80: status = c; q += 1
            if status == 0xFF:
                typ = b[q]; q += 1; l, q = _varlen(b, q)
                if typ == 0x51: tempos.append((tick, int.from_bytes(b[q:q + 3], "big")))
                q += l
            elif status in (0xF0, 0xF7):
                l, q = _varlen(b, q); q += l
            else:
                hi = status & 0xF0; nd = 1 if hi in (0xC0, 0xD0) else 2; d = b[q:q + nd]; q += nd
                if hi == 0x90 and d[1] > 0: ev.append((tick, 1, d[0], d[1], trk))
                elif hi == 0x80 or (hi == 0x90 and d[1] == 0): ev.append((tick, 0, d[0], 0, trk))
        p = end
    tempos = sorted(tempos) or [(0, 500000)]
    def t2s(tk):
        s = 0.0; lt, lu = 0, tempos[0][1]
        for tt, us in tempos:
            if tt >= tk: break
            s += (tt - lt) * lu / 1e6 / div; lt, lu = tt, us
        return s + (tk - lt) * lu / 1e6 / div
    open_notes = {}; notes = []
    for tick, on, pitch, vel, trk in sorted(ev, key=lambda e: (e[0], e[1])):
        t = t2s(tick)
        if on:
            if pitch in open_notes: o = open_notes.pop(pitch); notes.append(dict(on=o[0], off=t, pitch=pitch, vel=o[1], track=o[2]))
            open_notes[pitch] = (t, vel, trk)
        elif pitch in open_notes:
            o = open_notes.pop(pitch); notes.append(dict(on=o[0], off=t, pitch=pitch, vel=o[1], track=o[2]))
    for pitch, o in open_notes.items(): notes.append(dict(on=o[0], off=o[0] + 0.5, pitch=pitch, vel=o[1], track=o[2]))
    return sorted(notes, key=lambda n: (n["on"], n["pitch"]))

def write_notes(path, notes, bpm=120, div=480):
    """notes: list of dict(on, off, pitch, vel) in seconds -> type-0 .mid"""
    us = int(60e6 / bpm); evs = []
    for n in notes:
        evs.append((n["on"], 1, n["pitch"], n.get("vel", 64))); evs.append((n["off"], 0, n["pitch"], 0))
    evs.sort(key=lambda e: (e[0], e[1])); trk = bytearray(b"\x00\xFF\x51\x03" + us.to_bytes(3, "big")); last = 0
    def vl(v):
        out = [v & 0x7F]; v >>= 7
        while v: out.append(0x80 | (v & 0x7F)); v >>= 7
        return bytes(reversed(out))
    for t, on, pitch, vel in evs:
        tick = int(round(t * div * 1e6 / us)); trk += vl(max(0, tick - last)); last = max(last, tick)
        trk += bytes([0x90 if on else 0x80, pitch, vel if on else 0])
    trk += b"\x00\xFF\x2F\x00"
    open(path, "wb").write(b"MThd" + struct.pack(">IHHH", 6, 0, 1, div) + b"MTrk" + struct.pack(">I", len(trk)) + trk)

class RawMidiParser:
    """Feed raw MIDI bytes (e.g. from /dev/snd/midiC1D0) with a timestamp; collects note-ons. Handles running status."""
    def __init__(self): self.status = 0; self.buf = []; self.events = []
    def feed(self, data, t):
        for c in data:
            if c >= 0xF8: continue                      # realtime (clock, active sensing)
            if c & 0x80: self.status = c if c < 0xF0 else 0; self.buf = []; continue
            if not self.status: continue
            self.buf.append(c); hi = self.status & 0xF0; need = 1 if hi in (0xC0, 0xD0) else 2
            if len(self.buf) == need:
                if hi == 0x90 and self.buf[1] > 0: self.events.append(dict(t=t, pitch=self.buf[0], vel=self.buf[1], on=True))
                elif hi == 0x80 or (hi == 0x90 and self.buf[1] == 0): self.events.append(dict(t=t, pitch=self.buf[0], vel=0, on=False))
                self.buf = []

def note_name(m): return ["C", "C#", "D", "D#", "E", "F", "F#", "G", "G#", "A", "A#", "B"][m % 12] + str(m // 12 - 1)
