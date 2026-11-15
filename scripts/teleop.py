"""Webcam teleop: MediaPipe tracks your hand, simple angle retargeting drives the Wuji Hand 2.

    python experiments/teleop/teleop.py                 # dry run: camera + tracking + computed angles, no hand
    python experiments/teleop/teleop.py --go --note "..."   # drive the hand
    python experiments/teleop/teleop.py --go --no-thumb # hold the thumb still
    python experiments/teleop/teleop.py --plot experiments/teleop/data/<run>.csv

Keys in the window: q / Esc quit, space pause (hand holds its pose), c calibrate neutral,
f toggle fullscreen (starts fullscreen; --windowed to start in a window).
Works with either Wuji (left/right): pick with --hand left|right (default: the only one connected).
Use your own hand of the SAME side, palm toward the camera. The mapping is anatomical and the
Wuji URDFs show both sides use the same joint ranges (mirrored axes), so no sign changes per side.
If side-to-side spread looks mirrored anyway, add --flip-spread.

Retargeting (from MediaPipe 3D world landmarks, palm frame = wrist->middle MCP, index->pinky MCP):
  fingers: J1 = MCP bend (proximal bone out of the palm plane), J3 = PIP bend, J4 = DIP bend,
           J2 = spread in the palm plane vs a neutral splay, faded out as J1 bends
  thumb (Wuji roles from thumb_probe.py): J1 = base bend toward/across the palm,
           J2 = sideways swing (negative = away from index), J3 = middle joint, J4 = tip
Press 'c' with your hand relaxed, flat and open to calibrate that pose as neutral (thumb + spread).
Targets are clamped, smoothed (EMA), and rate-limited to --vmax rad/s at 200 Hz, so the hand
ramps from its current pose on start and never jumps. Lost tracking -> holds last pose.
"""

import argparse
import csv
import json
import pathlib
import sys
import threading
import time

import numpy as np

HERE = pathlib.Path(__file__).resolve().parent
sys.path.insert(0, str(HERE.parents[1]))

from handlib import FINGERS, N, PUB_HZ, by_index, connect, latest, read_positions, setup_mit  # noqa: E402

MODEL = HERE / "models" / "hand_landmarker.task"
DATA = HERE / "data"

# clamps (rad) per joint J1..J4; firmware soft limits clamp further
LO = np.array([0.0, -0.25, 0.0, 0.0])
HI = np.array([1.3, 0.25, 1.4, 1.1])
THUMB_LO = np.array([0.0, -1.0, 0.0, 0.0])   # probe: J1 0..1.3, J2 0..-1.5, J3/J4 up to ~1.5 by hand
THUMB_HI = np.array([1.2, 0.0, 1.2, 1.4])
# MediaPipe landmark ids: (mcp, pip, dip, tip) per finger, thumb = (cmc, mcp, ip, tip)
CHAINS = {0: (1, 2, 3, 4), 1: (5, 6, 7, 8), 2: (9, 10, 11, 12), 3: (13, 14, 15, 16), 4: (17, 18, 19, 20)}
# raw feature values of a relaxed, flat, open hand; 'c' replaces them with yours
DEFAULT_NEUTRAL = {"spread1": 0.15, "spread2": 0.0, "spread3": -0.10, "spread4": -0.25,
                   "th_out": 0.3, "th_radial": 0.7, "th_mcp": 0.1, "th_ip": 0.1}


def angle(a, b):
    c = np.dot(a, b) / (np.linalg.norm(a) * np.linalg.norm(b) + 1e-9)
    return float(np.arccos(np.clip(c, -1.0, 1.0)))


def unit(v):
    return v / (np.linalg.norm(v) + 1e-9)


def features(w):
    """w: (21,3) world landmarks -> dict of raw angles (rad)."""
    wrist = w[0]
    fwd = unit(w[9] - wrist)                          # toward middle MCP
    x_ip = unit((w[17] - w[5]) - np.dot(w[17] - w[5], fwd) * fwd)  # in-plane, index -> pinky
    normal = np.cross(x_ip, fwd)
    r = {}
    for f in range(1, 5):
        m, p, d, t = (w[i] for i in CHAINS[f])
        b = p - m
        b_in = b - np.dot(b, normal) * normal
        r[f"j1_{f}"] = angle(b, b_in) if np.dot(b_in, fwd) > 0 else np.pi / 2
        r[f"j3_{f}"] = angle(b, d - p)
        r[f"j4_{f}"] = angle(d - p, t - d)
        r[f"spread{f}"] = float(np.arctan2(np.dot(b_in, -x_ip), np.dot(b_in, fwd)))
    c, m, i, t = (w[k] for k in CHAINS[0])
    b = m - c                                         # thumb metacarpal
    b_in = b - np.dot(b, normal) * normal
    r["th_out"] = angle(b, b_in)                      # tilt out of the palm plane
    r["th_radial"] = float(np.arctan2(np.dot(b_in, -x_ip), np.dot(b_in, fwd)))  # + = away from index side
    r["th_mcp"] = angle(b, i - m)
    r["th_ip"] = angle(i - m, t - i)
    return r


def retarget(r, neutral, flip_spread, use_thumb, thumb_hold):
    """raw features -> 20 target angles (rad)."""
    q = np.zeros(N)
    for f in range(1, 5):
        j1 = r[f"j1_{f}"]
        spread = (r[f"spread{f}"] - neutral[f"spread{f}"]) * max(0.0, 1.0 - j1)  # noisy when bent: fade
        if flip_spread:
            spread = -spread
        q[f * 4:f * 4 + 4] = np.clip([j1, spread, r[f"j3_{f}"], r[f"j4_{f}"]], LO, HI)
    if use_thumb:
        radial = r["th_radial"] - neutral["th_radial"]
        j1 = (r["th_out"] - neutral["th_out"]) + max(0.0, -radial)   # tilt into palm + fold across it
        j2 = -max(0.0, radial)                                        # swing away from index -> negative
        j3 = r["th_mcp"] - neutral["th_mcp"]
        j4 = r["th_ip"] - neutral["th_ip"]
        q[0:4] = np.clip([j1, j2, j3, j4], THUMB_LO, THUMB_HI)
    else:
        q[0:4] = thumb_hold
    return q


class Commander(threading.Thread):
    """Publishes at PUB_HZ, moving the command toward `target` at most vmax rad/s."""

    def __init__(self, hand, start, vmax):
        super().__init__(daemon=True)
        self.hand, self.cmd, self.target = hand, np.array(start), np.array(start)
        self.step = vmax / PUB_HZ
        self.lock = threading.Lock()
        self.stop_ev = threading.Event()
        self.actual = None
        self.error = None

    def set_target(self, q):
        with self.lock:
            self.target = np.array(q)

    def run(self):
        from wuji_sdk import JointCommand
        pub = self.hand.joint_command().publish()
        sub = self.hand.joint_states().subscribe()
        dt, t0, i = 1.0 / PUB_HZ, time.monotonic(), 0
        try:
            while not self.stop_ev.is_set():
                with self.lock:
                    tgt = self.target
                self.cmd = self.cmd + np.clip(tgt - self.cmd, -self.step, self.step)
                pub.send([JointCommand(float(p), 0.0, 0.0) for p in self.cmd])
                if (fr := latest(sub)) is not None:
                    self.actual = by_index(fr)
                i += 1
                wait = t0 + i * dt - time.monotonic()
                if wait > 0:
                    time.sleep(wait)
        except Exception as e:  # surface to main thread
            self.error = e
        finally:
            sub.close()
            pub.close()


def draw(frame, lm, q, paused, go):
    import cv2
    h, w = frame.shape[:2]
    if lm is not None:
        pts = [(int(p.x * w), int(p.y * h)) for p in lm]
        for a, b in [(0, 1), (0, 5), (5, 9), (9, 13), (13, 17), (0, 17)] + \
                [(c[k], c[k + 1]) for c in CHAINS.values() for k in range(3)]:
            cv2.line(frame, pts[a], pts[b], (0, 220, 0), 2)
        for p in pts:
            cv2.circle(frame, p, 3, (0, 0, 255), -1)
    y = 22
    status = ("PAUSED" if paused else ("DRIVING HAND" if go else "DRY RUN (no hand)")) + \
        ("" if lm is not None else "  - no hand seen")
    cv2.putText(frame, status, (10, y), cv2.FONT_HERSHEY_SIMPLEX, 0.6, (0, 255, 255), 2)
    for f, name in enumerate(FINGERS):
        y += 22
        txt = f"{name:<7}" + " ".join(f"{v:+.2f}" for v in q[f * 4:f * 4 + 4])
        cv2.putText(frame, txt, (10, y), cv2.FONT_HERSHEY_SIMPLEX, 0.5, (255, 255, 255), 1)
    return frame


def analyze(csv_path):
    import matplotlib
    matplotlib.use("Agg")
    import matplotlib.pyplot as plt
    with open(csv_path) as fh:
        rows = list(csv.DictReader(fh))
    t = np.array([float(r["t"]) for r in rows])
    fig, axes = plt.subplots(5, 1, figsize=(12, 11), sharex=True)
    print(f"\n{'finger':<8}{'J1 RMS err':>11}{'J3 RMS err':>11}")
    for f, ax in enumerate(axes):
        errs = []
        for j, ls in ((0, "-"), (2, "--")):
            k = f * 4 + j
            tgt = np.array([float(r[f"t{k}"]) for r in rows])
            act = np.array([float(r[f"a{k}"]) if r[f"a{k}"] else np.nan for r in rows])
            ax.plot(t, tgt, ls, color="C0", lw=1, label=f"J{j + 1} camera target")
            ax.plot(t, act, ls, color="C1", lw=1, label=f"J{j + 1} hand actual")
            errs.append(np.sqrt(np.nanmean((act - tgt) ** 2)))
        print(f"{FINGERS[f]:<8}{errs[0]:11.3f}{errs[1]:11.3f}")
        ax.set_ylabel(f"{FINGERS[f]}\nrad"); ax.grid(alpha=0.3)
    axes[0].legend(fontsize=7, ncol=4, loc="upper right")
    axes[-1].set_xlabel("s")
    fig.suptitle("teleop: camera target vs hand actual (J1 solid, J3 dashed)")
    fig.tight_layout()
    png = pathlib.Path(csv_path).with_suffix(".png")
    fig.savefig(png, dpi=100)
    print(f"Plot: {png}")


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--go", action="store_true", help="connect and drive the hand")
    ap.add_argument("--hand", help="left / right / SN (default: env WUJI_HAND or the only hand found)")
    ap.add_argument("--camera", type=int, default=0)
    ap.add_argument("--windowed", action="store_true", help="start in a normal window instead of fullscreen")
    ap.add_argument("--no-thumb", action="store_true", help="hold the thumb still")
    ap.add_argument("--flip-spread", action="store_true", help="mirror J2 side-to-side")
    ap.add_argument("--vmax", type=float, default=3.0, help="max joint speed, rad/s (<=6)")
    ap.add_argument("--alpha", type=float, default=0.4, help="EMA smoothing, 0..1 (1 = none)")
    ap.add_argument("--kp", type=float, default=3.0)
    ap.add_argument("--kd", type=float, default=0.05)
    ap.add_argument("--note", default="")
    ap.add_argument("--plot", help="re-analyze a saved CSV and exit")
    args = ap.parse_args()
    if args.plot:
        analyze(args.plot)
        return

    import cv2
    import mediapipe as mp
    from mediapipe.tasks.python import BaseOptions, vision

    if not MODEL.exists():
        sys.exit(f"Missing {MODEL}. Download:\n  curl -fsSL -o {MODEL} https://storage.googleapis.com/"
                 "mediapipe-models/hand_landmarker/hand_landmarker/float16/latest/hand_landmarker.task")
    landmarker = vision.HandLandmarker.create_from_options(vision.HandLandmarkerOptions(
        base_options=BaseOptions(model_asset_path=str(MODEL)),
        running_mode=vision.RunningMode.VIDEO, num_hands=1,
        min_hand_detection_confidence=0.6, min_tracking_confidence=0.5))
    cap = cv2.VideoCapture(args.camera)
    if not cap.isOpened():
        sys.exit(f"Cannot open camera {args.camera} (try --camera 1/2).")

    manager = hand = cmdr = hand_sn = None
    rows, paused = [], False
    try:
        if args.go:
            manager, hand = connect("teleop", args.hand)
            side, hand_sn = hand.handedness().get(), hand.serial_number
            print(f"Use your {side.upper()} hand, palm toward the camera.")
            start = np.array(read_positions(hand))
            setup_mit(hand, kp=args.kp, kd=args.kd)
            cmdr = Commander(hand, start, min(args.vmax, 6.0))
            cmdr.start()
            q_f = start.copy()
        else:
            q_f = np.zeros(N)
        thumb_hold = q_f[0:4].copy()
        neutral, raw = dict(DEFAULT_NEUTRAL), None
        t0 = time.monotonic()
        win = "wuji teleop"
        cv2.namedWindow(win, cv2.WINDOW_NORMAL)
        fullscreen = not args.windowed

        def apply_fullscreen():
            cv2.setWindowProperty(win, cv2.WND_PROP_FULLSCREEN,
                                  cv2.WINDOW_FULLSCREEN if fullscreen else cv2.WINDOW_NORMAL)
        apply_fullscreen()
        print("Window open. q/Esc quit, space pause, c calibrate, f fullscreen.")
        while True:
            ok, frame = cap.read()
            if not ok:
                print("camera read failed"); break
            frame = cv2.flip(frame, 1)  # mirror view: feels natural
            ts = int((time.monotonic() - t0) * 1000)
            res = landmarker.detect_for_video(
                mp.Image(image_format=mp.ImageFormat.SRGB, data=cv2.cvtColor(frame, cv2.COLOR_BGR2RGB)), ts)
            lm = res.hand_landmarks[0] if res.hand_landmarks else None
            if lm is not None and not paused:
                raw = features(np.array([[p.x, p.y, p.z] for p in res.hand_world_landmarks[0]]))
                q = retarget(raw, neutral, args.flip_spread, not args.no_thumb, thumb_hold)
                q_f = args.alpha * q + (1 - args.alpha) * q_f
                if cmdr:
                    cmdr.set_target(q_f)
            if cmdr:
                if cmdr.error:
                    raise cmdr.error
                act = cmdr.actual or {}
                rows.append([ts / 1000.0] + list(q_f) + [act[k].position if k in act else "" for k in range(N)])
            cv2.imshow(win, draw(frame, lm, q_f, paused, args.go))
            key = cv2.waitKey(1) & 0xFF
            if key in (ord("q"), 27):
                break
            if key == ord(" "):
                paused = not paused
            if key == ord("f"):
                fullscreen = not fullscreen
                apply_fullscreen()
            if key == ord("c") and raw is not None:
                neutral.update({k: raw[k] for k in DEFAULT_NEUTRAL})
                print("Calibrated neutral: " + ", ".join(f"{k}={v:+.2f}" for k, v in neutral.items()))
    except KeyboardInterrupt:
        print("\nInterrupted.")
    finally:
        if cmdr:
            cmdr.stop_ev.set()
            cmdr.join(timeout=1.0)
        if hand is not None:
            hand.disable()
            print("Joints disabled.")
        if manager is not None:
            manager.disconnect_all()
        cap.release()
        cv2.destroyAllWindows()
        landmarker.close()

    if rows:
        DATA.mkdir(exist_ok=True)
        stem = DATA / time.strftime("%Y%m%d_%H%M%S_teleop")
        with open(stem.with_suffix(".csv"), "w", newline="") as fh:
            wr = csv.writer(fh)
            wr.writerow(["t"] + [f"t{k}" for k in range(N)] + [f"a{k}" for k in range(N)])
            wr.writerows(rows)
        stem.with_suffix(".json").write_text(json.dumps({
            "date": time.strftime("%Y-%m-%d %H:%M:%S"), "kp": args.kp, "kd": args.kd, "vmax": args.vmax,
            "alpha": args.alpha, "hand": hand_sn, "thumb": not args.no_thumb, "neutral": neutral, "flip_spread": args.flip_spread, "note": args.note,
            "clamp_lo": LO.tolist(), "clamp_hi": HI.tolist(),
        }, indent=2))
        print(f"Saved {len(rows)} samples -> {stem}.csv/.json")
        analyze(stem.with_suffix(".csv"))


if __name__ == "__main__":
    main()
