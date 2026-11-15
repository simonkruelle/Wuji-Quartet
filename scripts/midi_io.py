"""Dependency-free MIDI helpers: parse .mid (note on/off with tempo map), write .mid, raw MIDI byte stream parsing."""
import re
import struct

def _varlen(b, q):
    v = 0
    while True:
        c = b[q]; q += 1; v = (v << 7) | (c & 0x7F)
        if not c & 0x80: return v, q

GM = ["piano", "piano", "piano", "piano", "electric piano", "electric piano", "harpsichord", "clavinet", "celesta", "glockenspiel", "music box", "vibraphone",
      "marimba", "xylophone", "bells", "dulcimer", "organ", "organ", "organ", "church organ", "organ", "accordion", "harmonica", "accordion"] + \
     ["guitar"] * 8 + ["bass"] * 8 + ["violin", "viola", "cello", "contrabass", "strings", "strings", "harp", "timpani"] + ["strings"] * 4 + ["choir", "voice", "voice", "orchestra hit"] + \
     ["trumpet", "trombone", "tuba", "muted trumpet", "horn", "brass", "brass", "brass", "soprano sax", "alto sax", "tenor sax", "baritone sax", "oboe", "cor anglais",
      "bassoon", "clarinet", "piccolo", "flute", "recorder", "pan flute", "bottle", "shakuhachi", "whistle", "ocarina"] + ["synth lead"] * 8 + ["synth pad"] * 8 + \
     ["effects"] * 8 + ["sitar", "banjo", "shamisen", "koto", "kalimba", "bagpipe", "fiddle", "shanai"] + ["percussion"] * 8 + ["effects"] * 8


def read_notes(path, with_meta=False):
    """-> list of dict(on, off, pitch, vel, track, ch) in seconds, sorted by onset (all tracks/channels merged).
    with_meta: also return {track: dict(name, programs)}. Drum notes (channel 10) are kept here, marked ch == 9."""
    b = open(path, "rb").read(); assert b[:4] == b"MThd", "not a MIDI file"
    fmt, ntr, div = struct.unpack(">HHH", b[8:14]); p = 14; ev = []; tempos = []; meta = {}
    for trk in range(ntr):
        assert b[p:p + 4] == b"MTrk"; ln = struct.unpack(">I", b[p + 4:p + 8])[0]; q = p + 8; end = q + ln; tick = 0; status = 0
        while q < end:
            dt, q = _varlen(b, q); tick += dt; c = b[q]
            if c & 0x80: status = c; q += 1
            if status == 0xFF:
                typ = b[q]; q += 1; l, q = _varlen(b, q)
                if typ == 0x51: tempos.append((tick, int.from_bytes(b[q:q + 3], "big")))
                elif typ in (0x03, 0x04) and not meta.get(trk, {}).get("name"):
                    meta.setdefault(trk, dict(name="", programs=set()))["name"] = b[q:q + l].decode("latin-1", "replace").strip()
                q += l
            elif status in (0xF0, 0xF7):
                l, q = _varlen(b, q); q += l
            else:
                hi = status & 0xF0; ch = status & 0x0F; nd = 1 if hi in (0xC0, 0xD0) else 2; d = b[q:q + nd]; q += nd
                if hi == 0x90 and d[1] > 0: ev.append((tick, 1, d[0], d[1], trk, ch))
                elif hi == 0x80 or (hi == 0x90 and d[1] == 0): ev.append((tick, 0, d[0], 0, trk, ch))
                elif hi == 0xC0 and ch != 9: meta.setdefault(trk, dict(name="", programs=set()))["programs"].add(d[0]); meta.setdefault(("ch", trk, ch), d[0])
        p = end
    tempos = sorted(tempos) or [(0, 500000)]
    def t2s(tk):
        s = 0.0; lt, lu = 0, tempos[0][1]
        for tt, us in tempos:
            if tt >= tk: break
            s += (tt - lt) * lu / 1e6 / div; lt, lu = tt, us
        return s + (tk - lt) * lu / 1e6 / div
    open_notes = {}; notes = []                                        # one open note per (track, channel, pitch)
    for tick, on, pitch, vel, trk, ch in sorted(ev, key=lambda e: (e[0], e[1])):
        t = t2s(tick); key = (trk, ch, pitch)
        if on:
            if key in open_notes: o = open_notes.pop(key); notes.append(dict(on=o[0], off=t, pitch=pitch, vel=o[1], track=trk, ch=ch))
            open_notes[key] = (t, vel)
        elif key in open_notes:
            o = open_notes.pop(key); notes.append(dict(on=o[0], off=t, pitch=pitch, vel=o[1], track=trk, ch=ch))
    for (trk, ch, pitch), o in open_notes.items(): notes.append(dict(on=o[0], off=o[0] + 0.5, pitch=pitch, vel=o[1], track=trk, ch=ch))
    notes = sorted(notes, key=lambda n: (n["on"], n["pitch"]))
    return (notes, meta) if with_meta else notes


def part_of(n):
    """A part = one instrument: a track, or a channel of a one-track file. 'track:channel'."""
    return f"{n['track']}:{n['ch']}"


TUNE_NAMES = re.compile(r"vocal|voice|vox|melod|lead|solo|sing|gesang|stimme|tune", re.I)


def tracks(path):
    """Per part with notes (drums left out), with a guess which one carries the tune:
    dict(part, name, instrument, n, lo, hi, median, together, tune_score)."""
    notes, meta = read_notes(path, with_meta=True)
    notes = [n for n in notes if n["ch"] != 9]
    if not notes:
        return []
    T = max(n["off"] for n in notes)
    by = {}
    for n in notes:
        by.setdefault((n["track"], n["ch"]), []).append(n)
    out = []
    for (trk, ch), ns in sorted(by.items()):
        m = meta.get(trk, {})
        pr = [meta[("ch", trk, ch)]] if ("ch", trk, ch) in meta else sorted(m.get("programs") or [])
        ons = sorted({round(n["on"], 2) for n in ns})
        top = {}
        for n in ns:
            k = round(n["on"], 2)
            top[k] = max(top.get(k, 0), n["pitch"])
        line = [top[k] for k in ons]
        iv = [abs(b - a) for a, b in zip(line, line[1:])]
        step = sum(1 for v in iv if 0 < v <= 2) / max(1, len(iv))          # tunes move mostly by step
        cover = len({int(n["on"] // 4) for n in ns}) / max(1.0, T / 4)    # and are there for most of the song
        ps = sorted(n["pitch"] for n in ns)
        mono = len(ons) / len(ns)
        inst = GM[pr[0]] if pr else "piano"
        score = 0.0
        if mono >= 0.9 and 57 <= ps[len(ps) // 2] <= 84 and len(ns) >= 30 and inst not in ("bass", "timpani", "percussion", "effects", "synth pad"):
            score = step * cover * (3.0 if TUNE_NAMES.search(m.get("name", "")) else 1.0)
        out.append(dict(part=f"{trk}:{ch}", name=m.get("name", ""), instrument=inst, n=len(ns), lo=ps[0], hi=ps[-1], median=ps[len(ps) // 2],
                        together=round(len(ns) / max(1, len(ons)), 2), tune_score=round(score, 3)))
    return out


def guess_tune(parts):
    """The part most likely to carry the tune, or None (then the highest line of everything is used)."""
    best = max(parts, key=lambda p: p["tune_score"], default=None)
    return best["part"] if best and best["tune_score"] > 0.15 and len(parts) > 1 else None


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

def write_parts(path, parts, bpm=120, div=480):
    """parts: [dict(name, notes=[dict(on, off, pitch, vel)])] in seconds -> format-1 .mid, one named track and channel per part
    (channel 10, the drums, is skipped). The first part is meant to be the tune."""
    us = int(60e6 / bpm)
    def vl(v):
        out = [v & 0x7F]; v >>= 7
        while v: out.append(0x80 | (v & 0x7F)); v >>= 7
        return bytes(reversed(out))
    def chunk(data): return b"MTrk" + struct.pack(">I", len(data)) + bytes(data)
    tracks = [chunk(b"\x00\xFF\x51\x03" + us.to_bytes(3, "big") + b"\x00\xFF\x2F\x00")]
    for i, part in enumerate(parts):
        ch = i if i < 9 else i + 1
        name = part.get("name", f"part {i + 1}").encode("latin-1", "replace")[:60]
        trk = bytearray(b"\x00\xFF\x03" + vl(len(name)) + name + bytes([0, 0xC0 | ch, 0]))
        evs = sorted([(n["on"], 1, n["pitch"], n.get("vel", 64)) for n in part["notes"]] + [(n["off"], 0, n["pitch"], 0) for n in part["notes"]],
                     key=lambda e: (e[0], e[1]))
        last = 0
        for t, on, pitch, vel in evs:
            tick = int(round(t * div * 1e6 / us)); trk += vl(max(0, tick - last)); last = max(last, tick)
            trk += bytes([(0x90 if on else 0x80) | ch, pitch, vel if on else 0])
        trk += b"\x00\xFF\x2F\x00"
        tracks.append(chunk(trk))
    open(path, "wb").write(b"MThd" + struct.pack(">IHHH", 6, 1, len(tracks), div) + b"".join(tracks))


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
