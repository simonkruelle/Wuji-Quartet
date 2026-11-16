"""Two plans, two hands, one keyboard: plays both in ONE simulation, scores each hand's notes, counts contacts between the hands,
and writes a video (overview on top, one close-up per hand below, audio synthesised from the keys the SIM pressed).

  python scripts/render_duet.py plans/ode_level_stroke90_s0 plans/ode_accomp_left_s0 --out docs/media/ode_duet.mp4
  python scripts/render_duet.py <plan A> <plan B> --check          # numbers only, no video (10 s)
  python scripts/render_duet.py plans/jingle_level_bpm120_s0 plans/jingle_accomp_left_s0 --present --title "Jingle Bells" --out docs/media/jingle_two_hands.mp4
The plans carry their own mount, side and place in the piece (piece_t0), so the hands start together as written in the score."""
import argparse, os, subprocess, sys, wave
import numpy as np, mujoco
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import piano_core as pc
from midi_io import note_name
HERE = os.path.dirname(os.path.dirname(os.path.abspath(__file__))); WUJI = os.path.join(HERE, "assets/wuji-description")


def load(plan_dir):
    Z = np.load(os.path.join(plan_dir, "theme_q_1khz.npz"), allow_pickle=True); g = lambda k, d: Z[k] if k in Z.files else d
    x, dy, z, th = (float(v) for v in Z["mount"]); side = str(g("side", "right"))
    return dict(t=Z["t"], q=Z["q"].astype(float)[:, :20], pre=float(Z["pre_roll"]), t0=float(g("piece_t0", 0.0)), side=side, title=str(g("title", "")),
                notes=[dict(on=float(a), off=float(b), pitch=int(p)) for a, b, p in Z["notes"]], name=os.path.basename(os.path.normpath(plan_dir)),
                scene=dict(theta=th, mount_x=x, mount_z=z, mount_dy=dy, center_key=int(g("center", 76)), side=side, gain=5.0,
                           limits=pc.real_limits(side) if bool(g("real_limits", False)) else None))


def timeline(A, B):
    """Common clock: both plans keep their own 1.5 s lead-in; the part that enters later in the piece starts later."""
    t00 = min(A["t0"], B["t0"]); offs = [A["t0"] - t00, B["t0"] - t00]; T = max(A["t"][-1] + offs[0], B["t"][-1] + offs[1])
    t = np.arange(0, T, 0.001); Q = []
    for P, o in zip((A, B), offs):
        k = np.clip(np.round((t - o) * 1000).astype(int), 0, len(P["q"]) - 1); Q.append(P["q"][k])
    target = [dict(on=n["on"] + P["t0"] - t00, pitch=n["pitch"], hand=h) for h, P in enumerate((A, B)) for n in P["notes"]]
    return t, np.concatenate(Q, 1), target, A["pre"]


if __name__ == "__main__":
    ap = argparse.ArgumentParser(); ap.add_argument("plan_a"); ap.add_argument("plan_b"); ap.add_argument("--out", default=None); ap.add_argument("--check", action="store_true")
    ap.add_argument("--title", default=None); ap.add_argument("--test-frame", type=float, default=None, help="save one frame at this music time (s) and stop")
    ap.add_argument("--gain", type=float, default=5.0); ap.add_argument("--w", type=int, default=1280)
    ap.add_argument("--present", action="store_true", help="presentation video: 1920x1080, one view from the player's side above the keys, stereo piano sound")
    A_ = ap.parse_args()
    A, B = load(A_.plan_a), load(A_.plan_b); t, Q, target, pre = timeline(A, B)
    for P in (A, B): P["scene"]["gain"] = A_.gain
    xml = pc.build_duo_scene(WUJI, A["scene"], B["scene"])
    if not A_.check:
        xml = xml.replace("<asset>", '<asset><texture type="skybox" builtin="gradient" rgb1="0.30 0.32 0.37" rgb2="0.12 0.13 0.155" width="256" height="256"/>', 1).replace('rgba="0.55 0.55 0.6 1"', 'rgba="0.15 0.16 0.19 1"')
    if A_.present:
        import re; xml = re.sub(r'<global offwidth="\d+" offheight="\d+"\s*/>', '<global offwidth="1920" offheight="1080"/>', xml)
    m = mujoco.MjModel.from_xml_string(xml); d = mujoco.MjData(m); qa = pc.hand_qadr(m)
    keys = [int(m.joint(j).name[4:]) for j in range(m.njnt) if m.joint(j).name.startswith("key_")]
    kad = np.array([m.jnt_qposadr[m.joint(f"key_{k}").id] for k in keys]); kmax = np.array([m.jnt_range[m.joint(f"key_{k}").id, 1] for k in keys])
    kgeom = np.array([m.body_geomadr[m.body(f"key_{k}").id] for k in keys]); base_rgba = m.geom_rgba[kgeom].copy()
    root = lambda b: m.body(m.body_rootid[b]).name; hand_of = {"hand_mount": 0, "hand_mount_2": 1}
    yc = [float(m.body("hand_mount").pos[1]), float(m.body("hand_mount_2").pos[1])]; ymid = 0.5 * (yc[0] + yc[1]); span = abs(yc[0] - yc[1])
    TITLE = A_.title or (A["title"] or A["name"]); label = [f"{P['side']} hand · {P['name']}" for P in (A, B)]
    if not A_.check:
        from PIL import Image, ImageDraw, ImageFont
        W = A_.w; H1, H2 = int(W * 0.30), int(W * 0.26)
        if not A_.present: r1 = mujoco.Renderer(m, H1, W); r2 = mujoco.Renderer(m, H2, W // 2)      # one GL context only: a second one renders black
        OPT = mujoco.MjvOption(); OPT.geomgroup[2] = 0
        co = mujoco.MjvCamera(); co.lookat[:] = [0.13, ymid, 0.0]; co.distance = 0.40 + 0.95 * span; co.azimuth = 180; co.elevation = -50     # from the player's side: bass on the left
        cc = []
        for y in yc: c = mujoco.MjvCamera(); c.lookat[:] = [0.115, y, 0.022]; c.distance = 0.27; c.azimuth = 0; c.elevation = -16; cc.append(c)   # from the fallboard, facing the fingertips
        try: font = ImageFont.truetype("/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf", 18); small = ImageFont.truetype("/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf", 14)
        except Exception: font = small = ImageFont.load_default()
        order = np.argsort(yc)[::-1]              # fallboard view: treble is on the viewer's left
        T_music = max(n["on"] for n in target)
        def frame(tt):
            act = d.qpos[kad] >= kmax - pc.ACT_THR
            m.geom_rgba[kgeom] = np.where(act[:, None], np.array([0.2, 0.8, 0.3, 1.0]), base_rgba)
            r1.update_scene(d, co, scene_option=OPT); top = r1.render(); low = []
            for h in order: r2.update_scene(d, cc[h], scene_option=OPT); low.append(r2.render())
            im = Image.fromarray(np.concatenate([top, np.concatenate(low, 1)], 0)); dr = ImageDraw.Draw(im)
            dr.text((12, 10), f"simulation · two Wuji Hand 2.2, wrists fixed · {TITLE}", fill=(255, 255, 255), font=font)
            dr.text((12, H1 - 24), f"t = {max(tt - pre, 0):5.2f} s of {T_music:.1f} s · seen from the player's side · green = key reached its note-on depth", fill=(255, 255, 255), font=small)
            for i, h in enumerate(order): dr.text((12 + i * (W // 2), H1 + 8), label[h] + " · seen from the fallboard", fill=(255, 255, 255), font=small)
            return np.asarray(im)
        FW, FH = W, H1 + H2
        if A_.present:                                   # presentation: 1920x1080, one view from the player's side above the keys
            import render_human_robot as rhr
            FW, FH, TOP, PH = 1920, 1080, 96, 810; r1 = mujoco.Renderer(m, PH, FW)
            for b, rgba in (("r_mount", None), ("l_mount", None), ("r_wrist", (0.22, 0.23, 0.25, 1)), ("l_wrist", (0.22, 0.23, 0.25, 1))):
                if mujoco.mj_name2id(m, mujoco.mjtObj.mjOBJ_BODY, b) < 0: continue        # seen from above the flange plate hides the palm
                for g in range(m.body_geomadr[m.body(b).id], m.body_geomadr[m.body(b).id] + m.body_geomnum[m.body(b).id]):
                    if m.geom_group[g] == 1: m.geom_rgba[g] = rgba or (0, 0, 0, 0)
            co.lookat[:] = [0.10, ymid, 0.03]; co.distance = 0.41; co.azimuth = 180; co.elevation = -56
            HCOL = [rhr.BLUE, (0.69, 0.32, 0.87)]
            key_hand = {n["pitch"]: n["hand"] for n in target}
            tip_sites = [[m.site(f"{pfx}{f}_tip").id for f in ("thumb", "index_finger", "middle_finger", "ring_finger", "pinky")]
                         for pfx in [("b_" if h == 1 and A["side"] == B["side"] else "") + ("r_" if P["side"] == "right" else "l_") for h, P in enumerate((A, B))]]
            trail = [[[] for _ in range(5)] for _ in range(2)]; played = [[], []]; down_at = {}
            big, mid, sm = rhr.font(34, True), rhr.font(22), rhr.font(17)
            part = lambda P: "melody" if P is A else "accompaniment"
            T_end = max(n["on"] for n in target) + 0.6
            def frame(tt):
                t_ = tt - pre
                act = d.qpos[kad] >= kmax - pc.ACT_THR
                for i, k in enumerate(keys): m.geom_rgba[kgeom[i]] = (*HCOL[key_hand.get(k, 0)], 1) if act[i] else base_rgba[i]
                r1.update_scene(d, co, scene_option=OPT)
                for h in range(2):
                    for fi in range(5):
                        pts = np.array(trail[h][fi][-18:])
                        if len(pts) > 1: rhr.draw_trail(r1.scene, pts, rhr.FCOL[fi])
                im = Image.new("RGB", (FW, FH), (16, 19, 24)); im.paste(Image.fromarray(r1.render()), (0, TOP)); g = ImageDraw.Draw(im)
                g.text((40, 26), f"{TITLE} · two robot hands", fill=(240, 244, 248), font=big)
                g.text((FW - 40, 34), "Wuji Hand 2 × 2 · simulation · plans by SBTO", fill=(170, 182, 194), font=mid, anchor="ra")
                for row, h in enumerate(order[::-1]):        # bass hand first: it is on the left of the picture
                    P = (A, B)[h]; head = f"{'LEFT' if P['side'] == 'left' else 'RIGHT'} HAND"; sub = f"{part(P)} · {P['name']}"
                    y = TOP + 16 + row * 48; hw = g.textlength(head + "  ", font=rhr.font(22, True))
                    g.rectangle([16, y, 46 + hw + g.textlength(sub, font=mid), y + 40], fill=(16, 19, 24))
                    g.rectangle([24, y + 10, 44, y + 30], fill=tuple(int(c * 255) for c in HCOL[h]))
                    g.text((54, y + 6), head, fill=(255, 255, 255), font=rhr.font(22, True)); g.text((54 + hw, y + 6), sub, fill=(190, 200, 210), font=mid)
                y0 = TOP + PH; g.rectangle([0, y0, FW, FH], fill=(16, 19, 24))
                x0, x1 = 140, FW - 60; X = lambda s: x0 + (x1 - x0) * (s + pre) / (T_end + pre)
                for row, h in enumerate(order[::-1]):
                    yy = y0 + 28 + row * 30; col = tuple(int(c * 255) for c in HCOL[h])
                    g.text((16, yy - 10), f"{(A, B)[h]['side']} hand", fill=(170, 182, 194), font=sm)
                    for n in target:
                        if n["hand"] == h: g.rectangle([X(n["on"]), yy - 7, X(n["on"]) + 3, yy + 7], fill=(60, 66, 76))
                    for a, b in played[h] + [(s, t_) for k, (s, hh) in down_at.items() if hh == h]:
                        g.rectangle([X(a), yy - 7, max(X(a) + 3, X(min(b, a + 0.4))), yy + 7], fill=col)
                g.rectangle([X(t_) - 1, y0 + 12, X(t_) + 1, y0 + 92], fill=(240, 240, 240))
                g.text((x0, y0 + 108), "Grey: the notes written for each hand · coloured: the keys each hand pressed in the simulation. Wrists fixed, as on the real mount; each hand keeps five keys under its fingers",
                       fill=(150, 162, 174), font=sm)
                g.text((x0, y0 + 134), "Sound: the keys the two hands pressed in the simulation (synthesised piano)", fill=(150, 162, 174), font=sm)
                g.text((x1, y0 + 134), f"{max(t_, 0):5.1f} s / {T_end - 0.6:.0f} s", fill=(210, 218, 226), font=mid, anchor="ra")
                return np.asarray(im)
    d.qpos[qa] = Q[0]; d.ctrl[:] = Q[0]
    for _ in range(150): mujoco.mj_step(m, d)
    dt = m.opt.timestep; n = int(t[-1] / dt); onsets = []; armed = np.ones(len(keys), bool); nf = 0; touch = 0; ff = None
    if A_.test_frame is None and not A_.check:
        out = A_.out or os.path.join(A_.plan_a, "duet_sim.mp4"); tmp = out.replace(".mp4", "_v.mp4"); os.makedirs(os.path.dirname(os.path.abspath(out)), exist_ok=True)
        ff = subprocess.Popen(["ffmpeg", "-y", "-loglevel", "error", "-f", "rawvideo", "-pix_fmt", "rgb24", "-s", f"{FW}x{FH}", "-r", "30", "-i", "-",
                               "-c:v", "libx264", "-pix_fmt", "yuv420p", "-crf", "18" if A_.present else "21", tmp], stdin=subprocess.PIPE)
    next_trail, offs = 0.0, []
    for i in range(n):
        tt = i * dt; d.ctrl[:] = Q[min(int(round(tt * 1000)), len(Q) - 1)]; mujoco.mj_step(m, d)
        fr = d.qpos[kad] / kmax; act = fr >= 1 - pc.ACT_THR / kmax
        for k in np.nonzero(act & armed)[0]: onsets.append((tt, keys[k]))
        if A_.present and not A_.check:              # note lengths and fingertip trails, for the picture and the sound
            for k in np.nonzero(act & armed)[0]: down_at[keys[k]] = (tt - pre, key_hand.get(keys[k], 0))
            for k in np.nonzero(~act & ~armed & (fr < 0.5))[0]:
                if keys[k] in down_at: s_, h_ = down_at.pop(keys[k]); played[h_].append((s_, tt - pre)); offs.append((s_ + pre, keys[k], tt - pre - s_, h_))
            if tt + 1e-9 >= next_trail:
                for h in range(2):
                    for fi, s in enumerate(tip_sites[h]): trail[h][fi].append(d.site_xpos[s].copy())
                next_trail += 0.6 / 17
        armed &= ~act; armed |= fr < 0.5
        for c in d.contact[: d.ncon]:
            h1, h2 = hand_of.get(root(m.geom_bodyid[c.geom1])), hand_of.get(root(m.geom_bodyid[c.geom2]))
            if h1 is not None and h2 is not None and h1 != h2: touch += 1; break
        if A_.test_frame is not None and tt >= A_.test_frame + pre:
            Image.fromarray(frame(tt)).save(A_.out or "duet_test_frame.png"); print("saved", A_.out or "duet_test_frame.png"); sys.exit()
        if ff is not None and tt + 1e-9 >= nf / 30.0: ff.stdin.write(frame(tt).tobytes()); nf += 1
    det = [dict(t=tt - pre, pitch=k) for tt, k in onsets]
    for h, P in enumerate((A, B)):
        mine = {n["pitch"] for n in target if n["hand"] == h}
        s = pc.score([e for e in det if e["pitch"] in mine], [n for n in target if n["hand"] == h], tol=0.05)
        print(f"{label[h]}: {s['n_matched']}/{s['n_target']} notes, {len(s['extra'])} wrong, timing 90 % within {s['timing_ms']['p90_abs']:.0f} ms"
              + ("" if not s["missed"] else "  missed: " + str([(note_name(x['pitch']), round(x['on'], 2)) for x in s['missed']][:12])))
    allk = {n["pitch"] for n in target}; stray = [e for e in det if e["pitch"] not in allk]
    print(f"keys outside both parts: {len(stray)} · simulation steps with the two hands touching: {touch} · hands {span * 100:.1f} cm apart")
    if ff is not None and A_.present:                # stereo piano tone (render_human_robot.py), melody a little louder
        ff.stdin.close(); ff.wait()
        ev = [(t0, k, dur, 0.75 if h == 0 else 0.6, 1.0 if h == 0 else 0.7) for t0, k, dur, h in offs]
        ev += [(s + pre, k, 0.4, 0.75 if h == 0 else 0.6, 1.0 if h == 0 else 0.7) for k, (s, h) in down_at.items()]
        au = rhr.audio(ev, nf / 30.0); wav = out.replace(".mp4", ".wav")
        with wave.open(wav, "wb") as w: w.setnchannels(2); w.setsampwidth(2); w.setframerate(44100); w.writeframes((au * 32767).astype(np.int16).tobytes())
        subprocess.run(["ffmpeg", "-y", "-loglevel", "error", "-i", tmp, "-i", wav, "-c:v", "copy", "-c:a", "aac", "-b:a", "192k", "-shortest", out], check=True)
        os.remove(tmp); os.remove(wav); print(f"{out}: {nf} frames, {len(onsets)} sim note-ons")
    elif ff is not None:
        ff.stdin.close(); ff.wait(); sr = 44100; audio = np.zeros(int(sr * nf / 30.0) + sr)
        for tt, k in onsets:
            f0 = 440 * 2 ** ((k - 69) / 12); n_ = int(1.2 * sr); x = np.arange(n_) / sr
            tone = sum(a * np.sin(2 * np.pi * f0 * h * x) for h, a in ((1, 1.0), (2, 0.35), (3, 0.15), (4, 0.06))) * np.exp(-3.2 * x) * np.minimum(1, x / 0.004)
            i0 = int(tt * sr); audio[i0:i0 + n_] += 0.16 * tone[: len(audio) - i0]
        audio = np.clip(audio, -1, 1); wav = out.replace(".mp4", ".wav")
        with wave.open(wav, "wb") as w: w.setnchannels(1); w.setsampwidth(2); w.setframerate(sr); w.writeframes((audio * 32767).astype(np.int16).tobytes())
        subprocess.run(["ffmpeg", "-y", "-loglevel", "error", "-i", tmp, "-i", wav, "-c:v", "copy", "-c:a", "aac", "-shortest", out], check=True)
        os.remove(tmp); os.remove(wav); print(f"{out}: {nf} frames, {len(onsets)} sim note-ons")
