"""Play a theme plan (make_theme.py npz) on the real Wuji Hand 2, wall-clock locked at 1 kHz.
Logs joint states, optionally records the keyboard's MIDI and scores it.

  python scripts/play_on_hand.py out/theme_gain5/theme_q_1khz.npz --dry-run                 # no hardware
  python scripts/play_on_hand.py out/theme_gain5/theme_q_1khz.npz --tempo 0.5 --fingers index --effort 0.5
  python scripts/play_on_hand.py out/theme_gain5/theme_q_1khz.npz --midi-dev /dev/snd/midiC1D0
  python scripts/play_on_hand.py ... --mode position --effort-scale 0.6                     # Position control (Beta, fw >= 3.0.0)
Ctrl-C at any time: stops streaming and disables the hand."""
import argparse, json, os, sys, time
import numpy as np
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import wuji_hw as hw
from midi_io import write_notes, note_name
ap = argparse.ArgumentParser(); ap.add_argument("plan")
ap.add_argument("--mode", default="mit", choices=["mit", "position"]); ap.add_argument("--kp", type=float, default=3.0); ap.add_argument("--kd", type=float, default=0.05)
ap.add_argument("--effort", type=float, default=0.8, help="MIT current limit, A (docs: start 0.5, gentle 1.5)"); ap.add_argument("--effort-scale", type=float, default=0.8)
ap.add_argument("--cutoff", type=float, default=40.0); ap.add_argument("--tempo", type=float, default=1.0, help="0.5 = half speed")
ap.add_argument("--start", type=float, default=None, help="music time s"); ap.add_argument("--end", type=float, default=None)
ap.add_argument("--fingers", default="thumb,index,middle,ring,pinky"); ap.add_argument("--ramp", type=float, default=2.0)
ap.add_argument("--midi-dev", default=None); ap.add_argument("--yes", action="store_true"); ap.add_argument("--dry-run", action="store_true"); ap.add_argument("--sn", default=None)
ap.add_argument("--log", default=None); ap.add_argument("--fingers-only", action="store_true"); A = ap.parse_args()
Z = np.load(A.plan); t, q = Z["t"], Z["q"].astype(float)[:, :20]; pre = float(Z["pre_roll"]); notes = Z["notes"]
if "wrist" in Z.files and str(Z["wrist"]) != "fixed" and not A.fingers_only:
    raise SystemExit("this plan moves the wrist (needs an arm); the hand alone would play only the finger part. Add --fingers-only to do that anyway.")
# window + tempo (time-stretch the joint trajectory; lead stays as planned in plan time, fine for tempo <= 1)
t0 = 0.0 if A.start is None else max(0.0, A.start + pre - 1.0); t1 = t[-1] if A.end is None else min(t[-1], A.end + pre + 0.6)
tn = np.arange(t0, t1, A.tempo / 1000.0); cmd = np.stack([np.interp(tn, t, q[:, j]) for j in range(20)], 1)
keep = {"thumb": 0, "index": 1, "middle": 2, "ring": 3, "pinky": 4}; sel = [keep[f] for f in A.fingers.split(",")]
home = np.asarray(Z["home_hover"], float)
for f in range(5):
    if f not in sel: cmd[:, 4 * f:4 * f + 4] = home[4 * f:4 * f + 4]
clipped = np.mean((cmd < hw.LO - 1e-4) | (cmd > hw.HI + 1e-4)); vmax = np.abs(np.diff(cmd, axis=0)).max() * 1000
fmap = dict((int(m), int(f)) for m, f in Z["fing"]) if "fing" in Z.files else {}
target = [dict(on=(on - (t0 - pre)) / A.tempo, pitch=int(p)) for on, off, p in notes
          if t0 - pre <= on <= t1 - pre and fmap.get(int(p), 0) in sel]
print(f"plan {os.path.basename(os.path.dirname(A.plan))}: {len(cmd)/1000:.1f} s at tempo x{A.tempo}, fingers {A.fingers}, {len(target)} target notes, "
      f"max cmd speed {vmax:.1f} rad/s, {clipped*100:.2f} % samples beyond joint limits (clipped)")
if vmax > 35: raise SystemExit("command faster than 35 rad/s: refusing")
log = A.log or os.path.join(os.path.dirname(A.plan), time.strftime("hw_%m%d_%H%M%S.npz"))
midi = hw.MidiIn(A.midi_dev) if A.midi_dev else None
with hw.Session(mode=A.mode, kp=A.kp, kd=A.kd, effort=A.effort, effort_scale=A.effort_scale, cutoff=A.cutoff, dry_run=A.dry_run, sn=A.sn) as s:
    try:
        print(f"ramping to the start pose over {A.ramp:.1f} s ..."); s.ramp_to(cmd[0], A.ramp)
        if not (A.yes or A.dry_run): input("at start pose. Enter = play, Ctrl-C = abort ")
        tp, st = s.stream(cmd); print(f"streamed {st['sent']} frames, skipped {st['skipped']} (late host)")
        s.ramp_to(home, 0.8)
    except KeyboardInterrupt:
        print("\ninterrupted: disabling"); tp = None
    S = s.states
np.savez_compressed(log, t_cmd=tn, cmd=cmd.astype(np.float32), t_play=tp if tp else np.nan,
                    t_state=np.array([x[0] for x in S]), q=np.array([x[1] for x in S], np.float32), dq=np.array([x[2] for x in S], np.float32), effort=np.array([x[3] for x in S], np.float32))
print("log:", log)
try:        # what the hand did: how far each finger was from its command, and how hard it pushed
    if tp and len(S) > 100:
        ts = np.array([x[0] for x in S]); qm = np.array([x[1] for x in S]); em = np.abs(np.array([x[3] for x in S]))
        k = np.round((ts - tp) * 1000).astype(int); ok = (k >= 0) & (k < len(cmd)); err = np.abs(qm[ok] - np.clip(cmd[k[ok]], hw.LO, hw.HI))
        for f, name in enumerate(["thumb", "index", "middle", "ring", "pinky"]):
            sl = slice(4 * f, 4 * f + 4); e = em[ok][:, sl]
            print(f"  {name:6s} furthest from command {np.degrees(np.nanmax(err[:, sl])):5.1f} deg, peak current {np.nanmax(e):.2f} A, "
                  f"at the limit {np.nanmean(e >= 0.95 * A.effort) * 100:4.1f} % of the time" if A.mode == "mit" else
                  f"  {name:6s} furthest from command {np.degrees(np.nanmax(err[:, sl])):5.1f} deg, peak effort {np.nanmax(e):.2f}")
except Exception as ex: print("summary failed:", ex)
if midi and tp:
    ev = [dict(t=e["t"] - tp - (pre - t0 if t0 < pre else 0) / A.tempo, pitch=e["pitch"]) for e in midi.note_ons()]; midi.close()
    write_notes(log.replace(".npz", ".mid"), [dict(on=e["t"] + 1, off=e["t"] + 1.2, pitch=e["pitch"]) for e in ev])
    import piano_core as pc
    best = max((pc.score(ev, target, tol=0.1, offset=o / 1000) for o in range(-300, 301, 10)), key=lambda r: (r["n_matched"], -abs(r["timing_ms"]["median"])))
    print(f"keyboard heard {len(ev)} notes: F1 {best['f1']:.3f}, matched {best['n_matched']}/{best['n_target']}, timing median {best['timing_ms']['median']:+.0f} ms")
    print("missed:", [(note_name(n["pitch"]), round(n["on"], 2)) for n in best["missed"]][:30]); print("extra:", [(note_name(e["pitch"]), round(e["t"], 2)) for e in best["extra"]][:30])
