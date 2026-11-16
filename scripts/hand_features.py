"""Hand angle features from 21 3D hand joints (MediaPipe / OpenPose order). No Wuji SDK needed,
so other envs (e.g. experiments/wilor) can import it."""

import numpy as np

# MediaPipe landmark ids: (mcp, pip, dip, tip) per finger, thumb = (cmc, mcp, ip, tip)
CHAINS = {0: (1, 2, 3, 4), 1: (5, 6, 7, 8), 2: (9, 10, 11, 12), 3: (13, 14, 15, 16), 4: (17, 18, 19, 20)}

def angle(a, b):
    c = np.dot(a, b) / (np.linalg.norm(a) * np.linalg.norm(b) + 1e-9)
    return float(np.arccos(np.clip(c, -1.0, 1.0)))


def unit(v):
    return v / (np.linalg.norm(v) + 1e-9)


def features(w):
    """w: (21,3) world landmarks -> dict of raw angles (rad)."""
    wrist = w[0]
    fwd = unit(w[9] - wrist)                          # toward middle MCP
    x_ip = unit((w[17] - w[5]) - np.dot(w[17] - w[5], fwd) * fwd)  # in-plane, index -> pinky
    normal = np.cross(x_ip, fwd)
    r = {}
    for f in range(1, 5):
        m, p, d, t = (w[i] for i in CHAINS[f])
        b = p - m
        b_in = b - np.dot(b, normal) * normal
        r[f"j1_{f}"] = angle(b, b_in) if np.dot(b_in, fwd) > 0 else np.pi / 2
        r[f"j3_{f}"] = angle(b, d - p)
        r[f"j4_{f}"] = angle(d - p, t - d)
        r[f"spread{f}"] = float(np.arctan2(np.dot(b_in, -x_ip), np.dot(b_in, fwd)))
    c, m, i, t = (w[k] for k in CHAINS[0])
    b = m - c                                         # thumb metacarpal
    b_in = b - np.dot(b, normal) * normal
    r["th_out"] = angle(b, b_in)                      # tilt out of the palm plane
    r["th_radial"] = float(np.arctan2(np.dot(b_in, -x_ip), np.dot(b_in, fwd)))  # + = away from index side
    r["th_mcp"] = angle(b, i - m)
    r["th_ip"] = angle(i - m, t - i)
    # thumb tip across the palm: 0 = on the index-knuckle line, 1 = on the pinky-knuckle line
    # (folding the thumb into the palm barely moves MediaPipe's metacarpal, but moves the tip a lot)
    r["th_across"] = float(np.dot(t - w[5], x_ip) / (np.dot(w[17] - w[5], x_ip) + 1e-9))
    return r
