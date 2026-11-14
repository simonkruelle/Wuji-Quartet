"""SBTO-style domain-randomised CEM for piano plans (Wuji Hand 2, MuJoCo), receding horizon.

Decision variables (sampled by CEM, per window of 0.5 s of music):
  per note : [dt_on, dt_off, log depth, d_abd, d_flex]   timing, press depth, lateral and fore-aft correction of the stroke
  per knot : [dy, dz] wrist residual every 0.2 s         (moving wrist only)
Every sample is rolled out on EVERY training plant (mount error, servo stiffness) and ranked by the mean cost,
so no sample is ranked on a lucky plant. Cost = missed notes, onset timing, wrong notes, keys pushed outside
their note, small regulariser.

Wrist modes
  fixed : hand bolted at the best mount from sweep_mount.py (front approach, 25 deg, 10 cm, over D5)
  human : 3 stiff slide axes (an ideal arm) follow the pianist's wrist from FürElise, mapped onto this keyboard
  plan  : same axes; hand positions planned from the notes (dynamic programming), for pieces without human data

usage:
  python scripts/sbto_piano.py --piece k265 --wrist fixed --out out/sbto_k265_fixed
  python scripts/sbto_piano.py --piece k265 --wrist human --out out/sbto_k265_human
  python scripts/sbto_piano.py --piece furelise --wrist plan --out out/sbto_furelise
  python scripts/sbto_piano.py --piece ode --wrist fixed --out out/sbto_ode_fixed          # five-finger position, no stretch
  python scripts/sbto_piano.py --piece my_recording.mid --wrist plan --out out/sbto_mine   # any single-line melody
"""
import argparse, json, math, os, pickle, sys, time
import numpy as np, mujoco
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import piano_core as pc
from midi_io import read_notes, write_notes, note_name

HERE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
WUJI = os.path.join(HERE, "assets/wuji-description")
BASE = dict(theta=25.0, x=0.22, z=0.10, dy=-pc.PITCH)            # best fixed mount, sweep_front_gain5.json
U_BASE = pc.key_y(76) / pc.PITCH + BASE["dy"] / pc.PITCH         # mount position in white keys (= D5)
OFF = np.array([-1.0, 0.0, 1.0, 2.0, 3.0])                         # finger rest position vs mount, white keys
PRE, POST, VMAX = 1.5, 1.0, 20.0
T_DOWN, T_UP, T_MOVE, FAST, LIFT_RAD = 0.03, 0.03, 0.08, 0.25, 0.3
START_HOVER = False                                                # --start-hover: fingers wait at their hover pose, not curled up in the transit pose
WRIST_KP, WRIST_KV, KNOT_DT = 20000.0, 320.0, 0.2
SD0 = np.array([0.02, 0.03, 0.08, 0.06, 0.05]); LO = np.array([-0.06, -0.08, -0.3, -0.25, -0.2]); HI = -LO
WSD0 = np.array([0.004, 0.003]); WLO = np.array([-0.02, -0.01]); WHI = -WLO
W_T, W_MISS, W_SHORT, W_WRONG, W_DENSE, W_REG = 20.0, 3.0, 4.0, 4.0, 5.0, 0.01
TRAIN_PLANTS = [dict(gain=5.0), dict(gain=2.5, dz=0.002), dict(gain=10.0, dz=-0.002),
                dict(gain=5.0, dy=0.002, dth=1.5), dict(gain=4.0, dy=-0.002, dth=-1.5)]
MILD_PLANTS = [dict(gain=5.0), dict(gain=3.5, dz=0.001), dict(gain=7.0, dz=-0.001),
               dict(gain=5.0, dy=0.001, dth=0.5), dict(gain=5.0, dy=-0.001, dth=-0.5)]
TEST_PLANTS = [dict(gain=3.5, dz=-0.001, dy=0.001), dict(gain=7.0, dz=0.001, dy=-0.001, dth=-1.0),
               dict(gain=5.0, dz=0.002, dy=-0.002), dict(gain=3.0), dict(gain=6.0, dth=1.0, dz=-0.0015)]


def widx(m): return pc.key_y(m) / pc.PITCH


# ------------------------------------------------------------------ scene
PRESS_X_F = {}      # finger -> contact point along the key (m from the hinge); empty = pc.PRESS_X for all (--press-x)
LIMITS = None       # joint ranges narrower than the shipped model, e.g. pc.REAL_LIMITS (--real-limits)


def scene_xml(gain, keys, wrist, dx=0.0, dy=0.0, dz=0.0, dth=0.0):
    xml = pc.build_scene(WUJI, theta=BASE["theta"] + dth, mount_x=BASE["x"] + dx, mount_z=BASE["z"] + dz,
                         mount_dy=BASE["dy"] + dy, gain=gain, keys=keys, approach="front", limits=LIMITS)
    if not wrist: return xml
    tag = '<body name="hand_mount" pos="'; i = xml.index(tag); j = xml.index('"', i + len(tag)); pos = xml[i + len(tag): j]
    k = xml.index("</worldbody>")
    inner = xml[i:k].replace(f'{tag}{pos}"', f'{tag}0 0 0"', 1)
    joints = "".join(f'<joint name="wrist_{a}" type="slide" axis="{ax}" range="{r}" damping="1"/>'
                     for a, ax, r in (("x", "1 0 0", "-0.15 0.15"), ("y", "0 1 0", "-0.9 0.9"), ("z", "0 0 1", "-0.1 0.1")))
    xml = xml[:i] + f'<body name="wrist_base" pos="{pos}"><inertial pos="0 0 0" mass="0.5" diaginertia="0.001 0.001 0.001"/>{joints}{inner}</body>' + xml[k:]
    acts = "".join(f'<position name="wrist_{a}" joint="wrist_{a}" kp="{WRIST_KP}" kv="{WRIST_KV}" ctrlrange="{r}" forcerange="-300 300"/>'
                   for a, r in (("x", "-0.15 0.15"), ("y", "-0.9 0.9"), ("z", "-0.1 0.1")))
    return xml.replace("</actuator>", acts + "</actuator>")


# ------------------------------------------------------------------ pieces
def load_piece(name, t_end=None):
    if name == "k265":
        n = [x for x in read_notes(os.path.join(HERE, "assets/furelise/15/midi.mid")) if x["on"] < (t_end or 35) and x["pitch"] >= 71]
        title = "Mozart K.265 theme"
    elif name == "furelise":
        n = [x for x in read_notes(os.path.join(HERE, "assets/fur_elise_beethoven/fur_elise.mid")) if x["track"] == 1 and x["on"] < (t_end or 25.3)]
        title = "Beethoven Für Elise, opening"
    elif name == "ode":
        n = read_notes(os.path.join(HERE, "assets/ode_to_joy/ode_to_joy.mid")); title = "Beethoven Ode to Joy"
        if t_end: n = [x for x in n if x["on"] < t_end]
    elif name.endswith((".mid", ".midi")):       # any melody: one note at a time; --t-end cuts it
        n = sorted(read_notes(name), key=lambda x: x["on"]); title = os.path.splitext(os.path.basename(name))[0]
        if t_end: n = [x for x in n if x["on"] < n[0]["on"] + t_end]
    else: raise SystemExit(f"unknown piece {name}: use k265, furelise, ode or a path to a .mid file")
    t0 = n[0]["on"]
    return [dict(on=x["on"] - t0, off=x["off"] - t0, pitch=x["pitch"]) for x in n], title, t0


def human_wrist_u(notes, t0, fps=59.94):
    """Pianist's right wrist (FürElise piece 15) along this keyboard, in white keys, + the offset that best fits the
    Wuji finger layout. Cached in assets/furelise/15/wrist_u.npz (the 600 MB motion file is only needed once)."""
    cache = os.path.join(HERE, "assets/furelise/15/wrist_u.npz")
    if os.path.exists(cache):
        z = np.load(cache); t, idx = z["t"], z["idx"]
    else:
        ALLOWED = {("numpy.core.multiarray", "_reconstruct"), ("numpy._core.multiarray", "_reconstruct"), ("numpy", "ndarray"), ("numpy", "dtype"),
                   ("numpy.core.multiarray", "scalar"), ("numpy._core.multiarray", "scalar")}
        class Safe(pickle.Unpickler):
            def find_class(self, m, n):
                if (m, n) in ALLOWED: return super().find_class(m, n)
                raise pickle.UnpicklingError("blocked")
        J = Safe(open(os.path.join(HERE, "assets/furelise/15/motion.pkl"), "rb")).load()["right"]["joints"].astype(float)
        allm = [x for x in read_notes(os.path.join(HERE, "assets/furelise/15/midi.mid")) if x["pitch"] >= 71 and x["on"] < 35]
        fr = lambda tt: min(int(round(tt * fps)), len(J) - 1); TIPS = [4, 8, 12, 16, 20]
        wi = np.array([pc.white_index(x["pitch"]) for x in allm], float); A = np.c_[np.ones_like(wi), wi]; up = np.array([0, 0, 1.0])
        low = np.array([J[fr(x["on"]) + 2][TIPS][np.argmin(J[fr(x["on"]) + 2][TIPS][:, 2])] for x in allm])
        for _ in range(4):
            coef, *_ = np.linalg.lstsq(A, low, rcond=None); b = coef[1]; kax = b - (b @ up) * up; kax /= np.linalg.norm(kax); pred = A @ coef
            low = np.array([J[fr(x["on"]) + 2][TIPS][np.argmin(np.abs((J[fr(x["on"]) + 2][TIPS] - pred[k]) @ kax) + 0.5 * (J[fr(x["on"]) + 2][TIPS][:, 2] - J[fr(x["on"]) + 2][TIPS][:, 2].min()))] for k, x in enumerate(allm)])
        a = coef[0]; t = np.arange(len(J)) / fps; idx = ((J[:, 0] - a) @ kax) / (b @ kax)   # wrist in white-key units
        np.savez_compressed(cache, t=t, idx=idx, key_pitch_mm=abs(b @ kax) * 1000)
    tn = np.array([n["on"] for n in notes]) + t0
    w = np.interp(tn, t, idx); wn = np.array([widx(n["pitch"]) for n in notes])
    cs = np.arange(-6, 6, 0.05); fit = [np.sum(np.min(np.abs(wn[:, None] - (w[:, None] + c + OFF[None, :])), axis=1)) for c in cs]
    c = cs[int(np.argmin(fit))]
    un = [w[0] + c]
    for x in w[1:] + c: un.append(float(x) if abs(x - un[-1]) > 0.3 else un[-1])     # follow the pianist, 0.3-key dead band
    return np.array(un), dict(offset_keys=float(c), mean_abs_reach_keys=float(np.min(fit) / len(notes)), moves=int(np.sum(np.diff(un) != 0)))


def planned_wrist_u(notes):
    """Hand positions by dynamic programming: every note within reach, few and slow moves, no thumb on black keys."""
    wn = np.array([widx(n["pitch"]) for n in notes]); us = np.arange(math.floor(wn.min()) - 4, math.ceil(wn.max()) + 3)
    def reach(i, u):
        d = np.abs(wn[i] - (u + OFF)); f = int(np.argmin(d)); c = d[f] * 2.0
        if d[f] > 0.6: c += 100
        if f == 0 and pc.is_black(notes[i]["pitch"]): c += 2
        return c
    C = np.array([[reach(i, u) for u in us] for i in range(len(notes))]); D = C[0].copy(); back = []
    for i in range(1, len(notes)):
        dt = max(notes[i]["on"] - notes[i - 1]["on"], 0.05)
        trans = np.abs(us[:, None] - us[None, :]) * (1 + 0.2 / dt)                    # [prev, cur]
        tot = D[:, None] + trans; b = np.argmin(tot, axis=0); back.append(b); D = tot[b, np.arange(len(us))] + C[i]
    path = [int(np.argmin(D))]
    for b in reversed(back): path.append(int(b[path[-1]]))
    un = us[np.array(path[::-1])].astype(float)
    return un, dict(moves=int(np.sum(np.diff(un) != 0)))


def schedule_wrist(notes, un):
    """Wrist holds still while keys are down and moves between notes (cosine, lifted 8 mm). Notes still sounding when a
    move starts are released early (cap). Returns t, u(t) in white keys, z bump (m), release cap per note (music time)."""
    tt = np.arange(0, notes[-1]["off"] + 1.0, 0.001); u = np.full(len(tt), un[0]); zb = np.zeros(len(tt)); cap = np.full(len(notes), np.inf)
    for i in range(1, len(notes)):
        if abs(un[i] - un[i - 1]) < 1e-9: continue
        g = notes[i]["on"] - notes[i - 1]["on"]; rel = notes[i - 1]["on"] + max(0.06, 0.35 * g)
        t_beg = rel + 0.03; t_end = max(t_beg + 0.04, notes[i]["on"] - 0.06)
        for j in range(i):
            if notes[j]["off"] > rel: cap[j] = min(cap[j], max(notes[j]["on"] + 0.06, rel))
        m = (tt >= t_beg) & (tt < t_end); a = (tt[m] - t_beg) / (t_end - t_beg)
        u[m] = un[i - 1] + (un[i] - un[i - 1]) * 0.5 * (1 - np.cos(np.pi * a)); u[tt >= t_end] = un[i]
        zb[m] = np.maximum(zb[m], 0.008 * np.sin(np.pi * a))
    return tt, u, zb, cap


def assign_fingers(notes, u_at):
    fing = []; last = {}
    for i, n in enumerate(notes):
        d = np.abs(widx(n["pitch"]) - (u_at[i] + OFF)); cost = d.copy()
        if pc.is_black(n["pitch"]): cost[0] += 1.0
        for f in range(5):
            if f in last and last[f][1] != n["pitch"] and n["on"] - last[f][0] < 0.25: cost[f] += 0.8
        cost[d > 0.75] += 50
        f = int(np.argmin(cost)); fing.append(f); last[f] = (n["on"], n["pitch"])
    return fing


# ------------------------------------------------------------------ keyframes per note (IK at the wrist pose of that note)
def note_keyframes(notes, fing, u_note, wrist, gain=5.0):
    keys = sorted({n["pitch"] for n in notes}); kr = list(range(max(21, keys[0] - 7), min(108, keys[-1] + 7) + 1))
    kfr = pc.Keyframer(scene_xml(gain, kr, wrist))
    fixed_j = {}
    if wrist:
        for a in ("x", "y", "z"):
            j = kfr.model.joint(f"wrist_{a}").id; fixed_j[a] = j; kfr.post_cost[kfr.model.jnt_dofadr[j]] = 0.0
    cache = {}; out = []
    for n, f, u in zip(notes, fing, u_note):
        m = n["pitch"]; rel_mm = int(round((widx(m) - u) * pc.PITCH * 1000)) if wrist else m
        key = (f, pc.is_black(m), rel_mm)
        if key not in cache:
            if wrist:   # solve at the true pose: slides hold the wrist offset of this note
                fx = {fixed_j["x"]: 0.0, fixed_j["y"]: (u - U_BASE) * pc.PITCH, fixed_j["z"]: 0.0}
                kf = kfr.keyframes([(f, m)], fixed=fx, hover_h=0.016)[(f, m)]
            else:
                kf = kfr.keyframes([(f, m)], press_overrides={(4, 81): -0.013}, press_x=PRESS_X_F.get(f, pc.PRESS_X))[(f, m)]
            cache[key] = kf
        out.append(cache[key])
    return out, kr, len(cache)


# ------------------------------------------------------------------ plan: params -> 1 kHz commands
def cos_interp(wt, wq, t):
    k = np.clip(np.searchsorted(wt, t, side="right") - 1, 0, len(wt) - 2); t0 = wt[k]; dt = wt[k + 1] - t0
    a = np.clip(np.where(dt > 0, (t - t0) / np.where(dt > 0, dt, 1.0), 1.0), 0.0, 1.0); s = 0.5 * (1 - np.cos(np.pi * a))
    out = wq[k] + (wq[k + 1] - wq[k]) * s[:, None]
    out[t >= wt[-1]] = wq[-1]; return out


class Plan:
    def __init__(self, notes, fing, kf, lead, wrist_tu=None, sag=0.0):
        self.notes, self.fing, self.kf, self.lead = notes, fing, kf, np.asarray(lead, float)
        self.on = np.array([n["on"] for n in notes]) + PRE; self.off = np.array([n["off"] for n in notes]) + PRE
        self.pitch = np.array([n["pitch"] for n in notes]); self.T = self.off.max() + POST
        self.byf = [[i for i in range(len(notes)) if fing[i] == f] for f in range(5)]
        self.wrist = wrist_tu is not None; self.sag = sag
        self.cap = np.full(len(notes), np.inf)
        if self.wrist:
            tt, u, zb, cap = wrist_tu; self.wt = tt + PRE; self.wu = u; self.wz = zb; self.cap = cap + PRE
            self.knots = np.arange(0, self.T + KNOT_DT, KNOT_DT); self.mcum = np.concatenate([[0], np.cumsum(zb > 0)])
        else: self.knots = np.zeros(0)
        self.n_dim = 20 + (3 if self.wrist else 0)

    def moving(self, t0, t1):
        if not self.wrist or t1 <= t0: return False
        i0, i1 = np.searchsorted(self.wt, [t0, t1]); return self.mcum[min(i1, len(self.mcum) - 1)] > self.mcum[min(i0, len(self.mcum) - 1)]

    def finger_wps(self, f, P):
        idx = self.byf[f]; kf = self.kf
        if not idx: return None
        def hov(i): q = kf[i]["hover"].copy(); q[1] += P[i, 3]; return q
        def lift(i): q = kf[i]["lift"].copy(); q[1] += P[i, 3]; return q
        def prs(i):
            h = kf[i]["hover"]; a = float(np.clip(np.exp(P[i, 2]), 0.7, 1.6)); q = h + a * (kf[i]["press"] - h); q[1] += P[i, 3]; q[0] += P[i, 4]; return q
        def trn(i): q = kf[i]["transit"].copy(); q[1] += P[i, 3]; return q          # IK pose 18-30 mm above the black keys
        q_start = hov(idx[0]) if (START_HOVER and not self.wrist) else trn(idx[0])
        wl = [(0.0, q_start)]                           # start lifted, descend before the first stroke (speed-limited)
        t_first = self.on[idx[0]] - self.lead[f] + P[idx[0], 0]
        d_desc = max(T_UP, (math.pi / 2) * float(np.max(np.abs(hov(idx[0]) - q_start))) / VMAX)
        wl.append((max(0.3, t_first - 0.05 - d_desc), q_start)); wl.append((wl[-1][0] + d_desc, hov(idx[0])))
        def add(t, q):
            t0, q0 = wl[-1]; t = max(t, t0 + (math.pi / 2) * float(np.max(np.abs(q - q0))) / VMAX); wl.append((t, q))
        for k, i in enumerate(idx):
            j = idx[k + 1] if k + 1 < len(idx) else None
            ts = self.on[i] - self.lead[f] + P[i, 0]
            if ts > wl[-1][0]: wl.append((ts, wl[-1][1]))
            add(ts + T_DOWN, prs(i))
            rel = min(self.off[i], self.cap[i]) - self.lead[f] + P[i, 1]
            if j is not None: rel = min(rel, self.on[j] - self.lead[f] + P[j, 0] - T_UP - 0.005)
            rel = max(rel, wl[-1][0] + 0.01); wl.append((rel, wl[-1][1]))
            tsj = (self.on[j] - self.lead[f] + P[j, 0]) if j is not None else 0.0
            if j is None: add(rel + T_UP, hov(i))
            elif self.wrist and (tsj - rel > 0.3 + T_UP or self.moving(rel, tsj)):   # rest or wrist travel: wait in transit
                add(rel + T_UP, trn(i)); add(max(wl[-1][0] + T_MOVE, tsj - T_UP - 0.04), trn(j)); add(wl[-1][0] + T_UP, hov(j))
            elif self.pitch[j] == self.pitch[i] and self.on[j] - self.on[i] < FAST: add(rel + T_UP, lift(i))
            elif self.pitch[j] != self.pitch[i]:
                add(rel + T_UP, trn(i)); add(wl[-1][0] + T_MOVE, trn(j)); add(wl[-1][0] + T_UP, hov(j))
            else: add(rel + T_UP, hov(j))
        return np.array([w[0] for w in wl]), np.array([w[1] for w in wl])

    def commands(self, P, WK, t):
        C = np.zeros((len(t), self.n_dim))
        for f in range(5):
            w = self.finger_wps(f, P)
            if w is None: C[:, 4 * f:4 * f + 4] = 0.0
            else: C[:, 4 * f:4 * f + 4] = cos_interp(w[0], w[1], t)
        if self.wrist:
            u = np.interp(t, self.wt, self.wu)
            C[:, 21] = (u - U_BASE) * pc.PITCH + np.interp(t, self.knots, WK[:, 0])
            C[:, 22] = np.interp(t, self.knots, WK[:, 1]) + np.interp(t, self.wt, self.wz) + self.sag
        return C

    def idle_finger(self, f, P):    # fingers that never play hold their default hover (filled by the caller)
        return not self.byf[f]


# ------------------------------------------------------------------ workers
G = {}
def w_init(plants, plan, keys, default_q):
    G["plan"] = plan; G["keys"] = keys; G["default_q"] = default_q; G["m"] = []; G["d"] = []
    for p in plants:
        m = mujoco.MjModel.from_xml_string(scene_xml(p.get("gain", 5.0), keys, plan.wrist, p.get("dx", 0), p.get("dy", 0), p.get("dz", 0), p.get("dth", 0)))
        G["m"].append(m); G["d"].append(mujoco.MjData(m))
    m = G["m"][0]
    G["kad"] = np.array([m.jnt_qposadr[m.joint(f"key_{k}").id] for k in keys]); G["kmax"] = np.array([m.jnt_range[m.joint(f"key_{k}").id, 1] for k in keys])
    G["thr"] = 1 - pc.ACT_THR / G["kmax"]; G["qa"] = pc.hand_qadr(m)
    # allowed-down intervals per key
    pl = plan; al = {k: [] for k in range(len(keys))}; kpos = {k: i for i, k in enumerate(keys)}
    for i in range(len(pl.pitch)):
        nxt = [j for j in range(i + 1, len(pl.pitch)) if pl.pitch[j] == pl.pitch[i]]; end = pl.off[i] if not nxt else min(pl.off[i], pl.on[nxt[0]] - 0.03)
        al[kpos[pl.pitch[i]]].append((pl.on[i] - 0.10, max(end, pl.on[i] + 0.05) + 0.06))
    G["allowed"] = al


def fill_idle(C, plan):
    for f in range(5):
        if plan.idle_finger(f, None): C[:, 4 * f:4 * f + 4] = G["default_q"][4 * f:4 * f + 4]
    return C


def w_state(pid, P, WK, t_to):
    """Settle at the plan's first command, then roll to t_to (plan time). Returns the state."""
    m, d, pl = G["m"][pid], G["d"][pid], G["plan"]; mujoco.mj_resetData(m, d)
    C0 = fill_idle(pl.commands(P, WK, np.array([0.0])), pl)[0]; d.qpos[G["qa"]] = C0; d.ctrl[:] = C0
    for _ in range(150): mujoco.mj_step(m, d)
    d.time = 0.0; frac = d.qpos[G["kad"]] / G["kmax"]
    st = dict(qpos=d.qpos.copy(), qvel=d.qvel.copy(), act=d.act.copy(), time=0.0, armed=frac < 0.5)
    if t_to > 0: st = w_roll((pid, st, t_to, P, WK, False))[1]
    return st


def w_roll(args):
    pid, st, t_e, P, WK, want_events = args
    m, d, pl = G["m"][pid], G["d"][pid], G["plan"]; dt = m.opt.timestep
    d.qpos[:] = st["qpos"]; d.qvel[:] = st["qvel"]; d.act[:] = st["act"]; d.time = st["time"]; mujoco.mj_forward(m, d)
    n = int(round((t_e - st["time"]) / dt)); t = st["time"] + np.arange(n) * dt
    C = fill_idle(pl.commands(P, WK, t), pl); kad, kmax, thr = G["kad"], G["kmax"], G["thr"]
    F = np.empty((n, len(kad))); armed = st["armed"].copy(); ev = []
    for i in range(n):
        d.ctrl[:] = C[i]; mujoco.mj_step(m, d); fr = d.qpos[kad] / kmax; F[i] = fr
        act = fr >= thr; hit = act & armed
        if hit.any():
            for k in np.nonzero(hit)[0]: ev.append((t[i] + dt, k))
        armed &= ~act; armed |= fr < 0.5
    st2 = dict(qpos=d.qpos.copy(), qvel=d.qvel.copy(), act=d.act.copy(), time=float(d.time), armed=armed)
    return (t + dt, F, ev) if want_events else None, st2


def w_cost(args):
    pid, st, t_e, P, WK, ev_t0, ev_t1 = args
    (t, F, ev), _ = w_roll((pid, st, t_e, P, WK, True))
    pl = G["plan"]; keys = G["keys"]; kpos = {k: i for i, k in enumerate(keys)}; c = 0.0; used = set()
    for i in np.nonzero((pl.on >= ev_t0) & (pl.on <= ev_t1))[0]:
        k = kpos[pl.pitch[i]]; best = None
        for e, (te, ke) in enumerate(ev):
            if ke == k and e not in used and -0.08 <= te - pl.on[i] <= 0.10 and (best is None or abs(te - pl.on[i]) < abs(ev[best][0] - pl.on[i])): best = e
        if best is not None: used.add(best); c += W_T * abs(ev[best][0] - pl.on[i])
        else:
            m = (t >= pl.on[i] - 0.05) & (t <= pl.on[i] + 0.15)
            c += W_MISS + W_SHORT * (1 - (F[m, k].max() if m.any() else 0.0))
    for e, (te, ke) in enumerate(ev):
        if e in used or te < st["time"] + 0.05: continue
        if not any(abs(te - pl.on[i]) <= 0.10 for i in np.nonzero(pl.pitch == keys[ke])[0]): c += W_WRONG
    ok = np.zeros_like(F, bool)
    for k, ivs in G["allowed"].items():
        for a, b in ivs:
            if b >= t[0] and a <= t[-1]: ok[(t >= a) & (t <= b), k] = True
    c += W_DENSE * float(np.sum(np.maximum(F - 0.4, 0) * ~ok)) * (t[1] - t[0])
    return c


# ------------------------------------------------------------------ evaluation of a whole piece
def evaluate(pool, plants_n, P, WK, plan, keys):
    sts = pool.starmap(w_state, [(p, P, WK, 0.0) for p in range(plants_n)])
    res = pool.map(w_roll, [(p, sts[p], plan.T, P, WK, True) for p in range(plants_n)])
    out = []
    for (t, F, ev), _ in res:
        det = [dict(t=te - PRE, pitch=keys[k]) for te, k in ev]
        s = pc.score(det, plan.notes, tol=0.05); out.append((s, det))
    return out


def main():
    ap = argparse.ArgumentParser(); ap.add_argument("--piece", default="k265"); ap.add_argument("--wrist", default="fixed", choices=["fixed", "human", "plan"])
    ap.add_argument("--out", required=True); ap.add_argument("--workers", type=int, default=10); ap.add_argument("--samples", type=int, default=48)
    ap.add_argument("--elites", type=int, default=8); ap.add_argument("--iters", type=int, default=6); ap.add_argument("--commit", type=float, default=0.5)
    ap.add_argument("--t-end", type=float, default=None); ap.add_argument("--max-windows", type=int, default=0, help="debug: stop after N windows")
    ap.add_argument("--dr", default=None, choices=["wide", "mild"], help="default: wide for a fixed wrist (mount +-2 mm, 2.5-10x), mild otherwise")
    ap.add_argument("--mount", default=None, help="measured mount 'x,z,theta,dy' in m, m, deg, m (default 0.22,0.10,25,-0.0235)")
    ap.add_argument("--gain", type=float, default=5.0, help="identified stiffness (sysid_step.py); every plant's gain is scaled by gain/5")
    ap.add_argument("--from-npz", default=None, help="re-export a finished run: reuse its lead, P, WK (no CEM)")
    ap.add_argument("--press-x", default=None, help="contact point per finger, m from the key hinge: thumb,index,middle,ring,pinky (front edge = 0.15; default 0.115 for all)")
    ap.add_argument("--real-limits", action="store_true", help="use the joint stops measured on the real hand (pc.REAL_LIMITS)")
    ap.add_argument("--stroke", type=float, default=None, help="time of one key stroke, down or up, in s (default 0.03 = as fast as the joints allow; 0.09 = gentle)")
    ap.add_argument("--start-hover", action="store_true", help="fixed wrist: fingers wait at their hover pose from the start, instead of curled up until their first note")
    ap.add_argument("--recal-lead", action="store_true", help="with --from-npz: fit the per-finger command lead again (needed after changing --stroke)")
    ap.add_argument("--warm", action="store_true", help="with --from-npz: run the CEM again, starting from that plan")
    ap.add_argument("--seed", type=int, default=0); A = ap.parse_args()
    global LIMITS, T_DOWN, T_UP, START_HOVER
    if A.stroke: T_DOWN = T_UP = A.stroke
    START_HOVER = A.start_hover
    if A.real_limits: LIMITS = pc.REAL_LIMITS
    if A.press_x: PRESS_X_F.update({f: float(v) for f, v in enumerate(A.press_x.split(","))})
    if A.mount: x, z, th, dy = (float(v) for v in A.mount.split(",")); BASE.update(x=x, z=z, theta=th, dy=dy)
    global U_BASE; U_BASE = pc.key_y(76) / pc.PITCH + BASE["dy"] / pc.PITCH
    if A.gain != 5.0:
        for L in (TRAIN_PLANTS, MILD_PLANTS, TEST_PLANTS):
            for p_ in L: p_["gain"] = p_.get("gain", 5.0) * A.gain / 5.0
    os.makedirs(A.out, exist_ok=True); rng = np.random.default_rng(A.seed)
    T_ = time.time(); log = open(os.path.join(A.out, "log.txt"), "a")
    def say(*a):
        s = " ".join(str(x) for x in a); print(s, flush=True); log.write(s + "\n"); log.flush()
    notes, title, t0 = load_piece(A.piece, A.t_end); moving = A.wrist != "fixed"
    if A.wrist == "fixed":
        FIX = {71: 0, 72: 0, 74: 1, 76: 2, 77: 3, 79: 4, 81: 4}
        if any(n["pitch"] not in FIX for n in notes): raise SystemExit("fixed wrist covers B4..A5 only; use --wrist human or plan")
        fing = [FIX[n["pitch"]] for n in notes]; u_note = [U_BASE] * len(notes); wtu = None; winfo = {}
    else:
        un, winfo = human_wrist_u(notes, t0) if A.wrist == "human" else planned_wrist_u(notes)
        tt, u, zb, cap = schedule_wrist(notes, un); u_note = list(un); fing = assign_fingers(notes, u_note); wtu = (tt, u, zb, cap)
    say(f"{title}: {len(notes)} notes, {notes[-1]['off']:.1f} s, wrist {A.wrist} {winfo}; fingers used",
        {pc.SHORT[f]: fing.count(f) for f in range(5)})
    t_ = time.time(); kf, keys, nk = note_keyframes(notes, fing, u_note, moving); say(f"IK keyframes: {nk} distinct strokes in {time.time()-t_:.0f} s; keys {note_name(keys[0])}..{note_name(keys[-1])}")
    sag = 0.0
    if moving:
        m = mujoco.MjModel.from_xml_string(scene_xml(5.0, keys, True)); sag = float(m.body_subtreemass[m.body("wrist_base").id] * 9.81 / WRIST_KP)
    default_q = np.concatenate([kf[next((i for i in range(len(fing)) if fing[i] == f), 0)]["hover"] if f in fing else np.zeros(4) for f in range(5)])
    # idle fingers: hover pose of a neighbour's key would collide; use the hover of their home key at the base mount
    if any(f not in fing for f in range(5)):
        kfr = pc.Keyframer(scene_xml(5.0, keys, False)); home = {0: 72, 1: 74, 2: 76, 3: 77, 4: 79}
        for f in range(5):
            if f not in fing: default_q[4 * f:4 * f + 4] = kfr.keyframes([(f, home[f])], press_x=PRESS_X_F.get(f, pc.PRESS_X))[(f, home[f])]["hover"]
    lead = [0.06] * 5
    plan = Plan(notes, fing, kf, lead, wtu, sag); nN = len(notes); P = np.zeros((nN, 5)); WK = np.zeros((len(plan.knots), 2))
    # --- lead calibration on the nominal plant, in this process (servo lag per finger, like make_theme.py)
    w_init([TRAIN_PLANTS[0]], plan, keys, default_q)
    Zr = np.load(A.from_npz) if A.from_npz else None
    if Zr is not None: lead = list(Zr["lead"]); P = Zr["P"].copy(); WK = Zr["WK"].copy(); say("re-export: lead, P, WK from", A.from_npz)
    for it in range(3 if (Zr is None or A.recal_lead) else 0):
        plan.lead = np.asarray(lead, float)
        (tq, Fq, evq), _ = w_roll((0, w_state(0, P, WK, 0.0), plan.T, P, WK, True))
        s = pc.score([dict(t=te - PRE, pitch=keys[k]) for te, k in evq], notes, tol=0.15 if it < 2 else 0.05)
        per = {f: [] for f in range(5)}
        for n, dd in s["matched"]: per[fing[_note_index(notes, n)]].append(dd)
        say(f"lead iter {it}: lead ms {[round(l*1e3) for l in lead]} -> nominal F1 {s['f1']:.3f} ({s['n_matched']}/{nN}, {len(s['extra'])} wrong)")
        if it < 2: lead = [max(0.0, lead[f] + (float(np.median(per[f])) if per[f] else 0.03)) for f in range(5)]
    plan.lead = np.asarray(lead, float)
    from multiprocessing import Pool
    dr = A.dr or ("wide" if A.wrist == "fixed" else "mild"); plants = TRAIN_PLANTS if dr == "wide" else MILD_PLANTS; K = len(plants)
    say(f"DR set {dr}: {plants}")
    with Pool(A.workers, initializer=w_init, initargs=(plants + TEST_PLANTS, plan, keys, default_q)) as pool:
        base_eval = evaluate(pool, K + len(TEST_PLANTS), np.zeros_like(P), np.zeros_like(WK), plan, keys)
        say("baseline (no CEM) train plants:", [f"{e[0]['n_matched']}/{nN} w{len(e[0]['extra'])}" for e in base_eval[:K]], " test:", [f"{e[0]['n_matched']}/{nN} w{len(e[0]['extra'])}" for e in base_eval[K:]])
        # --- receding-horizon DR-CEM
        T0 = plan.on.min() - 0.05; S = T0 - 0.25
        states = pool.starmap(w_state, [(p, P, WK, S) for p in range(K)])
        sd_note = np.tile(SD0, (nN, 1)); win = 0; t_cem = time.time()
        while (Zr is None or A.warm) and T0 < plan.on.max() + 0.01:
            opt = np.nonzero((plan.on >= T0) & (plan.on < T0 + A.commit))[0]
            kn = np.nonzero((plan.knots >= T0 - 0.3) & (plan.knots < T0 + A.commit))[0] if moving else np.zeros(0, int)
            E = min(T0 + A.commit + 0.35, plan.T)
            if len(opt):
                d_n, d_k = len(opt) * 5, len(kn) * 2
                mu = np.concatenate([P[opt].ravel(), WK[kn].ravel()]); sd = np.concatenate([np.tile(SD0, len(opt)), np.tile(WSD0, len(kn))])
                lo = np.concatenate([np.tile(LO, len(opt)), np.tile(WLO, len(kn))]); hi = -lo; sd0 = sd.copy()
                best_x, best_c = mu.copy(), None; N = A.samples if len(mu) <= 25 else int(A.samples * 1.33)
                for it in range(A.iters):
                    X = np.clip(mu + sd * rng.standard_normal((N, len(mu))), lo, hi); X[0] = mu; X[1] = best_x
                    jobs = []
                    for x in X:
                        P2 = P.copy(); P2[opt] = x[:d_n].reshape(-1, 5); WK2 = WK.copy()
                        if d_k: WK2[kn] = x[d_n:].reshape(-1, 2)
                        for p in range(K): jobs.append((p, states[p], E, P2, WK2, S + 0.1, E - 0.17))
                    cs = np.array(pool.map(w_cost, jobs, chunksize=4)).reshape(N, K).mean(1) + W_REG * np.sum(((X - 0) / sd0) ** 2, axis=1)
                    o = np.argsort(cs); el = X[o[:A.elites]]
                    if best_c is None or cs[o[0]] < best_c: best_c, best_x = float(cs[o[0]]), X[o[0]].copy()
                    if it == 0: c_first = float(cs[0])
                    mu = el.mean(0); sd = np.maximum(0.6 * el.std(0) + 0.4 * sd, 0.15 * sd0)
                P[opt] = best_x[:d_n].reshape(-1, 5)
                if d_k: WK[kn] = best_x[d_n:].reshape(-1, 2)
                say(f"window {win:3d} t {T0-PRE:6.2f} s: {len(opt)} notes, dims {len(best_x):2d}, cost {c_first:6.2f} -> {best_c:6.2f}  [{time.time()-t_cem:.0f} s]")
            S_new = T0 + A.commit - 0.25
            states = [r[1] for r in pool.map(w_roll, [(p, states[p], S_new, P, WK, False) for p in range(K)])]
            T0 += A.commit; S = S_new; win += 1
            if A.max_windows and win >= A.max_windows: break
        say(f"CEM done in {time.time()-t_cem:.0f} s")
        fin = evaluate(pool, K + len(TEST_PLANTS), P, WK, plan, keys)
        say("CEM train plants:", [f"{e[0]['n_matched']}/{nN} w{len(e[0]['extra'])}" for e in fin[:K]], " test:", [f"{e[0]['n_matched']}/{nN} w{len(e[0]['extra'])}" for e in fin[K:]])
        s_nom, det_nom = fin[0]
        say("nominal missed:", [(note_name(n["pitch"]), round(n["on"], 2)) for n in s_nom["missed"]][:40]); say("nominal wrong:", [(note_name(e["pitch"]), round(e["t"], 2)) for e in s_nom["extra"]][:40])
        # --- export
        t = np.arange(0, plan.T, 0.001); C = np.zeros((len(t), plan.n_dim))
        G_local = dict(default_q=default_q)
        C = plan.commands(P, WK, t)
        calib = {}
        if A.wrist == "fixed":       # per-key poses for calibrate_keys.py: each finger's most played key is its home key
            pk = {}
            for n, f, k_ in zip(notes, fing, kf): pk.setdefault((f, n["pitch"]), k_)
            hk = {f: max({m for (g, m) in pk if g == f}, key=lambda m: sum(1 for n, g in zip(notes, fing) if g == f and n["pitch"] == m)) for f in sorted({f for f, _ in pk})}
            calib = dict(home=np.array(sorted(hk.items())), kf_pairs=np.array(sorted(pk)), kf_hover=np.array([pk[k_]["hover"] for k_ in sorted(pk)]), kf_press=np.array([pk[k_]["press"] for k_ in sorted(pk)]))
        for f in range(5):
            if not plan.byf[f]: C[:, 4 * f:4 * f + 4] = default_q[4 * f:4 * f + 4]
        np.savez_compressed(os.path.join(A.out, "theme_q_1khz.npz"), t=t, q=C.astype(np.float32), lead=np.array(lead), gain=A.gain, P=P, WK=WK,
                            mount=np.array([BASE["x"], BASE["dy"], BASE["z"], BASE["theta"]]), approach="front", rev="hand2_2", wrist=A.wrist,
                            home_hover=C[0, :20], notes=np.array([[n["on"], n["off"], n["pitch"]] for n in notes]), pre_roll=PRE, tempo=1.0,
                            fing=np.array([[n["pitch"], f] for n, f in zip(notes, fing)]), title=title,
                            press_x=np.array([PRESS_X_F.get(f, pc.PRESS_X) for f in range(5)]), real_limits=bool(LIMITS), stroke_s=T_DOWN, start_hover=START_HOVER, **calib)
        pc.write_scene(os.path.join(A.out, "scene.xml"), scene_xml(5.0, range(21, 109), moving))
        write_notes(os.path.join(A.out, "target.mid"), [dict(on=n["on"] + PRE, off=n["off"] + PRE, pitch=n["pitch"], vel=70) for n in notes])
        write_notes(os.path.join(A.out, "sim_played.mid"), [dict(on=e["t"] + PRE, off=e["t"] + PRE + 0.2, pitch=e["pitch"], vel=70) for e in det_nom])
        summ = lambda E: [dict(matched=e[0]["n_matched"], wrong=len(e[0]["extra"]), f1=round(e[0]["f1"], 3), timing_ms=e[0]["timing_ms"]) for e in E]
        json.dump(dict(piece=A.piece, title=title, wrist=A.wrist, wrist_info=winfo, notes=nN, lead_ms=[round(l * 1e3, 1) for l in lead],
                       fingers={pc.SHORT[f]: fing.count(f) for f in range(5)}, dr=dr, train_plants=plants, test_plants=TEST_PLANTS,
                       baseline_train=summ(base_eval[:K]), baseline_test=summ(base_eval[K:]), cem_train=summ(fin[:K]), cem_test=summ(fin[K:]),
                       cem=dict(samples=A.samples, elites=A.elites, iters=A.iters, commit_s=A.commit, windows=win), wall_s=round(time.time() - T_)),
                  open(os.path.join(A.out, "report.json"), "w"), indent=1)
        say(f"total {time.time()-T_:.0f} s -> {A.out}")


def _set_lead(lead): G["plan"].lead = np.asarray(lead, float); return 0
def _note_index(notes, n): return next(i for i, x in enumerate(notes) if x is n)


if __name__ == "__main__":
    main()
