"""Mount sweep with the whole theme as objective (F1 after one lead-calibration pass).
usage: sweep_mount.py [--gain 5] [--workers 6] [--quick]"""
import argparse, itertools, json, os, sys, time
import numpy as np
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import piano_core as pc
from midi_io import read_notes, note_name
HERE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
ap = argparse.ArgumentParser(); ap.add_argument("--gain", type=float, default=5.0); ap.add_argument("--workers", type=int, default=6)
ap.add_argument("--abd-cost", type=float, default=1.5e-2); ap.add_argument("--fingering", default="A", choices=["A", "B"]); ap.add_argument("--grid", default="coarse", choices=["coarse", "fine"]); ap.add_argument("--approach", default="front", choices=["front", "back"]); ap.add_argument("--out", default=None); A = ap.parse_args(); A.out = A.out or os.path.join(HERE, f'out/sweep_{A.approach}_gain{A.gain:g}.json')
WUJI = os.path.join(HERE, "assets/wuji-description")
FINGERINGS = {"front": ({71: 0, 72: 0, 74: 1, 76: 2, 77: 3, 79: 4, 81: 4}, {0: 72, 1: 74, 2: 76, 3: 77, 4: 79}),   # thumb on the bass side
              "back":  ({71: 4, 72: 4, 74: 3, 76: 2, 77: 1, 79: 0, 81: 0}, {4: 72, 3: 74, 2: 76, 1: 77, 0: 79})}   # thumb on the treble side
FING, HOME = FINGERINGS[A.approach]; STRETCH = {(FING[81], 81): -0.0085 - 0.0045}
KEYS = list(range(60, 85))
notes = [n for n in read_notes(os.path.join(HERE, "assets/furelise/15/midi.mid")) if n["on"] < 35 and n["pitch"] >= 71]
t0 = notes[0]["on"]; notes = [dict(on=n["on"] - t0, off=n["off"] - t0, pitch=n["pitch"]) for n in notes]
def case(c):
    th, z, x, dy = c
    try:
        xml = pc.build_scene(WUJI, theta=th, mount_x=x, mount_z=z, mount_dy=dy, gain=A.gain, keys=KEYS, approach=A.approach)
        kf = pc.Keyframer(xml, abd_cost=A.abd_cost).keyframes(sorted({(FING[n["pitch"]], n["pitch"]) for n in notes} | set(HOME.items())), press_overrides=STRETCH)
        lead = [0.0] * 5
        for it in range(2):
            t, q, _ = pc.build_trajectory(notes, FING, kf, HOME, lead)
            ts, fr, ks, km = pc.simulate(xml, t, q); det = [dict(t=e["t"] - 1.5, pitch=e["pitch"]) for e in pc.detect_onsets(ts, fr, ks, km)]
            s = pc.score(det, notes, tol=0.15 if it == 0 else 0.05)
            if it == 0:
                for f in range(5):
                    d = [dd for n, dd in s["matched"] if FING[n["pitch"]] == f]; lead[f] = float(np.median(d)) if d else 0.06
        miss = {}
        for n in s["missed"]: miss[pc.SHORT[FING[n["pitch"]]]] = miss.get(pc.SHORT[FING[n["pitch"]]], 0) + 1
        return dict(theta=th, z=z, x=x, dy_keys=round(dy / pc.PITCH, 2), missed_notes=[(note_name(n['pitch']), round(n['on'], 2)) for n in s['missed']], f1=round(s["f1"], 3), matched=s["n_matched"], extra=len(s["extra"]),
                    ik_press_max_mm=max(v["err_mm"][2] for v in kf.values()), hover_min_mm=min(v["hover_mm"] for v in kf.values()), missed_by_finger=miss, lead_ms=[round(l * 1e3) for l in lead])
    except Exception as e:
        return dict(theta=th, z=z, x=x, dy_keys=round(dy / pc.PITCH, 2), f1=-1, err=str(e)[:200])
P_ = pc.PITCH
GRIDS = {"front": list(itertools.product([20, 25, 30], [0.09, 0.10, 0.11], [0.20, 0.22, 0.24], [-P_, -0.5 * P_, 0.0, 0.5 * P_])),
         "back": list(itertools.product([25, 30], [0.10, 0.11], [0.0, 0.01, 0.02], [-0.5 * P_, 0.0, 0.5 * P_, P_]))}
grid = GRIDS[A.approach]
from multiprocessing import Pool
t_ = time.time()
with Pool(A.workers) as pool: R = pool.map(case, grid, chunksize=1)
R.sort(key=lambda r: (-r["f1"], r["extra"] if "extra" in r else 99))
json.dump(R, open(A.out, "w"), indent=1)
print(f"{A.approach}: {len(R)} mounts in {time.time()-t_:.0f} s, gain x{A.gain:g}, abd_cost {A.abd_cost}. F1 histogram:", np.histogram([r['f1'] for r in R], bins=[-1.01, 0, 0.5, 0.7, 0.8, 0.9, 0.95, 1.01])[0].tolist(), "(bins <0, <.5, <.7, <.8, <.9, <.95, <=1)")
for r in R[:6]: print({k: v for k, v in r.items() if k != 'missed_notes'})
print('best missed:', R[0].get('missed_notes'))
