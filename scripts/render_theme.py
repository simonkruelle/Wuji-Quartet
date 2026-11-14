"""Video of a theme plan in sim (house format: overview left, fingers close up right; real time with audio synthesised
from the keys the SIM pressed, then a trill in 4x slow motion). usage: render_theme.py <plan dir> [--test-frame]"""
import argparse, os, subprocess, sys, wave
import numpy as np, mujoco
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import piano_core as pc
from PIL import Image, ImageDraw, ImageFont
ap = argparse.ArgumentParser(); ap.add_argument("plan_dir"); ap.add_argument("--slow", default="5.75,7.6", help="music-time window for 4x slow motion")
ap.add_argument("--collision", action="store_true", help="show the collision shells (purple) on a black stage, as in the first videos")
ap.add_argument("--test-frame", action="store_true"); ap.add_argument("--out-name", default="theme_sim.mp4"); ap.add_argument("--w", type=int, default=640); ap.add_argument("--h", type=int, default=480); A = ap.parse_args()
Z = np.load(os.path.join(A.plan_dir, "theme_q_1khz.npz")); t, q = Z["t"], Z["q"].astype(float); pre = float(Z["pre_roll"]); gain = float(Z["gain"])
TITLE = str(Z["title"]) if "title" in Z.files else "Mozart K.265 theme (FürElise piece 15)"
WRIST = str(Z["wrist"]) if "wrist" in Z.files else "fixed"
WLABEL = {"fixed": "wrist fixed", "human": "wrist follows the pianist", "plan": "wrist planned from the notes"}.get(WRIST, WRIST)
CEM = "after DR-CEM" if "P" in Z.files else "IK + timing, no optimisation"
xml = pc.read_scene(os.path.join(A.plan_dir, "scene.xml"))
if not A.collision:      # slate stage: the hand's matte-black palm stays visible without the collision shells
    xml = xml.replace("<asset>", '<asset><texture type="skybox" builtin="gradient" rgb1="0.30 0.32 0.37" rgb2="0.12 0.13 0.155" width="256" height="256"/>', 1).replace('rgba="0.55 0.55 0.6 1"', 'rgba="0.15 0.16 0.19 1"')
OPT = mujoco.MjvOption(); OPT.geomgroup[2] = 1 if A.collision else 0
m = mujoco.MjModel.from_xml_string(xml); d = mujoco.MjData(m); qa = pc.hand_qadr(m)
keys = [int(m.joint(j).name[4:]) for j in range(m.njnt) if m.joint(j).name.startswith("key_")]
kad = np.array([m.jnt_qposadr[m.joint(f"key_{k}").id] for k in keys]); kmax = np.array([m.jnt_range[m.joint(f"key_{k}").id, 1] for k in keys])
kgeom = np.array([m.body_geomadr[m.body(f"key_{k}").id] for k in keys]); base_rgba = m.geom_rgba[kgeom].copy()
r = mujoco.Renderer(m, A.h, A.w); yc = pc.key_y(75)
def cams():
    a = mujoco.MjvCamera(); a.lookat[:] = [0.10, yc, 0.03]; a.distance = 0.70; a.azimuth = 215; a.elevation = -32    # player side, from the left
    b = mujoco.MjvCamera(); b.lookat[:] = [0.115, yc, 0.0]; b.distance = 0.26; b.azimuth = 0; b.elevation = -14      # from the fallboard, facing the fingertips
    return a, b
ca, cb = cams()
WB = m.body('wrist_base').id if mujoco.mj_name2id(m, mujoco.mjtObj.mjOBJ_BODY, 'wrist_base') >= 0 else -1
if WB >= 0: ca.distance = 0.95; ca.lookat[1] = float(np.mean([pc.key_y(int(p)) for p in Z['notes'][:, 2]]))
try: font = ImageFont.truetype("/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf", 18); small = ImageFont.truetype("/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf", 14)
except Exception: font = small = ImageFont.load_default()
T_total = t[-1]
def frame(tt, label):
    act = d.qpos[kad] >= kmax - pc.ACT_THR
    m.geom_rgba[kgeom] = np.where(act[:, None], np.array([0.2, 0.8, 0.3, 1.0]), base_rgba)
    imgs = []
    if WB >= 0: cb.lookat[1] = 0.85 * cb.lookat[1] + 0.15 * (d.xpos[WB][1] + 0.0)    # close-up follows the wrist
    for c in (ca, cb): r.update_scene(d, c, scene_option=OPT); imgs.append(r.render())
    im = Image.fromarray(np.concatenate(imgs, 1)); dr = ImageDraw.Draw(im)
    dr.text((12, 10), f"simulation · Wuji Hand 2.2 · {label} · {WLABEL} · {CEM}", fill=(255, 255, 255), font=font)
    dr.text((12, A.h - 48), f"t = {max(tt - pre, 0):5.2f} s of {float(Z['notes'][:, 1].max()):.1f} s · {TITLE}", fill=(255, 255, 255), font=small)
    dr.text((12, A.h - 26), f"finger servos x{gain:g} shipped MJCF kp · MuJoCo {mujoco.__version__} · green = key reached its note-on depth", fill=(255, 255, 255), font=small)
    return np.asarray(im)
d.qpos[qa] = q[0]; d.ctrl[:] = q[0]
for _ in range(150): mujoco.mj_step(m, d)
if A.test_frame:
    for _ in range(int((pre + 1.97 - 0.0) / 0.002)): d.ctrl[:] = q[min(int(round(d.time * 1000)), len(q) - 1)]; mujoco.mj_step(m, d)
    Image.fromarray(frame(d.time, "test")).save(os.path.join(A.plan_dir, "test_frame.png")); print("saved test_frame.png"); sys.exit()
s0, s1 = [float(x) + pre for x in A.slow.split(",")]
out = os.path.join(A.plan_dir, A.out_name); tmp = out.replace(".mp4", "_v.mp4")
ff = subprocess.Popen(["ffmpeg", "-y", "-loglevel", "error", "-f", "rawvideo", "-pix_fmt", "rgb24", "-s", f"{2*A.w}x{A.h}", "-r", "30", "-i", "-", "-c:v", "libx264", "-pix_fmt", "yuv420p", "-crf", "20", tmp], stdin=subprocess.PIPE)
dt = m.opt.timestep; n = int(T_total / dt); onsets = []; armed = np.ones(len(keys), bool); nf = 0; slow_frames = []
state0 = None
for i in range(n):
    tt = i * dt; d.ctrl[:] = q[min(int(round(tt * 1000)), len(q) - 1)]; mujoco.mj_step(m, d)
    fr = d.qpos[kad] / kmax; act = fr >= 1 - pc.ACT_THR / kmax
    for k in np.nonzero(act & armed)[0]: onsets.append((tt, keys[k]))
    armed &= ~act; armed |= fr < 0.5
    if tt + 1e-9 >= nf / 30.0: ff.stdin.write(frame(tt, "real time").tobytes()); nf += 1
    if s0 <= tt <= s1 and (i % int(round(1 / (120 * dt))) == 0): slow_frames.append(frame(tt, "slow motion 4x").tobytes())
for b in slow_frames: ff.stdin.write(b)
ff.stdin.close(); ff.wait()
# audio: simple piano-like tone per SIM note-on, then silence under the slow-motion part
sr = 44100; dur = nf / 30.0 + len(slow_frames) / 30.0; audio = np.zeros(int(sr * dur) + sr)
for tt, k in onsets:
    f0 = 440 * 2 ** ((k - 69) / 12); n_ = int(1.2 * sr); x = np.arange(n_) / sr
    tone = sum(a * np.sin(2 * np.pi * f0 * h * x) for h, a in ((1, 1.0), (2, 0.35), (3, 0.15), (4, 0.06))) * np.exp(-3.2 * x) * np.minimum(1, x / 0.004)
    i0 = int(tt * sr); audio[i0:i0 + n_] += 0.18 * tone[: len(audio) - i0]
audio = np.clip(audio, -1, 1); wav = out.replace(".mp4", ".wav")
with wave.open(wav, "wb") as w: w.setnchannels(1); w.setsampwidth(2); w.setframerate(sr); w.writeframes((audio * 32767).astype(np.int16).tobytes())
subprocess.run(["ffmpeg", "-y", "-loglevel", "error", "-i", tmp, "-i", wav, "-c:v", "copy", "-c:a", "aac", "-shortest", out], check=True)
os.remove(tmp); os.remove(wav); print(f"{out}: {nf} real-time + {len(slow_frames)} slow-motion frames, {len(onsets)} sim note-ons")
