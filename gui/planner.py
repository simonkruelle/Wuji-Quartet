"""Turns a request from the Retarget page into a scripts/sbto_piano.py command: where the hand sits for a piece,
how detailed the search is, and roughly how long it will take on this computer."""
import json
import math
import os
import re

import library as lib

REPO = lib.REPO
REF_PLAN = "plans/ode_level_stroke90_s0"                      # the level-mount plan every quick plan starts from
LEVEL_MOUNT = dict(x=0.27, z=0.06, theta=0.0, dy=0.0)
LEVEL_PRESS_X = [0.135, 0.115, 0.115, 0.115, 0.125]
PLANTS = 5                                                     # training setups every try is played on
TIMING_FILE = os.path.join(REPO, "out", "gui", "timing.json")
DEFAULT_SPEED = 11.5                                           # simulated seconds per second and worker (i7-10700KF, three reference runs)

# detail levels of the search. "tries" = samples per round, "rounds" = CEM iterations per half second of music
DETAIL = {
    "reuse": dict(label="Reuse", samples=0, iters=0, elites=0, help="No search. Takes over what the optimiser learned on Ode to Joy, per finger."),
    "draft": dict(label="Draft", samples=24, iters=3, elites=6, help="A quick search: 24 tries, 3 rounds."),
    "standard": dict(label="Standard", samples=48, iters=6, elites=8, help="The setting of every optimised plan in this repo: 48 tries, 6 rounds."),
    "fine": dict(label="Fine", samples=96, iters=8, elites=12, help="Twice the tries, more rounds."),
}


def _five_from_plan(p):
    """(five keys thumb..pinky, also 'key:finger' list) from a plan's fingering. None if a finger has no key."""
    by = {}
    for pitch, f in p["fing"]:
        by.setdefault(f, []).append(pitch)
    if sorted(by) != [0, 1, 2, 3, 4]:
        return None
    count = {}
    for _, _, pitch in p["notes"]:
        count[pitch] = count.get(pitch, 0) + 1
    five, also = [], []
    for f in range(5):
        home = max(by[f], key=lambda k: count.get(k, 0))
        five.append(home)
        also += [f"{k}:{f}" for k in by[f] if k != home]
    return (five, also) if len(set(five)) == 5 else None


def proven_hands(side="right"):
    """Hand positions (level mount, wrist fixed) that shared plans use: what a simplified song should prefer.
    -> [dict(keys, five, also, stretch, source)], keys = five plus the keys a finger also takes."""
    out, seen = [], set()
    for p in sorted(lib.plans(), key=lambda p: (p["id"] != REF_PLAN, -p.get("hw_runs", 0), p["id"])):
        if p.get("error") or not p.get("shared") or p.get("wrist") != "fixed" or p.get("side") != side or not p.get("level"):
            continue
        fa = _five_from_plan(p)
        if not fa:
            continue
        five, also = fa
        extra = [int(a.split(":")[0]) for a in also]
        keys = tuple(sorted(set(five) | set(extra)))
        if keys not in seen:
            seen.add(keys)
            out.append(dict(keys=list(keys), five=five, also=also, stretch=extra, plan=p["id"], source=p.get("title") or p["name"]))
    return out


def fits_fixed(piece_id, side="right"):
    """True if a hand that stays in place reaches every key of the piece (not counting the old tilted mount)."""
    return any(not o["legacy"] for o in positions(piece_id, side)["positions"])


def _describe(five, also, side):
    names = [lib.note_name(k) for k in five]
    extra = ""
    if also:
        extra = "; " + ", ".join(f"{lib.FINGERS[int(a.split(':')[1])]} also {lib.note_name(int(a.split(':')[0]))}" for a in also)
    return f"thumb {names[0]} · index {names[1]} · middle {names[2]} · ring {names[3]} · pinky {names[4]}{extra}"


def positions(piece_id, side="right"):
    """Where a fixed hand can sit to play this piece, best first. Each entry carries the sbto_piano.py arguments."""
    notes = lib.piece_notes(piece_id)
    keys = sorted({n[2] for n in notes})
    need = set(keys)
    out, seen = [], set()

    def add(five, also, mount, press_x, center, source, proven, legacy=False, note="", press_d=None):
        covered = set(five) | {int(a.split(":")[0]) for a in also}
        if not need <= covered:
            return
        deep = [round((-0.0085 - v) * 1000) for v in press_d] if press_d else [0] * 5      # mm each finger presses deeper than the usual 8.5 mm
        if not any(deep): press_d = None
        elif not note: note = "Presses deeper: " + ", ".join(f"{lib_finger(f)} {d} mm" for f, d in enumerate(deep) if d) + "."
        sig = (tuple(five), tuple(sorted(also)), tuple(round(mount[k], 4) for k in ("x", "z", "theta", "dy")), center, tuple(deep))
        if sig in seen:
            return
        seen.add(sig)
        level = abs(mount["theta"]) < 0.5 and abs(mount["z"] - 0.06) < 0.005
        out.append(dict(id=f"pos{len(out)}", side=side, five=five, also=also, mount=mount, press_x=press_x, press_d=press_d, center=center, source=source,
                        proven=proven, legacy=legacy, level=level, text=_describe(five, also, side), note=note,
                        reuse_from=REF_PLAN if level and os.path.exists(os.path.join(REPO, REF_PLAN, lib.PLAN_FILE)) else None))

    # 1. positions of plans that exist (same hand side, covering every key of the piece)
    for p in sorted(lib.plans(), key=lambda p: (p["id"] != REF_PLAN, not p.get("shared"), not p.get("level", False), -p.get("hw_runs", 0), p["id"])):
        if p.get("error") or p.get("wrist") != "fixed" or p.get("side") != side:
            continue
        fa = _five_from_plan(p)
        if not fa:
            continue
        legacy = not p["level"]
        add(fa[0], fa[1], p["mount"], p["press_x"] or [0.115] * 5, p["center"], f"as in {p['name']}", proven=p["shared"],
            legacy=legacy, note="First mount, tilted 25 degrees: on the real hand the thumb cannot reach from here." if legacy else "", press_d=p.get("press_d"))
    # 2. the rule those plans follow: five neighbouring white keys, level mount centred on the middle finger's key
    if keys and not any(lib.is_black(k) for k in keys) and lib.white_index(keys[-1]) - lib.white_index(keys[0]) <= 4:
        whites = [k for k in range(21, 109) if not lib.is_black(k)]
        i0 = whites.index(keys[0]); i1 = whites.index(keys[-1])
        for start in range(i1 - 4, i0 + 1):
            if start < 0 or start + 5 > len(whites):
                continue
            five = whites[start:start + 5]
            if side == "left":
                five = five[::-1]
            add(five, [], dict(LEVEL_MOUNT), list(LEVEL_PRESS_X), five[2], "five neighbouring white keys, level mount", proven=False,
                note="Same mount rule as Ode to Joy, moved sideways. Simulation only so far.")
    out.sort(key=lambda o: (o["legacy"], not o["proven"]))
    good = [o for o in out if not o["legacy"]]
    if good:          # an old-mount position is offered only when nothing else fits; a local run's variant only when no shared plan has those keys
        known = {(tuple(o["five"]), tuple(sorted(o["also"]))) for o in good if o["proven"]}
        out = [o for o in good if o["proven"] or (tuple(o["five"]), tuple(sorted(o["also"]))) not in known]
    why = ""
    if not [o for o in out if not o["legacy"]]:
        span = lib.white_index(keys[-1]) - lib.white_index(keys[0]) + 1 if keys else 0
        blacks = [lib.note_name(k) for k in keys if lib.is_black(k)]
        why = (f"This piece uses {len(keys)} keys across {span} white keys" + (f", with black keys {', '.join(blacks)}" if blacks else "") +
               ". A hand that stays in one place reaches five neighbouring keys. Use a moving wrist (needs an arm; simulation only), "
               "or search a mount for these keys with scripts/sweep_pose.py.")
    return dict(positions=out, keys=keys, key_names=[lib.note_name(k) for k in keys], why=why)


# ------------------------------------------------------------------ command
def _fmt(v):
    return f"{v:g}"


def suggest_name(req):
    piece = req["piece"]
    stem = piece if piece in lib.BUILTIN else re.sub(r"_(right|left)$", lambda m: "_" + m.group(1), os.path.splitext(os.path.basename(piece))[0])
    stem = re.sub(r"[^A-Za-z0-9]+", "_", stem).strip("_").lower()
    side = "left" if req.get("side") == "left" else "right"
    wrist = req.get("wrist", "fixed")
    part = side if wrist == "fixed" else ("wristplan" if wrist == "plan" else "wristhuman")
    m = re.match(r"^(.*)_(right|left)$", stem)          # a part of a two-hand piece: runaway_right on the right hand -> runaway_right_...
    if m and wrist == "fixed":
        stem = m.group(1) if m.group(2) == side else f"{m.group(1)}_{m.group(2)}_on"
    d = DETAIL.get(req.get("detail", ""), None)
    s, i = (int(req.get("samples", 0)), int(req.get("iters", 0))) if not d or req.get("detail") == "custom" else (d["samples"], d["iters"])
    search = "reuse" if req.get("detail") == "reuse" else f"n{s}x{i}"
    return f"{stem}_{part}_{search}_s{int(req.get('seed', 0))}"


def lib_finger(f):
    return ("thumb", "index", "middle", "ring", "pinky")[f]


def build_command(req, python):
    """req (from the page) -> (argv, out_dir_rel, normalised settings). Raises ValueError with a plain message."""
    piece = req.get("piece")
    if not piece or not (piece in lib.BUILTIN or os.path.exists(os.path.join(REPO, piece))):
        raise ValueError("choose a piece")
    wrist = req.get("wrist", "fixed")
    if wrist not in ("fixed", "plan", "human"):
        raise ValueError("unknown wrist mode")
    if wrist == "human" and piece != "k265":
        raise ValueError("only K.265 has a recorded pianist's wrist")
    detail = req.get("detail", "standard")
    d = DETAIL.get(detail)
    samples = int(req.get("samples") or (d or DETAIL["standard"])["samples"]) if detail in ("custom",) or not d else d["samples"]
    iters = int(req.get("iters") or (d or DETAIL["standard"])["iters"]) if detail in ("custom",) or not d else d["iters"]
    elites = int(req.get("elites") or (d or DETAIL["standard"])["elites"]) if detail in ("custom",) or not d else d["elites"]
    reuse = detail == "reuse"
    if not reuse:
        if not 4 <= samples <= 512: raise ValueError("tries per round: 4 to 512")
        if not 1 <= iters <= 30: raise ValueError("rounds: 1 to 30")
        if not 2 <= elites < samples: raise ValueError("kept per round: at least 2, fewer than the tries")
    commit = float(req.get("commit") or 0.5)
    if not 0.2 <= commit <= 2.0: raise ValueError("step length: 0.2 to 2 s")
    workers = max(1, min(int(req.get("workers") or default_workers()), os.cpu_count() or 1))
    seed = int(req.get("seed") or 0)
    name = re.sub(r"[^A-Za-z0-9_.-]+", "_", (req.get("name") or suggest_name(dict(req, samples=samples, iters=iters))).strip()).strip("._") or "run"
    taken = lambda n: os.path.exists(os.path.join(REPO, "out", n, lib.PLAN_FILE)) or os.path.exists(os.path.join(REPO, "plans", n)) or n in set(req.get("_busy") or ())
    if not req.get("name"):                       # a name the page suggested: the next free one (runaway_right_reuse_s0_2, _3 ...)
        base, k = name, 2
        while taken(name):
            name, k = f"{base}_{k}", k + 1
    out_rel = f"out/{name}"
    if taken(name):
        raise ValueError(f"a plan named {name} exists already: choose another name")
    argv = [python, "-u", "scripts/sbto_piano.py", "--piece", piece, "--wrist", wrist, "--out", out_rel, "--workers", str(workers), "--seed", str(seed)]
    used = dict(piece=piece, wrist=wrist, detail=detail, samples=samples, iters=iters, elites=elites, commit=commit, workers=workers, seed=seed, name=name)
    if wrist == "fixed":
        pos = req.get("position")
        if not pos:
            raise ValueError("choose where the hand sits")
        five = [int(k) for k in pos["five"]]
        if len(set(five)) != 5: raise ValueError("the five keys must differ")
        reach = set(five) | {int(a.split(":")[0]) for a in (pos.get("also") or [])}
        miss = sorted({n[2] for n in lib.piece_notes(piece)} - reach)
        if miss: raise ValueError("this hand position does not reach " + ", ".join(lib.note_name(k) for k in miss) + ": choose it again")
        m = pos["mount"]
        legacy_default = (not pos.get("level")) and five == [72, 74, 76, 77, 79] and sorted(pos.get("also") or []) == ["71:0", "81:4"]
        if not legacy_default:
            argv += ["--five", ",".join(str(k) for k in five)]
            if pos.get("also"): argv += ["--also", ",".join(pos["also"])]
        argv += ["--mount", ",".join(_fmt(float(m[k])) for k in ("x", "z", "theta", "dy"))]
        if pos.get("press_x") and pos.get("level"): argv += ["--press-x", ",".join(_fmt(float(v)) for v in pos["press_x"])]
        if pos.get("press_d") and pos.get("level"): argv += ["--press-d", ",".join(_fmt(abs(float(v))) for v in pos["press_d"])]
        side = pos.get("side", "right")
        if side == "left": argv += ["--side", "left"]
        if int(pos.get("center", 76)) != 76 or side == "left": argv += ["--center", str(int(pos["center"]))]
        if pos.get("level"):
            argv += ["--real-limits", "--start-hover", "--stroke", _fmt(float(req.get("stroke") or 0.09))]
        elif req.get("stroke"):
            argv += ["--stroke", _fmt(float(req["stroke"]))]
        used.update(side=side, five=five, also=pos.get("also") or [], mount=m, center=int(pos.get("center", 76)), level=bool(pos.get("level")))
        start = req.get("start_from") if req.get("start_from") is not None else pos.get("reuse_from")
        if reuse and not start:
            raise ValueError("Reuse needs a plan to start from: this position has none. Choose Draft, Standard or Fine.")
        if start and (reuse or req.get("warm", True)):
            lib.plan_npz(start)
            argv += ["--init-from", f"{start}/{lib.PLAN_FILE}"]
            used["start_from"] = start
    else:
        if reuse: raise ValueError("a moving wrist needs a search: choose Draft, Standard or Fine")
        knot = float(req.get("knot_dt") or 0.2)
        if not 0.05 <= knot <= 1.0: raise ValueError("wrist knots: every 0.05 to 1 s")
        if abs(knot - 0.2) > 1e-9: argv += ["--knot-dt", _fmt(knot)]
        used["knot_dt"] = knot
    if reuse:
        argv += ["--no-cem"]
    else:
        argv += ["--samples", str(samples), "--iters", str(iters), "--elites", str(elites)]
        if abs(commit - 0.5) > 1e-9: argv += ["--commit", _fmt(commit)]
    if req.get("dr") in ("wide", "mild"):
        argv += ["--dr", req["dr"]]; used["dr"] = req["dr"]
    gain = float(req.get("gain") or 5.0)
    if abs(gain - 5.0) > 1e-9:
        if not 1.0 <= gain <= 20.0: raise ValueError("stiffness: 1 to 20")
        argv += ["--gain", _fmt(gain)]; used["gain"] = gain
    if req.get("max_windows"):
        argv += ["--max-windows", str(int(req["max_windows"]))]; used["max_windows"] = int(req["max_windows"])
    return argv, out_rel, used


# ------------------------------------------------------------------ time estimate
def default_workers():
    n = os.cpu_count() or 2
    return max(1, min(10, n - 2 if n > 4 else n))


def _effective(workers):
    """Workers beyond the physical cores add little (the reference machine has 8 cores, 16 threads)."""
    phys = max(1, (os.cpu_count() or 2) // 2)
    return min(workers, phys) + 0.25 * max(0, workers - phys)


def _windows(notes, commit, moving, knot_dt, samples):
    """Per half-second step with notes: (music time, tries, simulated seconds per try), as sbto_piano.py's loop makes them."""
    ons = sorted(n[0] for n in notes)
    out = []
    t0 = ons[0] - 0.05
    t_end = max(n[1] for n in notes) + 1.0
    while t0 < ons[-1] + 0.01:
        k = sum(1 for o in ons if t0 <= o < t0 + commit)
        if k:
            dims = 5 * k + (2 * int(round((commit + 0.3) / knot_dt)) if moving else 0)
            tries = samples if dims <= 25 else int(samples * 1.33)
            out.append((t0, tries, min(t0 + commit + 0.35, t_end) - (t0 - 0.25)))
        t0 += commit
    return out


def machine_speed():
    try:
        with open(TIMING_FILE) as fh:
            runs = json.load(fh)["runs"]
        v = sorted(r["speed"] for r in runs[-12:])
        return v[len(v) // 2], len(v)
    except Exception:
        return DEFAULT_SPEED, 0


def estimate(req):
    """Seconds this request will take, with the parts that make it up."""
    notes = lib.piece_notes(req["piece"])
    if not notes:
        return dict(seconds=0, windows=0)
    moving = req.get("wrist", "fixed") != "fixed"
    detail = req.get("detail", "standard")
    d = DETAIL.get(detail)
    samples = d["samples"] if d else int(req.get("samples") or 48)
    iters = d["iters"] if d else int(req.get("iters") or 6)
    commit = float(req.get("commit") or 0.5)
    knot = float(req.get("knot_dt") or 0.2)
    workers = max(1, int(req.get("workers") or default_workers()))
    speed, n_hist = machine_speed()
    length = max(n[1] for n in notes) + 2.5
    keys = len({n[2] for n in notes})
    setup = (4 if not moving else 22) + 0.4 * keys + 0.3 * length * DEFAULT_SPEED / speed      # finger poses, servo-delay fit, scoring on ten setups
    wins = _windows(notes, commit, moving, knot, samples) if detail != "reuse" else []
    if req.get("max_windows"):
        wins = wins[:int(req["max_windows"])]
    sim = sum(iters * tries * PLANTS * span for _, tries, span in wins)
    search = sim / (speed * _effective(workers)) + 0.25 * len(wins)
    total = setup + search
    numbers = sum(5 * sum(1 for n in notes if t0 <= n[0] < t0 + commit) for t0, _, _ in wins)
    return dict(seconds=round(total), setup_s=round(setup), search_s=round(search), windows=len(wins), tries=samples, rounds=iters,
                rollouts=sum(iters * tries * PLANTS for _, tries, _ in wins), sim_hours=round(sim / 3600, 2), numbers=numbers,
                workers=workers, speed=round(speed, 1), calibrated_runs=n_hist, low=round(total * 0.7), high=round(total * 1.4))


def learn_speed(log_lines, used):
    """After a run: how fast this computer really was (simulated seconds per second and worker), from the log's time stamps."""
    stamps = []
    for line in log_lines:
        m = re.match(r"window\s+(\d+) t\s+(-?[\d.]+) s: (\d+) notes, dims\s+(\d+), cost.*\[(\d+) s\]", line)
        if m:
            stamps.append((float(m.group(2)), int(m.group(4)), float(m.group(5))))
    if len(stamps) < 4:
        return None
    commit, samples, iters, workers = used["commit"], used["samples"], used["iters"], used["workers"]
    sim = sum(iters * (samples if dims <= 25 else int(samples * 1.33)) * PLANTS * (commit + 0.6) for _, dims, _ in stamps[1:])
    wall = stamps[-1][2] - stamps[0][2]
    if wall < 5:
        return None
    speed = sim / (wall * _effective(workers))
    try:
        os.makedirs(os.path.dirname(TIMING_FILE), exist_ok=True)
        runs = []
        if os.path.exists(TIMING_FILE):
            with open(TIMING_FILE) as fh:
                runs = json.load(fh).get("runs", [])
        runs.append(dict(speed=round(speed, 2), workers=workers, windows=len(stamps), name=used.get("name")))
        with open(TIMING_FILE, "w") as fh:
            json.dump(dict(runs=runs[-40:]), fh, indent=1)
    except Exception:
        pass
    return speed


if __name__ == "__main__":
    for pid in ("ode", "k265", "assets/melodies/saints_D.mid", "assets/duets/ode_left.mid", "assets/duets/canon_right.mid", "furelise"):
        for side in ("right", "left"):
            r = positions(pid, side)
            print(pid, side, "|", len(r["positions"]), "positions", r["why"][:80])
            for o in r["positions"][:3]:
                print("     ", o["text"], "|", o["source"], "| proven" if o["proven"] else "| sim", "| legacy" if o["legacy"] else "")
    for pid, wrist in (("ode", "fixed"), ("k265", "fixed"), ("assets/duets/canon_left.mid", "fixed"), ("furelise", "plan")):
        for det in ("reuse", "draft", "standard", "fine"):
            e = estimate(dict(piece=pid, wrist=wrist, detail=det, workers=10))
            print(f"{pid:28s} {wrist:5s} {det:8s} {e['seconds']:5d} s  windows {e['windows']:3d}  rollouts {e['rollouts']}")
