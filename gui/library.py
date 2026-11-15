"""What the studio can show: pieces (the human side: which note, when) and plans (the robot side: joint commands).

A piece is a MIDI file or one of the three built-in pieces of scripts/sbto_piano.py. A plan is a folder with
theme_q_1khz.npz, in plans/ (shared through git) or out/ (this computer only). Nothing here needs MuJoCo.
"""
import json
import os
import re
import sys
import time

REPO = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(REPO, "scripts"))
from midi_io import guess_tune, note_name, part_of, read_notes, tracks  # noqa: E402

PLAN_FILE = "theme_q_1khz.npz"
BLACK = {1, 3, 6, 8, 10}
FINGERS = ["thumb", "index", "middle", "ring", "pinky"]

# the three pieces sbto_piano.py knows by name, with the same cuts as its load_piece()
BUILTIN = {
    "ode": dict(title="Ode to Joy", composer="Beethoven", file="assets/ode_to_joy/ode_to_joy.mid", origin="score"),
    "k265": dict(title="K.265 theme (Twinkle, twinkle)", composer="Mozart", file="assets/furelise/15/midi.mid", origin="human",
                 note="Played by a pianist (FürElise dataset, piece 15). The wrist path of that pianist is known."),
    "furelise": dict(title="Für Elise, opening", composer="Beethoven", file="assets/fur_elise_beethoven/fur_elise.mid", origin="score"),
}
NAMES = dict(jingle="Jingle Bells", saints="When the Saints Go Marching In", ode="Ode to Joy", mary="Mary Had a Little Lamb",
             korobeiniki="Korobeiniki", canon="Pachelbel's Canon in C", chopsticks="Chopsticks")
# videos in docs/media that show exactly this plan (or this pair of plans)
VIDEOS = {
    "plans/k265_fixed": "docs/media/k265_fixed.mp4", "plans/k265_human": "docs/media/k265_human.mp4",
    "plans/furelise_plan": "docs/media/furelise_plan.mp4", "plans/ode_fixed": "docs/media/ode_fixed.mp4",
    "plans/ode_level_s0": "docs/media/ode_level.mp4", "plans/saints_dmajor_bpm120_s0": "docs/media/saints_dmajor.mp4",
}
DUET_VIDEOS = {
    ("plans/ode_level_stroke90_s0", "plans/ode_accomp_left_s0"): "docs/media/ode_duet.mp4",
    ("plans/korobeiniki_melody_right_s0", "plans/korobeiniki_accomp_left_s0"): "docs/media/korobeiniki_duet.mp4",
    ("plans/canon_melody_right_s0", "plans/canon_bass_left_s0"): "docs/media/canon_duet.mp4",
}
# the melody of these two-hand pieces also exists as a one-hand piece: its plans pair with the accompaniment
MELODY_ALIASES = {"ode": ["ode", "assets/duets/ode_right.mid"], "jingle": ["assets/melodies/jingle.mid", "assets/duets/jingle_right.mid"]}


def is_black(m):
    return m % 12 in BLACK


def white_index(m):
    return sum(1 for k in range(21, m) if not is_black(k))


# ------------------------------------------------------------------ pieces
def _builtin_notes(name):
    notes = read_notes(os.path.join(REPO, BUILTIN[name]["file"]))
    if name == "k265":
        notes = [n for n in notes if n["on"] < 35 and n["pitch"] >= 71]
    elif name == "furelise":
        notes = [n for n in notes if n["track"] == 1 and n["on"] < 25.3]
    return notes


def piece_notes(piece_id, part=None):
    """[[on, off, pitch], ...] in seconds from the first note, as sbto_piano.py sees the piece. Drums (MIDI channel 10)
    are left out; part ('track:channel') keeps one instrument only."""
    if piece_id in BUILTIN:
        notes = _builtin_notes(piece_id)
    else:
        path = safe_path(piece_id, (".mid", ".midi"))
        notes = sorted((n for n in read_notes(path) if n.get("ch") != 9), key=lambda n: n["on"])
    if not notes:
        return []
    t0 = notes[0]["on"]                       # the whole piece's clock, also when one part is asked for
    if part is not None:
        notes = [n for n in notes if part_of(n) == part]
    return [[round(n["on"] - t0, 4), round(n["off"] - t0, 4), int(n["pitch"])] for n in notes]


def _pretty(stem):
    """'saints_D' -> 'When the Saints Go Marching In, in D major'."""
    m = re.match(r"^(.*?)(?:_([A-G]))?$", stem)
    base, key = m.group(1), m.group(2)
    title = NAMES.get(base, base.replace("_", " ").strip().title() if base.islower() else base.replace("_", " "))
    return title + (f", in {key} major" if key else "")


def piece_title(piece_id):
    """'assets/duets/ode_left.mid' -> 'Ode to Joy, accompaniment'."""
    if piece_id in BUILTIN:
        return f"{BUILTIN[piece_id]['composer']} · {BUILTIN[piece_id]['title']}"
    stem = os.path.splitext(os.path.basename(piece_id))[0]
    m = re.match(r"^(.*)_(right|left)$", stem) if "/duets/" in piece_id else None
    return f"{_pretty(m.group(1))}, {'melody' if m.group(2) == 'right' else 'accompaniment'}" if m else _pretty(stem)


def _stats(notes):
    if not notes:
        return dict(n_notes=0, duration=0.0, lo=0, hi=0, keys=[], n_black=0, max_together=0, fastest_ms=0)
    keys = sorted({n[2] for n in notes})
    ons = sorted(n[0] for n in notes)
    gaps = [b - a for a, b in zip(ons, ons[1:]) if b - a > 1e-6]
    ev = sorted([(n[0], 1) for n in notes] + [(n[1], -1) for n in notes], key=lambda e: (e[0], e[1]))
    cur = top = 0
    for _, d in ev:
        cur += d
        top = max(top, cur)
    return dict(n_notes=len(notes), duration=round(max(n[1] for n in notes), 2), lo=keys[0], hi=keys[-1], keys=keys,
                key_names=[note_name(k) for k in keys], n_black=sum(1 for k in keys if is_black(k)),
                span_white=white_index(keys[-1]) - white_index(keys[0]) + 1, max_together=top,
                fastest_ms=round(min(gaps) * 1000) if gaps else 0)


_piece_cache = {}


def _piece(piece_id, **extra):
    path = os.path.join(REPO, BUILTIN[piece_id]["file"] if piece_id in BUILTIN else piece_id)
    try:
        mt = os.path.getmtime(path)
    except OSError:
        return None
    hit = _piece_cache.get(piece_id)
    if hit and hit[0] == mt:
        return dict(hit[1], **extra)
    try:
        notes = piece_notes(piece_id)
    except Exception as e:  # a broken MIDI file must not take the library down
        info = dict(id=piece_id, error=str(e), **_stats([]))
    else:
        info = dict(id=piece_id, notes=notes, **_stats(notes))
    _piece_cache[piece_id] = (mt, info)
    return dict(info, **extra)


def _dataset():
    """The 153 recorded performances of the FürElise dataset (MIDI only; their hand motion stays on Hugging Face)."""
    try:
        with open(os.path.join(REPO, "assets/furelise/metadata.json")) as fh:
            return json.load(fh)
    except OSError:
        return []


def pieces(with_notes=False):
    """All pieces, grouped: our pieces (one hand), two hands (one entry per part), the FürElise dataset, imported.
    Without note lists unless asked: the dataset alone has about 400 000 notes."""
    out = []
    for name, b in BUILTIN.items():
        p = _piece(name, title=b["title"], composer=b["composer"], origin=b["origin"], group="one", file=b["file"], note=b.get("note", ""),
                   human_wrist=(name == "k265"))
        if p:
            out.append(p)
    for folder, group in (("assets/melodies", "one"), ("assets/songs", "songs"), ("assets/library", "imported")):
        d = os.path.join(REPO, folder)
        for f in sorted(os.listdir(d)) if os.path.isdir(d) else []:
            if f.lower().endswith((".mid", ".midi")):
                side = os.path.join(d, os.path.splitext(f)[0] + ".json")
                try:
                    with open(side) as fh:
                        src = json.load(fh)
                except (OSError, ValueError):
                    src = {}
                p = _piece(f"{folder}/{f}", title=src.get("title") or _pretty(os.path.splitext(f)[0]), composer=src.get("composer"), source=src.get("source"),
                           origin="imported" if group == "imported" else "score", group=group, file=f"{folder}/{f}",
                           **{k: src[k] for k in ("kind", "licence", "source_url", "lyrics", "version", "tune") if src.get(k)})
                if p:
                    out.append(p)
    for r in _dataset():
        f = f"assets/furelise/midi/{r['id']}.mid"
        p = _piece(f, title=r["title"], composer=r["composer"], origin="human", group="dataset", file=f, dataset_id=r["id"], motion_s=r["motion_s"])
        if p:
            out.append(p)
    d = os.path.join(REPO, "assets/duets")
    stems = sorted({f[:-len("_right.mid")] for f in os.listdir(d) if f.endswith("_right.mid")}) if os.path.isdir(d) else []
    for stem in stems:
        for part in ("right", "left"):
            f = f"assets/duets/{stem}_{part}.mid"
            if os.path.exists(os.path.join(REPO, f)):
                p = _piece(f, title=f"{_pretty(stem)}, {'melody' if part == 'right' else 'accompaniment'}", origin="score", group="two", file=f,
                           duet=stem, part=part, duet_title=_pretty(stem))
                if p:
                    out.append(p)
    used = {}
    for pl in plans():
        if pl.get("piece"):
            used.setdefault(pl["piece"], []).append(pl["id"])
    for p in out:
        p["plans"] = used.get(p["id"], [])
        if p["id"] == "k265":
            p["plans"] = p["plans"] + used.get("assets/furelise/midi/15.mid", [])
        if not with_notes:
            p.pop("notes", None)
    return out


def piece(piece_id):
    for p in pieces(with_notes=True):
        if p["id"] == piece_id:
            if piece_id not in BUILTIN and p.get("group") != "dataset":
                try:                          # a band arrangement: which instrument plays the tune
                    parts = tracks(safe_path(piece_id))
                except Exception:
                    parts = []
                if len(parts) > 1:
                    p["parts"], p["tune"] = parts, p.get("tune") or guess_tune(parts)     # the song's .json may name the tune part
            return p
    return None


MODES = ("onehand", "melody", "all")


def cut(piece_id, start, length, mode="onehand", tempo=1.0, at_once=1, split=60, part=None, hand=None):
    """A time window of a piece, as one of three versions:
      onehand  simplified so one hand reaches every note with its wrist in place: plays on the real hand
      melody   the top line (highest note of every chord from middle C up, notes never overlapping)
      all      every note
    part: take the tune from this instrument only ('track:channel', for band arrangements); then from its lowest note up.
    hand: a plan id: keep the hand where that plan has it (e.g. the Ode plan, the position the real hand plays in).
    -> (notes [[on, off, pitch]] from 0, info)."""
    import simplify
    notes = piece_notes(piece_id, part or None)
    every = piece_notes(piece_id) if part else notes     # chords under the tune come from every instrument
    if part:
        split = 0
    if not notes:
        raise ValueError("no notes")
    if mode not in MODES:
        raise ValueError("mode is onehand, melody or all")
    start, length = max(0.0, float(start)), min(max(float(length), 2.0), 180.0)
    win = [list(n) for n in notes if start <= n[0] < start + length]
    if not win:
        raise ValueError("no notes in this window" + (" for this instrument" if part else ""))
    info = dict(mode=mode, start=start, length=length, part=part or None)
    if mode == "melody":
        win = simplify.melody(win, split)
    elif mode == "onehand":
        import planner
        hands = planner.proven_hands("right")
        only = next((h for h in hands if h["plan"] == hand), None) if hand else None
        if hand and not only:
            raise ValueError("no shared plan with that hand position")
        r = simplify.fit(win, hands, tempo=tempo, split=split, at_once=at_once, only=only,
                         harmony_src=[list(n) for n in every if start - 0.1 <= n[0] < start + length + 0.1])
        win = r.pop("notes")
        info.update(r)
    if len(win) < 2:
        raise ValueError("fewer than two notes in this window")
    t0 = win[0][0]
    win = [[round(n[0] - t0, 4), round(n[1] - t0, 4), int(n[2])] for n in win]
    info["n_notes"] = len(win)
    info["keys"] = sorted({n[2] for n in win})
    info["key_names"] = [note_name(k) for k in info["keys"]]
    return win, info


def excerpt(piece_id, start, length, mode="onehand", tempo=1.0, at_once=1, name=None, split=60, part=None, hand=None):
    """Save cut() as a MIDI file in assets/library/ (with a .json beside it that says where it came from).
    Returns its piece id."""
    notes, info = cut(piece_id, start, length, mode, tempo, at_once, split, part, hand)
    start, length = info["start"], info["length"]
    p = piece(piece_id) or {}
    stem = name or re.sub(r"[^A-Za-z0-9]+", "_", (p.get("title") or os.path.basename(piece_id)))[:32].strip("_").lower()
    slow = mode == "onehand" and info.get("tempo", 1.0) != 1.0
    chords = mode == "onehand" and info.get("at_once", 1) > 1
    tag = {"melody": "", "all": "_all", "onehand": "_1h"}[mode] + (f"_c{info['at_once']}" if chords else "") + (f"_t{round(info['tempo'] * 100)}" if slow else "") + \
        (f"_p{part.replace(':', '-')}" if part else "") + ("_ode" if hand else "")
    rel = f"assets/library/{stem}_{int(start)}s_{int(length)}s{tag}.mid"
    os.makedirs(os.path.join(REPO, "assets/library"), exist_ok=True)
    from midi_io import write_notes
    write_notes(os.path.join(REPO, rel), [dict(on=n[0], off=n[1], pitch=n[2], vel=72) for n in notes])
    mm = lambda s: f"{int(s // 60)}:{int(s % 60):02d}"
    whole = start <= 0 and start + length >= (p.get("duration") or 1e9) - 0.5
    version = ([] if whole else [f"from {mm(start)}"]) + [{"melody": "melody", "all": "all notes", "onehand": "one hand, chords" if chords else "one hand"}[mode]]
    if mode == "onehand" and hand:
        version.append("hand like " + info["hand"]["source"].split(" · ")[-1])
    if slow:
        version.append(f"{round(info['tempo'] * 100)} %")
    side = dict(title=p.get("title") or stem, version=" · ".join(version), composer=p.get("composer"),
                source=piece_id, **{k: v for k, v in info.items() if k not in ("keys", "key_names")})
    for k in ("licence", "source_url"):
        if p.get(k):
            side[k] = p[k]
    with open(os.path.join(REPO, rel[:-4] + ".json"), "w") as fh:      # where it came from, for the library's title
        json.dump(side, fh, ensure_ascii=False)
    _piece_cache.pop(rel, None)
    return rel


def safe_path(rel, suffixes=None, must_exist=True):
    """A path inside the repo, given relative to it. Refuses anything that leaves the repo."""
    full = os.path.realpath(os.path.join(REPO, rel))
    if not (full == REPO or full.startswith(REPO + os.sep)):
        raise ValueError("path leaves the repository")
    if suffixes and not full.lower().endswith(tuple(suffixes)):
        raise ValueError("unexpected file type")
    if must_exist and not os.path.exists(full):
        raise FileNotFoundError(rel)
    return full


def import_midi(filename, data):
    """Save an uploaded MIDI file to assets/library/ and return its piece id."""
    stem = re.sub(r"[^A-Za-z0-9_-]+", "_", os.path.splitext(os.path.basename(filename))[0]).strip("_") or "piece"
    if data[:4] != b"MThd":
        raise ValueError("this is not a MIDI file")
    if len(data) > 2_000_000:
        raise ValueError("file larger than 2 MB")
    d = os.path.join(REPO, "assets/library")
    os.makedirs(d, exist_ok=True)
    rel = f"assets/library/{stem}.mid"
    with open(os.path.join(REPO, rel), "wb") as fh:
        fh.write(data)
    _piece_cache.pop(rel, None)
    notes = piece_notes(rel)          # raises if it cannot be read
    if not notes:
        os.remove(os.path.join(REPO, rel))
        raise ValueError("no notes in this file")
    return rel


# ------------------------------------------------------------------ plans
_plan_cache = {}


def _scores(rows):
    if not rows:
        return None
    return dict(lo=min(r["matched"] for r in rows), hi=max(r["matched"] for r in rows), wrong=max(r["wrong"] for r in rows), n=len(rows))


def _load_plan(rel):
    import numpy as np
    d = os.path.join(REPO, rel)
    Z = np.load(os.path.join(d, PLAN_FILE), allow_pickle=False)
    has = set(Z.files)

    def g(k, default=None):
        return Z[k] if k in has else default

    notes = [[round(float(a), 4), round(float(b), 4), int(p)] for a, b, p in Z["notes"]]
    fing = sorted({(int(p), int(f)) for p, f in Z["fing"]}) if "fing" in has else []
    x, dy, z, th = (float(v) for v in Z["mount"]) if "mount" in has else (0.22, -0.0235, 0.10, 25.0)
    wrist = str(g("wrist", "fixed"))
    info = dict(
        id=rel, name=os.path.basename(rel), shared=rel.startswith("plans/"), title=str(g("title", os.path.basename(rel))),
        side=str(g("side", "right")), wrist=wrist, playable=(wrist == "fixed"), notes=notes,
        length_s=round(float(Z["t"][-1]), 2), pre_roll=float(g("pre_roll", 1.5)), piece_t0=float(g("piece_t0", 0.0)),
        mount=dict(x=round(x, 4), z=round(z, 4), theta=round(th, 2), dy=round(dy, 4)), center=int(g("center", 76)),
        press_x=[round(float(v), 4) for v in Z["press_x"]] if "press_x" in has else None,
        stroke_ms=round(float(g("stroke_s", 0.03)) * 1000), real_limits=bool(g("real_limits", False)),
        start_hover=bool(g("start_hover", False)), gain=float(g("gain", 5.0)), fing=fing,
        level=(abs(th) < 0.5 and abs(z - 0.06) < 0.005), has_params=("P" in has and "lead" in has), joints=int(Z["q"].shape[1]),
        **_stats(notes))
    rp = os.path.join(d, "report.json")
    if os.path.exists(rp):
        with open(rp) as fh:
            R = json.load(fh)
        info["piece"] = R.get("piece")
        if info["piece"]:
            info["title"] = piece_title(info["piece"])
        info["cem"] = R.get("cem")
        info["dr"] = R.get("dr")
        info["wall_s"] = R.get("wall_s")
        info["optimised"] = bool((R.get("cem") or {}).get("windows"))
        train, test = R.get("cem_train") or [], R.get("cem_test") or []
        if train:
            info["score"] = dict(matched=train[0]["matched"], wrong=train[0]["wrong"], timing_ms=(train[0].get("timing_ms") or {}).get("p90_abs"))
        info["train"], info["test"] = _scores(train), _scores(test)
        info["before"] = dict(nominal=(R.get("baseline_train") or [{}])[0].get("matched"), train=_scores(R.get("baseline_train")), test=_scores(R.get("baseline_test")))
    hw = sorted(f for f in os.listdir(d) if f.startswith("hw_") and f.endswith(".npz"))
    info["hw_runs"] = len(hw)
    info["hw_last"] = hw[-1][3:-4] if hw else None
    return info


def _video(rel):
    own = os.path.join(rel, "theme_sim.mp4")
    if os.path.exists(os.path.join(REPO, own)):
        return own
    v = VIDEOS.get(rel)
    return v if v and os.path.exists(os.path.join(REPO, v)) else None


_plans_memo = [0.0, None]
PLANS_TTL = 5.0       # s: scanning ~100 folders on the exFAT disk takes 0.7 s; /api/library always scans afresh


def plans(fresh=False):
    if not fresh and _plans_memo[1] is not None and time.time() - _plans_memo[0] < PLANS_TTL:
        return list(_plans_memo[1])
    out = []
    for root in ("plans", "out"):
        d = os.path.join(REPO, root)
        for name in sorted(os.listdir(d)) if os.path.isdir(d) else []:
            f = os.path.join(d, name, PLAN_FILE)
            if not os.path.isfile(f):
                continue
            rel = f"{root}/{name}"
            rp = os.path.join(d, name, "report.json")
            stamp = (os.path.getmtime(f), os.path.getmtime(rp) if os.path.exists(rp) else 0, len(os.listdir(os.path.join(d, name))))
            hit = _plan_cache.get(rel)
            if not hit or hit[0] != stamp:
                try:
                    hit = (stamp, _load_plan(rel))
                except Exception as e:
                    hit = (stamp, dict(id=rel, name=name, shared=root == "plans", error=str(e), playable=False, notes=[], n_notes=0))
                _plan_cache[rel] = hit
            p = dict(hit[1])
            p["mtime"] = stamp[0]
            p["video"] = _video(rel)
            out.append(p)
    shared = {p["name"] for p in out if p["shared"]}
    out = [p for p in out if p["shared"] or p["name"] not in shared]      # a run copied to plans/ shows once
    _plans_memo[:] = [time.time(), out]
    return list(out)


def plan(plan_id):
    for fresh in (False, True):            # a run that has just finished may not be in the cached list yet
        for p in plans(fresh):
            if p["id"] == plan_id:
                return p
    return None


def plan_npz(plan_id):
    return safe_path(os.path.join(plan_id, PLAN_FILE), (".npz",))


def duets():
    """Pairs of plans that belong together: same two-hand piece, one melody plan and one accompaniment plan."""
    P = [p for p in plans() if p.get("playable") and not p.get("error")]
    out = []
    by_piece = {}
    shared_names = {p["name"] for p in P if p["shared"]}
    for p in P:
        if p.get("piece"):
            by_piece.setdefault(p["piece"], []).append(p)
    stems = sorted({m.group(1) for m in (re.match(r"assets/duets/(.+)_left\.mid$", k) for k in by_piece) if m})
    for stem in stems:
        melodies = []
        for pid in [f"assets/duets/{stem}_right.mid"] + MELODY_ALIASES.get(stem, []):
            melodies += by_piece.get(pid, [])
        melodies = [m for m in melodies if m["level"]]
        for a in melodies:
            for b in by_piece.get(f"assets/duets/{stem}_left.mid", []):
                if a["id"] == b["id"]:
                    continue
                v = DUET_VIDEOS.get((a["id"], b["id"]))
                own = os.path.join(a["id"], "duet_" + b["name"] + ".mp4")
                if os.path.exists(os.path.join(REPO, own)):
                    v = own
                if not (a["shared"] and b["shared"]) and (a["name"] in shared_names and not a["shared"] or b["name"] in shared_names and not b["shared"]):
                    continue
                out.append(dict(id=f"{a['id']}+{b['id']}", title=_pretty(stem), a=a["id"], b=b["id"], sides=[a["side"], b["side"]],
                                same_side=a["side"] == b["side"], shared=a["shared"] and b["shared"],
                                video=v if v and os.path.exists(os.path.join(REPO, v)) else None, gentle=a.get("stroke_ms", 0) >= 60))
    out.sort(key=lambda d: (not d["shared"], not d["video"], not d["gentle"], d["same_side"], d["title"]))
    return out


def share_plan(plan_id):
    """Move a run from out/ to plans/, where git shares it with the team."""
    if not plan_id.startswith("out/"):
        raise ValueError("only runs in out/ can be shared")
    src = safe_path(plan_id)
    dst = os.path.join(REPO, "plans", os.path.basename(plan_id))
    if os.path.exists(dst):
        raise ValueError(f"plans/{os.path.basename(plan_id)} exists already")
    os.rename(src, dst)
    _plan_cache.pop(plan_id, None)
    return "plans/" + os.path.basename(plan_id)


def recordings():
    """Camera sessions saved by scripts/camera_track.py (out/teleop/<stamp>/)."""
    d = os.path.join(REPO, "out/teleop")
    out = []
    for name in sorted(os.listdir(d), reverse=True) if os.path.isdir(d) else []:
        meta = os.path.join(d, name, "meta.json")
        if os.path.exists(meta):
            try:
                with open(meta) as fh:
                    out.append(dict(json.load(fh), id=f"out/teleop/{name}"))
            except Exception:
                pass
    return out


if __name__ == "__main__":
    t = time.time()
    for p in pieces():
        print(f"piece {p['id']:44s} {p['title'][:44]:44s} {p['n_notes']:4d} notes {p['duration']:6.1f} s  keys {p.get('key_names', [])[:8]} plans {len(p['plans'])}")
    for p in plans():
        print(f"plan  {p['id']:40s} {p.get('side', '?'):5s} {p.get('wrist', '?'):6s} {p.get('n_notes', 0):4d} notes  score {p.get('score')}  video {p.get('video')}  {p.get('error', '')}")
    for d in duets():
        print("duet ", d["title"], d["a"], "+", d["b"], d["video"])
    print(f"{time.time() - t:.2f} s")
