"""Theme pipeline: MIDI melody -> fixed-hand fingering -> IK keyframes -> 1 kHz joint trajectory with per-finger
command lead -> MuJoCo playback -> onset F1 -> export (npz + Wuji .replay + MIDI of what the sim played).

usage (defaults = best mount from scripts/sweep_mount.py --approach front: hand from the player's side, fingertips pitched
25 deg down, flange 10 cm above the white key tops and 22 cm in front of the key hinge line (7 cm in front of the key fronts),
centred on D5; Mozart K.265 theme from FürElise piece 15):
  python scripts/make_theme.py --out out/theme_gain5 --gain 5
  python scripts/make_theme.py --out out/theme_gain1 --gain 1 --robust        # + mount/gain perturbation grid
  python scripts/make_theme.py --out out/theme_half --tempo 0.5 --calib out/calib.json --mount-z 0.092
"""
import argparse, json, os, struct, sys, time
import numpy as np
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from midi_io import read_notes, write_notes, note_name
import piano_core as pc

HERE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
ap = argparse.ArgumentParser()
ap.add_argument("--piece", default=os.path.join(HERE, "assets/furelise/15"))
ap.add_argument("--wuji", default=os.path.join(HERE, "assets/wuji-description"))
ap.add_argument("--out", default=os.path.join(HERE, "out/theme"))
ap.add_argument("--t-end", type=float, default=35.0); ap.add_argument("--min-pitch", type=int, default=71)
ap.add_argument("--tempo", type=float, default=1.0, help="0.5 = half speed")
ap.add_argument("--no-ornaments", action="store_true", help="drop notes < 100 ms after the previous melody note (trills/turn)")
ap.add_argument("--gain", type=float, default=5.0, help="x shipped MJCF actuator gains (real stiffness unknown until on-site sysid)")
ap.add_argument("--rev", default="hand2_2", choices=["hand2_2", "hand2_1"], help="2.2 = tactile fingertips; ask on site")
ap.add_argument("--approach", default="front", choices=["front", "back"], help="front = pianist-like (verified best); back = over the fallboard")
ap.add_argument("--theta", type=float, default=25.0); ap.add_argument("--mount-x", type=float, default=0.22)
ap.add_argument("--mount-z", type=float, default=0.10); ap.add_argument("--mount-dy", type=float, default=-pc.PITCH)
ap.add_argument("--hover", type=float, default=0.012); ap.add_argument("--press", type=float, default=-0.0085); ap.add_argument("--a5-extra", type=float, default=-0.0045)
ap.add_argument("--calib", default=None, help="calib.json from calibrate_keys.py: per-finger press_alpha")
ap.add_argument("--lead-iters", type=int, default=2); ap.add_argument("--tol", type=float, default=0.05)
ap.add_argument("--robust", action="store_true"); ap.add_argument("--workers", type=int, default=4)
A = ap.parse_args(); os.makedirs(A.out, exist_ok=True)
FINGERINGS = {"front": ({71: 0, 72: 0, 74: 1, 76: 2, 77: 3, 79: 4, 81: 4}, {0: 72, 1: 74, 2: 76, 3: 77, 4: 79}),   # thumb B4 C5, index D5, middle E5, ring F5, pinky G5 A5
              "back":  ({71: 4, 72: 4, 74: 3, 76: 2, 77: 1, 79: 0, 81: 0}, {4: 72, 3: 74, 2: 76, 1: 77, 0: 79})}   # mirrored: thumb on the treble side
FING, HOME = FINGERINGS[A.approach]
SIMKEYS = list(range(60, 85))                                     # C4..C6 is everything this hand can reach

def scene(gain=None, dy=0.0, dz=0.0, dth=0.0, keys=SIMKEYS):
    return pc.build_scene(A.wuji, theta=A.theta + dth, mount_x=A.mount_x, mount_z=A.mount_z + dz, mount_dy=A.mount_dy + dy,
                          gain=A.gain if gain is None else gain, keys=keys, approach=A.approach, rev=A.rev)

# ---- notes ----
notes = [n for n in read_notes(os.path.join(A.piece, "midi.mid")) if n["on"] < A.t_end and n["pitch"] >= A.min_pitch]
if A.no_ornaments:
    keep = [notes[0]] + [b for a, b in zip(notes, notes[1:]) if b["on"] - a["on"] >= 0.1]; notes = keep
t0 = notes[0]["on"]
notes = [dict(on=(n["on"] - t0) / A.tempo, off=(n["off"] - t0) / A.tempo, pitch=n["pitch"], vel=n["vel"]) for n in notes]
bad = sorted({n["pitch"] for n in notes if n["pitch"] not in FING})
assert not bad, f"no finger for {[note_name(b) for b in bad]}; extend FING"
print(f"{len(notes)} melody notes, {notes[-1]['off']:.1f} s at tempo x{A.tempo}, keys {sorted({note_name(n['pitch']) for n in notes}, key=lambda s: pc.white_index([n['pitch'] for n in notes if note_name(n['pitch'])==s][0]))}")

# ---- keyframes (IK) ----
t_ = time.time(); kfr = pc.Keyframer(scene())
pairs = sorted({(FING[n["pitch"]], n["pitch"]) for n in notes} | {(f, m) for f, m in HOME.items()})
kf = kfr.keyframes(pairs, hover_h=A.hover, press_d=A.press, press_overrides={(FING[81], 81): A.press + A.a5_extra})   # finger stretched to A5 presses flat
print(f"IK keyframes ({time.time()-t_:.0f} s), error mm [hover, lift, press]:", {f"{pc.SHORT[f]}-{note_name(m)}": v["err_mm"] for (f, m), v in kf.items()})
alpha = [1.0] * 5
if A.calib:
    c = json.load(open(A.calib)); alpha = [float(c["press_alpha"].get(pc.SHORT[f], 1.0)) for f in range(5)]; print("press_alpha from calib:", alpha)

def run(lead, xml=None, keys=SIMKEYS):
    t, q, log = pc.build_trajectory(notes, FING, kf, HOME, lead, press_alpha=alpha)
    ts, frac, ks, kmax = pc.simulate(xml or scene(keys=keys), t, q)
    det = pc.detect_onsets(ts, frac, ks, kmax)
    det = [dict(t=e["t"] - 1.5, pitch=e["pitch"]) for e in det]          # trajectory has 1.5 s pre-roll
    return t, q, log, det

# ---- lead calibration: command lead per finger = median measured command->activation delay ----
lead = [0.0] * 5
for it in range(A.lead_iters + 1):
    t_ = time.time(); t, q, log, det = run(lead); s = pc.score(det, notes, tol=0.15 if it < A.lead_iters else A.tol)
    per = {f: [d for n, d in s["matched"] if FING[n["pitch"]] == f] for f in range(5)}
    print(f"iter {it}: lead ms {[round(l*1e3) for l in lead]} -> F1 {s['f1']:.3f} ({s['n_matched']}/{s['n_target']} matched, {s['n_detected']} detected) "
          f"timing median {s['timing_ms']['median']:+.0f} ms, |90%| {s['timing_ms']['p90_abs']:.0f} ms  [{time.time()-t_:.0f} s]")
    if it < A.lead_iters:
        lead = [max(0.0, lead[f] + float(np.median(per[f]))) if per[f] else lead[f] + 0.05 for f in range(5)]
final = pc.score(det, notes, tol=A.tol)
print("missed:", [(note_name(n["pitch"]), round(n["on"], 2), pc.SHORT[FING[n["pitch"]]]) for n in final["missed"]])
print("extra :", [(note_name(e["pitch"]), round(e["t"], 2)) for e in final["extra"]])

# ---- export ----
np.savez_compressed(os.path.join(A.out, "theme_q_1khz.npz"), t=t, q=q.astype(np.float32), lead=np.array(lead), gain=A.gain,
                    mount=np.array([A.mount_x, A.mount_dy, A.mount_z, A.theta]), approach=A.approach, rev=A.rev, press_alpha=np.array(alpha),
                    home_hover=np.concatenate([kf[(f, HOME[f])]["hover"] for f in range(5)]),
                    notes=np.array([[n["on"], n["off"], n["pitch"]] for n in notes]), pre_roll=1.5, tempo=A.tempo,
                    fing=np.array(sorted(FING.items())), home=np.array(sorted(HOME.items())),
                    kf_pairs=np.array(sorted(kf)), kf_hover=np.array([kf[k]['hover'] for k in sorted(kf)]), kf_press=np.array([kf[k]['press'] for k in sorted(kf)]))
with open(os.path.join(A.out, "right.replay"), "wb") as fh:                      # Wuji SDK replay container (WJH2RPL v1)
    fh.write(struct.pack("<8sHBBI", b"WJH2RPL\0", 1, 1, 20, len(t)))
    for ti, qi in zip(t, q.astype(np.float32)): fh.write(struct.pack("<I20f", int(round(ti * 1e6)), *qi))
write_notes(os.path.join(A.out, "target.mid"), [dict(on=n["on"] + 1.5, off=n["off"] + 1.5, pitch=n["pitch"], vel=70) for n in notes])
write_notes(os.path.join(A.out, "sim_played.mid"), [dict(on=e["t"] + 1.5, off=e["t"] + 1.7, pitch=e["pitch"], vel=70) for e in det])
pc.write_scene(os.path.join(A.out, "scene.xml"), scene(keys=range(21, 109)))
rep = dict(gain=A.gain, tempo=A.tempo, approach=A.approach, mount=dict(x=A.mount_x, dy=A.mount_dy, z=A.mount_z, theta=A.theta), lead_ms=[round(l * 1e3, 1) for l in lead],
           f1=final["f1"], precision=final["precision"], recall=final["recall"], matched=final["n_matched"], targets=final["n_target"],
           detected=final["n_detected"], timing_ms=final["timing_ms"], tol_ms=A.tol * 1e3,
           missed=[(note_name(n["pitch"]), round(n["on"], 3)) for n in final["missed"]], extra=[(note_name(e["pitch"]), round(e["t"], 3)) for e in final["extra"]],
           ik_err_mm={f"{pc.SHORT[f]}-{note_name(m)}": v["err_mm"] for (f, m), v in kf.items()}, qmin=q.min(0).round(3).tolist(), qmax=q.max(0).round(3).tolist(),
           max_joint_speed_rad_s=float(np.abs(np.diff(q, axis=0)).max() * 1000))

# ---- robustness: same trajectory, perturbed world ----
def robust_case(args):
    name, kw = args
    ts, frac, ks, kmax = pc.simulate(scene(**kw), t, q); d = [dict(t=e["t"] - 1.5, pitch=e["pitch"]) for e in pc.detect_onsets(ts, frac, ks, kmax)]
    s = pc.score(d, notes, tol=A.tol); return name, round(s["f1"], 3), s["n_matched"], len(s["extra"]), round(s["timing_ms"]["median"])
if A.robust:
    cases = [("nominal", {})] + [(f"side {d*1e3:+.0f} mm", dict(dy=d)) for d in (-0.006, -0.003, 0.003, 0.006)] \
          + [(f"height {d*1e3:+.0f} mm", dict(dz=d)) for d in (-0.003, -0.0015, 0.0015, 0.003)] \
          + [(f"pitch {d:+.0f} deg", dict(dth=d)) for d in (-3, 3)] + [(f"gain x{g:g}", dict(gain=g)) for g in (1, 2.5, 10) if g != A.gain]
    from multiprocessing import Pool
    t_ = time.time()
    with Pool(A.workers) as pool: R = pool.map(robust_case, cases)
    print(f"robustness ({time.time()-t_:.0f} s): case | F1 | matched/{len(notes)} | wrong-key/extra | timing median ms")
    for r in R: print("  ", " | ".join(str(x) for x in r))
    rep["robust"] = R
json.dump(rep, open(os.path.join(A.out, "report.json"), "w"), indent=1)
print("max joint command speed %.1f rad/s; wrote" % rep["max_joint_speed_rad_s"], A.out)
