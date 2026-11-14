"""Theme notes + how the human played them (FürElise). usage: analyze_theme.py <piece_dir> [t_end=35] [min_pitch=60]"""
import sys, os, pickle, json, numpy as np
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from midi_io import read_notes, note_name
d = sys.argv[1]; t_end = float(sys.argv[2]) if len(sys.argv) > 2 else 35.0; minp = int(sys.argv[3]) if len(sys.argv) > 3 else 71   # B4: melody only (K.265 left hand sits in the C4 octave)
notes = [n for n in read_notes(os.path.join(d, "midi.mid")) if n["on"] < t_end]
rh = [n for n in notes if n["pitch"] >= minp]; lh = [n for n in notes if n["pitch"] < minp]
print(f"theme (< {t_end:.0f} s): {len(notes)} notes, right hand (pitch >= {note_name(minp)}): {len(rh)}, left hand: {len(lh)}")
pc = {}
for n in rh: pc[n["pitch"]] = pc.get(n["pitch"], 0) + 1
print("right-hand pitches:", {note_name(k): v for k, v in sorted(pc.items())})
dur = np.array([n["off"] - n["on"] for n in rh]); ioi = np.diff([n["on"] for n in rh])
print(f"durations s: median {np.median(dur):.2f} min {dur.min():.2f} max {dur.max():.2f}; IOI median {np.median(ioi):.2f} min {ioi.min():.3f}")
chords = sum(1 for a, b in zip(rh, rh[1:]) if b["on"] - a["on"] < 0.03); print("right-hand simultaneous pairs (<30 ms):", chords)
print("melody:", " ".join(note_name(n["pitch"]) for n in rh[:30]), "...")
# --- human: FürElise motion, restricted unpickler ---
ALLOWED = {("numpy.core.multiarray", "_reconstruct"), ("numpy._core.multiarray", "_reconstruct"), ("numpy", "ndarray"), ("numpy", "dtype"), ("numpy.core.multiarray", "scalar"), ("numpy._core.multiarray", "scalar")}
class Safe(pickle.Unpickler):
    def find_class(self, m, n):
        if (m, n) in ALLOWED: return super().find_class(m, n)
        raise pickle.UnpicklingError(f"blocked {m}.{n}")
mp = os.path.join(d, "motion.pkl")
if not os.path.exists(mp): sys.exit(0)
with open(mp, "rb") as fh: mot = Safe(fh).load()
J = mot["right"]["joints"].astype(np.float64); FPS = 59.94; TIPS = [4, 8, 12, 16, 20]; FN = ["thumb", "index", "middle", "ring", "pinky"]
def fr(t): return min(int(round(t * FPS)), len(J) - 1)
# FürElise world frame: z is up (checked: lowest-tip fit gives 22.7 mm per white key with +z, < 9 mm for every other axis)
WHITE = lambda m: sum(1 for k in range(21, m) if k % 12 not in (1, 3, 6, 8, 10))
idx = np.array([WHITE(n["pitch"]) for n in rh], float); up = np.array([0, 0, 1.0]); A = np.c_[np.ones_like(idx), idx]
low = np.array([J[fr(n["on"]) + 2][TIPS][np.argmin(J[fr(n["on"]) + 2][TIPS][:, 2])] for n in rh])
for it in range(4):
    coef, *_ = np.linalg.lstsq(A, low, rcond=None); a, b = coef[0], coef[1]; kax = (b - (b @ up) * up); kax /= np.linalg.norm(kax)
    pred = A @ coef; fing = []; newlow = []
    for k, n in enumerate(rh):
        tips = J[fr(n["on"]) + 2][TIPS]; along = np.abs((tips - pred[k]) @ kax)        # distance along the keyboard only
        score = along + 0.5 * (tips[:, 2] - tips[:, 2].min())                       # tie-break: lower tip
        f = int(np.argmin(score)); fing.append(f); newlow.append(tips[f])
    low = np.array(newlow)
res = np.abs((low - pred) @ kax)
from collections import Counter
fmap = {}
for n, f in zip(rh, fing): fmap.setdefault(note_name(n["pitch"]), Counter())[FN[f]] += 1
print("human fingering per key:", {k: dict(v) for k, v in sorted(fmap.items(), key=lambda kv: WHITE([n['pitch'] for n in rh if note_name(n['pitch'])==kv[0]][0]))})
w = J[fr(rh[0]["on"]):fr(t_end), 0]; axis = kax
along = (w - w[0]) @ axis; hgt = w[:, 2] - w[0, 2]
p5, p95 = np.percentile(along, [5, 95]); h5, h95 = np.percentile(hgt, [5, 95])
print(f"human right wrist over the theme (5-95 pct): along keyboard {(p95-p5)*1000:.0f} mm, height {(h95-h5)*1000:.0f} mm (one white key = 23.5 mm)")
json.dump(dict(t_end=t_end, notes=rh, human_finger=[FN[f] for f in fing], key_pitch_mm=float(np.linalg.norm(b) * 1000), wrist_travel_mm=float((p95 - p5) * 1000)), open(os.path.join(d, "theme_analysis.json"), "w"), indent=1)
