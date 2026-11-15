"""Camera half of the webcam teleop, without a window: for the studio (gui/) and for piping into hand_follow.py.

The tracking (MediaPipe hand landmarks) and the angle retargeting are Sebas's, imported unchanged from scripts/teleop.py
(features, retarget, draw and his clamps). This script feeds them from a camera and sends the result on.

  python scripts/camera_track.py --fetch-model                                     # once: download the hand model (8 MB)
  python scripts/camera_track.py | python scripts/hand_follow.py --dry-run          # camera -> fake hand
  python scripts/camera_track.py --port 8771                                        # also serve the picture: http://127.0.0.1:8771/stream
  python scripts/camera_track.py --source my_hand.mp4                               # a video or a picture instead of the camera

stdout: T <seconds> <20 joint targets in rad>   one line per tracked frame (nothing while paused or while no hand is seen)
        # ...                                    status
stdin : one JSON object per line: {"pause": true} {"calibrate": true} {"thumb": false} {"flip_spread": true} {"alpha": 0.4} {"driving": true} {"quit": true}
        ("driving" only changes the picture's label: whether a hand follows is up to whoever reads the T lines)
--record DIR saves every frame's landmarks next to the joint targets (landmarks.npz + meta.json): the pairs a learned
retargeting would be trained on.
Needs: pip install -r requirements-camera.txt   (mediapipe, opencv)"""
import argparse, json, os, sys, threading, time, types
import numpy as np

HERE = os.path.dirname(os.path.abspath(__file__)); REPO = os.path.dirname(HERE)
MODEL = os.path.join(REPO, "assets", "mediapipe", "hand_landmarker.task")
MODEL_URL = "https://storage.googleapis.com/mediapipe-models/hand_landmarker/hand_landmarker/float16/latest/hand_landmarker.task"
NAMES = ["thumb", "index", "middle", "ring", "pinky"]


def sebas():
    """scripts/teleop.py as a module. It imports `handlib` from Sebas's own repository for the hand connection; here the
    hand is driven by hand_follow.py instead, so when handlib is missing a stand-in with the three constants is enough."""
    sys.path.insert(0, HERE); before = list(sys.path)
    try: import handlib  # noqa: F401
    except ImportError:
        h = types.ModuleType("handlib"); h.FINGERS, h.N, h.PUB_HZ = NAMES, 20, 200
        def absent(*_a, **_k): raise RuntimeError("handlib is not in this repository: drive the hand with scripts/hand_follow.py")
        for n in ("by_index", "connect", "latest", "read_positions", "setup_mit"): setattr(h, n, absent)
        sys.modules["handlib"] = h
    import teleop
    sys.path[:] = before            # teleop.py puts the folder above the repository on the import path: take it off again
    return teleop


def fetch_model():
    import urllib.request
    os.makedirs(os.path.dirname(MODEL), exist_ok=True); tmp = MODEL + ".part"
    print(f"# downloading {MODEL_URL}", flush=True)
    with urllib.request.urlopen(MODEL_URL, timeout=30) as r, open(tmp, "wb") as fh:
        while (b := r.read(1 << 16)): fh.write(b)
    if os.path.getsize(tmp) < 1_000_000: os.remove(tmp); raise SystemExit("download too small: not the model")
    os.replace(tmp, MODEL); print(f"# model saved: {MODEL} ({os.path.getsize(MODEL) / 1e6:.1f} MB)", flush=True)


class Frames:
    """Newest annotated picture as JPEG, for the MJPEG stream."""
    def __init__(self): self.cv = threading.Condition(); self.jpg = None; self.n = 0
    def put(self, jpg):
        with self.cv: self.jpg = jpg; self.n += 1; self.cv.notify_all()
    def wait(self, last, timeout=2.0):
        with self.cv:
            self.cv.wait_for(lambda: self.n != last, timeout); return self.jpg, self.n


def serve(port, frames, state):
    from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
    class H(BaseHTTPRequestHandler):
        def log_message(self, *a): pass
        def do_GET(self):
            if self.path.startswith("/state"):
                b = json.dumps(state).encode(); self.send_response(200); self.send_header("Content-Type", "application/json")
                self.send_header("Content-Length", str(len(b))); self.end_headers(); self.wfile.write(b); return
            if not self.path.startswith("/stream"): self.send_error(404); return
            self.send_response(200); self.send_header("Content-Type", "multipart/x-mixed-replace; boundary=frame"); self.send_header("Cache-Control", "no-store"); self.end_headers()
            n = -1
            try:
                while True:
                    jpg, n = frames.wait(n)
                    if jpg is None: continue
                    self.wfile.write(b"--frame\r\nContent-Type: image/jpeg\r\nContent-Length: " + str(len(jpg)).encode() + b"\r\n\r\n" + jpg + b"\r\n")
            except (BrokenPipeError, ConnectionResetError, OSError): pass
    srv = ThreadingHTTPServer(("127.0.0.1", port), H); srv.daemon_threads = True
    threading.Thread(target=srv.serve_forever, daemon=True).start(); return srv


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--camera", type=int, default=0); ap.add_argument("--source", default=None, help="a video file or a picture instead of the camera (loops)")
    ap.add_argument("--port", type=int, default=0, help="serve /stream (MJPEG) and /state on 127.0.0.1:PORT")
    ap.add_argument("--no-thumb", action="store_true"); ap.add_argument("--flip-spread", action="store_true")
    ap.add_argument("--alpha", type=float, default=0.4, help="smoothing, 0..1 (1 = none)"); ap.add_argument("--no-mirror", action="store_true")
    ap.add_argument("--width", type=int, default=640, help="width of the served picture"); ap.add_argument("--fps", type=float, default=30.0, help="frame rate for --source")
    ap.add_argument("--record", default=None, help="folder for landmarks.npz + meta.json"); ap.add_argument("--seconds", type=float, default=0, help="stop after this time (tests)")
    ap.add_argument("--fetch-model", action="store_true"); A = ap.parse_args()
    if A.fetch_model: fetch_model(); return
    try: import cv2, mediapipe as mp
    except ImportError as e: sys.exit(f"camera mode needs mediapipe and opencv ({e}): pip install -r requirements-camera.txt")
    from mediapipe.tasks.python import BaseOptions, vision
    if not os.path.exists(MODEL): sys.exit(f"hand model missing: python scripts/camera_track.py --fetch-model   (or the button on the Camera page)")
    T = sebas()
    still = None
    if A.source and A.source.lower().endswith((".jpg", ".jpeg", ".png")):
        still = cv2.imread(A.source)
        if still is None: sys.exit(f"cannot read {A.source}")
    else:
        cap = cv2.VideoCapture(A.source if A.source else A.camera)
        if not cap.isOpened(): sys.exit(f"cannot open {'the file ' + A.source if A.source else 'camera ' + str(A.camera)}" + ("" if A.source else ": try another camera number"))
    landmarker = vision.HandLandmarker.create_from_options(vision.HandLandmarkerOptions(
        base_options=BaseOptions(model_asset_path=MODEL), running_mode=vision.RunningMode.VIDEO, num_hands=1,
        min_hand_detection_confidence=0.6, min_tracking_confidence=0.5))
    opt = dict(pause=False, thumb=not A.no_thumb, flip_spread=A.flip_spread, alpha=float(np.clip(A.alpha, 0.05, 1.0)), quit=False, calibrate=False, driving=False)
    state = dict(tracked=False, paused=False, fps=0.0, frames=0, q=[0.0] * 20, thumb=opt["thumb"], flip_spread=opt["flip_spread"], alpha=opt["alpha"],
                 calibrated=False, source=A.source or f"camera {A.camera}", seen=0.0)
    def control():
        for line in sys.stdin:
            try: c = json.loads(line)
            except ValueError: continue
            for k in ("pause", "thumb", "flip_spread", "quit", "calibrate", "driving"):
                if k in c: opt[k] = bool(c[k])
            if "alpha" in c: opt["alpha"] = float(np.clip(float(c["alpha"]), 0.05, 1.0))
    threading.Thread(target=control, daemon=True).start()
    frames = Frames(); srv = serve(A.port, frames, state) if A.port else None
    neutral = dict(T.DEFAULT_NEUTRAL); raw = None; q_f = np.zeros(20); thumb_hold = np.zeros(4)
    rec = dict(t=[], world=[], image=[], q=[]) if A.record else None
    t0 = time.monotonic(); n = 0; n_tracked = 0; last_ts = -1; t_fps = t0; n_fps = 0
    print(f"# tracking {state['source']}" + (f", picture at http://127.0.0.1:{A.port}/stream" if A.port else ""), flush=True)
    try:
        while not opt["quit"]:
            if still is not None: frame = still.copy(); time.sleep(1.0 / A.fps)
            else:
                ok, frame = cap.read()
                if not ok:
                    if A.source: cap.set(cv2.CAP_PROP_POS_FRAMES, 0); ok, frame = cap.read()      # a file starts over
                    if not ok: print("# camera read failed", flush=True); break
                if A.source: time.sleep(1.0 / A.fps)
            if not A.no_mirror: frame = cv2.flip(frame, 1)                                         # mirror view: feels natural
            now = time.monotonic() - t0; ts = max(int(now * 1000), last_ts + 1); last_ts = ts
            res = landmarker.detect_for_video(mp.Image(image_format=mp.ImageFormat.SRGB, data=np.ascontiguousarray(cv2.cvtColor(frame, cv2.COLOR_BGR2RGB))), ts)
            lm = res.hand_landmarks[0] if res.hand_landmarks else None; paused = opt["pause"]
            if lm is not None:
                world = np.array([[p.x, p.y, p.z] for p in res.hand_world_landmarks[0]]); raw = T.features(world)
                if opt["calibrate"]: neutral.update({k: raw[k] for k in T.DEFAULT_NEUTRAL}); opt["calibrate"] = False; state["calibrated"] = True; print("# neutral pose calibrated", flush=True)
                if not paused:
                    q = T.retarget(raw, neutral, opt["flip_spread"], opt["thumb"], thumb_hold)
                    q_f = opt["alpha"] * q + (1 - opt["alpha"]) * q_f; n_tracked += 1
                    sys.stdout.write("T %.3f " % now + " ".join("%.4f" % v for v in q_f) + "\n"); sys.stdout.flush()
                    if rec is not None:
                        rec["t"].append(now); rec["world"].append(world); rec["image"].append([[p.x, p.y, p.z] for p in lm]); rec["q"].append(q_f.copy())
            elif opt["calibrate"]: opt["calibrate"] = False
            n += 1; n_fps += 1
            if now + t0 - t_fps >= 1.0: state["fps"] = round(n_fps / (now + t0 - t_fps), 1); t_fps = now + t0; n_fps = 0
            state.update(tracked=lm is not None, paused=paused, frames=n, q=[round(float(v), 4) for v in q_f], thumb=opt["thumb"], flip_spread=opt["flip_spread"],
                         alpha=opt["alpha"], seen=round(n_tracked / max(n, 1), 3))
            if srv is not None:
                pic = T.draw(frame, lm, q_f, paused, opt["driving"]); h, w = pic.shape[:2]
                if w > A.width: pic = cv2.resize(pic, (A.width, int(h * A.width / w)))
                ok, jpg = cv2.imencode(".jpg", pic, [cv2.IMWRITE_JPEG_QUALITY, 72])
                if ok: frames.put(jpg.tobytes())
            if A.seconds and now > A.seconds: break
    except (KeyboardInterrupt, BrokenPipeError):
        pass
    finally:
        try: landmarker.close()
        except Exception: pass
        if still is None: cap.release()
        if rec is not None and rec["t"]:
            os.makedirs(A.record, exist_ok=True)
            np.savez_compressed(os.path.join(A.record, "landmarks.npz"), t=np.array(rec["t"]), world=np.array(rec["world"], np.float32),
                                image=np.array(rec["image"], np.float32), q=np.array(rec["q"], np.float32))
            json.dump(dict(date=time.strftime("%Y-%m-%d %H:%M:%S"), frames=len(rec["t"]), seconds=round(rec["t"][-1], 1), source=state["source"], neutral=neutral,
                           thumb=opt["thumb"], flip_spread=opt["flip_spread"], alpha=opt["alpha"], mirror=not A.no_mirror,
                           clamp_lo=T.LO.tolist(), clamp_hi=T.HI.tolist(), retarget="scripts/teleop.py features() + retarget()"),
                      open(os.path.join(A.record, "meta.json"), "w"), indent=1)
        try: sys.stderr.write(f"# camera stopped: {n} frames, a hand in {n_tracked}\n")
        except Exception: pass


if __name__ == "__main__":
    main()
