import sys, io, os, pickle, struct, urllib.request, zipfile
URL = "https://huggingface.co/datasets/rcwang/for_elise/resolve/main/dataset.zip"
OUT = sys.argv[1]; CAP = int(sys.argv[2]) if len(sys.argv) > 2 else 700_000_000
CANDIDATES = [15, 23, 46, 57, 86, 87, 90, 93, 105, 106, 107, 115]

class RangeFile(io.RawIOBase):
    def __init__(self, url, block=8 << 20):
        self.block, self.pos, self.cache = block, 0, {}
        with urllib.request.urlopen(urllib.request.Request(url, method="HEAD")) as r:
            self.size, self.final = int(r.headers["Content-Length"]), r.geturl()
        self.nreq = 0
    def readable(self): return True
    def seekable(self): return True
    def tell(self): return self.pos
    def seek(self, off, whence=0):
        self.pos = {0: off, 1: self.pos + off, 2: self.size + off}[whence]; return self.pos
    def _fetch(self, s, e):
        self.nreq += 1
        with urllib.request.urlopen(urllib.request.Request(self.final, headers={"Range": f"bytes={s}-{e}"})) as r:
            return r.read()
    def read(self, n=-1):
        n = self.size - self.pos if n < 0 else min(n, self.size - self.pos)
        out = bytearray()
        while n > 0:
            b = self.pos // self.block
            if b not in self.cache:
                s = b * self.block; self.cache[b] = self._fetch(s, min(s + self.block, self.size) - 1)
                if len(self.cache) > 6: self.cache.pop(next(iter(self.cache)))
            o = self.pos - b * self.block; chunk = self.cache[b][o:o + n]
            if not chunk: break
            out += chunk; self.pos += len(chunk); n -= len(chunk)
        return bytes(out)

f = RangeFile(URL); print(f"zip size {f.size/1e9:.1f} GB, final host {f.final.split('/')[2]}")
zf = zipfile.ZipFile(f); infos = zf.infolist(); print(f"members: {len(infos)}  (requests so far {f.nreq})")
print("first names:", [i.filename for i in infos[:8]])
pieces = {}
for i in infos:
    parts = i.filename.split("/")
    if len(parts) >= 3 and parts[1].isdigit() and parts[2] in ("motion.pkl", "midi.mid"):
        pieces.setdefault(int(parts[1]), {})[parts[2]] = i
print("piece_id | motion.pkl MB | midi KB")
for pid in CANDIDATES:
    d = pieces.get(pid, {}); m = d.get("motion.pkl"); k = d.get("midi.mid")
    print(f"{pid:4d} | {m.file_size/1e6 if m else -1:8.1f} | {k.file_size/1e3 if k else -1:6.1f}")
sizes = sorted((d["motion.pkl"].file_size, pid) for pid, d in pieces.items() if "motion.pkl" in d)
print("smallest 5 pieces (MB,id):", [(round(s/1e6), p) for s, p in sizes[:5]])
# pick: piece 15 (Mozart Twinkle variations) if under cap, else the smallest candidate under cap
pick = None
for pid in [15] + CANDIDATES:
    m = pieces.get(pid, {}).get("motion.pkl")
    if m and m.file_size <= CAP: pick = pid; break
if pick is None: pick = sizes[0][1]
print("PICK", pick)
os.makedirs(os.path.join(OUT, str(pick)), exist_ok=True)
for name in ("midi.mid", "motion.pkl"):
    info = pieces[pick][name]
    with zf.open(info) as src, open(os.path.join(OUT, str(pick), name), "wb") as dst:
        while True:
            chunk = src.read(16 << 20)
            if not chunk: break
            dst.write(chunk)
print(f"downloaded piece {pick}; total range requests {f.nreq}")
# also grab the tiny MIDI for every candidate
for pid in CANDIDATES:
    k = pieces.get(pid, {}).get("midi.mid")
    if k:
        os.makedirs(os.path.join(OUT, str(pid)), exist_ok=True)
        with zf.open(k) as src, open(os.path.join(OUT, str(pid), "midi.mid"), "wb") as dst: dst.write(src.read())
print("midis saved; requests", f.nreq)

# --- inspect motion.pkl with a restricted unpickler ---
import numpy as np
ALLOWED = {("numpy.core.multiarray", "_reconstruct"), ("numpy._core.multiarray", "_reconstruct"), ("numpy", "ndarray"), ("numpy", "dtype"),
           ("numpy.core.multiarray", "scalar"), ("numpy._core.multiarray", "scalar"), ("collections", "OrderedDict"), ("numpy.core.numeric", "_frombuffer"), ("numpy._core.numeric", "_frombuffer")}
class SafeUnpickler(pickle.Unpickler):
    def find_class(self, module, name):
        if (module, name) in ALLOWED: return super().find_class(module, name)
        raise pickle.UnpicklingError(f"blocked {module}.{name}")
with open(os.path.join(OUT, str(pick), "motion.pkl"), "rb") as fh: d = SafeUnpickler(fh).load()
def show(x, pre=""):
    if isinstance(x, dict):
        for k, v in x.items(): show(v, pre + str(k) + "/")
    elif hasattr(x, "shape"): print(f"  {pre:40s} {x.shape} {x.dtype}")
    else: print(f"  {pre:40s} {type(x).__name__} {x if isinstance(x,(int,float,str)) else ''}")
show(d)
J = d["right"]["joints"]; N = J.shape[0]; print(f"frames {N}  -> {N/59.94:.1f} s at 59.94 fps")
j0 = J[N//2]; dist = np.linalg.norm(j0 - j0[0], axis=1)
print("frame mid: dist from joint0 (wrist?) per index, mm:", np.round(dist*1000).astype(int).tolist())
# chain lengths assuming mediapipe order (wrist, thumb1-4, index5-8, middle9-12, ring13-16, pinky17-20)
for name, idx in [("thumb", [1,2,3,4]), ("index", [5,6,7,8]), ("middle", [9,10,11,12]), ("ring", [13,14,15,16]), ("pinky", [17,18,19,20])]:
    segs = [np.linalg.norm(j0[idx[i+1]] - j0[idx[i]]) for i in range(3)]
    print(f"  if mediapipe order: {name:6s} mcp->tip segs mm {[round(s*1000) for s in segs]}")
# MANO order guess (wrist, index 1-3, middle 4-6, pinky 7-9, ring 10-12, thumb 13-15, tips 16-20)
print("  z range of all joints over the piece (m):", float(J[:,:,2].min()), float(J[:,:,2].max()), " x range:", float(J[:,:,0].min()), float(J[:,:,0].max()))

# --- minimal MIDI note-on parser ---
def parse_midi(path, maxnotes=24):
    b = open(path, "rb").read(); assert b[:4] == b"MThd"
    fmt, ntr, div = struct.unpack(">HHH", b[8:14]); p = 14; notes = []; tempos = []
    for t in range(ntr):
        assert b[p:p+4] == b"MTrk"; ln = struct.unpack(">I", b[p+4:p+8])[0]; q = p + 8; end = q + ln; tick = 0; status = 0
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
                hi = status & 0xF0; nd = 1 if hi in (0xC0, 0xD0) else 2; data = b[q:q+nd]; q += nd
                if hi == 0x90 and data[1] > 0: notes.append((tick, data[0], data[1]))
                elif hi in (0x80, 0x90): notes.append((tick, data[0], 0))
        p = end
    tempos = sorted(tempos) or [(0, 500000)]
    def t2s(tk):
        s = 0.0; last_t, last_us = 0, tempos[0][1]
        for tt, us in tempos:
            if tt >= tk: break
            s += (tt - last_t) * last_us / 1e6 / div; last_t, last_us = tt, us
        return s + (tk - last_t) * last_us / 1e6 / div
    ons = [(t2s(tk), n, v) for tk, n, v in sorted(notes) if v > 0]
    return fmt, ntr, div, len(tempos), ons
names = {0:"C",1:"C#",2:"D",3:"D#",4:"E",5:"F",6:"F#",7:"G",8:"G#",9:"A",10:"A#",11:"B"}
fmt, ntr, div, nt, ons = parse_midi(os.path.join(OUT, str(pick), "midi.mid"))
print(f"MIDI fmt {fmt} tracks {ntr} div {div} tempo events {nt} note-ons {len(ons)} duration {ons[-1][0]:.1f} s")
print("first 24 note-ons (t s, note, vel):", [(round(t,2), f"{names[n%12]}{n//12-1}", v) for t, n, v in ons[:24]])
lo = min(n for _, n, _ in ons); hi = max(n for _, n, _ in ons); print(f"pitch range {names[lo%12]}{lo//12-1}..{names[hi%12]}{hi//12-1}")
