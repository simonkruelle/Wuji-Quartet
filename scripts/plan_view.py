"""What the studio's 3D view shows for any plan (or a pair of plans for two hands): the robot hand(s) in simulation on the
nominal setup, the keys they pressed, the SBTO search that made the plan, and, when the piece comes from a FürElise
recording whose hands are prepared, the pianist's two hands on the same keyboard and clock.

usage:
  python scripts/plan_view.py <plan dir> [<second plan dir>] --out view.json     (the studio runs this, once per plan)
  python scripts/plan_view.py --hands 15 --motion <path>/motion.pkl                (once per FürElise piece: its hands -> assets/furelise/15/hands.npz)

Keyboard frame = the simulation's piano frame (piano_core.build_scene), in mm: +x toward the player (key hinge at 0, key fronts
at 150), +y toward the treble (white key i at i * 23.5 mm from A0), z = white key top. The pianist's hands are moved into it
rigidly (no scaling): the keyboard line is fitted to the lowest right-hand fingertip at each melody note-on.
"""
import argparse, ast, json, os, pickle, re, sys
import numpy as np
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import piano_core as pc
from midi_io import read_notes

HERE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
FPS = 30
TIPS = [4, 8, 12, 16, 20]                                    # 21 joints: wrist, then 4 per finger (thumb..pinky), tip last
FINGERS = ["thumb", "index_finger", "middle_finger", "ring_finger", "pinky"]
BONES = [[0, 1], [1, 2], [2, 3], [3, 4], [0, 5], [5, 6], [6, 7], [7, 8], [0, 9], [9, 10], [10, 11], [11, 12],
         [0, 13], [13, 14], [14, 15], [15, 16], [0, 17], [17, 18], [18, 19], [19, 20]]


# ------------------------------------------------------------------ the pianist (FürElise)
def perf_midi(fid):
    for f in (f"assets/furelise/{fid}/midi.mid", f"assets/furelise/midi/{fid}.mid"):
        if os.path.exists(os.path.join(HERE, f)): return os.path.join(HERE, f)
    return None


def make_hands(fid, motion, fps_mocap=59.94, fit_min_pitch=71, fit_t_end=35.0):
    """Both hands of one recorded performance at 30 fps, moved onto the simulation's keyboard. Saved as int16 mm."""
    ok = {("numpy.core.multiarray", "_reconstruct"), ("numpy._core.multiarray", "_reconstruct"), ("numpy", "ndarray"), ("numpy", "dtype"),
          ("numpy.core.multiarray", "scalar"), ("numpy._core.multiarray", "scalar")}

    class Safe(pickle.Unpickler):
        def find_class(self, m, n):
            if (m, n) in ok: return super().find_class(m, n)
            raise pickle.UnpicklingError(f"blocked {m}.{n}")
    with open(motion, "rb") as fh:
        d = Safe(fh).load()
    J = {s: d[s]["joints"].astype(float) for s in ("left", "right")}
    melody = [n for n in read_notes(perf_midi(fid)) if n["on"] < fit_t_end and n["pitch"] >= fit_min_pitch]
    R, info = J["right"], {}
    fr = lambda t: min(int(round(t * fps_mocap)) + 2, len(R) - 1)
    wi = np.array([pc.white_index(n["pitch"]) for n in melody], float)
    A = np.c_[np.ones_like(wi), wi]; up = np.array([0, 0, 1.0])
    tips = np.array([R[fr(n["on"])][TIPS] for n in melody])
    low = tips[np.arange(len(tips)), np.argmin(tips[:, :, 2], 1)]
    for _ in range(4):                                           # as sbto_piano.human_wrist_u: the finger nearest the fitted key line
        coef, *_ = np.linalg.lstsq(A, low, rcond=None); b = coef[1]
        kax = b - (b @ up) * up; kax /= np.linalg.norm(kax); pred = A @ coef
        k = [int(np.argmin(np.abs((tips[i] - pred[i]) @ kax) + 0.5 * (tips[i][:, 2] - tips[i][:, 2].min()))) for i in range(len(tips))]
        low = tips[np.arange(len(tips)), k]
    a = coef[0]; dax = np.cross(up, kax)
    if (R[:, 0] - a).mean(0) @ dax < 0: dax = -dax                                              # +x = the player's side (where the wrist is)
    Rm = np.stack([dax, kax, up]); pitch = abs(b @ kax)
    white = ~np.array([pc.is_black(n["pitch"]) for n in melody])
    loc = (low - a) @ Rm.T; mid = np.median(wi)
    shift = np.array([pc.PRESS_X - np.median(loc[white, 0]), mid * pc.PITCH - mid * pitch, -0.006 - np.median(loc[white, 2])])
    idx = np.clip(np.round(np.arange(int(len(R) / fps_mocap * FPS)) / FPS * fps_mocap).astype(int), 0, len(R) - 1)
    out = {s: np.round(((J[s][idx] - a) @ Rm.T + shift) * 1000).astype(np.int16) for s in ("right", "left")}
    loc_all = ((low - a) @ Rm.T + shift)
    err = loc_all[:, 1] - np.array([pc.key_y(n["pitch"]) for n in melody])
    dst = os.path.join(HERE, f"assets/furelise/{fid}/hands.npz")
    os.makedirs(os.path.dirname(dst), exist_ok=True)
    np.savez_compressed(dst, right=out["right"], left=out["left"], fps=FPS, key_pitch_mm=round(pitch * 1000, 2))
    print(f"{dst}: {len(idx)} frames ({len(idx) / FPS:.0f} s), key pitch {pitch * 1000:.2f} mm, fingertip vs key centre at "
          f"{len(melody)} note-ons: median {np.median(err) * 1000:.1f} mm, 90 % within {np.percentile(np.abs(err), 90) * 1000:.1f} mm; "
          f"{os.path.getsize(dst) / 1e6:.1f} MB")


def furelise_source(piece, depth=0, start=None):
    """The FürElise performance a piece comes from (k265, one of its MIDIs, or a part cut from one): (id, where the cut starts
    in it or None), else None."""
    if not piece or depth > 4: return None
    if piece == "k265": return 15, None
    m = re.match(r"assets/furelise/(?:midi/(\d+)\.mid|(\d+)/midi\.mid)$", piece)
    if m: return int(m.group(1) or m.group(2)), start
    side = os.path.join(HERE, piece[:-4] + ".json") if piece.endswith(".mid") else None
    if side and os.path.exists(side):
        with open(side) as fh:
            info = json.load(fh)
        return furelise_source(info.get("source"), depth + 1, info.get("start") if start is None else start)
    return None


def match_performance(targets, perf, same_pitch=True, near=None):
    """Where in the performance the plan's notes are, and at what tempo: the offset and tempo under which most note-ons line up
    within 40 ms. same_pitch=False for a one-hand version (it may move the tune to other keys); then only offsets within 3 s of
    where the cut starts (near) are tried, since a dense performance has some note within 40 ms of almost any time."""
    tg = sorted((n[0], n[2]) for n in targets); on = np.array([t for t, _ in tg]); tp = np.array([p for _, p in tg])
    perf = sorted(perf, key=lambda n: n["on"]); pon = np.array([n["on"] for n in perf]); pp = np.array([n["pitch"] for n in perf])
    best = (0.0, 0.0, 1.0)
    for tempo in (1.0, 0.75, 0.5):
        offs = np.unique(np.round(pon - tempo * on[0], 3))
        if near is not None: offs = offs[np.abs(offs - near) <= 3.0]
        elif not same_pitch: continue
        for off in offs:
            pred = off + tempo * on
            lo, hi = np.searchsorted(pon, pred - 0.04), np.searchsorted(pon, pred + 0.04, side="right")
            hit = np.mean([hi[i] > lo[i] and (not same_pitch or (pp[lo[i]:hi[i]] == tp[i]).any()) for i in range(len(on))])
            if hit > best[0]: best = (float(hit), float(off), tempo)
    return best


# ------------------------------------------------------------------ the robot
def robot_run(plan):
    """Simulate the plan on the nominal setup (as render_theme does); record the hand's joints and the keys at note-on depth."""
    import mujoco
    Z = np.load(os.path.join(plan, "theme_q_1khz.npz"))
    t, q = Z["t"], Z["q"].astype(float)
    m = mujoco.MjModel.from_xml_string(pc.read_scene(os.path.join(plan, "scene.xml"))); d = mujoco.MjData(m); qa = pc.hand_qadr(m)
    pre = "r_" if mujoco.mj_name2id(m, mujoco.mjtObj.mjOBJ_BODY, "r_wrist") >= 0 else "l_"
    pts = [("body", pre + "wrist")]
    for f in FINGERS:
        pts += [("body", pre + f + "_proximal"), ("body", pre + f + "_middle"), ("body", pre + f + "_distal"), ("site", pre + f + "_tip")]
    ids = [(k, m.body(n).id if k == "body" else m.site(n).id) for k, n in pts]
    keys = [int(m.joint(j).name[4:]) for j in range(m.njnt) if m.joint(j).name.startswith("key_")]
    kad = np.array([m.jnt_qposadr[m.joint(f"key_{k}").id] for k in keys]); kmax = np.array([m.jnt_range[m.joint(f"key_{k}").id, 1] for k in keys])
    d.qpos[qa] = q[0]; d.ctrl[:] = q[0]
    for _ in range(150): mujoco.mj_step(m, d)
    frames, down, onsets = [], [], []
    armed = np.ones(len(keys), bool); dt = m.opt.timestep; nf = 0
    for i in range(int(t[-1] / dt)):
        tt = i * dt
        d.ctrl[:] = q[min(int(round(tt * 1000)), len(q) - 1)]
        mujoco.mj_step(m, d)
        frac = d.qpos[kad] / kmax; act = frac >= 1 - pc.ACT_THR / kmax
        for k in np.nonzero(act & armed)[0]: onsets.append([tt, keys[k]])
        armed &= ~act; armed |= frac < 0.5
        if tt + 1e-9 >= nf / FPS:
            frames.append(np.array([d.xpos[j] if k == "body" else d.site_xpos[j] for k, j in ids]))
            down.append([keys[k] for k in np.nonzero(act)[0]])
            nf += 1
    g = lambda k, dflt: Z[k] if k in Z.files else dflt
    return dict(pre=float(Z["pre_roll"]), t0=float(g("piece_t0", 0.0)), notes=Z["notes"], frames=np.array(frames), down=down, onsets=onsets,
                side="right" if pre == "r_" else "left", wrist=str(g("wrist", "fixed")), gain=float(g("gain", 5.0)), title=str(g("title", "")))


def scores(v):
    rows = ast.literal_eval(v) if isinstance(v, str) else (v or [])
    return [[int(r["matched"]), int(r["wrong"])] for r in rows]


def plan_dir_of(path):
    """A plan folder named in a log line (plans/x, plans/x/theme_q_1khz.npz), if it is another plan with a log."""
    d = path[:-len("/theme_q_1khz.npz")] if path.endswith("/theme_q_1khz.npz") else path
    full = d if os.path.isabs(d) else os.path.join(HERE, d)
    return full if os.path.exists(os.path.join(full, "log.txt")) and os.path.exists(os.path.join(full, "report.json")) else None


def sbto_info(plan, depth=0):
    """The search that made the plan: cost of every step before and after its tries, notes before and after on ten setups.
    A plan re-exported from another plan's result (same notes, e.g. gentler strokes) shows that plan's search; a plan that
    reuses another plan's per-finger parameters (another piece) names the plan whose search found them."""
    rp, lp = os.path.join(plan, "report.json"), os.path.join(plan, "log.txt")
    if not os.path.exists(rp) or depth > 4: return None
    rep = json.load(open(rp))
    log = open(lp).read() if os.path.exists(lp) else ""
    runs = log.split("\ntotal ")
    run = next((r for r in runs if re.search(r"^window\s+\d+", r, re.M)), runs[0])                # the run that searched (a re-export may follow)
    win = [[float(m.group(1)), float(m.group(3)), float(m.group(4)), int(m.group(2))]
           for m in re.finditer(r"^window\s+\d+ t\s+(-?[\d.]+) s: (\d+) notes, dims\s+\d+, cost\s+([\d.]+) ->\s+([\d.]+)", run, re.M)]
    srch = re.search(r"CEM done in (\d+) s", run)
    out = dict(windows=win, n_notes=rep.get("notes"), cem=rep.get("cem") or {}, dr=rep.get("dr"), lead_ms=rep.get("lead_ms"), fingers=rep.get("fingers"),
               wrist_info=rep.get("wrist_info") or {}, search_s=int(srch.group(1)) if srch and win else None, derived_from=None, reuse_from=None, searched_on=None,
               earlier_search=False, warm_from=None,
               before=dict(train=scores(rep.get("baseline_train")), test=scores(rep.get("baseline_test"))),
               after=dict(train=scores(rep.get("cem_train")), test=scores(rep.get("cem_test"))))
    if not win:
        m = re.search(r"^re-export: .* from (\S+)\s*$", log, re.M)
        src = m and plan_dir_of(m.group(1))
        if src and os.path.realpath(src) == os.path.realpath(plan):
            out["earlier_search"] = True                # re-exported from its own earlier search, whose steps are not in this log
        elif src:
            o = sbto_info(src, depth + 1)
            if o and o["windows"]:                     # same notes: that search's steps are this plan's steps
                out.update(windows=o["windows"], cem=o["cem"], search_s=o["search_s"], derived_from=os.path.relpath(src, HERE), searched_on=os.path.relpath(src, HERE))
        m = re.search(r"^start parameters: .* from (\S+)\s*$", log, re.M)
        src = m and plan_dir_of(m.group(1))
        if src and not out["derived_from"]:
            o = sbto_info(src, depth + 1)
            out["reuse_from"] = os.path.relpath(src, HERE)
            out["searched_on"] = (o or {}).get("searched_on") or (os.path.relpath(src, HERE) if o and o["windows"] else None)
    else:
        out["searched_on"] = os.path.relpath(plan, HERE)
        m = re.search(r"^start parameters: .* from (\S+)\s*$", log, re.M)
        src = m and plan_dir_of(m.group(1))
        out["warm_from"] = os.path.relpath(src, HERE) if src else None     # the search started from another plan's parameters
    return out


# ------------------------------------------------------------------ the view
def view(plans):
    hands = [dict(dir=p, rel=os.path.relpath(p, HERE), **robot_run(p)) for p in plans]
    t00 = min(H["t0"] for H in hands)
    for H in hands: H["shift"] = H["t0"] - t00                 # place in the piece: two hands start together as in the score
    t_lo = min(-H["pre"] + H["shift"] for H in hands); t_hi = max(len(H["frames"]) / FPS - H["pre"] + H["shift"] for H in hands)
    T = np.arange(int((t_hi - t_lo) * FPS)) / FPS + t_lo              # music time of every frame, 0 = the first note
    mm = lambda P: np.round(P * 1000).astype(int).reshape(len(P), -1).tolist()
    out_hands, targets = [], []
    for H in hands:
        f = np.clip(np.round((T - H["shift"] + H["pre"]) * FPS).astype(int), 0, len(H["frames"]) - 1)
        notes = [[round(float(a) + H["shift"], 3), round(float(b) + H["shift"], 3), int(c)] for a, b, c in H["notes"]]
        targets += notes
        rp = os.path.join(H["dir"], "report.json")
        piece = json.load(open(rp)).get("piece") if os.path.exists(rp) else None
        out_hands.append(dict(plan=H["rel"], side=H["side"], wrist=H["wrist"], gain=H["gain"], shift=round(H["shift"], 3), pre=H["pre"], piece=piece,
                              points=mm(H["frames"][f]), down=[H["down"][i] for i in f],
                              onsets=[[round(t - H["pre"] + H["shift"], 3), p] for t, p in H["onsets"]], notes=notes, sbto=sbto_info(H["dir"])))
    human = None
    # the performance the piece comes from; a plan that does not say (older report) is tried against every prepared one
    src = next((x for x in (furelise_source(h["piece"]) for h in out_hands) if x is not None), None)
    fid, near = src if src else (None, None)
    prepared = sorted(int(d) for d in os.listdir(os.path.join(HERE, "assets/furelise")) if d.isdigit() and os.path.exists(os.path.join(HERE, f"assets/furelise/{d}/hands.npz")))
    unknown = all(h["piece"] is None for h in out_hands)
    best = None
    for cand in ([fid] if fid is not None else prepared if unknown else []):
        if cand not in prepared or not perf_midi(cand): continue
        perf = read_notes(perf_midi(cand))
        m = match_performance(targets, perf, same_pitch=near is None, near=near)
        if best is None or m[0] > best[0][0]: best = (m, cand, perf)
    if best:
        (hit, off, tempo), fid, perf = best
        hp = os.path.join(HERE, f"assets/furelise/{fid}/hands.npz")
        if hit >= (0.6 if src else 0.8):
            Hz = np.load(hp); fps_h = float(Hz["fps"])
            k = np.clip(np.round((off + tempo * T) * fps_h).astype(int), 0, len(Hz["right"]) - 1)
            p_lo, p_hi = off + tempo * T[0], off + tempo * T[-1]
            tg = {(n[2], round(n[0], 2)) for n in targets}
            pn = []
            for n in perf:
                if n["off"] <= p_lo or n["on"] >= p_hi: continue
                a, b = (n["on"] - off) / tempo, (n["off"] - off) / tempo
                robot_plays = any((n["pitch"], round(a + e, 2)) in tg for e in (-0.02, -0.01, 0.0, 0.01, 0.02))
                pn.append([round(a, 3), round(b, 3), n["pitch"], int(robot_plays), int(n.get("vel", 64))])
            human = dict(furelise_id=fid, offset_s=round(off, 3), tempo=tempo, aligned=round(hit, 3), key_pitch_mm=float(Hz["key_pitch_mm"]),
                         right=Hz["right"][k].reshape(len(k), -1).tolist(), left=Hz["left"][k].reshape(len(k), -1).tolist(), notes=pn,
                         source=dict(dataset="FürElise (Wang et al. 2024)", url="https://huggingface.co/datasets/rcwang/for_elise", licence="CC BY-NC 4.0",
                                     capture="multi-view video → MANO hands, 59.94 fps"))
    return dict(version=2, fps=FPS, start=round(float(T[0]), 3), t_end=round(float(T[-1]), 3), bones=BONES, hands=out_hands, human=human)


def main():
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    ap.add_argument("plans", nargs="*", help="one plan folder, or two for two hands")
    ap.add_argument("--out", default=None)
    ap.add_argument("--hands", type=int, default=None, help="prepare a FürElise piece's hands (needs --motion)")
    ap.add_argument("--motion", default=None, help="that piece's motion.pkl (590 MB for piece 15): python scripts/furelise_peek.py assets/furelise")
    A = ap.parse_args()
    if A.hands is not None:
        return make_hands(A.hands, A.motion or os.path.join(HERE, f"assets/furelise/{A.hands}/motion.pkl"))
    if not 1 <= len(A.plans) <= 2: raise SystemExit("one or two plan folders")
    plans = [p if os.path.isabs(p) else os.path.join(HERE, p) for p in A.plans]
    v = view(plans)
    dst = A.out or os.path.join(HERE, "out/gui/views", "+".join(os.path.basename(p.rstrip("/")) for p in plans) + ".json")
    os.makedirs(os.path.dirname(os.path.abspath(dst)), exist_ok=True)
    tmp = dst + ".tmp"
    with open(tmp, "w") as fh: json.dump(v, fh, separators=(",", ":"))
    os.replace(tmp, dst)
    hm = v["human"]
    print(f"{dst}: {len(v['hands'][0]['points'])} frames, " + ", ".join(f"{h['side']} hand {len(h['onsets'])} note-ons" for h in v["hands"]) +
          (f"; pianist: FürElise {hm['furelise_id']} from {hm['offset_s']:.2f} s at {hm['tempo']:g}x, {hm['aligned'] * 100:.0f} % of note-ons aligned" if hm else "; no pianist recording") +
          f"; {os.path.getsize(dst) / 1e6:.1f} MB")


if __name__ == "__main__":
    main()
