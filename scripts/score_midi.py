"""Score a recorded keyboard MIDI file (any recorder/DAW) against a plan's melody. Finds the time offset itself.
  python scripts/score_midi.py recording.mid out/theme_gain5/theme_q_1khz.npz [--tol 0.05] [--tempo 1.0]"""
import argparse, os, sys
import numpy as np
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from midi_io import read_notes, note_name
import piano_core as pc
ap = argparse.ArgumentParser(); ap.add_argument("mid"); ap.add_argument("plan"); ap.add_argument("--tol", type=float, default=0.05); ap.add_argument("--tempo", type=float, default=1.0); A = ap.parse_args()
Z = np.load(A.plan); target = [dict(on=on / A.tempo, pitch=int(p)) for on, off, p in Z["notes"]]
ev = [dict(t=n["on"], pitch=n["pitch"]) for n in read_notes(A.mid)]
first = ev[0]["t"] if ev else 0.0
best = max((pc.score(ev, target, tol=0.1, offset=first + o / 1000) for o in range(-2000, 2001, 10)), key=lambda r: (r["n_matched"], -abs(r["timing_ms"]["median"])))
r = max((pc.score(ev, target, tol=A.tol, offset=first + o / 1000) for o in range(-2000, 2001, 5)), key=lambda r: (r["n_matched"], -abs(r["timing_ms"]["median"])))
print(f"{len(ev)} notes recorded, {len(target)} in the plan: F1 {r['f1']:.3f} (tol {A.tol*1e3:.0f} ms), matched {r['n_matched']}, timing median {r['timing_ms']['median']:+.0f} ms, |90%| {r['timing_ms']['p90_abs']:.0f} ms")
print(f"with tol 100 ms: F1 {best['f1']:.3f}, matched {best['n_matched']}")
print("missed:", [(note_name(n["pitch"]), round(float(n["on"]), 2)) for n in r["missed"]]); print("extra :", [(note_name(e["pitch"]), round(float(e["t"] - first), 2)) for e in r["extra"]])
