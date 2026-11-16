"""Webcam teleop: MediaPipe tracks your hand, simple angle retargeting drives the Wuji Hand 2.

    python scripts/teleop.py                 # dry run: camera + tracking + angles, no hand (still logs + records video)
    python scripts/teleop.py --go --camera 0 --camera2 4   # two cameras fused per joint
    python scripts/teleop.py --go --note "..."   # drive the hand
    python scripts/teleop.py --go --no-thumb # hold the thumb still
    python scripts/teleop.py --plot out/teleop_runs/<run>.csv

Keys in the window: q / Esc quit, space pause (hand holds its pose), c calibrate neutral,
f toggle fullscreen (starts fullscreen; --windowed to start in a window).
Works with either Wuji (left/right): pick with --hand left|right (default: the only one connected).
Use your own hand of the SAME side, palm toward the camera. The mapping is anatomical and the
Wuji URDFs show both sides use the same joint ranges (mirrored axes), so no sign changes per side.
If side-to-side spread looks mirrored anyway, add --flip-spread.

Retargeting (from MediaPipe 3D world landmarks, palm frame = wrist->middle MCP, index->pinky MCP):
  fingers: J1 = MCP bend (proximal bone out of the palm plane), J3 = PIP bend, J4 = DIP bend,
           J2 = spread from the in-plane angle between neighbouring fingers (middle = reference),
                x1.5, faded out as J1 bends; --decouple removes some ring->middle style coupling
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
sys.path.insert(0, str(HERE.parents[1]))   # handlib.py lives one level above this repo (Sebas's wuji2 folder)
sys.path.insert(0, str(HERE))              # hand_features.py

from hand_features import CHAINS, features, unit  # noqa: E402
from handlib import FINGERS, N, PUB_HZ, by_index, connect, latest, read_positions, setup_mit  # noqa: E402

# In Wuji-Quartet: the model camera_track.py --fetch-model downloads; elsewhere models/ next to this file.
MODEL = next((m for m in (HERE.parent / "assets" / "mediapipe" / "hand_landmarker.task",
                          HERE / "models" / "hand_landmarker.task") if m.exists()),
             HERE.parent / "assets" / "mediapipe" / "hand_landmarker.task")
DATA = HERE.parent / "out" / "teleop_runs"   # gitignored

# clamps (rad) per joint J1..J4; firmware soft limits clamp further (J2 clamped per finger below)
LO = np.array([0.0, -0.5, 0.0, 0.0])
HI = np.array([1.3, 0.5, 1.4, 1.1])
# Robot J2 sign (URDF + pose_check run 20261115_170715): +index / -ring / -pinky move TOWARD the middle finger,
# so spreading is index -, ring/pinky +. Up to 0.5 away from the middle, only 0.1 toward it (avoid collisions).
J2_RANGE = {1: (-0.5, 0.1), 2: (0.0, 0.0), 3: (-0.1, 0.5), 4: (-0.1, 0.5)}
SPREAD_GAIN = 1.5        # robot spread / human spread
THUMB_SWING_GAIN = 2.0   # robot thumb J2 / human thumb swing away from index
THUMB_LO = np.array([0.0, -1.0, 0.0, 0.0])   # probe: J1 0..1.3, J2 0..-1.5, J3/J4 up to ~1.5 by hand
THUMB_HI = np.array([1.2, 0.0, 1.2, 1.4])
# raw feature values of a relaxed, flat, open hand; 'c' replaces them with yours
DEFAULT_NEUTRAL = {"spread1": 0.15, "spread2": 0.0, "spread3": -0.10, "spread4": -0.25,
                   "th_out": 0.3, "th_radial": 0.7, "th_mcp": 0.1, "th_ip": 0.1, "th_across": 0.0,
                   # MediaPipe reads straight fingers as bent by 0.1-0.7 rad; 'c' measures that offset
                   **{f"j{j}_{f}": 0.0 for f in range(1, 5) for j in (1, 3, 4)}}
THUMB_ACROSS_GAIN = 1.5  # thumb J1 per palm-width the thumb tip moves across the palm


# features seen best when the palm faces the camera (in the palm plane); all others = bending out of it
IN_PLANE = {"spread1", "spread2", "spread3", "spread4", "th_radial"}


def palm_facing(lm, w_px, h_px, world):
    """0 = palm seen edge-on, 1 = palm faces the camera. From the 2D image only: palm width
    (index->pinky knuckles) / palm length (wrist->middle knuckle) shrinks when the palm turns
    edge-on; the same ratio from the 3D landmarks (true hand proportions) normalises it.
    MediaPipe's 3D palm *direction* can't be used: both 90-deg views reported ~0.9 at once."""
    p = np.array([[a.x * w_px, a.y * h_px] for a in lm])
    ratio = np.linalg.norm(p[17] - p[5]) / (np.linalg.norm(p[9] - p[0]) + 1e-9)
    true = np.linalg.norm(world[17] - world[5]) / (np.linalg.norm(world[9] - world[0]) + 1e-9)
    return float(np.clip(ratio / true, 0.0, 1.0))


def fuse(views, eps=0.05):  # used with --fuse weighted
    """views: [(features, facing, score)] -> one feature dict. Each feature is a weighted mean:
    in-plane features trust the palm-facing view, bending features trust the edge-on view."""
    if len(views) == 1:
        return views[0][0]
    out = {}
    for k in views[0][0]:
        ws = [sc * (eps + (fa ** 2 if k in IN_PLANE else 1 - fa ** 2)) for _, fa, sc in views]
        out[k] = sum(w * v[0][k] for w, v in zip(ws, views)) / sum(ws)
    return out


def spread_fade(j1):
    """Spread is noisy once a finger bends; keep it full up to 0.3 rad J1, fade to 0 by 1.2."""
    return float(np.clip(1.0 - max(0.0, j1 - 0.3) / 0.9, 0.0, 1.0))


def retarget(r, neutral, flip_spread, use_thumb, thumb_hold, decouple=0.3, clip=True):
    """raw features -> 20 target angles (rad). neutral["gain"] (20 per-joint factors, from fit_calibration) scales
    each joint before clamping. clip=False skips clamps and decoupling (fit_calibration needs the raw values)."""
    q = np.zeros(N)
    g = np.asarray(neutral.get("gain") or np.ones(N), float)
    cl = np.clip if clip else (lambda x, lo, hi: x)
    def cal(k, j):  # subtract the calibrated straight-finger offset, rescale so a full bend still reaches HI
        n = neutral[k]
        return (r[k] - n) * HI[j] / max(HI[j] - n, 0.3)
    for f in range(1, 5):
        q[f * 4:f * 4 + 4] = cl(np.array([cal(f"j1_{f}", 0), 0.0, cal(f"j3_{f}", 2), cal(f"j4_{f}", 3)]) * g[f * 4:f * 4 + 4], LO, HI)
    # spread from angles BETWEEN neighbouring fingers (relative to neutral); middle finger is the reference
    d = lambda a, b: (r[f"spread{a}"] - r[f"spread{b}"]) - (neutral[f"spread{a}"] - neutral[f"spread{b}"])
    spread = {1: d(1, 2), 2: 0.0, 3: -d(2, 3), 4: -(d(2, 3) + d(3, 4))}
    for f in range(1, 5):
        s = -SPREAD_GAIN * spread[f] * spread_fade(q[f * 4]) * g[f * 4 + 1]  # minus: human spread -> robot sign (see J2_RANGE)
        if flip_spread:
            s = -s
        q[f * 4 + 1] = cl(s, *J2_RANGE[f])
    if decouple > 0 and clip:  # undo neighbour coupling: a finger bending less than its neighbours bends even less
        flex = q.copy()
        for f in range(1, 5):
            nb = [n for n in (f - 1, f + 1) if 1 <= n <= 4]
            for j in (0, 2, 3):
                most = max(flex[n * 4 + j] for n in nb)
                q[f * 4 + j] = max(LO[j], flex[f * 4 + j] - decouple * max(0.0, most - flex[f * 4 + j]))
    if use_thumb:
        radial = r["th_radial"] - neutral["th_radial"]
        across = THUMB_ACROSS_GAIN * max(0.0, r["th_across"] - neutral["th_across"])
        j1 = (r["th_out"] - neutral["th_out"]) + max(0.0, -radial) + across  # tilt + fold + tip across palm
        j2 = -THUMB_SWING_GAIN * max(0.0, radial)                     # swing away from index -> negative
        j3 = r["th_mcp"] - neutral["th_mcp"]
        j4 = r["th_ip"] - neutral["th_ip"]
        q[0:4] = cl(np.array([j1, j2, j3, j4]) * g[0:4], THUMB_LO, THUMB_HI)
    else:
        q[0:4] = thumb_hold
    return q


# Guided calibration: the user holds each pose for a few seconds. "open" sets the neutral (zero) values; in each other
# pose the listed joints should reach the robot angle given here, so each joint gets a gain = robot angle / mapped angle.
CAL_POSES = {
    "open":   {},                                                             # flat, fingers together, thumb alongside
    "fist":   {f * 4 + j: float(HI[j]) for f in range(1, 5) for j in (0, 2, 3)},  # all four fingers fully curled
    "spread": {5: -0.4, 13: 0.3, 17: 0.5, 1: float(THUMB_LO[1])},             # fingers and thumb as wide as possible
    "thumb":  {0: float(THUMB_HI[0])},                                        # thumb tip on the base of the little finger
}
GAIN_RANGE = (0.5, 3.0)


def fit_calibration(captures, flip_spread=False, neutral=None):
    """captures: {pose: [raw feature dicts]} -> (neutral dict with "gain", report). Uses the median of each pose."""
    med = {p: {k: float(np.median([r[k] for r in rs])) for k in rs[0]} for p, rs in captures.items() if rs}
    out = dict(neutral or DEFAULT_NEUTRAL)
    if "open" in med:
        out.update({k: med["open"][k] for k in DEFAULT_NEUTRAL})
    gain = np.ones(N)
    report = {p: dict(frames=len(captures.get(p) or [])) for p in CAL_POSES}
    for p, targets in CAL_POSES.items():
        if not targets or p not in med:
            continue
        q = retarget(med[p], {**out, "gain": None}, flip_spread, True, np.zeros(4), decouple=0.0, clip=False)
        weak = 0                                     # joints the pose did not move well: their gain stays 1
        for i, t in targets.items():
            if abs(q[i]) >= 0.05:                    # too little movement to scale: leave the gain at 1
                raw_gain = abs(t) / abs(q[i])
                if GAIN_RANGE[0] <= raw_gain <= GAIN_RANGE[1]:
                    gain[i] = float(raw_gain)
                else:                                # implausible (pose not held, or tracking failed): keep 1
                    weak += 1
            else:
                weak += 1
        report[p]["gains"] = {int(i): round(float(gain[i]), 2) for i in targets}
        report[p]["weak"] = weak
        report[p]["joints"] = len(targets)
    out["gain"] = [round(float(v), 4) for v in gain]
    out["poses"] = med                                # raw medians: the pose / robot-angle pairs, for later fitting
    return out, report


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


def draw_view(frame, lm, label):
    import cv2
    h, w = frame.shape[:2]
    if lm is not None:
        pts = [(int(p.x * w), int(p.y * h)) for p in lm]
        for a, b in [(0, 1), (0, 5), (5, 9), (9, 13), (13, 17), (0, 17)] + \
                [(c[k], c[k + 1]) for c in CHAINS.values() for k in range(3)]:
            cv2.line(frame, pts[a], pts[b], (0, 220, 0), 2)
        for p in pts:
            cv2.circle(frame, p, 3, (0, 0, 255), -1)
    cv2.putText(frame, label, (10, h - 40), cv2.FONT_HERSHEY_SIMPLEX, 0.5, (255, 200, 0), 1)
    return frame


def draw(frame, lm, q, paused, go, calibrated=True):
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
    if not calibrated:
        cv2.putText(frame, "NOT CALIBRATED: hold hand flat, open, fingers together -> press c",
                    (10, h - 15), cv2.FONT_HERSHEY_SIMPLEX, 0.5, (0, 0, 255), 2)
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
    ap.add_argument("--camera2", type=int, help="second camera, used when --camera loses the hand (see --fuse)")
    ap.add_argument("--fuse", choices=["fallback", "weighted"], default="fallback",
                    help="fallback: use --camera, --camera2 only if it loses the hand (default). weighted: "
                         "average both by palm-facing; at 90 deg this hurts (occluded fingers, run 20261115_123824)")
    ap.add_argument("--windowed", action="store_true", help="start in a normal window instead of fullscreen")
    ap.add_argument("--no-video", action="store_true", help="don't record the window to data/<run>.mp4")
    ap.add_argument("--no-thumb", action="store_true", help="hold the thumb still")
    ap.add_argument("--flip-spread", action="store_true", help="mirror J2 side-to-side")
    ap.add_argument("--decouple", type=float, default=0.3,
                    help="reduce a finger's bend by this x how much more its neighbours bend (0 = off)")
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
    cams = [args.camera] + ([args.camera2] if args.camera2 is not None else [])
    landmarkers = [vision.HandLandmarker.create_from_options(vision.HandLandmarkerOptions(
        base_options=BaseOptions(model_asset_path=str(MODEL)),
        running_mode=vision.RunningMode.VIDEO, num_hands=1,
        min_hand_detection_confidence=0.6, min_tracking_confidence=0.5)) for _ in cams]
    caps = [cv2.VideoCapture(c) for c in cams]
    for c, cap in zip(cams, caps):
        if not cap.isOpened():
            sys.exit(f"Cannot open camera {c} (list them: ls /dev/video*).")

    manager = hand = cmdr = hand_sn = video = None
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
        frame_no = 0
        neutral, raw, calibrated = dict(DEFAULT_NEUTRAL), None, False
        t0 = time.monotonic()
        win = "wuji teleop"
        cv2.namedWindow(win, cv2.WINDOW_NORMAL)
        fullscreen = not args.windowed

        def apply_fullscreen():
            cv2.setWindowProperty(win, cv2.WND_PROP_FULLSCREEN,
                                  cv2.WINDOW_FULLSCREEN if fullscreen else cv2.WINDOW_NORMAL)
        apply_fullscreen()
        print("Window open. q/Esc quit, space pause, c calibrate, f fullscreen.")
        facing, per_view = [""] * len(cams), [None] * len(cams)
        feat_keys = list(features(np.random.default_rng(0).normal(size=(21, 3))))
        while True:
            for cap in caps:      # grab all first, then decode: keeps the views in sync
                cap.grab()
            frames = [cap.retrieve()[1] for cap in caps]
            if any(f is None for f in frames):
                print("camera read failed"); break
            ts = int((time.monotonic() - t0) * 1000)
            views, lms = [], []
            for i, (frame, lmk) in enumerate(zip(frames, landmarkers)):
                frames[i] = frame = cv2.flip(frame, 1)  # mirror view: feels natural (features don't care)
                res = lmk.detect_for_video(
                    mp.Image(image_format=mp.ImageFormat.SRGB, data=cv2.cvtColor(frame, cv2.COLOR_BGR2RGB)), ts)
                lms.append(res.hand_landmarks[0] if res.hand_landmarks else None)
                facing[i], per_view[i] = "", None
                if res.hand_landmarks:
                    w = np.array([[p.x, p.y, p.z] for p in res.hand_world_landmarks[0]])
                    facing[i] = palm_facing(res.hand_landmarks[0], frame.shape[1], frame.shape[0], w)
                    feats = features(w)
                    per_view[i] = feats
                    views.append((feats, facing[i], res.handedness[0][0].score))
            if args.fuse == "fallback":
                views = views[:1]
            h0 = frames[0].shape[0]  # raw (mirrored, undrawn) frames side by side, for the video
            raw_view = np.hstack([f if f.shape[0] == h0 else cv2.resize(f, (int(f.shape[1] * h0 / f.shape[0]), h0))
                                  for f in frames])
            if views and not paused:
                raw = fuse(views)
                q = retarget(raw, neutral, args.flip_spread, not args.no_thumb, thumb_hold, args.decouple)
                q_f = args.alpha * q + (1 - args.alpha) * q_f
                if cmdr:
                    cmdr.set_target(q_f)
            if cmdr and cmdr.error:
                raise cmdr.error
            act = (cmdr.actual if cmdr else None) or {}   # logged in dry runs too (actual empty)
            rows.append([ts / 1000.0] + list(q_f) + [act[k].position if k in act else "" for k in range(N)]
                        + [raw[k] if raw else "" for k in DEFAULT_NEUTRAL] + facing
                        + [pv[k] if pv else "" for pv in per_view for k in feat_keys] + [frame_no])
            for i in range(1, len(frames)):
                fa = f"palm-facing {facing[i]:.2f}" if facing[i] != "" else "no hand"
                frames[i] = draw_view(frames[i], lms[i], f"cam {cams[i]}: {fa}")
                if frames[i].shape[0] != frames[0].shape[0]:
                    h0 = frames[0].shape[0]
                    frames[i] = cv2.resize(frames[i], (int(frames[i].shape[1] * h0 / frames[i].shape[0]), h0))
            frames[0] = draw(frames[0], lms[0], q_f, paused, args.go, calibrated)
            if len(cams) > 1:
                fa = f"palm-facing {facing[0]:.2f}" if facing[0] != "" else "no hand"
                cv2.putText(frames[0], f"cam {cams[0]}: {fa}", (10, frames[0].shape[0] - 40),
                            cv2.FONT_HERSHEY_SIMPLEX, 0.5, (255, 200, 0), 1)
            shown = np.hstack(frames)
            if not args.no_video:   # raw camera video; frame N <-> CSV column `frame`
                if video is None:
                    DATA.mkdir(exist_ok=True)
                    video_path = DATA / time.strftime("%Y%m%d_%H%M%S_teleop.mp4")
                    video = cv2.VideoWriter(str(video_path), cv2.VideoWriter_fourcc(*"mp4v"), 30,
                                            (raw_view.shape[1], raw_view.shape[0]))
                video.write(raw_view)
                frame_no += 1
            cv2.imshow(win, shown)
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
                calibrated = True
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
        if video is not None:
            video.release()
        for cap in caps:
            cap.release()
        cv2.destroyAllWindows()
        for lmk in landmarkers:
            lmk.close()

    if rows:
        DATA.mkdir(exist_ok=True)
        stem = DATA / time.strftime("%Y%m%d_%H%M%S_teleop")
        with open(stem.with_suffix(".csv"), "w", newline="") as fh:
            wr = csv.writer(fh)
            wr.writerow(["t"] + [f"t{k}" for k in range(N)] + [f"a{k}" for k in range(N)]
                        + [f"raw_{k}" for k in DEFAULT_NEUTRAL] + [f"facing_cam{c}" for c in cams]
                        + [f"cam{c}_{k}" for c in cams for k in feat_keys] + ["frame"])
            wr.writerows(rows)
        stem.with_suffix(".json").write_text(json.dumps({
            "date": time.strftime("%Y-%m-%d %H:%M:%S"), "kp": args.kp, "kd": args.kd, "vmax": args.vmax,
            "alpha": args.alpha, "hand": hand_sn, "thumb": not args.no_thumb, "neutral": neutral, "calibrated": calibrated, "decouple": args.decouple,
            "spread_gain": SPREAD_GAIN, "thumb_swing_gain": THUMB_SWING_GAIN, "thumb_across_gain": THUMB_ACROSS_GAIN, "flip_spread": args.flip_spread, "note": args.note, "cameras": cams, "fuse": args.fuse,
            "clamp_lo": LO.tolist(), "clamp_hi": HI.tolist(),
        }, indent=2))
        if video is not None:
            video_path.rename(stem.with_suffix(".mp4"))
        print(f"Saved {len(rows)} samples -> {stem}.csv/.json" + ("/.mp4" if video is not None else ""))
        analyze(stem.with_suffix(".csv"))


if __name__ == "__main__":
    main()
