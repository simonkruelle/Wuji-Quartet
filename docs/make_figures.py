"""Renders the README pictures from the real model and a real plan. Only the labels are drawn on top.

  python docs/make_figures.py                  # docs/banner.png, docs/hand.png, docs/setup.png
  python docs/make_figures.py hand             # one of them

Needs a GL backend: MUJOCO_GL=egl (GPU) or MUJOCO_GL=osmesa (software, the Docker image's default)."""
import math, os, sys
import numpy as np, mujoco
from PIL import Image, ImageDraw, ImageFont
HERE = os.path.dirname(os.path.abspath(__file__)); REPO = os.path.dirname(HERE)
sys.path.insert(0, os.path.join(REPO, "scripts"))
import piano_core as pc

WUJI = os.path.join(REPO, "assets/wuji-description")
INK, IVORY, MUTED, GOLD = (24, 26, 32), (245, 242, 234), (176, 180, 192), (232, 184, 86)
SKY = 'rgb1="0.30 0.32 0.37" rgb2="0.12 0.13 0.155"'
SS = 2                                                     # supersampling


def font(name, size):
    for p in (f"/usr/share/fonts/opentype/fira/FiraSans-{name}.otf", f"/usr/share/fonts/truetype/dejavu/DejaVuSans{'-Bold' if name in ('Bold', 'SemiBold', 'Medium') else ''}.ttf"):
        if os.path.exists(p): return ImageFont.truetype(p, size)
    return ImageFont.load_default()


def serif(size):
    for p in ("/usr/share/fonts/truetype/msttcorefonts/Georgia_Bold.ttf", "/usr/share/fonts/truetype/dejavu/DejaVuSerif-Bold.ttf"):
        if os.path.exists(p): return ImageFont.truetype(p, size)
    return ImageFont.load_default()


def stage(xml, w, h, fovy=38, ortho=False):
    """Slate stage: the matte-black palm and the black piano both stay readable. ortho: fovy = picture height in metres."""
    xml = xml.replace('<global offwidth="1280" offheight="720"/>', f'<global offwidth="{w}" offheight="{h}" fovy="{fovy}" orthographic="{"true" if ortho else "false"}"/><headlight ambient="0.24 0.24 0.26" diffuse="0.28 0.28 0.28" specular="0.1 0.1 0.1"/><rgba haze="0.16 0.17 0.20 1"/>')
    xml = xml.replace("<asset>", f'<asset><texture type="skybox" builtin="gradient" {SKY} width="256" height="256"/>', 1)
    return xml.replace('rgba="0.55 0.55 0.6 1"', 'rgba="0.15 0.16 0.19 1"')   # floor


def camera(lookat, distance, azimuth, elevation):
    c = mujoco.MjvCamera(); c.lookat[:] = lookat; c.distance = distance; c.azimuth = azimuth; c.elevation = elevation; return c


def cam_axes(c):
    az, el = math.radians(c.azimuth), math.radians(c.elevation)
    fwd = np.array([math.cos(el) * math.cos(az), math.cos(el) * math.sin(az), math.sin(el)])
    right = np.cross(fwd, [0, 0, 1.0]); right /= np.linalg.norm(right); return fwd, right, np.cross(right, fwd)


def project(c, m, w, h, p):
    """World point -> pixel for a free camera."""
    fwd, right, up = cam_axes(c); v = np.asarray(p, float) - (np.asarray(c.lookat) - c.distance * fwd)
    if m.vis.global_.orthographic: s = h / m.vis.global_.fovy; return np.array([w / 2 + s * (v @ right), h / 2 - s * (v @ up)])
    f = (h / 2) / math.tan(math.radians(m.vis.global_.fovy) / 2)
    return np.array([w / 2 + f * (v @ right) / (v @ fwd), h / 2 - f * (v @ up) / (v @ fwd)])


def render(m, d, cam, w, h):
    r = mujoco.Renderer(m, h * SS, w * SS); o = mujoco.MjvOption(); o.geomgroup[2] = 0     # hide the collision shells
    r.update_scene(d, cam, scene_option=o); im = Image.fromarray(r.render()).resize((w, h), Image.LANCZOS); r.close(); return im


def playing_scene(w, h, t_music=7.45, plan="k265_fixed", fovy=38, ortho=False):
    """The committed K.265 plan, simulated up to a moment with a key down (C5 held from 7.10 to 7.64 s)."""
    Z = np.load(os.path.join(REPO, "plans", plan, "theme_q_1khz.npz")); q = Z["q"].astype(float); pre = float(Z["pre_roll"])
    m = mujoco.MjModel.from_xml_string(stage(pc.read_scene(os.path.join(REPO, "plans", plan, "scene.xml")), w * SS, h * SS, fovy, ortho)); d = mujoco.MjData(m)
    d.qpos[pc.hand_qadr(m)] = q[0, :20]; d.ctrl[:] = q[0]
    for _ in range(150): mujoco.mj_step(m, d)
    d.time = 0.0
    while d.time < pre + t_music: d.ctrl[:] = q[min(int(round(d.time * 1000)), len(q) - 1)]; mujoco.mj_step(m, d)
    keys = [int(m.joint(j).name[4:]) for j in range(m.njnt) if m.joint(j).name.startswith("key_")]
    down = [k for k in keys if d.qpos[m.jnt_qposadr[m.joint(f"key_{k}").id]] >= m.jnt_range[m.joint(f"key_{k}").id, 1] - pc.ACT_THR]
    for k in down: m.geom_rgba[m.body_geomadr[m.body(f"key_{k}").id]] = [GOLD[0] / 255, GOLD[1] / 255, GOLD[2] / 255, 1]
    return m, d, down, Z


def pill(dr, xy, text, f, fill=IVORY, bg=(24, 26, 32, 235), anchor="mm", pad=(10, 6)):
    x0, y0, x1, y1 = dr.textbbox(xy, text, font=f, anchor=anchor)
    dr.rounded_rectangle((x0 - pad[0], y0 - pad[1], x1 + pad[0], y1 + pad[1]), radius=8, fill=bg); dr.text(xy, text, font=f, fill=fill, anchor=anchor)


def dim(dr, a, b, text, f, off=(0, 0), tick=9):
    """Dimension line a-b with end ticks and a label."""
    a, b = np.asarray(a, float), np.asarray(b, float); n = (b - a) / np.linalg.norm(b - a); t = np.array([-n[1], n[0]]) * tick
    dr.line((*a, *b), fill=GOLD, width=3)
    for p in (a, b): dr.line((*(p - t), *(p + t)), fill=GOLD, width=3)
    pill(dr, tuple((a + b) / 2 + np.asarray(off)), text, f, fill=GOLD)


def banner():
    w, h = 1600, 520
    m, d, down, _ = playing_scene(w, h)
    cam = camera([0.105, pc.key_y(74), 0.03], 0.46, 236, -17); _, right, _ = cam_axes(cam); cam.lookat[:] = np.asarray(cam.lookat) - 0.165 * right
    arr = np.asarray(render(m, d, cam, w, h)).astype(float)
    a = np.clip((np.linspace(0, 1, w)[None, :, None] - 0.24) / 0.36, 0, 1) ** 1.3      # calm area for the title on the left
    im = Image.fromarray((arr * a + np.array(INK, float) * (1 - a)).astype(np.uint8)); dr = ImageDraw.Draw(im)
    dr.text((84, 138), "Wuji Quartet", font=serif(100), fill=IVORY)
    dr.line((88, 276, 184, 276), fill=GOLD, width=4)
    dr.text((86, 304), "A 20-joint robot hand learns the piano.", font=font("Light", 37), fill=IVORY)
    dr.text((86, 362), "A MIDI file in  ·  an optimised finger plan out", font=font("Regular", 23), fill=MUTED)
    dr.text((86, 394), "Rehearsed in simulation before it touches a key", font=font("Regular", 23), fill=MUTED)
    im.save(os.path.join(HERE, "banner.png")); print("banner.png", im.size, "keys down:", [pc_name(k) for k in down])


def pc_name(k): return ["C", "C#", "D", "D#", "E", "F", "F#", "G", "G#", "A", "A#", "B"][k % 12] + str(k // 12 - 1)


def hand():
    w, h = 1400, 780
    xml, meshdir = pc.hand_paths(WUJI, "hand2_2", "right")
    src = open(xml).read().replace('meshdir="../meshes/right/"', f'meshdir="{meshdir}"')
    src = src.replace("<asset>", f'<visual><global offwidth="{w*SS}" offheight="{h*SS}" fovy="30"/><headlight ambient="0.30 0.30 0.32" diffuse="0.55 0.55 0.55" specular="0.25 0.25 0.25"/></visual><asset><texture type="skybox" builtin="gradient" {SKY} width="256" height="256"/>', 1)
    src = src.replace("<worldbody>", '<worldbody><light pos="0.25 -0.35 0.6" dir="-0.3 0.4 -1" diffuse="0.9 0.88 0.82" specular="0.4 0.4 0.4"/><body name="pose" euler="3.14159 0 0">', 1).replace("</worldbody>", "</body></worldbody>")
    m = mujoco.MjModel.from_xml_string(src); d = mujoco.MjData(m); q = np.zeros(m.nq)
    for j in range(m.njnt):                            # relaxed, slightly curled, fingers up
        n = m.joint(j).name
        if "mcp_flex" in n or n.endswith("thumb_mcp"): q[j] = 0.25
        if "pip" in n: q[j] = 0.35
        if "dip" in n or n.endswith("_ip"): q[j] = 0.25
    d.qpos[:] = q; mujoco.mj_forward(m, d)
    cam = camera(d.subtree_com[1] + np.array([0, 0, 0.022]), 0.52, 72, -8); _, right, _ = cam_axes(cam); cam.lookat[:] = np.asarray(cam.lookat) + 0.045 * right
    im = render(m, d, cam, w, h); dr = ImageDraw.Draw(im, "RGBA"); P = lambda p: project(cam, m, w, h, p)
    lab, small, big, num = font("Medium", 24), font("Regular", 20), font("Light", 26), font("SemiBold", 44)
    # finger names above the fingertips
    for f, name in zip(pc.FINGERS, ("Thumb", "Index", "Middle", "Ring", "Pinky")):
        b = [i for i in range(m.nbody) if f in m.body(i).name and "tip" in m.body(i).name][-1]; x, y = P(d.xpos[b])
        if name == "Thumb": pill(dr, (x + 62, y - 30), name, lab)
        else: pill(dr, (x, y - 50), name, lab)
    # the four joints of the index finger
    idx = [j for j in range(m.njnt) if "index_finger" in m.joint(j).name]; pts = [P(d.xanchor[j]) for j in idx]
    for x, y in pts: dr.ellipse((x - 8, y - 8, x + 8, y + 8), fill=GOLD + (255,), outline=INK + (255,), width=2)
    jx, jy = pts[2]; dr.line((jx + 12, jy, 735, jy), fill=GOLD + (255,), width=2); pill(dr, (748, jy), "4 joints per finger", lab, fill=GOLD, anchor="lm")
    # fingertip pad and flange
    b = [i for i in range(m.nbody) if "pinky" in m.body(i).name and "tip" in m.body(i).name][-1]; x, y = P(d.xpos[b])
    dr.line((x - 16, y + 6, 250, y + 6), fill=IVORY + (200,), width=2); pill(dr, (40, y + 6), "Touch pad on", lab, anchor="lm"); pill(dr, (40, y + 44), "every fingertip", lab, anchor="lm")
    x, y = P(d.xpos[m.body("r_mount").id]); dr.line((x - 44, y - 6, 262, y - 6), fill=IVORY + (200,), width=2); pill(dr, (40, y - 6), "Arm-flange mount", lab, anchor="lm")
    # spec column (docs.wuji.tech, Hand 2.2 overview)
    x0, y0 = 1010, 150
    for i, (n, t) in enumerate((("20", "joints, each with its own motor"), ("1 kHz", "command rate over Ethernet"), ("800 g", "180 × 80 × 40 mm"), ("12 V", "XT30 power, RJ45 data"))):
        dr.text((x0, y0 + i * 124), n, font=num, fill=GOLD + (255,)); dr.text((x0, y0 + i * 124 + 56), t, font=small, fill=IVORY + (255,))
    dr.text((40, 34), "Wuji Hand 2.2, right hand", font=big, fill=IVORY + (255,)); dr.text((40, 72), "rendered from Wuji's own model in assets/wuji-description", font=small, fill=MUTED + (255,))
    im.save(os.path.join(HERE, "hand.png")); print("hand.png", im.size)


def setup():
    w, h = 1400, 700
    m, d, down, Z = playing_scene(w, h, t_music=0.25, plan="ode_level_s0", fovy=0.30, ortho=True)
    mx, mdy, mz, th = [float(v) for v in Z["mount"]]; y = pc.key_y(76) + mdy                # flange centre (x, y, z), pitch
    cam = camera([0.155, y, 0.052], 3.0, 90, 0)                                                # looking along the keyboard, player on the right
    im = render(m, d, cam, w, h); dr = ImageDraw.Draw(im, "RGBA"); P = lambda p: project(cam, m, w, h, p)
    f, small, big = font("Medium", 24), font("Regular", 20), font("Light", 26)
    fl, kf = P([mx, y, mz]), P([0.15, y, 0.0])
    dr.ellipse((fl[0] - 8, fl[1] - 8, fl[0] + 8, fl[1] + 8), fill=GOLD + (255,), outline=INK + (255,), width=2)
    xr = mx + 0.045
    dr.line((*P([0.15, y, 0.0]), *P([xr + 0.012, y, 0.0])), fill=IVORY + (120,), width=1); dr.line((*fl, *P([xr + 0.012, y, mz])), fill=IVORY + (120,), width=1)
    dim(dr, P([xr, y, 0.0]), P([xr, y, mz]), f"{mz*100:.0f} cm above the keys", f, off=(125, 0))
    zt = mz + 0.045
    dr.line((*kf, *P([0.15, y, zt + 0.008])), fill=IVORY + (120,), width=1); dr.line((*fl, *P([mx, y, zt + 0.008])), fill=IVORY + (120,), width=1)
    dim(dr, P([0.15, y, zt]), P([mx, y, zt]), f"{(mx-0.15)*100:.0f} cm in front of the keys", f, off=(0, -30))
    # pitch: horizontal reference and hand axis from the flange
    L = 0.075; a0 = P([mx - L, y, mz]); a1 = P([mx - L * math.cos(math.radians(th)), y, mz - L * math.sin(math.radians(th))])
    dr.line((*fl, *a0), fill=GOLD + (255,), width=2); dr.line((*fl, *a1), fill=GOLD + (255,), width=2)
    pill(dr, tuple(P([mx - 0.118, y, mz - 0.016])), "level" if abs(th) < 0.5 else f"{th:.0f}° down", f, fill=GOLD)
    c = P([pc.PRESS_X, y, 0.0]); dr.line((c[0], c[1] + 6, c[0], c[1] + 150), fill=IVORY + (200,), width=2)
    px = Z["press_x"] if "press_x" in Z.files else [pc.PRESS_X]
    pill(dr, (c[0], c[1] + 166), f"fingertips land {(0.15-max(px))*1000:.0f} to {(0.15-min(px))*1000:.0f} mm behind the key front", f)
    pill(dr, tuple(fl + np.array([0, -34])), "flange centre", small, fill=GOLD)
    dr.text((40, 34), "Where the hand is mounted", font=big, fill=IVORY + (255,)); dr.text((40, 72), "side view  ·  Ode to Joy, five keys C5 to G5  ·  chosen for straight fingers", font=small, fill=MUTED + (255,))
    dr.text((w - 40, h - 44), "player's side  →", font=small, fill=MUTED + (255,), anchor="rm"); dr.text((40, h - 44), "←  fallboard", font=small, fill=MUTED + (255,), anchor="lm")
    im.save(os.path.join(HERE, "setup.png")); print("setup.png", im.size, "mount", mx, mdy, mz, th)


# ---------------------------------------------------------------- diagrams (drawn, 2x for sharp text)
K = 2
BG, CARD, EDGE = (35, 38, 46), (47, 51, 61), (86, 92, 108)


class Sheet:
    def __init__(self, w, h, title, sub):
        self.w, self.h = w, h; self.im = Image.new("RGB", (w * K, h * K), BG); self.dr = ImageDraw.Draw(self.im)
        self.text((40, 30), title, "Light", 26, IVORY); self.text((40, 68), sub, "Regular", 19, MUTED)
    def text(self, xy, t, weight="Regular", size=20, fill=IVORY, anchor="la"):
        self.dr.text((xy[0] * K, xy[1] * K), t, font=font(weight, size * K), fill=fill, anchor=anchor)
    def box(self, x, y, w, h, head, lines, accent=False, tag=None):
        self.dr.rounded_rectangle((x * K, y * K, (x + w) * K, (y + h) * K), radius=14 * K, fill=CARD, outline=GOLD if accent else EDGE, width=(2 if accent else 1) * K)
        if tag: self.text((x + 18, y + 16), tag, "SemiBold", 15, GOLD)
        self.text((x + 18, y + (40 if tag else 18)), head, "Medium", 22, IVORY)
        for i, l in enumerate(lines): self.text((x + 18, y + (74 if tag else 52) + i * 26), l, "Regular", 17, MUTED)
    def arrow(self, a, b, label=None, dashed=False, color=GOLD, label_off=(0, -16), both=False):
        a, b = np.asarray(a, float), np.asarray(b, float); n = (b - a) / np.linalg.norm(b - a); t = np.array([-n[1], n[0]])
        if dashed:
            L = np.linalg.norm(b - a); k = 0.0
            while k < L - 6: self.dr.line((*((a + n * k) * K), *((a + n * min(k + 9, L - 6)) * K)), fill=color, width=2 * K); k += 16
        else: self.dr.line((*(a * K), *((b - n * 6) * K)), fill=color, width=2 * K)
        for tip, s in ((b, 1),) + (((a, -1),) if both else ()):
            self.dr.polygon([tuple(tip * K), tuple((tip - s * n * 13 + t * 6) * K), tuple((tip - s * n * 13 - t * 6) * K)], fill=color)
        if label: self.text(tuple((a + b) / 2 + np.asarray(label_off)), label, "Medium", 16, color, anchor="mm")
    def save(self, name): self.im.save(os.path.join(HERE, name), optimize=True); print(name, self.im.size)


def pipeline():
    S = Sheet(1400, 400, "From notes to a plan the hand can play", "one command: scripts/sbto_piano.py  ·  15 to 19 minutes per piece on 10 CPU cores")
    cols = [("1", "Notes", ["MIDI file", "K.265 theme: 80 notes", "Für Elise: 86 notes"]),
            ("2", "Fingering", ["which finger plays", "which key, and where", "the wrist sits"]),
            ("3", "First plan", ["fingertip targets to", "joint angles (IK),", "1,000 commands / s"]),
            ("4", "Optimise", ["48 candidates × 6 rounds", "per half second, each", "played on 5 setups"]),
            ("5", "Plan file", ["theme_q_1khz.npz", "sim video with sound,", "or the real hand"])]
    w, g, x0, y0, h = 236, 30, 40, 128, 176
    for i, (tag, head, lines) in enumerate(cols):
        x = x0 + i * (w + g); S.box(x, y0, w, h, head, lines, accent=(i == 3), tag="STEP " + tag)
        if i: S.arrow((x - g + 3, y0 + h / 2), (x - 3, y0 + h / 2))
    S.text((40, 346), "The 5 setups differ in servo stiffness and mount position, so the plan does not depend on one lucky simulation.", "Regular", 18, MUTED)
    S.save("pipeline.png")


def wiring():
    S = Sheet(1400, 600, "How everything is connected", "the robot computer talks to the hand by cable; laptops reach the robot computer by Wi-Fi")
    S.box(50, 150, 300, 150, "Laptops (Mac)", ["optimise plans, watch the sim", "ssh into the RDK X5", "git pull / push"])
    S.box(520, 150, 360, 150, "D-Robotics RDK X5", ["runs the Docker image: ./wq hand …", "eth0 = 192.168.1.50 / 24 (we set this)", "Wi-Fi for ssh and internet"], accent=True)
    S.box(1050, 150, 300, 150, "Wuji Hand 2 (right)", ["fixed IP 192.168.1.111", "UDP port 50001", "left hand: 192.168.1.110"])
    S.arrow((350, 225), (520, 225), "Wi-Fi", dashed=True, both=True)
    S.arrow((880, 225), (1050, 225), "Ethernet", both=True); S.text((965, 244), "RJ45 Cat5e", "Regular", 15, MUTED, anchor="mm")
    S.box(520, 420, 360, 124, "USB-C power supply, 5 V 5 A", ["not a laptop USB port:", "the board browns out and reboots"])
    S.box(1050, 420, 300, 124, "Power adapter, 12 V 20 A", ["XT30 plug, comes with the hand", "plug the hand end in first"])
    S.box(50, 420, 300, 124, "Digital piano", ["USB-MIDI out (usually USB-B)", "scores what the hand played"])
    S.arrow((700, 420), (700, 300), "USB-C", color=IVORY, label_off=(40, 0)); S.arrow((1200, 420), (1200, 300), "XT30", color=IVORY, label_off=(36, 0))
    S.arrow((350, 462), (560, 300), "USB (MIDI)", color=IVORY, label_off=(-62, 0))
    S.save("wiring.png")


def fingering():
    S = Sheet(1400, 470, "Fixed-wrist fingering for the K.265 theme", "the hand stays in one place: seven white keys, five fingers")
    names = ["B4", "C5", "D5", "E5", "F5", "G5", "A5"]; kw, x0, y0, kh = 132, 238, 190, 220
    for i, n in enumerate(names):
        x = x0 + i * kw; S.dr.rounded_rectangle((x * K, y0 * K, (x + kw - 6) * K, (y0 + kh) * K), radius=8 * K, fill=(238, 235, 226)); S.text((x + kw / 2 - 3, y0 + kh - 30), n, "Medium", 20, INK, anchor="mm")
    for i in (1, 2, 4, 5):                                                    # C#5 D#5 F#5 G#5
        x = x0 + (i + 1) * kw - 3 - 38; S.dr.rounded_rectangle((x * K, y0 * K, (x + 76) * K, (y0 + 132) * K), radius=6 * K, fill=(16, 17, 21))
    for name, a, b in (("Thumb", 0, 1), ("Index", 2, 2), ("Middle", 3, 3), ("Ring", 4, 4), ("Pinky", 5, 6)):
        xa, xb = x0 + a * kw + 14, x0 + (b + 1) * kw - 20; y = y0 - 26
        S.dr.line((xa * K, y * K, xb * K, y * K), fill=GOLD, width=4 * K)
        for x in (xa, xb): S.dr.line((x * K, y * K, x * K, (y + 12) * K), fill=GOLD, width=4 * K)
        S.text(((xa + xb) / 2, y - 22), name, "Medium", 22, GOLD, anchor="mm")
    S.text((x0 + 6.5 * kw, y0 + kh + 26), "A5 by stretching the pinky", "Regular", 17, MUTED, anchor="mm")
    S.text((x0 + 0.5 * kw, y0 + kh + 26), "bass side", "Regular", 17, MUTED, anchor="mm")
    S.save("fingering.png")


FIGS = {"banner": banner, "hand": hand, "setup": setup, "pipeline": pipeline, "wiring": wiring, "fingering": fingering}
if __name__ == "__main__":
    for name in (sys.argv[1:] or list(FIGS)): FIGS[name]()
