"""Theme length / density of a FürElise MIDI. usage: midi_stats.py <midi.mid>"""
import sys, struct
def parse(path):
    b = open(path, "rb").read(); fmt, ntr, div = struct.unpack(">HHH", b[8:14]); p = 14; notes = []; tempos = []
    for t in range(ntr):
        ln = struct.unpack(">I", b[p+4:p+8])[0]; q = p + 8; end = q + ln; tick = 0; status = 0
        while q < end:
            dt = 0
            while True:
                c = b[q]; q += 1; dt = (dt << 7) | (c & 0x7F)
                if not c & 0x80: break
            tick += dt; c = b[q]
            if c & 0x80: status = c; q += 1
            if status == 0xFF:
                typ = b[q]; q += 1; l = 0
                while True:
                    c2 = b[q]; q += 1; l = (l << 7) | (c2 & 0x7F)
                    if not c2 & 0x80: break
                if typ == 0x51: tempos.append((tick, int.from_bytes(b[q:q+3], "big")))
                q += l
            elif status in (0xF0, 0xF7):
                l = 0
                while True:
                    c2 = b[q]; q += 1; l = (l << 7) | (c2 & 0x7F)
                    if not c2 & 0x80: break
                q += l
            else:
                hi = status & 0xF0; nd = 1 if hi in (0xC0, 0xD0) else 2; d = b[q:q+nd]; q += nd
                if hi == 0x90 and d[1] > 0: notes.append((tick, d[0], d[1]))
        p = end
    tempos = sorted(tempos) or [(0, 500000)]
    def t2s(tk):
        s = 0.0; lt, lu = 0, tempos[0][1]
        for tt, us in tempos:
            if tt >= tk: break
            s += (tt - lt) * lu / 1e6 / div; lt, lu = tt, us
        return s + (tk - lt) * lu / 1e6 / div
    return sorted((t2s(tk), n, v) for tk, n, v in notes)
ons = parse(sys.argv[1]); T = ons[-1][0]
print(f"note-ons {len(ons)}, last onset {T:.1f} s, tempo: first bass/treble onsets {ons[0][0]:.2f} s")
# right hand ~ notes >= 60 (middle C); theme = until the first run of fast notes (IOI < 0.2 s) in the right hand
rh = [t for t, n, v in ons if n >= 60]; ioi = [b - a for a, b in zip(rh, rh[1:])]
fast = [i for i, d in enumerate(ioi) if 0.0 < d < 0.2]
run_start = None
for i in range(len(fast) - 8):
    if fast[i + 8] - fast[i] == 8: run_start = fast[i]; break
theme_end = rh[run_start] if run_start is not None else None
print(f"right-hand notes {len(rh)}; first sustained fast run (IOI<0.2 s) starts at {theme_end:.1f} s -> theme ~ {theme_end:.0f} s, {sum(1 for t in rh if t < theme_end)} right-hand notes, {sum(1 for t,n,v in ons if t < theme_end)} notes both hands")
# 10-s window note density across the piece
import math
W = 10; bins = [0] * (int(T // W) + 1)
for t, n, v in ons: bins[int(t // W)] += 1
print("notes per 10 s window:", bins)
