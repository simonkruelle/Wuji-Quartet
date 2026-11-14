"""Stiffness identification: small joint steps on the real hand vs the MuJoCo model at several gain multipliers.
Picks the --gain for make_theme.py whose step response matches the hand (rise time + steady-state sag).
Steps go in the extension direction (fingers lift, away from the keys).

  python scripts/sysid_step.py out/theme_gain5/theme_q_1khz.npz                    # real hand, MIT kp 3 kd 0.05
  python scripts/sysid_step.py out/theme_gain5/theme_q_1khz.npz --dry-run --sim-only"""
import argparse, json, os, sys, time
import numpy as np
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import wuji_hw as hw
HERE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
ap = argparse.ArgumentParser(); ap.add_argument("plan"); ap.add_argument("--joints", default="4,6,8,10,16,18", help="index mcp/pip, middle mcp/pip, pinky mcp/pip")
ap.add_argument("--step", type=float, default=0.15); ap.add_argument("--hold", type=float, default=0.6); ap.add_argument("--gains", default="0.5,1,2.5,5,10,20")
ap.add_argument("--mode", default="mit", choices=["mit", "position"]); ap.add_argument("--kp", type=float, default=3.0); ap.add_argument("--kd", type=float, default=0.05); ap.add_argument("--effort", type=float, default=0.8)
ap.add_argument("--dry-run", action="store_true"); ap.add_argument("--sim-only", action="store_true"); A = ap.parse_args()
Z = np.load(A.plan); home = np.asarray(Z["home_hover"], float); J = [int(j) for j in A.joints.split(",")]; mount = Z["mount"]

def metrics(t, y, y0, y1):
    """t63 (s) and steady-state fraction reached, for a step y0 -> y1 starting at t=0."""
    frac = (y - y0) / (y1 - y0); i = np.argmax(frac >= 0.632) if np.any(frac >= 0.632) else None
    return (float(t[i]) if i is not None and i > 0 else float("nan")), float(np.nanmedian(frac[t > 0.7 * t[-1]]))

real = {}
if not A.sim_only:
    with hw.Session(mode=A.mode, kp=A.kp, kd=A.kd, effort=A.effort, dry_run=A.dry_run) as s:
        s.ramp_to(home, 2.0); time.sleep(0.5)
        for j in J:
            q1 = home.copy(); q1[j] -= A.step; k0 = len(s.states); t0 = time.monotonic()
            s.stream(np.repeat(q1[None], int(A.hold * 1000), 0)); s.stream(np.repeat(home[None], int(A.hold * 1000), 0))
            S = s.states[k0:]; t = np.array([x[0] for x in S]) - t0; y = np.array([x[1][j] for x in S]); m = t < A.hold
            real[j] = metrics(t[m], y[m], home[j], q1[j]); print(f"real joint {j}: t63 {real[j][0]*1e3:.0f} ms, reached {real[j][1]*100:.0f} % of the step")
import mujoco, piano_core as pc
sim = {}
for g in [float(x) for x in A.gains.split(",")]:
    xml = pc.build_scene(os.path.join(HERE, "assets/wuji-description"), theta=float(mount[3]), mount_x=float(mount[0]), mount_z=float(mount[2]), mount_dy=float(mount[1]), gain=g, keys=list(range(60, 85)), approach=str(Z['approach']) if 'approach' in Z.files else 'front', rev=str(Z['rev']) if 'rev' in Z.files else 'hand2_2')
    m = mujoco.MjModel.from_xml_string(xml); d = mujoco.MjData(m); qa = pc.hand_qadr(m)
    for j in J:
        mujoco.mj_resetData(m, d); d.qpos[qa] = home; d.ctrl[:] = home
        for _ in range(250): mujoco.mj_step(m, d)
        y0 = d.qpos[qa[j]]; c = home.copy(); c[j] -= A.step; d.ctrl[:] = c; ts, ys = [], []
        for i in range(int(A.hold / m.opt.timestep)):
            mujoco.mj_step(m, d); ts.append((i + 1) * m.opt.timestep); ys.append(d.qpos[qa[j]])
        sim[(g, j)] = metrics(np.array(ts), np.array(ys), home[j], c[j])
print("sim  t63 ms / reached %:")
for g in sorted({k[0] for k in sim}): print(f"  gain x{g:<4g}", "  ".join(f"j{j}: {sim[(g, j)][0]*1e3:4.0f} ms {sim[(g, j)][1]*100:3.0f}%" for j in J))
if real:
    def cost(g):
        c = [abs(np.log(sim[(g, j)][0] / real[j][0])) + 2 * abs(sim[(g, j)][1] - real[j][1]) for j in J]
        return float(np.mean(c)) if np.all(np.isfinite(c)) else float("inf")      # never reached 63 % = no match
    gains = sorted({k[0] for k in sim}); best = min(gains, key=cost)
    print(f"best match: gain x{best:g}  (costs: {', '.join(f'x{g:g} {cost(g):.2f}' for g in gains)})")
    print(f"next: python scripts/make_theme.py --gain {best:g} --out out/theme_hw")
    json.dump(dict(real={str(j): v for j, v in real.items()}, best_gain=best, kp=A.kp, kd=A.kd, mode=A.mode), open(os.path.join(os.path.dirname(A.plan), "sysid.json"), "w"), indent=1)
