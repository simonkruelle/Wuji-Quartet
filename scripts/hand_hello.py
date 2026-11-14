"""First motion on a real hand: the smallest test that the control path works.
Enables at a low current limit while commanding the pose the hand is already in, holds it, moves ONE joint a few degrees
and back, and disables. Run it with the hand in the air or lying on its back, fingers free, someone watching.

  python scripts/hand_hello.py                       # index finger base joint, 0.15 rad (9 deg), finger lifts, 0.5 A
  python scripts/hand_hello.py --joint 8 --delta -0.1
  python scripts/hand_hello.py --dry-run
Ctrl-C at any time: disables the hand."""
import argparse, math, os, sys, time
import numpy as np
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import wuji_hw as hw
ap = argparse.ArgumentParser(); ap.add_argument("--joint", type=int, default=4, help="0-19 = finger*4 + (0 base bend, 1 sideways, 2 middle, 3 tip); 4 = index base")
ap.add_argument("--delta", type=float, default=-0.15, help="rad; negative = the finger straightens"); ap.add_argument("--reps", type=int, default=2)
ap.add_argument("--period", type=float, default=1.0, help="seconds one way"); ap.add_argument("--effort", type=float, default=0.5, help="current limit, A")
ap.add_argument("--kp", type=float, default=3.0); ap.add_argument("--kd", type=float, default=0.05); ap.add_argument("--sn", default=None)
ap.add_argument("--side", default=None, choices=["left", "right"], help="which hand, when two are connected")
ap.add_argument("--yes", action="store_true"); ap.add_argument("--dry-run", action="store_true"); ap.add_argument("--log", default=None); A = ap.parse_args()
if abs(A.delta) > 0.3 or A.effort > 0.8: raise SystemExit("this is a first-motion test: |delta| <= 0.3 rad and effort <= 0.8 A")
J = A.joint; NAMES = ["thumb", "index", "middle", "ring", "pinky"]
if not (A.yes or A.dry_run): input(f"hand in the air or on its back, fingers free? Enter = enable and move {NAMES[J // 4]} joint {J % 4} by {A.delta} rad, Ctrl-C = abort ")
k0 = None
with hw.Session(mode="mit", kp=A.kp, kd=A.kd, effort=A.effort, dry_run=A.dry_run, sn=A.sn, side=A.side) as s:
    try:
        q0 = s.q_before.copy()
        def hold(sec, q):
            t_ = time.monotonic()
            while time.monotonic() - t_ < sec: s.send(q); time.sleep(0.001)
        hold(1.0, q0); jump = np.abs(s.latest() - q0)
        print(f"enabled and holding: largest joint change since before enabling {np.degrees(np.nanmax(jump)):.1f} deg (joint {int(np.nanargmax(jump))})")
        tgt = float(np.clip(q0[J] + A.delta, hw.LO[J] + 0.05, hw.HI[J] - 0.05)); n = max(1, int(A.period * 1000)); k0 = len(s.states); q = q0.copy()
        for r in range(A.reps):
            for a, b in ((q0[J], tgt), (tgt, q0[J])):
                t_ = time.monotonic()
                for i in range(1, n + 1):
                    q = q0.copy(); q[J] = a + (b - a) * 0.5 * (1 - math.cos(math.pi * i / n)); s.send(q)
                    w = t_ + i / 1000 - time.monotonic()
                    if w > 0: time.sleep(w)
                hold(0.3, q)
        hold(0.5, q0)
    except KeyboardInterrupt: print("\ninterrupted: disabling")
    S = list(s.states)
if k0 is not None and len(S) > k0 + 10:
    Q = np.array([x[1] for x in S[k0:]]); E = np.abs(np.array([x[3] for x in S[k0:]])); others = np.delete(np.arange(20), J)
    print(f"{NAMES[J // 4]} joint {J % 4}: asked to travel {np.degrees(abs(tgt - q0[J])):.1f} deg, measured {np.degrees(np.nanmax(Q[:, J]) - np.nanmin(Q[:, J])):.1f} deg, peak current {np.nanmax(E[:, J]):.2f} A")
    print(f"all other joints: moved at most {np.degrees(np.nanmax(np.abs(Q[:, others] - q0[others]))):.1f} deg, peak current {np.nanmax(E[:, others]):.2f} A")
log = A.log or os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "out", time.strftime("hello_%m%d_%H%M%S.npz")); os.makedirs(os.path.dirname(log), exist_ok=True)
np.savez_compressed(log, t=np.array([x[0] for x in S]), q=np.array([x[1] for x in S], np.float32), dq=np.array([x[2] for x in S], np.float32), effort=np.array([x[3] for x in S], np.float32), joint=J, delta=A.delta)
print("log:", log)
