"""One Wuji Hand 2 follows joint targets that arrive on stdin: the hand half of the webcam teleop.

  python scripts/camera_track.py | python scripts/hand_follow.py --dry-run          # no hardware
  python scripts/camera_track.py | python scripts/hand_follow.py --effort 0.5       # hand on this computer
  python scripts/camera_track.py | ssh sunrise@<board> 'cd ~/Wuji-Quartet && ~/wq-venv/bin/python -u scripts/hand_follow.py --effort 0.5'

stdin : T <seconds> <20 joint targets in rad>        thumb 0-3, index 4-7, middle 8-11, ring 12-15, pinky 16-19; other lines are ignored
stdout: A <seconds> <20 measured joint angles>       ten times a second, plus status lines

As in Sebas's scripts/teleop.py the command moves toward the newest target at no more than --vmax rad/s, 200 times a second,
starting from the pose the hand is in: it never jumps. No new target: the hand holds its pose.
The hand side is ours (wuji_hw.Session): current limit read back before enabling, 1.5 A hard limit, commands clipped to the
measured joint stops, and stdin closed / Ctrl-C / a dropped SSH session / kill all end with the hand switched off and confirmed."""
import argparse, os, sys, threading, time
import numpy as np
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import wuji_hw as hw

RATE = 200
ap = argparse.ArgumentParser()
ap.add_argument("--effort", type=float, default=0.5, help="current limit, A (first try 0.5; hard limit 1.5)")
ap.add_argument("--kp", type=float, default=3.0); ap.add_argument("--kd", type=float, default=0.05)
ap.add_argument("--vmax", type=float, default=3.0, help="fastest joint motion, rad/s (at most 6)")
ap.add_argument("--sn", default=None); ap.add_argument("--side", default=None, choices=["left", "right"])
ap.add_argument("--dry-run", action="store_true", help="fake hand, no hardware")
ap.add_argument("--log", default=None, help="save targets and measured angles to this .npz at the end")
A = ap.parse_args()
step = min(max(A.vmax, 0.1), 6.0) / RATE
target = [None]; got = [0, time.monotonic()]; closed = threading.Event()


def reader():
    """stdin -> newest target. Anything that is not 20 finite numbers is dropped."""
    for line in sys.stdin:
        if not line.startswith("T "): continue
        try: q = np.array(line.split()[2:22], float)
        except ValueError: continue
        if q.shape == (20,) and np.isfinite(q).all():
            target[0] = np.clip(q, hw.LO, hw.HI); got[0] += 1; got[1] = time.monotonic()
    closed.set()


threading.Thread(target=reader, daemon=True).start()
rows = []
with hw.Session(mode="mit", kp=A.kp, kd=A.kd, effort=A.effort, dry_run=A.dry_run, sn=A.sn, side=A.side, log_states=False) as s:
    try:
        cmd = np.clip(s.q_before, hw.LO, hw.HI)
        print(f"following: at most {step * RATE:.1f} rad/s, {RATE} Hz, current limit {A.effort} A" + (" (fake hand)" if A.dry_run else ""), flush=True)
        t0 = time.monotonic(); i = 0; said = None
        while not closed.is_set():
            tgt = target[0]
            if tgt is not None: cmd = cmd + np.clip(tgt - cmd, -step, step)
            s.send(cmd); i += 1
            now = time.monotonic()
            if s.states and now - s.states[-1][0] > 0.5: raise RuntimeError("no joint states from the hand for 0.5 s: connection lost, stopping")
            if i % (RATE // 10) == 0:
                q = s.latest(); fresh = tgt is not None and now - got[1] < 0.5
                print("A %.3f " % (now - t0) + " ".join("%.4f" % v for v in q), flush=True)
                if A.log and tgt is not None: rows.append(np.concatenate([[now - t0], tgt, q]))
                state = "following" if fresh else "holding (no new target)"
                if state != said: print(f"# {state}", flush=True); said = state
            w = t0 + i / RATE - time.monotonic()
            if w > 0: time.sleep(w)
        print("input closed: switching the hand off", flush=True)
    except KeyboardInterrupt:
        print("\ninterrupted: switching the hand off", flush=True)
    except RuntimeError as e:
        print(f"\n{e}", flush=True)
print("hand switched off: confirmed" if getattr(s, "off_confirmed", False) else "!!! hand switched off: NOT CONFIRMED, run scripts/hand_off.py", flush=True)
if A.log and rows:
    R = np.array(rows); os.makedirs(os.path.dirname(os.path.abspath(A.log)), exist_ok=True)
    np.savez_compressed(A.log, t=R[:, 0], target=R[:, 1:21].astype(np.float32), q=R[:, 21:41].astype(np.float32), effort=A.effort, vmax=step * RATE, kp=A.kp, kd=A.kd)
    print("log:", A.log, flush=True)
