"""Where a plan's hand goes on the real piano, and where its fingertips are when the plan starts (its first frame = the start pose
the hand ramps to before playing). For the Play page's "Where the hand goes" card.

Piano frame as in piano_core.build_scene, in mm: +x toward the player (key hinge at 0, white key fronts at 150, black key fronts at 90),
+y toward the treble (white key i at i * 23.5 mm from A0), z = 0 on the white key tops. Fingertip heights are above the top of
the key under the tip (black keys stand 12.5 mm higher).
"""
import os
import sys
import threading

import numpy as np

REPO = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(REPO, "scripts"))
import piano_core as pc                               # noqa: E402  (imports mujoco)
import mujoco                                         # noqa: E402

PLAN_FILE = "theme_q_1khz.npz"
_cache, _lock = {}, threading.Lock()


def key_under(x, y):
    """The key whose top a point at (x, y) (m, piano frame) is over: a black key where black keys are, else the nearest white."""
    w = int(round(y / pc.PITCH))
    white = next(m for m in range(21, 109) if not pc.is_black(m) and pc.white_index(m) == max(0, min(51, w)))
    if 0.0 <= x <= pc.BL:
        for m in (white - 1, white + 1):
            if 21 <= m <= 108 and pc.is_black(m) and abs(y - pc.key_y(m)) <= pc.BW / 2:
                return m
    return white


def key_top(m, d, key):
    """Height of a key's top surface (m, piano frame: 0 = white key tops, black keys stand 12.5 mm higher)."""
    b = m.jnt_bodyid[m.joint(f"key_{key}").id]
    return max(float(d.geom_xpos[g][2] + m.geom_size[g][2]) for g in range(m.ngeom) if m.geom_bodyid[g] == b)


def start_pose(plan_id):
    """Mount (flange centre) and the five fingertips at the plan's first frame, with the keys each finger plays."""
    d = os.path.join(REPO, plan_id)
    f = os.path.join(d, PLAN_FILE)
    stamp = (os.path.getmtime(f), os.path.getmtime(os.path.join(d, "scene.xml")) if os.path.exists(os.path.join(d, "scene.xml")) else 0)
    with _lock:
        hit = _cache.get(plan_id)
        if hit and hit[0] == stamp:
            return hit[1]
    Z = np.load(f, allow_pickle=False)
    has = set(Z.files)
    x, dy, z, th = (float(v) for v in Z["mount"]) if "mount" in has else (0.22, -0.0235, 0.10, 25.0)
    center = int(Z["center"]) if "center" in has else 76
    side = str(Z["side"]) if "side" in has else "right"
    home = {int(a): int(b) for a, b in Z["home"]} if "home" in has else {}
    plays = {k: sorted({int(p) for p, g in Z["fing"] if int(g) == k}) for k in range(5)} if "fing" in has else {}
    out = dict(plan=plan_id, side=side, center=center, wrist=str(Z["wrist"]) if "wrist" in has else "fixed",
               start_hover=bool(Z["start_hover"]) if "start_hover" in has else False,
               mount=dict(front_mm=round((x - pc.L) * 1000, 1), height_mm=round(z * 1000, 1), pitch_deg=round(th, 1), side_mm=round(dy * 1000, 1),
                          y_mm=round((pc.key_y(center) + dy) * 1000, 1)),
               fingers=[dict(finger=pc.SHORT[k], home=home.get(k), plays=plays.get(k, [])) for k in range(5)])
    scene = os.path.join(d, "scene.xml")
    if os.path.exists(scene):
        try:
            m = mujoco.MjModel.from_xml_string(pc.read_scene(scene))
            dd = mujoco.MjData(m)
            dd.qpos[pc.hand_qadr(m)] = Z["q"][0].astype(float)[:m.nu]
            mujoco.mj_forward(m, dd)
            pre = "l_" if mujoco.mj_name2id(m, mujoco.mjtObj.mjOBJ_SITE, "l_thumb_tip") >= 0 else "r_"
            mb = dd.body("hand_mount").xpos
            out["mount"]["y_mm"] = round(float(mb[1]) * 1000, 1)
            for k, fn in enumerate(pc.FINGERS):
                tx, ty, tz = (float(v) for v in dd.site(f"{pre}{fn}_tip").xpos)
                key = key_under(tx, ty)
                front = pc.BL if pc.is_black(key) else pc.L
                out["fingers"][k].update(x_mm=round(tx * 1000, 1), y_mm=round(ty * 1000, 1), over=key,
                                         behind_front_mm=round((front - tx) * 1000, 1), off_mm=round((ty - pc.key_y(key)) * 1000, 1),
                                         above_mm=round((pc.pad_min_z(m, dd, fn) - key_top(m, dd, key)) * 1000, 1))
        except Exception as e:                    # an old scene that no longer loads: the mount numbers still hold
            out["error"] = f"{type(e).__name__}: {e}"
    with _lock:
        _cache[plan_id] = (stamp, out)
    return out


if __name__ == "__main__":
    import json
    for p in sys.argv[1:]:
        print(json.dumps(start_pose(p), indent=1))
