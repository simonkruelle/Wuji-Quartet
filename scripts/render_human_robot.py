"""Presentation video: the recorded pianist's hands and the robot hand that SBTO made from that performance, on the same
simulated piano, same clock, with sound. --layout overlay (default): one top-front view, the pianist's hands see-through
over the robot; --layout side: pianist left, robot right, same camera. Real time first, then a few seconds in 4x slow
motion. The pianist comes from the FürElise motion capture (assets/furelise/<id>/hands.npz, see plan_view.py --hands).

usage: python scripts/render_human_robot.py [plan dir] [--layout overlay|side] [--out docs/media/....mp4] [--test-frame 8.0]
"""
import argparse, json, os, subprocess, sys, wave
import numpy as np, mujoco
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import piano_core as pc, plan_view as pv
from midi_io import read_notes
from PIL import Image, ImageDraw, ImageFont

HERE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
W, H, PW, PH, TOP = 1920, 1080, 960, 810, 96            # frame, one panel, header height (footer = the rest)
FPS, SLOW = 30, 4
FCOL = [(1.0, 0.62, 0.04), (0.20, 0.78, 0.35), (0.04, 0.52, 1.0), (0.69, 0.32, 0.87), (1.0, 0.22, 0.37)]
SKIN, SKIN_DARK = (0.93, 0.74, 0.62), (0.80, 0.58, 0.47)
ORANGE, BLUE = (0.95, 0.61, 0.29), (0.04, 0.52, 1.0)


def font(size, bold=False):
    for f in (f"/usr/share/fonts/truetype/dejavu/DejaVuSans{'-Bold' if bold else ''}.ttf",):
        try: return ImageFont.truetype(f, size)
        except OSError: pass
    return ImageFont.load_default()


# ------------------------------------------------------------------ sound: a simple piano-like tone, stereo by pitch
def piano(sr, f0, dur, vel):
    n = int((dur + 1.6) * sr); t = np.arange(n) / sr
    out = np.zeros(n)
    for k in range(1, 9):
        fk = k * f0 * np.sqrt(1 + 0.0004 * k * k)
        if fk > sr / 2.2: break
        amp = (0.55 + 0.45 * vel) ** (k * 0.5) / k ** 1.1
        decay = (0.9 + 0.7 * k) * (f0 / 440) ** 0.35
        out += amp * np.sin(2 * np.pi * fk * t + 0.3 * k) * (0.65 * np.exp(-t * decay) + 0.35 * np.exp(-t * decay * 0.18))
    out *= np.minimum(1, t / 0.003)
    rel = t > dur
    out[rel] *= np.exp(-(t[rel] - dur) * 9)
    return out * vel


def audio(events, total, sr=44100):
    """events: (time s, pitch, duration s, velocity 0..1, gain)."""
    L = np.zeros(int(total * sr) + sr * 3); R = L.copy()
    for t0, p, d, v, g in events:
        x = g * piano(sr, 440 * 2 ** ((p - 69) / 12), max(0.08, d), v)
        i = int(t0 * sr); n = min(len(x), len(L) - i)
        if n <= 0: continue
        pan = np.clip((p - 40) / 50, 0.15, 0.85)
        L[i:i + n] += x[:n] * np.sqrt(1 - pan); R[i:i + n] += x[:n] * np.sqrt(pan)
    m = max(np.abs(L).max(), np.abs(R).max(), 1e-9)
    return np.stack([L, R], 1) / m * 0.8


# ------------------------------------------------------------------ the pianist's hands as capsules in the MuJoCo scene
BONES = pv.BONES + [[1, 5], [5, 9], [9, 13], [13, 17], [0, 2]]          # + palm links
def radius(a, b):
    if [a, b] in ([1, 5], [5, 9], [9, 13], [13, 17], [0, 2]) or a == 0: return 0.0092
    k = b % 4
    base = 0.0085 if b <= 4 else 0.0074
    return base * {1: 1.0, 2: 1.0, 3: 0.92, 0: 0.84}[k]


def add_geom(scn, kind, size, pos, rgba, frm=None, to=None):
    if scn.ngeom >= scn.maxgeom: return
    g = scn.geoms[scn.ngeom]
    mujoco.mjv_initGeom(g, kind, np.array(size, float), np.array(pos, float), np.eye(3).flatten(), np.array(rgba, np.float32))
    if frm is not None: mujoco.mjv_connector(g, kind, size[0], np.array(frm, float), np.array(to, float))
    scn.ngeom += 1


def draw_hand(scn, J, alpha=1.0):
    for a, b in BONES:
        r = radius(a, b)
        add_geom(scn, mujoco.mjtGeom.mjGEOM_CAPSULE, [r, 0, 0], J[a], (*SKIN, alpha), J[a], J[b])
    for j in range(21):
        if j % 4 == 0 and j: add_geom(scn, mujoco.mjtGeom.mjGEOM_SPHERE, [0.0062, 0, 0], J[j], (*FCOL[(j - 1) // 4], alpha))


def draw_trail(scn, pts, color):
    """pts: [n, 3] oldest first; a fading line of thin capsules."""
    n = len(pts)
    for i in range(1, n):
        a = 0.15 + 0.85 * i / n
        add_geom(scn, mujoco.mjtGeom.mjGEOM_CAPSULE, [0.0016, 0, 0], pts[i], (*color, a), pts[i - 1], pts[i])


# ------------------------------------------------------------------ main
def main():
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    ap.add_argument("plan", nargs="?", default="plans/k265_human")
    ap.add_argument("--layout", choices=["overlay", "side"], default="overlay",
                    help="overlay: one view, the pianist's hands see-through over the robot; side: pianist left, robot right")
    ap.add_argument("--out", default=None, help="default docs/media/k265_pianist_robot_overlay.mp4 (overlay) or k265_pianist_and_robot.mp4 (side)")
    ap.add_argument("--slow", default="5.75,7.6", help="music-time window shown again in 4x slow motion")
    ap.add_argument("--test-frame", type=float, default=None, help="save one frame at this music time (s) and stop")
    ap.add_argument("--cam", default=None, help="lookat x, lookat y offset, lookat z, distance, azimuth, elevation (y offset from the melody's keys)")
    ap.add_argument("--ghost", type=float, default=0.5, help="overlay: opacity of the pianist's hands")
    A = ap.parse_args()
    A.out = A.out or ("docs/media/k265_pianist_robot_overlay.mp4" if A.layout == "overlay" else "docs/media/k265_pianist_and_robot.mp4")
    A.cam = [float(v) for v in (A.cam or ("0.10,-0.12,0.03,0.41,180,-56" if A.layout == "overlay" else "0.10,0,0.03,0.46,232,-26")).split(",")]
    PW_, PH_ = (W, PH) if A.layout == "overlay" else (PW, PH)
    plan = os.path.join(HERE, A.plan) if not os.path.isabs(A.plan) else A.plan
    Z = np.load(os.path.join(plan, "theme_q_1khz.npz")); t_cmd, q = Z["t"], Z["q"].astype(float); pre = float(Z["pre_roll"])
    targets = [[float(a), float(b), int(c)] for a, b, c in Z["notes"]]
    # the pianist: which performance, from where, at what tempo
    rep = os.path.join(plan, "report.json")
    src = pv.furelise_source(json.load(open(rep)).get("piece")) if os.path.exists(rep) else None
    fid = src[0] if src else 15
    perf = read_notes(pv.perf_midi(fid))
    hit, off, tempo = pv.match_performance(targets, perf)
    if hit < 0.6: raise SystemExit(f"the plan's notes do not match FürElise piece {fid} ({hit:.0%})")
    Hz = np.load(os.path.join(HERE, f"assets/furelise/{fid}/hands.npz")); hfps = float(Hz["fps"])
    HR, HL = Hz["right"].astype(float) / 1000, Hz["left"].astype(float) / 1000
    def human(t):                       # both hands at music time t, linear between frames
        x = np.clip((off + tempo * t) * hfps, 0, len(HR) - 1.001); i = int(x); a = x - i
        return (HR[i] * (1 - a) + HR[i + 1] * a).reshape(21, 3), (HL[i] * (1 - a) + HL[i + 1] * a).reshape(21, 3)
    pnotes = [dict(on=(n["on"] - off) / tempo, off=(n["off"] - off) / tempo, pitch=n["pitch"], vel=n.get("vel", 64)) for n in perf]
    tg = {(n[2], round(n[0], 2)) for n in targets}
    for n in pnotes: n["robot"] = any((n["pitch"], round(n["on"] + e, 2)) in tg for e in (-0.02, -0.01, 0, 0.01, 0.02))

    # the scene: slate stage as render_theme.py, large offscreen buffer, collision shells hidden
    xml = pc.read_scene(os.path.join(plan, "scene.xml"))
    xml = xml.replace('<global offwidth="1280" offheight="720"/>', f'<global offwidth="{W}" offheight="{H}"/>')
    xml = xml.replace("<asset>", '<asset><texture type="skybox" builtin="gradient" rgb1="0.30 0.32 0.37" rgb2="0.10 0.11 0.13" width="256" height="256"/>', 1)
    xml = xml.replace('rgba="0.55 0.55 0.6 1"', 'rgba="0.15 0.16 0.19 1"')
    m = mujoco.MjModel.from_xml_string(xml); d = mujoco.MjData(m); d2 = mujoco.MjData(m); qa = pc.hand_qadr(m)
    opt = mujoco.MjvOption(); opt.geomgroup[2] = 0
    keys = [int(m.joint(j).name[4:]) for j in range(m.njnt) if m.joint(j).name.startswith("key_")]
    kad = np.array([m.jnt_qposadr[m.joint(f"key_{k}").id] for k in keys]); kmax = np.array([m.jnt_range[m.joint(f"key_{k}").id, 1] for k in keys])
    kgeom = np.array([m.body_geomadr[m.body(f"key_{k}").id] for k in keys]); base_rgba = m.geom_rgba[kgeom].copy()
    robot_roots = {m.body(n).id for n in ("hand_mount", "wrist_base") if mujoco.mj_name2id(m, mujoco.mjtObj.mjOBJ_BODY, n) >= 0}
    def under(b):
        while b > 0:
            if b in robot_roots: return True
            b = m.body_parentid[b]
        return False
    rgeoms = np.array([g for g in range(m.ngeom) if under(m.geom_bodyid[g])]); robot_rgba = m.geom_rgba[rgeoms].copy()
    side = "r_" if mujoco.mj_name2id(m, mujoco.mjtObj.mjOBJ_BODY, "r_wrist") >= 0 else "l_"
    tips = [m.site(side + f + "_tip").id for f in pv.FINGERS]
    if A.layout == "overlay":                   # seen from above, the black flange plate hides the palm: drop it, palm dark grey
        for b, rgba in ((side + "mount", None), (side + "wrist", (0.22, 0.23, 0.25, 1))):
            for g in range(m.body_geomadr[m.body(b).id], m.body_geomadr[m.body(b).id] + m.body_geomnum[m.body(b).id]):
                if m.geom_group[g] == 1: m.geom_rgba[g] = rgba or (0, 0, 0, 0)
        robot_rgba = m.geom_rgba[rgeoms].copy()
    r = mujoco.Renderer(m, PH_, PW_)
    cam = mujoco.MjvCamera()
    span = [n[2] for n in targets]                          # the keys the robot plays: the camera starts from the melody hand
    yc = 0.5 * (pc.key_y(min(span)) + pc.key_y(max(span)))
    cam.lookat[:] = [A.cam[0], yc + A.cam[1], A.cam[2]]; cam.distance = A.cam[3]; cam.azimuth = A.cam[4]; cam.elevation = A.cam[5]

    big, mid, small = font(34, True), font(22), font(17)
    T_end = max(n[1] for n in targets)
    def footer(img, t, slow):
        g = ImageDraw.Draw(img); y0 = TOP + PH
        g.rectangle([0, y0, W, H], fill=(16, 19, 24))
        x0, x1 = 60, W - 60; X = lambda s: x0 + (x1 - x0) * (s + pre) / (T_end + pre + 0.5)
        for row, (label, col, notes) in enumerate([("pianist", tuple(int(c * 255) for c in ORANGE), [(n["on"], n["off"]) for n in pnotes if n["robot"]]),
                                                    ("robot", tuple(int(c * 255) for c in BLUE), [(a, b) for a, b in robot_notes])]):
            yy = y0 + 28 + row * 30
            g.text((8, yy - 10), label, fill=(170, 182, 194), font=small)
            for a, b in notes:
                if -pre <= a <= T_end + 0.5: g.rectangle([X(a), yy - 7, max(X(a) + 2, X(min(b, a + 0.4))), yy + 7], fill=col)
        g.rectangle([X(t) - 1, y0 + 12, X(t) + 1, y0 + 92], fill=(240, 240, 240))
        g.text((x0, y0 + 108), "Pianist: FürElise motion capture (Wang et al. 2024, CC BY-NC 4.0) · Robot: Wuji Hand 2 in MuJoCo, plan by SBTO; its wrist follows the pianist's on an ideal arm",
               fill=(150, 162, 174), font=small)
        g.text((x0, y0 + 134), "Sound: the keys the robot pressed in simulation + the pianist's left hand (recording)" if not slow else "slow motion 4×, no sound",
               fill=(150, 162, 174), font=small)
        g.text((x1, y0 + 134), f"{max(t, 0):5.1f} s / {T_end:.0f} s", fill=(210, 218, 226), font=mid, anchor="ra")

    def label(g, x, y, head, sub):
        g.rectangle([x + 16, y + 16, x + 30 + g.textlength(head + "  " + sub, font=mid), y + 56], fill=(16, 19, 24))
        g.text((x + 24, y + 22), head, fill=(255, 255, 255), font=font(22, True))
        g.text((x + 24 + g.textlength(head + "  ", font=font(22, True)), y + 22), sub, fill=(190, 200, 210), font=mid)

    def slow_badge(g, cx):                          # on a dark box: the keys under it are white
        bw = g.textlength("slow motion 4×", font=big) + 40
        g.rounded_rectangle([cx - bw / 2, TOP + PH - 78, cx + bw / 2, TOP + PH - 22], radius=10, fill=(16, 19, 24))
        g.text((cx, TOP + PH - 50), "slow motion 4×", fill=(255, 255, 255), font=big, anchor="mm")

    def header(g):
        g.text((40, 26), "From a pianist's hands to a robot hand", fill=(240, 244, 248), font=big)
        g.text((W - 40, 34), "Mozart · K.265, theme (“Twinkle, twinkle”)", fill=(170, 182, 194), font=mid, anchor="ra")

    def frame_overlay(t, slow=False):
        """One view: the robot as simulated, the pianist's hands see-through on top of it. Keys: blue = the robot
        pressed it (simulation), orange = the pianist pressed it and the robot did not (mostly the pianist's left hand)."""
        d2.qpos[:] = d.qpos
        act = d.qpos[kad] >= kmax - pc.ACT_THR
        down_h = {n["pitch"] for n in pnotes if n["on"] <= t < n["off"]}
        for i, k in enumerate(keys):
            if act[i]: m.geom_rgba[kgeom[i]] = (*BLUE, 1)
            elif k in down_h: d2.qpos[kad[i]] = kmax[i]; m.geom_rgba[kgeom[i]] = (*ORANGE, 1)
            else: m.geom_rgba[kgeom[i]] = base_rgba[i]
        mujoco.mj_forward(m, d2)
        r.update_scene(d2, cam, scene_option=opt)
        for fi in range(5):                         # the robot's fingertips: one colour per finger
            pts = np.array(trail_hist[fi][-18:])
            if len(pts) > 1: draw_trail(r.scene, pts, FCOL[fi])
        JR, JL = human(t)
        draw_hand(r.scene, JL, A.ghost); draw_hand(r.scene, JR, A.ghost)
        for fi, j in enumerate(pv.TIPS):            # the pianist's fingertips: the same colours, lighter
            draw_trail(r.scene, np.array([human(t - 0.6 + 0.6 * s / 17)[0][j] for s in range(18)]), tuple(0.55 + 0.45 * c for c in FCOL[fi]))
        img = Image.new("RGB", (W, H), (16, 19, 24))
        img.paste(Image.fromarray(r.render()), (0, TOP))
        g = ImageDraw.Draw(img)
        header(g)
        label(g, 0, TOP, "PIANIST", "see-through skin: recorded hands (motion capture)")
        label(g, 0, TOP + 48, "ROBOT", "Wuji Hand 2 in simulation, retargeted with SBTO")
        kx = W - 40                                  # key colour legend, top right
        for txt, col in [("robot pressed", BLUE), ("pianist pressed", ORANGE)][::-1]:
            w_ = g.textlength(txt, font=mid) + 44
            g.rectangle([kx - w_ - 8, TOP + 16, kx + 8, TOP + 56], fill=(16, 19, 24))
            g.rectangle([kx - w_, TOP + 26, kx - w_ + 22, TOP + 46], fill=tuple(int(c * 255) for c in col))
            g.text((kx - w_ + 32, TOP + 22), txt, fill=(220, 226, 232), font=mid); kx -= w_ + 24
        if slow: slow_badge(g, W // 2)
        footer(img, t, slow)
        return np.asarray(img)

    def frame(t, slow=False):
        """Both panels at music time t (the simulation in d is at t)."""
        if A.layout == "overlay": return frame_overlay(t, slow)
        panels = []
        # pianist: robot hidden, keys follow the recording
        m.geom_rgba[rgeoms, 3] = 0
        d2.qpos[:] = d.qpos
        down_h = {n["pitch"]: n["robot"] for n in pnotes if n["on"] <= t < n["off"]}
        for i, k in enumerate(keys):
            d2.qpos[kad[i]] = kmax[i] if k in down_h else 0.0
            m.geom_rgba[kgeom[i]] = (*ORANGE, 1) if down_h.get(k) else (0.98, 0.82, 0.62, 1) if k in down_h else base_rgba[i]
        mujoco.mj_forward(m, d2)
        r.update_scene(d2, cam, scene_option=opt)
        JR, JL = human(t)
        draw_hand(r.scene, JL); draw_hand(r.scene, JR)
        for fi, j in enumerate(pv.TIPS):
            draw_trail(r.scene, np.array([human(t - 0.6 + 0.6 * s / 17)[0][j] for s in range(18)]), FCOL[fi])
        panels.append(r.render())
        m.geom_rgba[rgeoms] = robot_rgba
        # robot: the simulation as it is
        act = d.qpos[kad] >= kmax - pc.ACT_THR
        m.geom_rgba[kgeom] = np.where(act[:, None], np.array([*BLUE, 1.0]), base_rgba)
        r.update_scene(d, cam, scene_option=opt)
        for fi in range(5):
            pts = np.array(trail_hist[fi][-18:])
            if len(pts) > 1: draw_trail(r.scene, pts, FCOL[fi])
        panels.append(r.render())
        img = Image.new("RGB", (W, H), (16, 19, 24))
        img.paste(Image.fromarray(panels[0]), (0, TOP)); img.paste(Image.fromarray(panels[1]), (PW, TOP))
        g = ImageDraw.Draw(img)
        header(g)
        for x, head, sub in [(0, "PIANIST", "recorded hands, motion capture"), (PW, "ROBOT", "Wuji Hand 2 · simulation · retargeted with SBTO")]:
            label(g, x, TOP, head, sub)
        g.line([(PW, TOP), (PW, TOP + PH)], fill=(16, 19, 24), width=4)
        if slow: slow_badge(g, W // 2)
        footer(img, t, slow)
        return np.asarray(img)

    # simulate the plan (as render_theme.py) and film it
    d.qpos[qa] = q[0]; d.ctrl[:] = q[0]
    for _ in range(150): mujoco.mj_step(m, d)
    trail_hist = [[] for _ in range(5)]
    robot_notes, onsets, down_since = [], [], {}
    dt = m.opt.timestep; n_steps = int(t_cmd[-1] / dt)
    s0, s1 = [float(x) for x in A.slow.split(",")]
    out = os.path.join(HERE, A.out); os.makedirs(os.path.dirname(out), exist_ok=True)
    tmp = out[:-4] + "_v.mp4"
    ff = None if A.test_frame is not None else subprocess.Popen(["ffmpeg", "-y", "-loglevel", "error", "-f", "rawvideo", "-pix_fmt", "rgb24", "-s", f"{W}x{H}",
                                                                 "-r", str(FPS), "-i", "-", "-c:v", "libx264", "-pix_fmt", "yuv420p", "-crf", "18", "-preset", "medium", tmp], stdin=subprocess.PIPE)
    slow_frames, nf, next_trail = [], 0, 0.0
    armed = np.ones(len(keys), bool)
    for i in range(n_steps):
        tt = i * dt; t = tt - pre
        d.ctrl[:] = q[min(int(round(tt * 1000)), len(q) - 1)]; mujoco.mj_step(m, d)
        fr = d.qpos[kad] / kmax; act = fr >= 1 - pc.ACT_THR / kmax
        for k in np.nonzero(act & armed)[0]: onsets.append((t, keys[k])); down_since[keys[k]] = t
        for k in np.nonzero(~act & ~armed & (fr < 0.5))[0]:
            if keys[k] in down_since: robot_notes.append((down_since.pop(keys[k]), t))
        armed &= ~act; armed |= fr < 0.5
        if tt + 1e-9 >= next_trail:
            for fi, s in enumerate(tips): trail_hist[fi].append(d.site_xpos[s].copy())
            next_trail += 0.6 / 17
        if A.test_frame is not None:
            if t >= A.test_frame:
                Image.fromarray(frame(t)).save(out[:-4] + "_test.png"); print("saved", out[:-4] + "_test.png"); return
            continue
        if tt + 1e-9 >= nf / FPS: ff.stdin.write(frame(t).tobytes()); nf += 1
        if s0 <= t <= s1 and i % int(round(1 / (FPS * SLOW * dt))) == 0: slow_frames.append(frame(t, slow=True).tobytes())
    for b in slow_frames: ff.stdin.write(b)
    ff.stdin.close(); ff.wait()
    # sound: the robot's keys (simulation) + the pianist's left hand, then silence under the slow motion
    ev = [(t + pre, p, 0.35, 0.7, 1.0) for t, p in onsets]
    ev += [(n["on"] + pre, n["pitch"], n["off"] - n["on"], n["vel"] / 127, 0.55) for n in pnotes if not n["robot"] and n["pitch"] < 71 and -pre < n["on"] < T_end + 1]
    total = nf / FPS + len(slow_frames) / FPS
    au = audio(ev, total)
    wav = out[:-4] + ".wav"
    with wave.open(wav, "wb") as w:
        w.setnchannels(2); w.setsampwidth(2); w.setframerate(44100); w.writeframes((au * 32767).astype(np.int16).tobytes())
    subprocess.run(["ffmpeg", "-y", "-loglevel", "error", "-i", tmp, "-i", wav, "-c:v", "copy", "-c:a", "aac", "-b:a", "192k", "-shortest", out], check=True)
    os.remove(tmp); os.remove(wav)
    print(f"{out}: {nf} real-time + {len(slow_frames)} slow-motion frames ({total:.1f} s), robot pressed {len(onsets)} keys; pianist from {off:.2f} s at {tempo:g}x")


if __name__ == "__main__":
    main()
