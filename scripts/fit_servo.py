"""Fit the simulated finger servos to a log from the real hand played in the AIR (no keys).
Replays the logged commands in MuJoCo for several stiffness multipliers and prints how far the simulated joints are
from the measured ones. The firmware limits the current, so the simulated torque limit is tied to the stiffness:
limit = stiffness * (current limit / kp), e.g. 0.5 A / 3 A per rad = saturation at 0.167 rad of error.

  python scripts/fit_servo.py out/ode_air_full.npz --effort 0.5 --imu -3.04,-8.92,2.24
  --imu: accelerometer reading (wuji get imu) while the hand was in the run pose; sets the direction of gravity."""
import argparse, os, sys
from multiprocessing import Pool
import numpy as np
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import mujoco, piano_core as pc, wuji_hw as hw
HERE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
N = ["th_flex", "th_abd", "th_mcp", "th_ip"] + [f + s for f in ["ix", "md", "rg", "pk"] for s in ["_flex", "_abd", "_pip", "_dip"]]

def load(p):
    Z = np.load(p); cmd = np.clip(Z["cmd"].astype(float), hw.LO, hw.HI); ts = Z["t_state"] - float(Z["t_play"]); ok = (ts >= 0) & (ts < len(cmd) / 1000)
    return cmd, ts[ok], Z["q"].astype(float)[ok]

def run(a):
    log, gain, effort, kp_fw, imu, tied, hi = a
    cmd, ts, Q = load(log)
    m = mujoco.MjModel.from_xml_string(pc.build_scene(os.path.join(HERE, "assets/wuji-description"), mount_z=0.4, gain=1.0, keys=[])); d = mujoco.MjData(m); qa = pc.hand_qadr(m)
    for i in range(m.nu):
        kp = m.actuator_gainprm[i, 0] * gain; kv = -m.actuator_biasprm[i, 2] * np.sqrt(gain)
        m.actuator_gainprm[i, 0] = kp; m.actuator_biasprm[i, 1] = -kp; m.actuator_biasprm[i, 2] = -kv
        if tied: m.actuator_forcerange[i] = [-kp * effort / kp_fw, kp * effort / kp_fw]; m.actuator_forcelimited[i] = 1
    for j, v in hi.items(): m.jnt_range[m.dof_jntid[qa[j] - 0] if False else np.where(m.jnt_qposadr == qa[j])[0][0], 1] = v
    d.qpos[qa] = Q[0]; d.ctrl[:] = cmd[0]; mujoco.mj_forward(m, d)
    if imu is not None:
        R = d.site_xmat[mujoco.mj_name2id(m, mujoco.mjtObj.mjOBJ_SITE, "r_wrist_imu_frame")].reshape(3, 3); a_ = np.array(imu, float)
        m.opt.gravity[:] = -R @ (a_ / np.linalg.norm(a_)) * 9.81       # at rest the accelerometer reads the upward reaction
    else: m.opt.gravity[:] = 0
    n = int(len(cmd) / 1000 / m.opt.timestep); out = np.zeros((n, 20)); k = max(1, int(round(m.opt.timestep * 1000)))
    for i in range(n):
        d.ctrl[:] = cmd[min(i * k, len(cmd) - 1)]; mujoco.mj_step(m, d); out[i] = d.qpos[qa]
    tsim = (np.arange(n) + 1) * m.opt.timestep; Qs = np.stack([np.interp(ts, tsim, out[:, j]) for j in range(20)], 1)
    C = cmd[np.round(ts * 1000).astype(int).clip(0, len(cmd) - 1)]
    trav = lambda X, j: np.polyfit(C[:, j] - C[:, j].mean(), X[:, j] - X[:, j].mean(), 1)[0]
    return gain, np.degrees(np.sqrt(np.mean((Qs - Q) ** 2, 0))), np.array([trav(Qs, j) for j in range(20)]), np.array([trav(Q, j) for j in range(20)]), np.degrees(np.sqrt(np.mean((C - Q) ** 2, 0)))

if __name__ == "__main__":
    ap = argparse.ArgumentParser(); ap.add_argument("log"); ap.add_argument("--effort", type=float, default=0.5); ap.add_argument("--kp", type=float, default=3.0)
    ap.add_argument("--gains", default="0.5,1,1.5,2,3,5,8"); ap.add_argument("--imu", default=None); ap.add_argument("--untied", action="store_true", help="keep the model's own torque limits")
    ap.add_argument("--stops", default="", help="real upper stops, e.g. 1:0.442,5:0.60"); ap.add_argument("--workers", type=int, default=8); A = ap.parse_args()
    imu = [float(x) for x in A.imu.split(",")] if A.imu else None; hi = {int(a.split(":")[0]): float(a.split(":")[1]) for a in A.stops.split(",") if a}
    G = [float(g) for g in A.gains.split(",")]
    with Pool(A.workers) as p: R = p.map(run, [(A.log, g, A.effort, A.kp, imu, not A.untied, hi) for g in G])
    grp = {"base bend (0,4,8,12,16)": [0, 4, 8, 12, 16], "sideways (1,5,9,13,17)": [1, 5, 9, 13, 17], "middle joints (2,6,10,14,18)": [2, 6, 10, 14, 18], "tip joints (3,7,11,15,19)": [3, 7, 11, 15, 19]}
    print(f"{os.path.basename(A.log)}: gravity {'from the motion sensor' if imu else 'off'}, torque limit {'tied to ' + str(A.effort) + ' A' if not A.untied else 'as in the model'}")
    print("real hand: travel reached " + "  ".join(f"{k.split(' (')[0]} {np.mean(R[0][3][v])*100:.0f} %" for k, v in grp.items()))
    for g, e, ts_, tr_, ec in R:
        print(f"  stiffness x{g:<4g} sim-vs-real error (deg) " + "  ".join(f"{k.split(' (')[0]} {np.mean(e[v]):4.1f}" for k, v in grp.items()) + "   | sim travel " + " ".join(f"{np.mean(ts_[v])*100:3.0f}%" for v in grp.values()))
    best = {k: G[int(np.argmin([np.mean(r[1][v]) for r in R]))] for k, v in grp.items()}; print("best stiffness per joint group:", best)
    bj = [G[int(np.argmin([r[1][j] for r in R]))] for j in range(20)]; print("best per joint:", " ".join(f"{N[j]}:x{bj[j]:g}" for j in range(20)))
