"""Shared pieces: 88-key piano + Wuji Hand 2 scene, fingertip IK keyframes, 1 kHz trajectory builder, simulation, onset scoring.

Joint/actuator order everywhere = MJCF actuator order = Wuji SDK flat-20 order
(thumb 0-3: cmc_flex, cmc_abd, mcp, ip; index 4-7, middle 8-11, ring 12-15, pinky 16-19: mcp_flex, mcp_abd, pip, dip),
confirmed against docs.wuji.tech control-guide "Joint Table" and Wuji's own right.replay recording.
"""
import math, os, re, xml.etree.ElementTree as ET
import numpy as np, mujoco

# ---- piano geometry (RoboPianist constants, Kawai regulation manual) ----
W, L, H, SP = 0.0225, 0.15, 0.0225, 0.001          # white key width, length, height, gap
BW, BL, BH, BOFF = 0.01, 0.09, 0.018, 0.0125        # black key
TW, TB = math.atan(0.01 / L), math.atan(0.008 / BL)  # max hinge angle (10 mm / 8 mm travel at the key front)
PITCH = W + SP                                       # 23.5 mm per white key
YMID = 0.5 * 51 * (W + SP)                           # keyboard centre (A0 at y = 0, C8 at y = 51 white keys)
KEY_MODELS = {"piano": (0.5, -0.2), "robopianist": (2.0, -0.01745)}  # (stiffness Nm/rad, springref rad)
ACT_THR = math.radians(0.5)                          # RoboPianist: active within 0.5 deg of the bottom
PRESS_X = 0.115                                      # fingertip contact point, m in front of the key hinge
FINGERS = ["thumb", "index_finger", "middle_finger", "ring_finger", "pinky"]
SHORT = ["thumb", "index", "middle", "ring", "pinky"]
BLACK = {1, 3, 6, 8, 10}

REPO = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))


def write_scene(path, xml):
    """Save a scene with the mesh folder written relative to the file, so a plan folder works on any machine."""
    d = os.path.dirname(os.path.abspath(path))
    xml = re.sub(r'meshdir="([^"]+)"', lambda mo: 'meshdir="%s"' % os.path.relpath(mo.group(1), d).replace(os.sep, "/"), xml, count=1)
    with open(path, "w") as fh: fh.write(xml)


def read_scene(path):
    """Load a saved scene. A relative mesh folder is resolved against the file's folder; an absolute one from
    another machine is mapped onto this checkout's assets/wuji-description."""
    d = os.path.dirname(os.path.abspath(path))
    def fix(mo):
        q = mo.group(1)
        if not os.path.isabs(q): q = os.path.normpath(os.path.join(d, q))
        elif not os.path.isdir(q) and "wuji-description" in q: q = os.path.join(REPO, "assets", "wuji-description" + q.split("wuji-description", 1)[1])
        return 'meshdir="%s"' % q
    with open(path) as fh: return re.sub(r'meshdir="([^"]+)"', fix, fh.read(), count=1)


def is_black(m): return m % 12 in BLACK
def white_index(m): return sum(1 for k in range(21, m) if not is_black(k))
def key_y(m):
    """Key centre along the keyboard. Pitch rises toward +y: with the player at +x (in front of the key fronts) the bass is
    on the player's left, as on a real piano and in RoboPianist. (Versions before 2026-11-13 had this mirrored.)"""
    return (white_index(m) - 0.5) * PITCH if is_black(m) else white_index(m) * PITCH


def hand_paths(root, rev="hand2_2", side="right"):
    base = os.path.join(root, "hand2", rev, "body")
    return os.path.join(base, "mjcf", f"{side}.xml"), os.path.abspath(os.path.join(base, "meshes", side))


# Upper joint stops measured on our real hand (14 Nov, both in-air runs): the shipped model allows 0.698 rad on both.
REAL_LIMITS = {"r_thumb_cmc_abd": (None, 0.44), "r_index_finger_mcp_abd": (None, 0.60)}
def real_limits(side="right"):
    """The same two stops for either hand. They were measured on our RIGHT hand only; for a left hand they are an assumption."""
    return {("l_" + k[2:] if side == "left" else k): v for k, v in REAL_LIMITS.items()}


def build_scene(root, theta=20.0, mount_x=0.0, mount_z=0.09, mount_dy=PITCH, center_key=76, gain=1.0,
                key_model="piano", keys=range(21, 109), rev="hand2_2", side="right", timestep=0.002, approach="front", limits=None):
    """Scene XML. Mount = hand root (arm flange) at (mount_x, key_y(center_key)+mount_dy, mount_z) in the piano frame
    (origin: key hinge line at A0; +x toward the player, key fronts at x = 0.15; +y toward the treble; z = white key top).
    approach="front": hand comes from the player's side like a pianist, fingers point -x, thumb on the bass side.
    approach="back" : hand reaches over the fallboard, fingers point +x, thumb on the TREBLE side.
    Palm down, fingertips pitched down by theta degrees.
    side="left": the left-hand model at the mirrored mount (mirror plane across the keyboard): thumb on the treble side
    for approach="front". The left model is the mirror image of the right one, so equal joint values give mirrored poses."""
    hand_xml, meshdir = hand_paths(root, rev, side)
    st, sr = KEY_MODELS[key_model]
    kx = []
    for m in keys:
        y = key_y(m)
        if is_black(m):
            kx.append(f'<body name="key_{m}" pos="0 {y:.4f} {BOFF}"><joint name="key_{m}" type="hinge" axis="0 1 0" range="0 {TB:.5f}" stiffness="{st}" springref="{sr}" damping="0.05" armature="0.001" solreflimit="0.004 1"/><geom type="box" size="{BL/2} {BW/2} {BH/2}" pos="{BL/2} 0 {-BH/2}" mass="0.02" rgba="0.1 0.1 0.1 1" contype="0" conaffinity="1"/></body>')
        else:
            kx.append(f'<body name="key_{m}" pos="0 {y:.4f} 0"><joint name="key_{m}" type="hinge" axis="0 1 0" range="0 {TW:.5f}" stiffness="{st}" springref="{sr}" damping="0.05" armature="0.001" solreflimit="0.004 1"/><geom type="box" size="{L/2} {W/2} {H/2}" pos="{L/2} 0 {-H/2}" mass="0.04" rgba="0.92 0.92 0.92 1" contype="0" conaffinity="1"/></body>')
    h = ET.parse(hand_xml).getroot()
    hb = [b.get("name") for b in h.iter("body")]
    assets = ET.tostring(h.find("asset"), encoding="unicode")
    defaults = ET.tostring(h.find("default"), encoding="unicode") if h.find("default") is not None else ""
    bodies = "".join(ET.tostring(b, encoding="unicode") for b in h.find("worldbody"))
    acts = h.find("actuator")
    for a in acts:
        a.set("kp", str(float(a.get("kp")) * gain)); a.set("kv", str(float(a.get("kv")) * math.sqrt(gain)))
    for name, (lo, hi) in (limits or {}).items():          # narrower joint ranges, e.g. REAL_LIMITS
        for e, attr in [(j, "range") for j in h.iter("joint") if j.get("name") == name] + [(a, "ctrlrange") for a in acts if a.get("joint") == name]:
            r = [float(v) for v in e.get(attr).split()]; e.set(attr, f"{r[0] if lo is None else lo} {r[1] if hi is None else hi}")
    act = ET.tostring(acts, encoding="unicode")
    pre = "r_" if side == "right" else "l_"
    excl = "".join(f'<exclude body1="{a}" body2="{b}"/>' for a in (pre + "wrist", pre + "mount") for b in hb if b not in (pre + "wrist", pre + "mount"))
    th = math.radians(theta)
    R0 = np.array([[0, 0, -1], [1, 0, 0], [0, -1, 0]], float)
    Ry = np.array([[math.cos(th), 0, math.sin(th)], [0, 1, 0], [-math.sin(th), 0, math.cos(th)]])
    Rz = np.diag([-1.0, -1.0, 1.0]) if approach == "front" else np.eye(3)      # 180 deg about z: fingers toward the fallboard
    Rm = Rz @ Ry @ R0
    if side == "left": Mi = np.diag([1.0, -1.0, 1.0]); Rm = Mi @ Rm @ Mi       # mirror of the right hand's mount
    q = np.zeros(4); mujoco.mju_mat2Quat(q, Rm.flatten())
    my = key_y(center_key) + mount_dy
    return f'''<mujoco model="wuji_piano"><compiler angle="radian" meshdir="{meshdir}"/>
<option timestep="{timestep}" integrator="implicitfast" solver="Newton" iterations="50" tolerance="1e-10"/>
<visual><global offwidth="1280" offheight="720"/><quality shadowsize="4096"/></visual>
{defaults}{assets}<worldbody><light pos="0.7 {key_y(center_key):.3f} 1.1" dir="-0.5 0 -1" diffuse="0.8 0.8 0.8"/><light pos="-0.4 {key_y(center_key):.3f} 0.8" dir="0.5 0 -1" diffuse="0.35 0.35 0.35"/>
<geom name="floor" type="plane" size="3 3 0.1" pos="0.3 {YMID:.3f} -0.75" rgba="0.55 0.55 0.6 1" contype="0" conaffinity="0"/>
<body name="piano"><geom name="bed" type="box" size="0.03 0.65 0.005" pos="0.12 {YMID:.3f} {-H-0.0105-0.005:.4f}" rgba="0.3 0.2 0.1 1" contype="1" conaffinity="0"/>
<geom type="box" size="0.05 0.65 0.02" pos="-0.05 {YMID:.3f} -0.02" rgba="0.12 0.12 0.12 1" contype="0" conaffinity="0"/>
<geom type="box" size="0.1 0.65 0.35" pos="0.075 {YMID:.3f} -0.4" rgba="0.12 0.12 0.12 1" contype="0" conaffinity="0"/>{"".join(kx)}</body>
<body name="hand_mount" pos="{mount_x:.4f} {my:.4f} {mount_z:.4f}" quat="{q[0]:.6f} {q[1]:.6f} {q[2]:.6f} {q[3]:.6f}">{bodies}</body>
</worldbody><contact>{excl}</contact>{act}</mujoco>'''


def build_duo_scene(root, first, second, keys=range(21, 109), **common):
    """One keyboard, two hands. first / second: build_scene keyword sets (theta, mount_x, mount_z, mount_dy, center_key, side, gain, limits).
    Actuators: the first hand's 20, then the second hand's 20. A second hand of the same side gets the name prefix "b_"."""
    import re as _re
    A = build_scene(root, keys=keys, **{**common, **first}); B = build_scene(root, keys=[], **{**common, **second})
    sa, sb = first.get("side", "right"), second.get("side", "right")
    md = _re.search(r'meshdir="([^"]+)"', A).group(1); A = A.replace(f'meshdir="{md}"', f'meshdir="{os.path.dirname(md)}"', 1)
    A = _re.sub(r'file="([^"/]+\.STL)"', lambda mo: f'file="{sa}/{mo.group(1)}"', A)
    cut = lambda x, a, b: x[x.index(a) + len(a): x.index(b)]
    assets = _re.sub(r'file="([^"/]+\.STL)"', lambda mo: f'file="{sb}/{mo.group(1)}"', cut(B, "<asset>", "</asset>")) if sb != sa else ""
    if sb != sa: assets = _re.sub(r'<material [^>]*/>', "", assets)                    # the materials are the same in both models
    i = B.index('<body name="hand_mount"'); body = B[i: B.index("</worldbody>")].replace('name="hand_mount"', 'name="hand_mount_2"', 1)
    excl = cut(B, "<contact>", "</contact>"); act = _re.sub(r"^<actuator[^>]*>|</actuator>$", "", B[B.index("<actuator"): B.index("</mujoco>")].strip())
    if sb == sa:
        ren = lambda x: _re.sub(r'\b(name|joint|body1|body2)="([rl]_)', r'\1="b_\2', x); body, excl, act = ren(body), ren(excl), ren(act)
    A = A.replace("</asset>", assets + "</asset>", 1).replace("</worldbody>", body + "</worldbody>", 1).replace("</contact>", excl + "</contact>", 1)
    k = A.rindex("</actuator>"); return A[:k] + act + A[k:]


def hand_qadr(model):
    """qpos address of each actuator's joint, actuator (= SDK) order."""
    return np.array([model.jnt_qposadr[model.actuator_trnid[i, 0]] for i in range(model.nu)])


def pad_min_z(model, data, finger):
    """Lowest collision-mesh vertex (world z) of a finger's distal + tip-sensor links."""
    zmin = 1e9
    for g in range(model.ngeom):
        bn = model.body(model.geom_bodyid[g]).name
        if finger in bn and ("distal" in bn or "tip_sensor" in bn) and model.geom_contype[g] != 0 and model.geom_type[g] == mujoco.mjtGeom.mjGEOM_MESH:
            mid = model.geom_dataid[g]; v = model.mesh_vert[model.mesh_vertadr[mid]: model.mesh_vertadr[mid] + model.mesh_vertnum[mid]]
            zmin = min(zmin, float((data.geom_xmat[g].reshape(3, 3) @ v.T).T[:, 2].min() + data.geom_xpos[g][2]))
    return zmin


class Keyframer:
    """Per (finger, key): hover / lift / press joint 4-vectors from fingertip IK (mink), pad-referenced heights."""
    def __init__(self, xml, abd_cost=1.5e-2, limit_margin=0.05):
        import mink
        self.mink = mink
        self.model = mujoco.MjModel.from_xml_string(xml); self.data = mujoco.MjData(self.model)
        self.ik = mujoco.MjModel.from_xml_string(xml)
        for j in range(self.ik.njnt):
            n = self.ik.joint(j).name
            if not n.startswith(("r_", "l_")): continue
            self.ik.jnt_range[j] += np.array([limit_margin, -limit_margin])   # stay off the hard stops (real hand: stall / heat)
            if any(s in n for s in ("mcp_flex", "_pip", "_dip")) and "thumb" not in n: self.ik.jnt_range[j, 0] = 0.0   # no hyperextension
        self.qadr = hand_qadr(self.model)
        self.pre = "l_" if mujoco.mj_name2id(self.model, mujoco.mjtObj.mjOBJ_SITE, "l_thumb_tip") >= 0 else "r_"   # left or right hand
        self.q_nom = np.zeros(self.model.nq)
        self.post_cost = np.full(self.model.nv, 5e-3)
        for j in range(self.model.njnt):
            n = self.model.joint(j).name
            if "mcp_abd" in n: self.post_cost[self.model.jnt_dofadr[j]] = abd_cost   # discourage sideways splay
        for i in range(self.model.nu):
            n = self.model.joint(self.model.actuator_trnid[i, 0]).name
            if "thumb" not in n:
                self.q_nom[self.qadr[i]] = 0.35 if "mcp_flex" in n else 0.6 if "_pip" in n else 0.3 if "_dip" in n else 0.0

    def solve(self, targets, q0, iters=200, fixed=None):
        """fixed: {joint_id: value} held during the solve (e.g. wrist slide joints at the planned wrist pose)."""
        mink = self.mink; q0 = q0.copy(); qn = self.q_nom.copy(); saved = {}
        for j, v in (fixed or {}).items():
            a = self.ik.jnt_qposadr[j]; saved[j] = self.ik.jnt_range[j].copy(); self.ik.jnt_range[j] = [v - 1e-6, v + 1e-6]; q0[a] = v; qn[a] = v
        try: return self._solve(targets, q0, qn, iters)
        finally:
            for j, r in saved.items(): self.ik.jnt_range[j] = r

    def _solve(self, targets, q0, qn, iters):
        mink = self.mink
        cfg = mink.Configuration(self.ik); cfg.update(q0)
        tasks = []
        for site, xyz in targets.items():
            t = mink.FrameTask(frame_name=site, frame_type="site", position_cost=1.0, orientation_cost=0.0)
            t.set_target(mink.SE3.from_translation(np.asarray(xyz))); tasks.append(t)
        post = mink.PostureTask(model=self.ik, cost=self.post_cost); post.set_target(qn); tasks.append(post)
        for _ in range(iters):
            v = mink.solve_ik(cfg, tasks, 0.02, solver="daqp", limits=[mink.ConfigurationLimit(self.ik)], damping=1e-3)
            cfg.integrate_inplace(v, 0.02)
        err = {s: float(np.linalg.norm(cfg.get_transform_frame_to_world(s, "site").translation() - np.asarray(x))) for s, x in targets.items()}
        return cfg.q.copy(), err

    def pad(self, q, finger):
        self.data.qpos[:] = q; mujoco.mj_forward(self.model, self.data)
        return float(self.data.site(f"{self.pre}{finger}_tip").xpos[2]) - pad_min_z(self.model, self.data, finger)

    def keyframes(self, pairs, hover_h=0.012, lift_h=0.003, press_d=-0.0085, press_x=PRESS_X, press_overrides=None, fixed=None, q_start=None):
        """pairs: iterable of (finger_index, midi). Returns {(f, m): dict(hover, lift, press, err_mm)} with 4-vectors."""
        out = {}
        for f, m in pairs:
            fin = FINGERS[f]; site = f"{self.pre}{fin}_tip"; x = press_x + (0.0 if not is_black(m) else -0.04)   # black: 15 mm behind its front edge
            ztop = 0.0 if not is_black(m) else BOFF
            q1, _ = self.solve({site: (x, key_y(m), ztop + 0.02)}, self.q_nom if q_start is None else q_start, fixed=fixed)
            pad = self.pad(q1, fin)
            for hh in sorted({hover_h, 0.012, 0.009, 0.006}, reverse=True):   # lower the hover if it is out of reach
                qh, eh = self.solve({site: (x, key_y(m), ztop + hh + pad)}, q1, fixed=fixed)
                pad = self.pad(qh, fin)                                 # re-measure at the hover pose
                qh, eh = self.solve({site: (x, key_y(m), ztop + hh + pad)}, qh, fixed=fixed)
                if eh[site] < 0.003: break
            ql, el = self.solve({site: (x, key_y(m), ztop + lift_h + pad)}, qh, fixed=fixed)
            for th in (0.030, 0.024, 0.018):                          # transit: clear of the black keys (12.5 mm above the whites)
                qt, et = self.solve({site: (x, key_y(m), max(ztop, BOFF) + th + pad)}, qh, fixed=fixed)
                if et[site] < 0.004: break
            pd = (press_overrides or {}).get((f, m), press_d)            # stretched fingers press flat -> deeper target
            qp, ep = self.solve({site: (x, key_y(m), ztop + pd + pad)}, ql, fixed=fixed)
            sl = slice(4 * f, 4 * f + 4); a = self.qadr[sl]
            out[(f, m)] = dict(hover=qh[a].copy(), lift=ql[a].copy(), press=qp[a].copy(), transit=qt[a].copy(),
                               err_mm=[round(eh[site] * 1e3, 1), round(el[site] * 1e3, 1), round(ep[site] * 1e3, 1)], pad_mm=round(pad * 1e3, 1), hover_mm=round(hh * 1e3, 1))
        return out


def cosine_track(waypoints, t):
    """waypoints: list of (time, vector) with nondecreasing times; returns samples at times t (cosine blend between points)."""
    ts = np.array([w[0] for w in waypoints]); Q = np.array([w[1] for w in waypoints]); out = np.empty((len(t), Q.shape[1]))
    j = np.searchsorted(ts, t, side="right") - 1
    for i, (tt, k) in enumerate(zip(t, j)):
        if k < 0: out[i] = Q[0]
        elif k >= len(ts) - 1: out[i] = Q[-1]
        else:
            dt = ts[k + 1] - ts[k]; a = 1.0 if dt <= 0 else (tt - ts[k]) / dt
            out[i] = Q[k] + (Q[k + 1] - Q[k]) * 0.5 * (1 - math.cos(math.pi * min(max(a, 0.0), 1.0)))
    return out


def build_trajectory(notes, fingering, kf, home, lead, rate=1000, pre=1.5, post=1.5, t_down=0.03, t_up=0.03,
                     min_hold=0.05, fast_gap=0.25, press_alpha=None, t_move=0.08, vmax=20.0, lift_rad=0.3):
    """notes: list of dict(on, off, pitch) [s]; fingering: pitch -> finger; kf: Keyframer.keyframes output;
    home: finger -> default midi; lead: per-finger command lead [s] (servo lag compensation);
    press_alpha: per-finger depth scale (1 = IK press, >1 deeper along hover->press), from on-site calibration.
    Returns t [N], q [N,20] (SDK order), and per-note command log."""
    press_alpha = press_alpha or [1.0] * 5
    T = max(n["off"] for n in notes) + pre + post
    t = np.arange(0, T, 1.0 / rate)
    q = np.zeros((len(t), 20)); log = []
    for f in range(5):
        mine = [n for n in notes if fingering[n["pitch"]] == f]
        def P(m): return kf[(f, m)]
        def press_q(m): k = P(m); return k["hover"] + press_alpha[f] * (k["press"] - k["hover"])
        def transit(qh):
            qq = qh.copy(); j = 2 if f == 0 else 0          # thumb: lift at the MCP; fingers: lift at mcp_flex
            qq[j] = max(qq[j] - lift_rad, -0.3); return qq
        first_key = mine[0]["pitch"] if mine else home[f]
        wps = [(0.0, P(first_key)["hover"])]
        for i, n in enumerate(mine):
            m = n["pitch"]; on = n["on"] + pre; off = n["off"] + pre
            nxt = mine[i + 1] if i + 1 < len(mine) else None
            ts = on - lead[f]; last_t, last_q = wps[-1]
            if ts < last_t: ts = last_t                      # late: previous release not done
            tf = ts + t_down
            rel = off - lead[f]
            if nxt is not None: rel = min(rel, nxt["on"] + pre - lead[f] - t_up - 0.005)
            rel = max(rel, tf + min_hold * 0.4, ts + min_hold) if nxt is None else max(rel, tf + 0.01)
            lateral = nxt is not None and nxt["pitch"] != m
            if nxt is not None and nxt["pitch"] == m and nxt["on"] - n["on"] < fast_gap: rq = P(m)["lift"]
            elif lateral: rq = P(nxt["pitch"])["hover"]
            else: rq = P(m)["hover"]
            if ts > last_t: wps.append((ts, last_q))
            wps += [(tf, press_q(m)), (rel, press_q(m))]
            if lateral:      # lift clear of the keys first (base joint up), cross in the air, then descend: a low finger drags the pressed key along
                up_a = transit(P(m)["hover"]); up_b = transit(rq)
                wps += [(rel + t_up, up_a), (rel + t_up + t_move, up_b), (rel + 2 * t_up + t_move, rq)]
            else:
                wps.append((rel + t_up, rq))
            log.append(dict(finger=SHORT[f], pitch=m, on=n["on"], cmd_down=ts - pre, cmd_up=rel - pre))
        q[:, 4 * f:4 * f + 4] = cosine_track(wps, t)
    if vmax:                                             # joint speed limit (rad/s); the lead absorbs the extra lag
        dmax = vmax / rate
        for i in range(1, len(q)): q[i] = q[i - 1] + np.clip(q[i] - q[i - 1], -dmax, dmax)
    return t, q, sorted(log, key=lambda r: r["on"])


def simulate(xml, t, q, dt=0.002, keys=None, settle=0.3, frame_cb=None, fps=30):
    """Play the 1 kHz command q[t] as position targets. Returns sim times, key travel fraction [T, K], key list."""
    model = mujoco.MjModel.from_xml_string(xml); data = mujoco.MjData(model); qa = hand_qadr(model)
    keys = keys or [int(model.joint(j).name[4:]) for j in range(model.njnt) if model.joint(j).name.startswith("key_")]
    kad = np.array([model.jnt_qposadr[model.joint(f"key_{m}").id] for m in keys]); kmax = np.array([model.jnt_range[model.joint(f"key_{m}").id, 1] for m in keys])
    data.qpos[qa] = q[0]; data.ctrl[:] = q[0]
    for _ in range(int(settle / dt)): mujoco.mj_step(model, data)
    n = int(round(t[-1] / dt)); rate = 1.0 / (t[1] - t[0]); frac = np.empty((n, len(keys))); ts = np.arange(n) * dt
    next_frame = 0.0
    for i in range(n):
        data.ctrl[:] = q[min(int(round(ts[i] * rate)), len(q) - 1)]
        mujoco.mj_step(model, data)
        frac[i] = data.qpos[kad] / kmax
        if frame_cb is not None and ts[i] + 1e-9 >= next_frame: frame_cb(model, data, ts[i]); next_frame += 1.0 / fps
    return ts, frac, keys, kmax


def detect_onsets(ts, frac, keys, kmax, release_frac=0.5):
    """Note-on = key reaches the activation band (within 0.5 deg of the bottom); re-arm only after rising above
    release_frac of travel (a real keyboard needs the key to come back up before it retriggers)."""
    ev = []
    act = frac >= (1 - ACT_THR / kmax)[None, :]
    armed = np.ones(len(keys), bool)
    for i in range(len(ts)):
        hit = act[i] & armed
        for k in np.nonzero(hit)[0]: ev.append(dict(t=float(ts[i]), pitch=keys[k]))
        armed &= ~act[i]; armed |= frac[i] < release_frac
    return ev


def score(detected, targets, tol=0.05, offset=0.0):
    """Onset matching: same pitch, |dt| <= tol, greedy by time, one-to-one. targets: dict(on, pitch)."""
    used = set(); matched = []; missed = []
    det = sorted(detected, key=lambda e: e["t"])
    for n in sorted(targets, key=lambda n: n["on"]):
        best = None
        for j, e in enumerate(det):
            if j in used or e["pitch"] != n["pitch"]: continue
            d = e["t"] - offset - n["on"]
            if abs(d) <= tol and (best is None or abs(d) < abs(best[1])): best = (j, d)
        if best is None: missed.append(n)
        else: used.add(best[0]); matched.append((n, best[1]))
    extra = [e for j, e in enumerate(det) if j not in used]
    p = len(matched) / max(len(det), 1); r = len(matched) / max(len(targets), 1); f1 = 2 * p * r / max(p + r, 1e-9)
    dts = np.array([d for _, d in matched]) if matched else np.zeros(1)
    return dict(precision=p, recall=r, f1=f1, n_target=len(targets), n_detected=len(det), n_matched=len(matched),
                timing_ms=dict(median=float(np.median(dts) * 1e3), p90_abs=float(np.percentile(np.abs(dts), 90) * 1e3)),
                missed=missed, extra=extra, matched=matched)
