"""On-site key calibration: each finger slowly presses its home key (hover -> press -> deeper) until the keyboard
reports a note (MIDI) or you hit Enter (--manual). Gives per-finger depth (press_alpha) and checks it hit the RIGHT key.

  python scripts/calibrate_keys.py out/theme_gain5/theme_q_1khz.npz --midi-dev /dev/snd/midiC1D0
  python scripts/calibrate_keys.py out/theme_gain5/theme_q_1khz.npz --manual          # listen, press Enter on the sound
then: python scripts/make_theme.py --gain <g> --calib out/theme_gain5/calib.json --out out/theme_cal"""
import argparse, json, os, sys, threading, time
import numpy as np
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import wuji_hw as hw
from midi_io import note_name
ap = argparse.ArgumentParser(); ap.add_argument("plan"); ap.add_argument("--midi-dev", default=None); ap.add_argument("--manual", action="store_true")
ap.add_argument("--fingers", default="thumb,index,middle,ring,pinky"); ap.add_argument("--alpha-max", type=float, default=1.6); ap.add_argument("--speed", type=float, default=0.25, help="alpha per second")
ap.add_argument("--margin", type=float, default=0.15, help="alpha past the first sound; 0.15 ~ 3 mm deeper. Sim: 0.3 deeper starts hitting neighbour keys"); ap.add_argument("--effort", type=float, default=0.6); ap.add_argument("--kp", type=float, default=3.0); ap.add_argument("--kd", type=float, default=0.05)
ap.add_argument("--mode", default="mit", choices=["mit", "position"]); ap.add_argument("--dry-run", action="store_true"); A = ap.parse_args()
Z = np.load(A.plan); assert "kf_pairs" in Z.files, "plan made before calibration support: re-run make_theme.py"
home_key = dict((int(f), int(m)) for f, m in Z["home"]); kf = {(int(f), int(m)): (h, p) for (f, m), h, p in zip(Z["kf_pairs"], Z["kf_hover"], Z["kf_press"])}
NAMES = ["thumb", "index", "middle", "ring", "pinky"]; home = np.asarray(Z["home_hover"], float)
midi = hw.MidiIn(A.midi_dev) if A.midi_dev else None
if not midi and not A.manual and not A.dry_run: raise SystemExit("give --midi-dev (see: ls /dev/snd/) or --manual")
enter = threading.Event()
if A.manual: threading.Thread(target=lambda: [enter.set() for _ in iter(sys.stdin.readline, "")], daemon=True).start()
res = {}
with hw.Session(mode=A.mode, kp=A.kp, kd=A.kd, effort=A.effort, dry_run=A.dry_run) as s:
    s.ramp_to(home, 2.0)
    for name in A.fingers.split(","):
        f = NAMES.index(name); m = home_key[f]; h, p = kf[(f, m)]; sl = slice(4 * f, 4 * f + 4)
        print(f"{name}: pressing {note_name(m)} slowly ... " + ("press Enter when it sounds" if A.manual else ""))
        enter.clear(); t_start = time.monotonic(); hit = None; a = 0.0
        while a < A.alpha_max:
            a = (time.monotonic() - t_start) * A.speed; q = home.copy(); q[sl] = h + a * (p - h); s.send(q); time.sleep(0.002)
            ons = midi.note_ons(t_start) if midi else []
            if ons: hit = dict(alpha=round(a, 3), pitch=ons[0]["pitch"], vel=ons[0]["vel"]); break
            if A.manual and enter.is_set(): hit = dict(alpha=round(a, 3), pitch=None); break
            if A.dry_run and not midi and not A.manual and a >= 0.9: hit = dict(alpha=round(a, 3), pitch=m); break
        st = s.states[-1]; s.ramp_to(home, 0.6)
        if hit is None: print(f"  {name}: NO note up to alpha {A.alpha_max} -> hand too high or key not under the finger"); res[name] = dict(alpha=None); continue
        hit["expected"] = m; hit["effort_A"] = np.round(st[3][sl], 2).tolist()
        ok = hit["pitch"] in (None, m); res[name] = hit
        msg = "OK" if ok else f"WRONG KEY {note_name(hit['pitch'])} (expected {note_name(m)}): shift the hand {'toward the treble' if hit['pitch'] < m else 'toward the bass'}"
        print(f"  {name}: note at alpha {hit['alpha']:.2f} ({'velocity ' + str(hit.get('vel')) if hit.get('vel') else 'manual'}) -> {msg}")
if midi: midi.close()
alpha = {n: float(np.clip(r["alpha"] + A.margin, 0.6, A.alpha_max)) for n, r in res.items() if r.get("alpha") is not None}
out = os.path.join(os.path.dirname(A.plan), "calib.json"); json.dump(dict(press_alpha=alpha, hits=res, plan=A.plan, margin=A.margin), open(out, "w"), indent=1)
print("press_alpha:", alpha, "->", out)
if alpha and max(alpha.values()) > 1.4: print("some fingers need > 1.4: hand mounted too high -> lower 2-3 mm and re-run")
if alpha and min(alpha.values()) < 0.8: print("some fingers sound early: hand mounted low -> raise 2 mm or keep (press_alpha handles it)")
