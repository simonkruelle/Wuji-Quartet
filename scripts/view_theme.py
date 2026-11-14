"""Watch a plan in MuJoCo's interactive 3D viewer (orbit with the mouse, keys turn green on note-on depth).
  python scripts/view_theme.py out/theme_gain5            # real time, loops
  python scripts/view_theme.py out/theme_gain5 --speed 0.25
macOS: run with `mjpython` (ships with the mujoco package) instead of python."""
import argparse, os, sys, time
import numpy as np, mujoco, mujoco.viewer
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import piano_core as pc
ap = argparse.ArgumentParser(); ap.add_argument("plan_dir"); ap.add_argument("--speed", type=float, default=1.0); ap.add_argument("--once", action="store_true")
ap.add_argument("--check", action="store_true", help="load and step 1 s without opening a window"); A = ap.parse_args()
Z = np.load(os.path.join(A.plan_dir, "theme_q_1khz.npz")); t, q = Z["t"], Z["q"].astype(float)
m = mujoco.MjModel.from_xml_string(pc.read_scene(os.path.join(A.plan_dir, "scene.xml"))); d = mujoco.MjData(m); qa = pc.hand_qadr(m)
keys = [int(m.joint(j).name[4:]) for j in range(m.njnt) if m.joint(j).name.startswith("key_")]
kad = np.array([m.jnt_qposadr[m.joint(f"key_{k}").id] for k in keys]); kmax = np.array([m.jnt_range[m.joint(f"key_{k}").id, 1] for k in keys])
kg = np.array([m.body_geomadr[m.body(f"key_{k}").id] for k in keys]); base = m.geom_rgba[kg].copy(); green = np.array([0.2, 0.8, 0.3, 1.0])
def reset():
    mujoco.mj_resetData(m, d); d.qpos[qa] = q[0]; d.ctrl[:] = q[0]
    for _ in range(150): mujoco.mj_step(m, d)
    d.time = 0.0
def step():
    d.ctrl[:] = q[min(int(round(d.time * 1000)), len(q) - 1)]; mujoco.mj_step(m, d)
    m.geom_rgba[kg] = np.where((d.qpos[kad] >= kmax - pc.ACT_THR)[:, None], green, base)
reset()
if A.check:
    for _ in range(500): step()
    print(f"ok: {len(q)/1000:.1f} s plan, {m.nu} actuators, {len(keys)} keys"); sys.exit()
with mujoco.viewer.launch_passive(m, d) as v:
    v.cam.lookat[:] = [0.10, pc.key_y(75), 0.02]; v.cam.distance = 0.6; v.cam.azimuth = 215; v.cam.elevation = -30
    while v.is_running():
        w0, s0 = time.perf_counter(), d.time
        while v.is_running() and d.time < t[-1]:
            target = s0 + (time.perf_counter() - w0) * A.speed
            while d.time < target: step()
            v.sync(); time.sleep(0.005)
        if A.once: break
        time.sleep(1.0); reset()
