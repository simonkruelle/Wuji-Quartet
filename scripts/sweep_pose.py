"""Search a fixed-wrist mount for five neighbouring white keys by POSTURE, not by notes hit:
natural, fairly straight fingers (close to a relaxed curved pose), no sideways lean, every joint away from its stops
(the stops measured on the real hand included), fingertips well ahead of the knuckles, only fingertips on the keys.
Each finger picks its own contact point along the key (short fingers play nearer the front edge, like a pianist).

usage: sweep_pose.py [--keys 72,74,76,77,79] [--workers 12] [--out out/sweep_pose.json]"""
import argparse, itertools, json, os, sys
from multiprocessing import Pool
import numpy as np
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import mujoco, piano_core as pc
HERE = os.path.dirname(os.path.dirname(os.path.abspath(__file__))); WUJI = os.path.join(HERE, "assets/wuji-description")
PX = [0.115, 0.125, 0.135, 0.143]            # contact point, m from the key hinge (front edge = 0.150)
PX_BLACK = [0.110, 0.115, 0.120]             # black key: the keyframer moves the contact 40 mm toward the hinge -> 20, 15, 10 mm behind the black key's front edge
NOM = np.array([0.35, 0.0, 0.6, 0.3])        # relaxed finger: base bend, sideways, middle joint, tip joint

def evaluate(c):
    x, z, th, dy, keys = c
    try:
        xml = pc.build_scene(WUJI, theta=th, mount_x=x, mount_z=z, mount_dy=dy, gain=5.0, keys=list(range(60, 85)), approach="front", limits=pc.REAL_LIMITS)
        kfr = pc.Keyframer(xml, limit_margin=0.10)
    except Exception as e: return dict(c=c[:4], ok=False, why=str(e)[:80])
    m, d = kfr.model, kfr.data; qa = kfr.qadr; jid = [int(np.where(m.jnt_qposadr == a)[0][0]) for a in qa]; lo = m.jnt_range[jid, 0]; hi = m.jnt_range[jid, 1]
    best = {}
    for f in range(5):
        cand = []
        for px in (PX_BLACK if pc.is_black(keys[f]) else PX):
            k = kfr.keyframes([(f, keys[f])], press_x=px)[(f, keys[f])]; sl = slice(4 * f, 4 * f + 4)
            mar = min(float(np.min(np.minimum(k[n] - lo[sl], hi[sl] - k[n]))) for n in ("hover", "lift", "press", "transit"))
            dev = float(np.linalg.norm((k["press"] - NOM) * [1, 2, 1, 1])) if f else 0.0
            cand.append((max(k["err_mm"]) > 1.5, dev if max(k["err_mm"]) <= 1.5 else max(k["err_mm"]), px, k, mar))
        best[f] = min(cand, key=lambda t: (t[0], t[1]))
    kf = {f: best[f][3] for f in range(5)}; px = [best[f][2] for f in range(5)]; err = [max(kf[f]["err_mm"]) for f in range(5)]
    H = np.concatenate([kf[f]["hover"] for f in range(5)]); P = np.array([kf[f]["press"] for f in range(5)])
    bad = 0; self_c = 0
    for f in [None] + list(range(5)):                      # all hovering, then each finger pressing its key fully down
        q = H.copy(); d.qpos[:] = 0
        if f is not None: q[4 * f:4 * f + 4] = P[f]; d.qpos[m.jnt_qposadr[mujoco.mj_name2id(m, mujoco.mjtObj.mjOBJ_JOINT, f"key_{keys[f]}")]] = pc.TW
        d.qpos[qa] = q; mujoco.mj_forward(m, d)
        for i in range(d.ncon):
            b1 = m.body(m.geom_bodyid[d.contact[i].geom1]).name; b2 = m.body(m.geom_bodyid[d.contact[i].geom2]).name
            k1, k2 = b1.startswith("key_") or b1 == "piano", b2.startswith("key_") or b2 == "piano"
            if k1 and k2: continue
            if k1 or k2:
                hb = b2 if k1 else b1; kb = b1 if k1 else b2
                bad += 0 if (f is not None and pc.FINGERS[f] in hb and ("distal" in hb or "tip_sensor" in hb) and kb == f"key_{keys[f]}") else 1
            else: self_c += 1
    d.qpos[:] = 0; d.qpos[qa] = P.reshape(-1); mujoco.mj_forward(m, d)
    kn = [d.xanchor[mujoco.mj_name2id(m, mujoco.mjtObj.mjOBJ_JOINT, "r_thumb_cmc_flex" if f == 0 else f"r_{pc.FINGERS[f]}_mcp_flex")] for f in range(5)]
    fwd = [float(kn[f][0] - d.site(f"r_{pc.FINGERS[f]}_tip").xpos[0]) for f in range(5)]
    return dict(c=c[:4], ok=True, px=px, err_mm=err, margin=min(best[f][4] for f in range(5)), dev=float(np.mean([best[f][1] for f in range(1, 5)])) if max(err) <= 1.5 else 9.0,
                curl=float(np.mean(P[1:, 2] + P[1:, 3])), dip_max=float(P[1:, 3].max()), lean_max=float(np.abs(P[1:, 1]).max()), bad_contacts=bad, self_contacts=self_c,
                reach_mm=[round(v * 1000) for v in fwd], knuckle_z_mm=[round(float(k[2]) * 1000) for k in kn], press=[[round(float(v), 2) for v in r] for r in P])

if __name__ == "__main__":
    ap = argparse.ArgumentParser(); ap.add_argument("--keys", default="72,74,76,77,79"); ap.add_argument("--workers", type=int, default=12); ap.add_argument("--out", default=os.path.join(HERE, "out/sweep_pose.json"))
    ap.add_argument("--x", default="0.25,0.27,0.29,0.31"); ap.add_argument("--z", default="0.06,0.075,0.09,0.105"); ap.add_argument("--theta", default="0,8,16")
    ap.add_argument("--dy", default="0,0.010"); A = ap.parse_args()
    keys = [int(k) for k in A.keys.split(",")]; fl = lambda s: [float(v) for v in s.split(",")]
    C = [(*c, keys) for c in itertools.product(fl(A.x), fl(A.z), fl(A.theta), fl(A.dy))]; print(len(C), "mounts", flush=True)
    with Pool(A.workers) as p: R = p.map(evaluate, C, chunksize=1)
    os.makedirs(os.path.dirname(A.out), exist_ok=True); json.dump(R, open(A.out, "w"))
    ok = [r for r in R if r["ok"] and max(r["err_mm"]) <= 1.5 and r["bad_contacts"] == 0 and r["margin"] >= 0.095]
    print(f"{len(ok)} of {len(R)} mounts: all five keys reached, every joint >= 0.10 rad from its stops, only fingertips on the keys")
    ok.sort(key=lambda r: r["dev"] + 0.2 * r["self_contacts"])
    print("   x      z   pitch   dy   | off-relaxed  pip+dip  tip max  lean max  self | knuckle-to-tip mm    knuckle height mm   contact point per finger")
    for r in ok[:14]:
        x, z, th, dy = r["c"]; print(f" {x:.3f} {z:.3f} {th:4.0f}  {dy:+.3f} |   {np.degrees(r['dev']):4.0f} deg   {np.degrees(r['curl']):4.0f}    {np.degrees(r['dip_max']):4.0f}     {np.degrees(r['lean_max']):3.0f}     {r['self_contacts']}  | {r['reach_mm']}  {r['knuckle_z_mm']}  {r['px']}")
    if not ok:
        R2 = sorted([r for r in R if r["ok"]], key=lambda r: (max(r["err_mm"]), r["bad_contacts"]))[:8]
        for r in R2: print("  closest:", r["c"], "err per finger", r["err_mm"], "bad contacts", r["bad_contacts"], "margin", round(r["margin"], 2), "px", r["px"])
