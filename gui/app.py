"""Wuji Quartet Studio: one window for the whole project, in the browser.

    python gui/app.py            # opens http://127.0.0.1:8770
    ./wq gui                     # the same inside the Docker image

Pages: the library (pieces and plans), Retarget (the SBTO optimiser with a time estimate), Play (one hand, two hands),
Teach, Camera (Sebas's webcam teleop) and Settings. Everything that takes time runs as a job (gui/jobs.py) by calling the
scripts in scripts/, so the studio never does anything the command line cannot do.

Only the Python standard library is needed to start it. Pages that need more (MuJoCo to optimise, MediaPipe for the
camera) say so. The server listens on this computer only unless --host says otherwise; then a token is required.
"""
import argparse
import importlib.util
import json
import os
import re
import secrets
import shutil
import signal
import socket
import subprocess
import sys
import threading
import time
import urllib.request
import webbrowser
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from urllib.parse import parse_qs, unquote, urlparse

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
import jobs as J  # noqa: E402
import library as lib  # noqa: E402
import planner  # noqa: E402

REPO = lib.REPO
STATIC = os.path.join(HERE, "static")
SETTINGS_FILE = os.path.join(HERE, "settings.local.json")
PY = sys.executable
MAX_EFFORT = 1.5                      # the team's hard limit (also enforced by scripts/wuji_hw.py)
SAFE = re.compile(r"^[A-Za-z0-9@._~/:+-]+$")      # what may appear in the SSH host, path and interpreter
DEFAULTS = dict(target="fake", ssh_host="", ssh_repo="~/Wuji-Quartet", ssh_python="~/wq-venv/bin/python", effort=1.0,
                teach_effort=1.0, teach_tempo=0.5, workers=planner.default_workers(), camera=0, sound=True)
M = J.Manager()
TOKEN = None
CAM = dict(job=None, port=None, target=None, actual=None, sink=None, follow=None, lock=threading.Lock(), record=None)


# ------------------------------------------------------------------ settings and environment
def load_settings():
    s = dict(DEFAULTS)
    try:
        with open(SETTINGS_FILE) as fh:
            s.update({k: v for k, v in json.load(fh).items() if k in DEFAULTS})
    except Exception:
        pass
    return s


S = load_settings()


def save_settings(new):
    for k, v in new.items():
        if k not in DEFAULTS:
            continue
        if k in ("ssh_host", "ssh_repo", "ssh_python"):
            v = str(v).strip()
            if v and not SAFE.match(v):
                raise ValueError(f"{k}: only letters, digits and @ . _ ~ / : + - are allowed")
        elif k in ("effort", "teach_effort"):
            v = min(max(float(v), 0.1), MAX_EFFORT)
        elif k == "teach_tempo":
            v = min(max(float(v), 0.25), 1.0)
        elif k in ("workers", "camera"):
            v = max(0, int(v))
        elif k == "target":
            if v not in ("fake", "local", "board"):
                raise ValueError("unknown hand")
        elif k == "sound":
            v = bool(v)
        if k == "ssh_host" and v != S.get(k):
            LINK["board"] = dict(new_link(), checking=True)
        S[k] = v
        if k in ("target", "ssh_host"):
            LINK_KICK.set()                   # check the hand now, not in a minute
    with open(SETTINGS_FILE, "w") as fh:
        json.dump(S, fh, indent=1)


def has(mod):
    try:
        return importlib.util.find_spec(mod) is not None
    except Exception:
        return False


ENV = {}


def probe_env():
    try:
        rev = subprocess.run(["git", "-C", REPO, "rev-parse", "--short", "HEAD"], capture_output=True, text=True, timeout=5).stdout.strip()
    except Exception:
        rev = ""
    ENV.update(python=sys.version.split()[0], platform=sys.platform, cores=os.cpu_count() or 1, mujoco=has("mujoco") and has("mink"), numpy=has("numpy"),
               sdk=has("wuji_sdk"), cv2=has("cv2"), mediapipe=has("mediapipe"), ffmpeg=bool(shutil.which("ffmpeg")), ssh=bool(shutil.which("ssh")),
               display=bool(os.environ.get("DISPLAY")) or sys.platform == "darwin", docker=os.path.exists("/.dockerenv"), rev=rev,
               hand_model=os.path.exists(os.path.join(REPO, "assets/mediapipe/hand_landmarker.task")), max_effort=MAX_EFFORT)


def targets():
    out = [dict(id="fake", label="Fake hand", short="Fake hand", real=False, help="No hardware. The full playback path with a simulated hand."),
           dict(id="local", label="Hand on this computer", short="This computer", real=True, ok=ENV.get("sdk", False),
                help="A Wuji Hand 2 on this computer's network port." if ENV.get("sdk") else "Needs the wuji-sdk package on this computer.")]
    if S["ssh_host"]:
        out.append(dict(id="board", label=f"Hand on {S['ssh_host'].split('@')[-1]}", short="Robot computer", real=True, ok=ENV.get("ssh", False),
                        help=f"Through SSH: {S['ssh_host']}, folder {S['ssh_repo']}."))
    return out


def hand_argv(target, script_args, tty=False):
    """The command that runs `python -u <script_args>` where the hand is: here, or on the robot computer through SSH."""
    if target in ("fake", "local"):
        return [PY, "-u"] + script_args
    if target != "board" or not S["ssh_host"]:
        raise ValueError("unknown hand")
    for v in (S["ssh_host"], S["ssh_repo"], S["ssh_python"]):
        if not SAFE.match(v):
            raise ValueError("check the SSH settings")
    remote = f"cd {S['ssh_repo']} && {S['ssh_python']} -u " + " ".join(J._show(a) for a in script_args)
    return ["ssh", "-tt" if tty else "-T", "-o", "BatchMode=yes", "-o", "ConnectTimeout=8", "-o", "ServerAliveInterval=5",
            "-o", "ServerAliveCountMax=3", S["ssh_host"], remote]


def ssh_run(cmd, timeout=15):
    r = subprocess.run(["ssh", "-T", "-o", "BatchMode=yes", "-o", "ConnectTimeout=8", S["ssh_host"], cmd], capture_output=True, text=True, timeout=timeout)
    return r.returncode, r.stdout.strip(), r.stderr.strip()


def need_real_ok(req, target):
    if target != "fake" and not req.get("confirm"):
        raise ValueError("a real hand needs the confirmation")
    if target == "local" and not ENV.get("sdk"):
        raise ValueError("the wuji-sdk package is not installed on this computer")


def note_hand_line(line):
    """Keep the last word on whether the hand is off. hand_off.py prints one line per hand ('<SN>: off, all joints limp'):
    start_util counts those, since with two hands one limp hand must not confirm the other."""
    if "switched off: confirmed" in line:
        M.set_hand("confirmed", "off, confirmed")
    elif "NOT CONFIRMED" in line or "STILL SWITCHED ON" in line or "STILL ON" in line or "no answer after switching off" in line:
        M.set_hand("not_confirmed", "switch-off NOT confirmed")


# ------------------------------------------------------------------ are the real hands there? (reads only, never a command to a hand)
# The robot computer pings both hands' fixed addresses every few seconds (only while a page is open and no hand job runs), and every
# job on a real hand reports what it found (serial number, firmware, joints online). The hand on this computer is never pinged: a home
# Wi-Fi on 192.168.1.x would answer for it. The robot computer has one Ethernet port: the second hand comes in through a USB-Ethernet
# adapter, which the probe lists so the Hands page can say when it is plugged in but not set up (scripts/hand_adapter.sh).
SIDES = (("right", "192.168.1.111"), ("left", "192.168.1.110"))
HAND_SIDE = {ip: s for s, ip in SIDES}


def new_link():
    return dict(state="unknown", text="not checked yet", time=None, checking=False, adapters=[],
                hands={s: dict(ip=ip, up=None, dev=None, wifi=False, sn=None, firmware=None, joints=None, read=None) for s, ip in SIDES})


LINK = {t: new_link() for t in ("local", "board")}
LINK_KICK = threading.Event()
SEEN = [0.0]                                        # when a page last asked for /api/state
PROBE = ("for a in 192.168.1.111 192.168.1.110; do d=$(ip -o route get $a 2>/dev/null | sed -n 's/.* dev \\([^ ]*\\).*/\\1/p'); "
         "if ping -c 1 -W 1 $a >/dev/null 2>&1; then echo \"up $a $d\"; else echo \"down $a $d\"; fi; done; "
         "for n in /sys/class/net/*; do i=${n##*/}; case $i in enx*|eth[1-9]*) "
         "echo \"nic $i $(cat $n/carrier 2>/dev/null || echo -) $(ip -4 -o addr show dev $i | awk '{print $4}' | paste -sd, -)\";; esac; done")
SSH_DOWN = re.compile(r"ssh: |Connection timed out|Could not resolve|No route to host|Connection refused|Permission denied \(|does not answer")
DOWN = "the robot computer does not answer: is it on, and on Tailscale?"


def link_says(target, down=None):
    """The one line over the page, from what is known about each hand."""
    L, now = LINK[target], time.time()
    hs = L["hands"]
    up = [s for s, _ in SIDES if hs[s]["up"]]
    off = [s for s, _ in SIDES if hs[s]["up"] is False]
    if down:
        state, text = "down", down
    elif up:
        state = "ok"
        text = "both hands answer" if len(up) == 2 else f"{up[0]} hand answers" + (f", the {off[0]} hand does not" if off else "")
    elif off:
        state = "no_hand"
        text = ("the robot computer sends 192.168.1.x through Wi-Fi, not the cable to the hands" if any(hs[s]["wifi"] for s in off)
                else "no hand answers: power on? network cable in?")
    else:
        state, text = "unknown", "not checked yet"
    L.update(state=state, text=text, time=now, checking=False)


def note_link_line(target, line):
    """What a job on a real hand learnt about the connection (hand_info.py, hand_off.py and wuji_hw print 'found SN=...')."""
    if target not in LINK:
        return
    hs, now = LINK[target]["hands"], time.time()
    m = re.search(r"found\s+SN=(\S+)\s+\(?(LEFT|RIGHT|left|right|side unknown)\)?(?:\s+hand)?\s+ip=([\d.]+)\S*\s+(?:firmware|fw)=(\S*)", line)
    if m:                                         # at scan time the SDK may not know the firmware yet: it comes with 'Discovered device'
        side = m.group(2).lower() if m.group(2).lower() in hs else HAND_SIDE.get(m.group(3))
        if side:
            old = hs[side]
            same = old["sn"] == m.group(1)
            hs[side].update(up=True, wifi=False, sn=m.group(1), firmware=m.group(4) or (old["firmware"] if same else None), read=now,
                            joints=old["joints"] if same else None)
            link_says(target)
    elif m := re.search(r"Discovered device: (\S+) \(IP: [^,]*, FW: ([^)\s]+)\)", line):
        for h in hs.values():
            if h["sn"] == m.group(1):
                h["firmware"] = m.group(2)
    elif m := re.search(r"(\S+): joints online: (\d+) of 20", line):
        for h in hs.values():
            if h["sn"] == m.group(1):
                h.update(joints=int(m.group(2)), read=now)
    elif m := re.search(r"no Wuji Hand 2 found(?: for: (left|right) hand)?", line):
        for s in ([m.group(1)] if m.group(1) else hs):
            hs[s]["up"] = False
        link_says(target)
    elif target == "board" and SSH_DOWN.search(line):
        link_says(target, DOWN)


def probe_board():
    LINK["board"]["checking"] = True
    try:
        rc, out, err = ssh_run(PROBE, timeout=20)
    except Exception:
        rc, out, err = 255, "", "timeout"
    if rc != 0 and not out:
        return link_says("board", DOWN)
    hs, adapters = LINK["board"]["hands"], []
    for parts in (ln.split() for ln in out.splitlines()):
        if len(parts) >= 2 and parts[0] in ("up", "down") and parts[1] in HAND_SIDE:
            dev = parts[2] if len(parts) > 2 else None
            wifi = bool(dev and dev.startswith("wl"))    # 192.168.1.x leaves through Wi-Fi: a stranger there may answer, not the hand
            hs[HAND_SIDE[parts[1]]].update(up=parts[0] == "up" and not wifi, dev=dev, wifi=wifi)
        elif len(parts) >= 3 and parts[0] == "nic":
            adapters.append(dict(name=parts[1], link=parts[2] == "1", addrs=parts[3].split(",") if len(parts) > 3 else []))
    LINK["board"]["adapters"] = adapters
    link_says("board")


def link_loop():
    last = 0.0
    while True:
        kicked = LINK_KICK.wait(2.0)
        LINK_KICK.clear()
        if not S["ssh_host"] or not ENV.get("ssh"):
            continue
        every = 10 if S["target"] == "board" else 60
        if not kicked and (time.time() - SEEN[0] > 30 or time.time() - last < every):
            continue
        if M.active("hand"):                      # a running hand job reports the connection itself
            LINK["board"]["checking"] = False
            continue
        last = time.time()
        probe_board()


# ------------------------------------------------------------------ retarget (the SBTO optimiser)
def start_retarget(req):
    if not ENV.get("mujoco"):
        raise ValueError("optimising needs MuJoCo and mink on this computer: pip install -r requirements.txt, or ./wq gui")
    busy = [os.path.basename(j.meta.get("plan", "")) for j in M.active(kind="retarget")]   # queued runs have no folder yet
    argv, out_rel, used = planner.build_command(dict(req, _busy=busy), PY)
    est = planner.estimate(dict(req, **{k: used[k] for k in ("samples", "iters", "commit", "workers") if k in used}))
    notes = lib.piece_notes(used["piece"])
    t_first, t_last = min(n[0] for n in notes), max(n[0] for n in notes)
    p = lib.piece(used["piece"]) or {}
    meta = dict(plan=out_rel, used=used, estimate=est, windows=[], piece_title=p.get("title", used["piece"]), n_notes=len(notes), command=" ".join(J._show(a) for a in argv[1:]))
    if req.get("pair"):                           # one of two runs started together by 'Both hands': the duet's stem and the hand
        meta["pair"] = dict(stem=str(req["pair"]), side=used.get("side", "right"))

    def run(job):
        t_search = [None]

        def on_line(line):
            if line.startswith("IK keyframes"):
                job.phase = "Measuring the servo delay"
            elif line.startswith("lead iter"):
                m = re.search(r"\((\d+)/(\d+), (\d+) wrong\)", line)
                if m:
                    meta["first"] = dict(matched=int(m.group(1)), wrong=int(m.group(3)))
            elif line.startswith("DR set"):
                job.phase = "Scoring the start on ten setups"
            elif line.startswith(("baseline (no CEM)", "start (before CEM)", "CEM train plants")):
                key = "baseline" if line.startswith("baseline") else "start" if line.startswith("start") else "result"
                rows = re.findall(r"'(\d+)/(\d+) w(\d+)'", line)
                k = planner.PLANTS
                meta[key] = dict(train=[[int(a), int(c)] for a, _, c in rows[:k]], test=[[int(a), int(c)] for a, _, c in rows[k:]])
                if key != "result" and used["detail"] != "reuse":
                    job.phase = "Searching"
                    t_search[0] = t_search[0] or time.time()
                    job.progress = job.progress or 0.0
            elif line.startswith("window"):
                m = re.match(r"window\s+(\d+) t\s+(-?[\d.]+) s: (\d+) notes, dims\s+(\d+), cost\s+([\d.]+) ->\s+([\d.]+)\s+\[(\d+) s\]", line)
                if m:
                    t = float(m.group(2))
                    meta["windows"].append([round(t, 2), float(m.group(5)), float(m.group(6)), int(m.group(3))])
                    done = len(meta["windows"])
                    total = max(est.get("windows") or 1, done)
                    job.progress = min(0.99, done / total)
                    job.phase = f"Searching: step {done} of {total}"
                    el = time.time() - (t_search[0] or job.started)
                    job.eta = round(el / done * (total - done) + 6)
            elif line.startswith("CEM done"):
                job.phase = "Scoring the result on ten setups"
                job.eta = None
            elif line.startswith("total "):
                job.phase = "Done"

        job.phase = "Finger poses for every key"
        rc = job.exec(argv, on_line)
        ok = rc == 0 and os.path.exists(os.path.join(REPO, out_rel, lib.PLAN_FILE))
        if ok:
            meta["wall_s"] = round(time.time() - job.started)
            if used["detail"] != "reuse":
                sp = planner.learn_speed(job.log, used)
                if sp:
                    meta["speed"] = round(sp, 1)
        return ok

    return M.submit(J.Job("retarget", f"Retarget: {meta['piece_title']} → {used['name']}", "compute", run, meta))


# ------------------------------------------------------------------ videos and checks in simulation
_GL = {}


def gl_env():
    """A MuJoCo offscreen backend that works on this computer (tried once): the one already set, then EGL, the window system, OSMesa."""
    if "env" in _GL:
        return _GL["env"]
    test = "import mujoco;m=mujoco.MjModel.from_xml_string('<mujoco><worldbody><geom size=\"1\"/></worldbody></mujoco>');r=mujoco.Renderer(m,32,32);r.update_scene(mujoco.MjData(m));r.render()"
    tries = ([os.environ["MUJOCO_GL"]] if os.environ.get("MUJOCO_GL") else []) + (["egl", "glfw", "osmesa"] if sys.platform != "darwin" else ["glfw"])
    for gl in tries:
        e = dict(MUJOCO_GL=gl, PYOPENGL_PLATFORM="" if gl == "glfw" else gl)
        try:
            if subprocess.run([PY, "-c", test], env=dict(os.environ, **e), capture_output=True, timeout=60).returncode == 0:
                _GL["env"] = e
                return e
        except Exception:
            pass
    _GL["env"] = None
    return None


# ------------------------------------------------------------------ the 3D view of a plan (scripts/plan_view.py, cached in out/gui/views)
VIEW_LOCKS = {}
VIEW_LOCK = threading.Lock()


def plan_view(ids):
    """The 3D view's data for one plan or a pair: simulated once, rebuilt when a plan, the script or a pianist's hands change."""
    if not 1 <= len(ids) <= 2:
        raise ValueError("one plan, or two for two hands")
    ps = [lib.plan(i) for i in ids]
    if any(not p or p.get("error") for p in ps):
        raise ValueError("unknown plan")
    if not ENV.get("mujoco"):
        raise ValueError("the 3D view simulates the plan: it needs MuJoCo on this computer (./wq gui)")
    key = "+".join(re.sub(r"[^A-Za-z0-9._-]+", "~", p["id"]) for p in ps)
    out = os.path.join(REPO, "out/gui/views", key + ".json")
    deps = [os.path.join(REPO, p["id"], f) for p in ps for f in (lib.PLAN_FILE, "report.json", "scene.xml", "log.txt")]
    deps += [os.path.join(REPO, "scripts/plan_view.py")] + [os.path.join(REPO, "assets/furelise", d, "hands.npz")
                                                           for d in os.listdir(os.path.join(REPO, "assets/furelise")) if d.isdigit()]
    newest = max((os.path.getmtime(f) for f in deps if os.path.exists(f)), default=0)
    fresh = lambda: os.path.exists(out) and os.path.getmtime(out) >= newest
    if fresh():
        return out
    with VIEW_LOCK:
        lock = VIEW_LOCKS.setdefault(key, threading.Lock())
    with lock:                                   # two pages asking at once: one simulation
        if not fresh():
            r = subprocess.run([PY, "-B", "scripts/plan_view.py", *[p["id"] for p in ps], "--out", out], cwd=REPO, capture_output=True, text=True, timeout=900)
            if r.returncode != 0 or not os.path.exists(out):
                raise RuntimeError("plan_view.py failed: " + ((r.stderr or r.stdout).strip().splitlines() or ["no output"])[-1])
    return out


def start_pose_of(plan_id):
    """Where the plan's hand goes and its fingertips at the first frame (gui/startpose.py; needs MuJoCo for the fingertips)."""
    p = lib.plan(plan_id)
    if not p or p.get("error"):
        raise ValueError("unknown plan")
    if not ENV.get("mujoco"):
        raise ValueError("the start pose is computed with MuJoCo: run the studio where MuJoCo is installed (./wq gui)")
    import startpose
    return startpose.start_pose(p["id"])


def start_render(req):
    if not (ENV.get("mujoco") and ENV.get("ffmpeg")):
        raise ValueError("videos need MuJoCo and ffmpeg on this computer")
    a = lib.plan(req["plan"])
    if not a or a.get("error"):
        raise ValueError("unknown plan")
    b = lib.plan(req["plan_b"]) if req.get("plan_b") else None
    if b:
        out = os.path.join(a["id"], f"duet_{b['name']}.mp4")
        argv = [PY, "-u", "scripts/render_duet.py", a["id"], b["id"], "--out", out]
        title = f"Video: {a['name']} + {b['name']}"
    else:
        out = os.path.join(a["id"], "theme_sim.mp4")
        argv = [PY, "-u", "scripts/render_theme.py", a["id"]]
        title = f"Video: {a['name']}"
    meta = dict(plan=a["id"], plan_b=b["id"] if b else None, video=out, seconds=(a["length_s"] + (8 if not b else 0)))

    def run(job):
        job.phase = "Looking for a renderer"
        e = gl_env()
        if e is None:
            job.say("[studio] no offscreen renderer works on this computer (tried EGL, the window system, OSMesa). Use ./wq gui.")
            return False
        job.phase = "Simulating and filming"
        job.progress = 0.0
        t0 = time.time()
        guess = max(15.0, 1.0 * meta["seconds"])           # 13 s for a 33 s piece on a desktop graphics card; software rendering is slower
        done = threading.Event()

        def tick():
            while not done.wait(0.5):
                job.progress = min(0.97, (time.time() - t0) / guess)
                job.eta = max(1, round(guess - (time.time() - t0)))
        threading.Thread(target=tick, daemon=True).start()
        try:
            rc = job.exec(argv, env=e)
        finally:
            done.set()
        return rc == 0 and os.path.exists(os.path.join(REPO, out))

    return M.submit(J.Job("render", title, "compute", run, meta))


def start_check(req):
    """Both hands in one simulation: notes per hand, hand-to-hand contacts. About ten seconds."""
    if not ENV.get("mujoco"):
        raise ValueError("the check needs MuJoCo on this computer")
    a, b = lib.plan(req["plan"]), lib.plan(req["plan_b"])
    if not a or not b:
        raise ValueError("unknown plan")
    meta = dict(plan=a["id"], plan_b=b["id"], hands=[])

    def run(job):
        def on_line(line):
            m = re.match(r"(left|right) hand · (\S+): (\d+)/(\d+) notes, (\d+) wrong", line)
            if m:
                meta["hands"].append(dict(side=m.group(1), plan=m.group(2), matched=int(m.group(3)), total=int(m.group(4)), wrong=int(m.group(5))))
            m = re.search(r"keys outside both parts: (\d+) · simulation steps with the two hands touching: (\d+) · hands ([\d.]+) cm apart", line)
            if m:
                meta.update(stray=int(m.group(1)), touching=int(m.group(2)), apart_cm=float(m.group(3)))
        job.phase = "Both hands in one simulation"
        return job.exec([PY, "-u", "scripts/render_duet.py", a["id"], b["id"], "--check"], on_line) == 0

    return M.submit(J.Job("check", f"Check: {a['name']} + {b['name']}", "compute", run, meta))


def start_viewer(req):
    a = lib.plan(req["plan"])
    if not a or not ENV.get("mujoco") or not ENV.get("display") or ENV.get("docker"):
        raise ValueError("the 3D viewer needs MuJoCo and a screen on this computer (not inside Docker)")
    exe = shutil.which("mjpython") if sys.platform == "darwin" else PY

    def run(job):
        job.phase = "Viewer open"
        job.exec([exe or PY, "-u", "scripts/view_theme.py", a["id"]])
        return True

    return M.submit(J.Job("viewer", f"3D viewer: {a['name']}", "util", run, dict(plan=a["id"])))


# ------------------------------------------------------------------ playing on a hand
def clock_offset(job):
    """Robot computer's clock minus this computer's clock, in seconds (the start time is given in the robot computer's time)."""
    best = None
    for _ in range(3):
        t0 = time.time()
        rc, out, err = ssh_run("python3 -c 'import time; print(time.time())'")
        t1 = time.time()
        if rc != 0:
            raise RuntimeError(f"the robot computer does not answer: {err or out}")
        if best is None or t1 - t0 < best[0]:
            best = (t1 - t0, float(out.split()[-1]) - 0.5 * (t0 + t1))
    job.say(f"[studio] robot computer clock is {best[1]:+.2f} s from this one (round trip {best[0] * 1000:.0f} ms)")
    return best[1], best[0]


def push_plan(job, plan_id):
    """Copy the plan file to the robot computer when it is missing there or differs in size."""
    rel = f"{plan_id}/{lib.PLAN_FILE}"
    size = os.path.getsize(os.path.join(REPO, rel))
    rc, out, _ = ssh_run(f"stat -c %s {S['ssh_repo']}/{rel} 2>/dev/null || echo missing")
    if out.strip() == str(size):
        return True
    job.say(f"[studio] copying {rel} to the robot computer")
    ssh_run(f"mkdir -p {S['ssh_repo']}/{plan_id}")
    r = subprocess.run(["scp", "-q", "-o", "BatchMode=yes", "-o", "ConnectTimeout=8", os.path.join(REPO, rel), f"{S['ssh_host']}:{S['ssh_repo']}/{rel}"],
                       capture_output=True, text=True, timeout=120)
    if r.returncode != 0:
        job.say(f"[studio] copy failed: {r.stderr.strip()}")
    return r.returncode == 0


def start_play(req):
    target = req.get("target") or S["target"]
    need_real_ok(req, target)
    teach = req.get("mode") == "teach"
    tempo = min(max(float(req.get("tempo") or 1.0), 0.25), 1.0)
    effort = min(max(float(req.get("effort") or S["effort"]), 0.1), MAX_EFFORT)
    repeats = min(max(int(req.get("repeats") or 1), 1), 30)
    pause = min(max(float(req.get("pause") or 4.0), 0.0), 60.0)
    countdown = min(max(float(req.get("countdown") or (4 if target == "fake" else 9 if target == "local" else 13)), 3.0), 60.0)
    b = lib.plan(req["plan_b"]) if req.get("plan_b") else None
    a = lib.plan(req["plan"])
    for p in (a, b) if req.get("plan_b") else (a,):
        if not p or p.get("error"):
            raise ValueError("unknown plan")
        if not p["playable"]:
            raise ValueError(f"{p['name']} moves the wrist: it needs an arm, the hand alone cannot play it")
    fingers = [f for f in lib.FINGERS if f in (req.get("fingers") or lib.FINGERS)] or lib.FINGERS
    start = float(req["start"]) if req.get("start") not in (None, "") else None
    end = float(req["end"]) if req.get("end") not in (None, "") else None
    if b:
        t00 = min(a["piece_t0"], b["piece_t0"])
        tracks = [dict(plan=p["id"], side=p["side"], shift=(p["piece_t0"] - t00) / tempo, offset=p["pre_roll"]) for p in (a, b)]
        title = f"{'Teach' if teach else 'Play'}: {a['name']} + {b['name']}"
    else:
        t0 = 0.0 if start is None else max(0.0, start + a["pre_roll"] - 1.0)
        tracks = [dict(plan=a["id"], side=a["side"], shift=0.0, offset=a["pre_roll"] - t0)]
        title = f"{'Teach' if teach else 'Play'}: {a['name']}"
    meta = dict(plan=a["id"], plan_b=b["id"] if b else None, target=target, real=target != "fake", tempo=tempo, effort=effort, repeats=repeats, teach=teach,
                fingers=fingers, start=start, end=end, summary=[], rep=0, timeline=None, played=0)

    def run(job):
        off = 0.0
        if target == "board":
            job.phase = "Reaching the robot computer"
            off, rt = clock_offset(job)
            for p in (a, b) if b else (a,):
                if not push_plan(job, p["id"]):
                    return False
        for rep in range(repeats):
            if job.stop_requested:
                break
            meta["rep"] = rep + 1
            start_at = time.time() + countdown
            if b:
                args = ["scripts/play_duet.py", a["id"], b["id"], "--effort", f"{effort:g}", "--tempo", f"{tempo:g}", "--yes", "--start-at", repr(start_at + off)]
                if req.get("sn_a"): args += ["--sn-a", str(req["sn_a"])]
                if req.get("sn_b"): args += ["--sn-b", str(req["sn_b"])]
                if target == "fake": args += ["--dry-run"]
            else:
                args = ["scripts/play_on_hand.py", f"{a['id']}/{lib.PLAN_FILE}", "--effort", f"{effort:g}", "--tempo", f"{tempo:g}", "--yes",
                        "--start-at", repr(start_at + off)]
                if len(fingers) < 5: args += ["--fingers", ",".join(fingers)]
                if start is not None: args += ["--start", f"{start:g}"]
                if end is not None: args += ["--end", f"{end:g}"]
                if target == "fake":
                    os.makedirs(os.path.join(REPO, "out/gui/dry"), exist_ok=True)
                    args += ["--dry-run", "--log", f"out/gui/dry/{a['name']}.npz"]
            meta["timeline"] = dict(start_at=start_at, tempo=tempo, tracks=tracks, rep=rep + 1, repeats=repeats, start=start, end=end)
            meta["late"] = False
            got = dict(played=0, off=False)
            job.phase = "Getting ready"
            M.set_hand("on", "in use")
            rep_done = threading.Event()
            span = max(p["length_s"] for p in ((a, b) if b else (a,))) if start is None and end is None else ((end if end is not None else a["duration"]) - (start or 0.0) + 2.6)

            def tick(start_at=start_at, span=span / tempo):
                while not rep_done.wait(0.25):
                    job.progress = min(1.0, max(0.0, (rep + (time.time() - start_at) / span) / repeats)) if time.time() > start_at else rep / repeats
            threading.Thread(target=tick, daemon=True).start()

            def on_line(line):
                note_hand_line(line)
                note_link_line(target, line)
                if "ramping to the start pose" in line:
                    job.phase = "Moving to the start pose"
                elif "at start pose" in line:
                    job.phase = "Playing"
                elif "streamed " in line and "frames" in line:
                    got["played"] += 1
                    m = re.search(r"skipped (\d+)", line)
                    meta["skipped"] = int(m.group(1)) if m else 0
                    job.phase = "Switching the hand off"
                elif "switched off: confirmed" in line:
                    got["off"] = True
                elif "after the common start time" in line:
                    meta["late"] = True
                elif re.match(r"\s+(thumb|index|middle|ring|pinky)\s+furthest", line):
                    m = re.match(r"\s+(\w+)\s+furthest from command\s+([\d.]+) deg, peak (?:current|effort) ([\d.]+)(?: A, at the limit\s+([\d.]+) %)?", line)
                    if m:
                        meta["summary"] = [r for r in meta["summary"] if r["finger"] != m.group(1)] + [
                            dict(finger=m.group(1), err_deg=float(m.group(2)), peak=float(m.group(3)), at_limit=float(m.group(4) or 0))]

            try:
                job.exec(hand_argv(target, args, tty=True), on_line, ctrl_c_on_stdin=(target == "board"))
            finally:
                rep_done.set()
            need = 2 if b else 1
            if not got["off"]:
                if M.hand["state"] != "not_confirmed":
                    M.set_hand("not_confirmed", "switch-off not seen")
                job.say("[studio] the switch-off was not confirmed: press 'Switch the hand off'")
                return False
            if got["played"] < need:
                if meta["late"]:
                    job.say("[studio] the hand was ready after the start time: raise the countdown and start again")
                return False
            meta["played"] = rep + 1
            if rep + 1 < repeats:
                job.phase = f"Pause before round {rep + 2} of {repeats}"
                meta["timeline"] = dict(meta["timeline"], next_in=pause, paused_at=time.time())
                if not job.wait(pause):
                    break
        return meta["played"] == repeats

    return M.submit(J.Job("teach" if teach else "play", title, "hand", run, meta))


def start_util(req, which):
    target = req.get("target") or S["target"]
    if target == "fake":
        raise ValueError("the fake hand has nothing to check")
    if target == "local" and not ENV.get("sdk"):
        raise ValueError("the wuji-sdk package is not installed on this computer")
    script, title = dict(off=("scripts/hand_off.py", "Switch the hand off"), info=("scripts/hand_info.py", "Find the hand (reads only)"))[which]
    meta = dict(target=target, hands=[])

    def run(job):
        off = dict(limp=0, bad=0)                 # hand_off.py: one line per hand it found

        def on_line(line):
            note_hand_line(line)
            note_link_line(target, line)
            m = re.match(r"found\s+SN=(\S+)\s+(LEFT|RIGHT|side unknown) hand\s+ip=(\S+)\s+firmware=(\S*)", line)
            if m:
                meta["hands"].append(dict(sn=m.group(1), side=m.group(2).lower(), ip=m.group(3), firmware=m.group(4)))
            m = re.match(r"(\S+): joints online: (\d+) of 20", line)
            if m:
                for h in meta["hands"]:
                    if h["sn"] == m.group(1):
                        h["joints"] = int(m.group(2))
            if re.match(r"\S+: off, all joints limp", line):
                off["limp"] += 1
            elif re.match(r"\S+: (no answer after switching off|\d+ joints STILL ON)", line):
                off["bad"] += 1
        ok = job.exec(hand_argv(target, [script]), on_line) == 0
        if which == "off":                        # confirmed only when every hand found said limp and the script ended cleanly
            if ok and off["limp"] and not off["bad"]:
                M.set_hand("confirmed", "off, confirmed")
            else:
                M.set_hand("not_confirmed", "switch-off NOT confirmed")
                job.say(f"[studio] switch-off NOT confirmed: {off['limp']} hand(s) limp, {off['bad']} not; look at the hands, unplug the power if one holds a pose")
        return ok

    return M.submit(J.Job("hand_" + which, title, "util", run, meta))


def start_adapter(req):
    """The second hand through a USB-Ethernet adapter on the robot computer: scripts/hand_adapter.sh, sent over SSH (no copy needed)."""
    target = req.get("target") or S["target"]
    if target != "board" or not S["ssh_host"]:
        raise ValueError("the adapter is set up on the robot computer: choose it first")
    if not SAFE.match(S["ssh_host"]):
        raise ValueError("check the SSH settings")
    if M.active("hand"):
        raise ValueError("a hand is moving: set the adapter up after it")

    def run(job):
        ok = job.exec(["sh", "-c", f"ssh -T -o BatchMode=yes -o ConnectTimeout=8 {S['ssh_host']} 'bash -s' < scripts/hand_adapter.sh"],
                      lambda line: note_link_line(target, line)) == 0
        LINK_KICK.set()                           # the hands page shows the result of a fresh ping, not the script's word
        return ok

    return M.submit(J.Job("hand_adapter", "Set up the USB adapter for the second hand", "util", run, dict(target=target)))


def start_hello(req):
    """First motion on one hand: scripts/hand_hello.py (index finger base joint 9 deg and back, twice, 0.5 A)."""
    target, side = req.get("target") or S["target"], req.get("side")
    if side not in ("left", "right"):
        raise ValueError("which hand: left or right")
    if target == "fake":
        raise ValueError("the fake hand has nothing to wave")
    need_real_ok(req, target)
    meta = dict(target=target, side=side, real=True)

    def run(job):
        got = dict(on=False, off=False)

        def on_line(line):
            note_hand_line(line)
            note_link_line(target, line)
            if "enabled and holding" in line:
                got["on"] = True
                job.phase = f"{side.capitalize()} hand: index finger 9° and back"
            elif "switched off: confirmed" in line:
                got["off"] = True

        job.phase = f"Finding the {side} hand"
        M.set_hand("on", "in use")
        ok = job.exec(hand_argv(target, ["scripts/hand_hello.py", "--side", side, "--yes"], tty=True), on_line, ctrl_c_on_stdin=(target == "board")) == 0
        if got["off"]:
            M.set_hand("confirmed", "off, confirmed")
        elif got["on"]:
            M.set_hand("not_confirmed", "switch-off not seen")
            job.say("[studio] the switch-off was not confirmed: press 'Switch the hand off'")
            return False
        else:
            M.set_hand("unknown", "never switched on")
        return ok

    return M.submit(J.Job("hello", f"{side.capitalize()} hand: one finger, 9° and back", "hand", run, meta))


def start_sync(req):
    if not S["ssh_host"]:
        raise ValueError("set the robot computer in Settings first")
    if not shutil.which("rsync"):
        raise ValueError("rsync is not installed on this computer")
    dst = f"{S['ssh_host']}:{S['ssh_repo']}/"

    def run(job):
        job.phase = "Copying scripts and plans"
        ssh = "ssh -o BatchMode=yes -o ConnectTimeout=8"
        a = job.exec(["rsync", "-az", "-e", ssh, "--exclude", "__pycache__", "scripts", dst])
        b = job.exec(["rsync", "-az", "-e", ssh, "--prune-empty-dirs", "--include", "*/", "--include", lib.PLAN_FILE, "--exclude", "*", "plans", dst])
        return a == 0 and b == 0

    return M.submit(J.Job("sync", "Copy scripts and plans to the robot computer", "util", run, {}))


# ------------------------------------------------------------------ camera (Sebas's webcam teleop)
def free_port():
    s = socket.socket()
    s.bind(("127.0.0.1", 0))
    p = s.getsockname()[1]
    s.close()
    return p


def start_camera(req):
    if M.active(kind="camera"):
        raise ValueError("the camera is running already")
    if not (ENV.get("cv2") and ENV.get("mediapipe")):
        raise ValueError("the camera needs mediapipe and opencv on this computer: pip install -r requirements-camera.txt")
    if not os.path.exists(os.path.join(REPO, "assets/mediapipe/hand_landmarker.task")):
        raise ValueError("the hand model is missing: press 'Download the hand model' first")
    port = free_port()
    stamp = time.strftime("%Y%m%d_%H%M%S")
    record = f"out/teleop/{stamp}" if req.get("record", True) else None
    argv = [PY, "-u", "scripts/camera_track.py", "--port", str(port)]
    src = (req.get("source") or "").strip()
    if src:
        argv += ["--source", lib.safe_path(src) if not os.path.isabs(src) else src]
    else:
        argv += ["--camera", str(int(req.get("camera", S["camera"])))]
    if record:
        argv += ["--record", record]
    argv += ["--calibration", "out/camera_calibration.json"]     # the last guided calibration, reused at the next start
    if req.get("no_thumb"): argv += ["--no-thumb"]
    if req.get("flip_spread"): argv += ["--flip-spread"]
    meta = dict(port=port, record=record, source=src or f"camera {int(req.get('camera', S['camera']))}")

    def run(job):
        CAM.update(job=job, port=port, target=None, record=record)

        def on_line(line):
            if line.startswith("T "):
                CAM["target"] = line
                sink = CAM["sink"]
                if sink is not None:
                    try:
                        sink.write(line + "\n")
                        sink.flush()
                    except (OSError, ValueError):
                        CAM["sink"] = None
                del job.log[-1]          # the stream of targets does not belong in the log
            elif "calibrated" in line:
                meta["calibrated"] = True
        job.phase = "Tracking"
        try:
            rc = job.exec(argv, on_line, stdin=True)
        finally:
            release_hand()
            CAM.update(job=None, port=None, target=None)
        return rc == 0 or job.stop_requested

    job = J.Job("camera", "Camera tracking", "util", run, meta)
    orig_stop = job.stop

    def stop():           # ask it to finish (it saves the session), then the usual Ctrl-C
        try:
            camera_cmd(dict(quit=True))
        except Exception:
            pass
        return orig_stop()
    job.stop = stop
    return M.submit(job)


def camera_cmd(cmd):
    job = CAM["job"]
    if not job or not job.proc or job.proc.poll() is not None:
        raise ValueError("the camera is not running")
    allowed = {k: cmd[k] for k in ("pause", "calibrate", "thumb", "flip_spread", "alpha", "quit", "driving", "capture", "fit") if k in cmd}
    if allowed.get("capture") not in (None, "open", "fist", "spread", "thumb"):
        raise ValueError("unknown calibration pose")
    job.proc.stdin.write(json.dumps(allowed) + "\n")
    job.proc.stdin.flush()


def release_hand():
    """Close the follower's input: it switches the hand off and confirms."""
    sink, CAM["sink"] = CAM["sink"], None
    if sink is not None:
        try:
            sink.close()
        except OSError:
            pass


def start_follow(req):
    if not CAM["job"]:
        raise ValueError("start the camera first")
    target = req.get("target") or S["target"]
    need_real_ok(req, target)
    effort = min(max(float(req.get("effort") or 0.5), 0.1), MAX_EFFORT)
    vmax = min(max(float(req.get("vmax") or 3.0), 0.2), 6.0)
    args = ["scripts/hand_follow.py", "--effort", f"{effort:g}", "--vmax", f"{vmax:g}"]
    if req.get("side") in ("left", "right"): args += ["--side", req["side"]]
    if target == "fake": args += ["--dry-run"]
    if CAM.get("record") and target != "board": args += ["--log", f"{CAM['record']}/hand.npz"]
    meta = dict(target=target, real=target != "fake", effort=effort, vmax=vmax)

    def run(job):
        M.set_hand("on", "in use")
        job.phase = "Connecting"
        got = dict(off=False)

        def on_line(line):
            note_hand_line(line)
            note_link_line(target, line)
            if line.startswith("A "):
                CAM["actual"] = line
                del job.log[-1]
            elif line.startswith("following:"):
                job.phase = "The hand follows the camera"
                CAM["sink"] = job.proc.stdin
                try:
                    camera_cmd(dict(driving=True))
                except Exception:
                    pass
            elif "switched off: confirmed" in line:
                got["off"] = True
        try:
            job.exec(hand_argv(target, args), on_line, stdin=True)
        finally:
            CAM["sink"] = None
            CAM["actual"] = None
            try:
                camera_cmd(dict(driving=False))
            except Exception:
                pass
        if not got["off"]:
            M.set_hand("not_confirmed", "switch-off not seen")
            job.say("[studio] the switch-off was not confirmed: press 'Switch the hand off'")
        return got["off"]

    job = J.Job("follow", "Camera drives the hand", "hand", run, meta)
    orig_stop = job.stop

    def stop():           # first the gentle way (input closed), then the Ctrl-C every job gets
        release_hand()
        try:
            if job.proc and job.proc.stdin:
                job.proc.stdin.close()
        except OSError:
            pass
        return orig_stop()
    job.stop = stop
    return M.submit(job)


def camera_state():
    job = CAM["job"]
    out = dict(running=bool(job), driving=bool(M.active(kind="follow")), record=CAM.get("record"))
    if job and CAM["port"]:
        try:
            with urllib.request.urlopen(f"http://127.0.0.1:{CAM['port']}/state", timeout=0.5) as r:
                out.update(json.load(r))
        except Exception:
            out["starting"] = True
    a = CAM["actual"]
    if a:
        try:
            out["actual"] = [float(v) for v in a.split()[2:22]]
        except ValueError:
            pass
    return out


def start_model_download():
    def run(job):
        job.phase = "Downloading the hand model (8 MB)"
        ok = job.exec([PY, "-u", "scripts/camera_track.py", "--fetch-model"]) == 0
        probe_env()
        return ok
    return M.submit(J.Job("model", "Download the hand model", "util", run, {}))


# ------------------------------------------------------------------ HTTP
TYPES = {".html": "text/html; charset=utf-8", ".js": "text/javascript; charset=utf-8", ".css": "text/css; charset=utf-8", ".svg": "image/svg+xml",
         ".png": "image/png", ".mp4": "video/mp4", ".gif": "image/gif", ".ico": "image/x-icon", ".json": "application/json"}


class Handler(BaseHTTPRequestHandler):
    protocol_version = "HTTP/1.1"
    server_version = "WujiQuartetStudio"

    def log_message(self, *a):
        pass

    # ---- helpers
    def send(self, code, body, ctype="application/json", extra=None):
        if not isinstance(body, bytes):
            body = json.dumps(body).encode()
        self.send_response(code)
        self.send_header("Content-Type", ctype)
        self.send_header("Content-Length", str(len(body)))
        self.send_header("Cache-Control", "no-store")
        self.send_header("X-Content-Type-Options", "nosniff")
        for k, v in (extra or {}).items():
            self.send_header(k, v)
        self.end_headers()
        if self.command != "HEAD":
            self.wfile.write(body)

    def fail(self, code, text):
        self.send(code, dict(error=text))

    def allowed(self, url):
        """Who may talk to the studio.
        A browser on this computer: no token, but the request must name this computer (so a foreign web page cannot reach
        the hand through the browser by pointing its own name at 127.0.0.1).
        Any other computer: the token, as a cookie that the printed link sets.
        Always: a request that says which page sent it must come from the studio's own page."""
        host_hdr = self.headers.get("Host") or ""
        host = host_hdr.rsplit(":", 1)[0].strip("[]")
        origin = self.headers.get("Origin")
        if origin and urlparse(origin).netloc != host_hdr:
            self.fail(403, "cross-site request refused")
            return False
        if self.client_address[0] in ("127.0.0.1", "::1") or not TOKEN:
            if host not in self.server.hosts:
                self.fail(403, "unexpected Host header")
                return False
            return True
        q = parse_qs(url.query)
        if q.get("token", [""])[0] == TOKEN:
            self.send(302, b"", "text/plain", {"Location": "/", "Set-Cookie": f"wq={TOKEN}; Path=/; HttpOnly; SameSite=Strict"})
            return False
        if f"wq={TOKEN}" not in (self.headers.get("Cookie") or ""):
            self.send(403, b"This studio is open to other computers: open the link with the token that its terminal printed.", "text/plain")
            return False
        return True

    def body(self):
        n = int(self.headers.get("Content-Length") or 0)
        if n > 4_000_000:
            raise ValueError("request too large")
        return self.rfile.read(n) if n else b""

    def file(self, path, ctype=None):
        try:
            size = os.path.getsize(path)
            fh = open(path, "rb")
        except OSError:
            return self.fail(404, "not found")
        ctype = ctype or TYPES.get(os.path.splitext(path)[1].lower(), "application/octet-stream")
        rng = self.headers.get("Range")
        start, end = 0, size - 1
        m = re.match(r"bytes=(\d*)-(\d*)$", rng or "")
        with fh:
            if m and (m.group(1) or m.group(2)):
                if m.group(1):
                    start = int(m.group(1)); end = min(int(m.group(2)), size - 1) if m.group(2) else size - 1
                else:
                    start = max(0, size - int(m.group(2)))
                if start > end or start >= size:
                    return self.send(416, b"", ctype, {"Content-Range": f"bytes */{size}"})
                self.send_response(206)
                self.send_header("Content-Range", f"bytes {start}-{end}/{size}")
            else:
                self.send_response(200)
            self.send_header("Content-Type", ctype)
            self.send_header("Content-Length", str(end - start + 1))
            self.send_header("Accept-Ranges", "bytes")
            self.send_header("Cache-Control", "no-cache")
            self.end_headers()
            if self.command == "HEAD":
                return
            fh.seek(start)
            left = end - start + 1
            try:
                while left > 0:
                    b = fh.read(min(1 << 16, left))
                    if not b:
                        break
                    self.wfile.write(b)
                    left -= len(b)
            except (BrokenPipeError, ConnectionResetError):
                pass

    # ---- GET
    def do_HEAD(self):
        self.do_GET()

    def do_GET(self):
        url = urlparse(self.path)
        if not self.allowed(url):
            return
        p = unquote(url.path)
        q = parse_qs(url.query)
        try:
            if p == "/":
                return self.file(os.path.join(STATIC, "index.html"))
            if p.startswith("/static/"):
                return self.file(lib_static(p[len("/static/"):]))
            if p.startswith("/media/"):
                rel = p[len("/media/"):]
                if not rel.startswith(("docs/", "plans/", "out/")):
                    return self.fail(403, "not served")
                return self.file(lib.safe_path(rel, (".mp4", ".gif", ".png")))
            if p == "/api/state":
                if SEEN[0] == 0.0 or time.time() - SEEN[0] > 30:
                    LINK_KICK.set()                      # a page opened: check the hand right away
                SEEN[0] = time.time()
                return self.send(200, dict(time=time.time(), env=ENV, settings=S, targets=targets(), jobs=M.snapshot(), hand=M.hand, link=LINK,
                                           queue=len(M.queue), camera=dict(running=bool(CAM["job"]), driving=bool(M.active(kind="follow")))))
            if p == "/api/library":
                lib.plans(fresh=True)                   # after a run ends the page asks here: never an old list
                return self.send(200, dict(pieces=lib.pieces(), plans=lib.plans(), duets=lib.duets(), recordings=lib.recordings(), detail=planner.DETAIL,
                                           ref_plan=planner.REF_PLAN))
            if p == "/api/piece":
                pc = lib.piece(q["id"][0])
                if pc and pc.get("group") != "dataset":
                    pc["fits"] = planner.fits_fixed(pc["id"], "right") or planner.fits_fixed(pc["id"], "left")
                return self.send(200, pc) if pc else self.fail(404, "no such piece")
            if p == "/api/startpose":
                return self.send(200, dict(hands=[start_pose_of(i) for i in q.get("plan", [])[:2]]))
            if p == "/api/positions":
                return self.send(200, planner.positions(q["piece"][0], q.get("side", ["right"])[0]))
            if p == "/api/view":
                return self.file(plan_view(q.get("plan", [])), "application/json")
            if p == "/api/job":
                job = M.get(q["id"][0])
                start = int(q.get("from", ["0"])[0])
                if job:
                    lines, nxt = job.lines(start)
                    return self.send(200, dict(job=job.info(), lines=lines, next=nxt))
                old = M.old_log(q["id"][0])
                if old is None:
                    return self.fail(404, "no such job")
                return self.send(200, dict(job=next((h for h in M.history if h["id"] == q["id"][0]), None), lines=old[start:], next=len(old)))
            if p == "/api/camera/state":
                return self.send(200, camera_state())
            if p == "/api/camera/stream":
                return self.camera_stream()
            return self.fail(404, "not found")
        except (BrokenPipeError, ConnectionResetError):
            pass
        except (ValueError, KeyError, FileNotFoundError) as ex:
            self.fail(400, str(ex))
        except Exception as ex:
            self.fail(500, f"{type(ex).__name__}: {ex}")

    def camera_stream(self):
        if not CAM["port"]:
            return self.fail(404, "the camera is not running")
        try:
            up = urllib.request.urlopen(f"http://127.0.0.1:{CAM['port']}/stream", timeout=5)
        except Exception:
            return self.fail(503, "the camera is starting")
        self.send_response(200)
        self.send_header("Content-Type", up.headers.get("Content-Type", "multipart/x-mixed-replace; boundary=frame"))
        self.send_header("Cache-Control", "no-store")
        self.send_header("Connection", "close")
        self.end_headers()
        self.close_connection = True
        try:
            while True:
                b = up.read1(1 << 15)
                if not b:
                    break
                self.wfile.write(b)
        except Exception:
            pass
        finally:
            up.close()

    # ---- POST
    def do_POST(self):
        url = urlparse(self.path)
        if not self.allowed(url):
            return
        if self.headers.get("X-WQ") != "1":            # only this page's own script sets it: a form on another site cannot
            self.body()
            return self.fail(403, "missing X-WQ header")
        p = url.path
        try:
            raw = self.body()
            if p == "/api/import":
                name = parse_qs(url.query).get("name", ["piece.mid"])[0]
                return self.send(200, dict(piece=lib.import_midi(name, raw)))
            req = json.loads(raw or b"{}")
            if p == "/api/excerpt":
                args = (req["piece"], req.get("start", 0), req.get("length", 20), req.get("mode", "onehand"), req.get("tempo", 1.0), req.get("at_once", 1))
                part = req.get("part") or None
                if part is not None and not re.fullmatch(r"\d{1,3}:\d{1,2}", str(part)):
                    raise ValueError("unknown part")
                if req.get("preview"):                  # what the excerpt would be, without saving it: for Listen and the numbers
                    notes, info = lib.cut(*args, part=part, hand=req.get("hand") or None)
                    return self.send(200, dict(notes=notes, info=info))
                return self.send(200, dict(piece=lib.excerpt(*args, part=part, hand=req.get("hand") or None)))
            if p == "/api/estimate":
                out = planner.estimate(req)
                try:
                    busy = [os.path.basename(j.meta.get("plan", "")) for j in M.active(kind="retarget")]
                    argv, out_rel, used = planner.build_command(dict(req, _busy=busy), "python")
                    out.update(command=" ".join(J._show(a) for a in argv), name=used["name"], ok=True)
                except ValueError as ex:
                    out.update(ok=False, why=str(ex), name=planner.suggest_name(req) if req.get("piece") else "")
                return self.send(200, out)
            if p == "/api/retarget": return self.job(start_retarget(req))
            if p == "/api/render": return self.job(start_render(req))
            if p == "/api/check": return self.job(start_check(req))
            if p == "/api/viewer": return self.job(start_viewer(req))
            if p == "/api/play": return self.job(start_play(req))
            if p == "/api/hand/off": return self.job(start_util(req, "off"))
            if p == "/api/hand/info": return self.job(start_util(req, "info"))
            if p == "/api/hand/adapter": return self.job(start_adapter(req))
            if p == "/api/hand/hello": return self.job(start_hello(req))
            if p == "/api/hand/link":
                if (req.get("target") or S["target"]) == "board":
                    LINK["board"]["checking"] = True
                    LINK_KICK.set()
                return self.send(200, dict(ok=True))
            if p == "/api/sync": return self.job(start_sync(req))
            if p == "/api/stop":
                if req.get("all"):
                    M.stop_all("hand")
                    return self.send(200, dict(ok=True))
                return self.send(200, dict(ok=M.stop(req["id"])))
            if p == "/api/share": return self.send(200, dict(plan=lib.share_plan(req["plan"])))
            if p == "/api/settings":
                save_settings(req)
                return self.send(200, dict(settings=S, targets=targets()))
            if p == "/api/camera/start": return self.job(start_camera(req))
            if p == "/api/camera/cmd":
                camera_cmd(req)
                return self.send(200, dict(ok=True))
            if p == "/api/camera/drive": return self.job(start_follow(req))
            if p == "/api/camera/release":
                release_hand()
                return self.send(200, dict(ok=True))
            if p == "/api/camera/model": return self.job(start_model_download())
            return self.fail(404, "not found")
        except J.Busy as ex:
            self.fail(409, str(ex))
        except (ValueError, KeyError, FileNotFoundError) as ex:
            self.fail(400, str(ex) if not isinstance(ex, KeyError) else f"missing {ex}")
        except Exception as ex:
            self.fail(500, f"{type(ex).__name__}: {ex}")

    def job(self, job):
        self.send(200, dict(job=job.info()))


def lib_static(rel):
    full = os.path.realpath(os.path.join(STATIC, rel))
    if not full.startswith(STATIC + os.sep):
        raise ValueError("path leaves the static folder")
    return full


class Server(ThreadingHTTPServer):
    daemon_threads = True
    allow_reuse_address = True


def tailscale_address():
    """This computer's address in the tailnet, and its name there (None if Tailscale is not running)."""
    try:
        ip = subprocess.run(["tailscale", "ip", "-4"], capture_output=True, text=True, timeout=5).stdout.split()[0]
    except Exception:
        return None, None
    name = None
    try:
        name = json.loads(subprocess.run(["tailscale", "status", "--json"], capture_output=True, text=True, timeout=5).stdout)["Self"]["DNSName"].rstrip(".")
    except Exception:
        pass
    return ip, name


def load_token(new=False):
    """The token other computers need. Kept in out/gui/token so a restart keeps the links (and browser cookies) working;
    --new-token makes a new one, which ends every link given out before."""
    path = os.path.join(REPO, "out", "gui", "token")
    if not new:
        try:
            with open(path) as fh:
                t = fh.read().strip()
            if re.fullmatch(r"[A-Za-z0-9_-]{12,64}", t):
                return t
        except OSError:
            pass
    t = secrets.token_urlsafe(12)
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(os.open(path, os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600), "w") as fh:
        fh.write(t + "\n")
    return t


def main():
    global TOKEN
    ap = argparse.ArgumentParser(description="Wuji Quartet Studio")
    ap.add_argument("--port", type=int, default=8770)
    ap.add_argument("--tailscale", action="store_true", help="also reachable from your other Tailscale devices (and only from those); they need the token link that is printed")
    ap.add_argument("--host", default="127.0.0.1", help="address to listen on (default: this computer only). Anything else asks other computers for a token")
    ap.add_argument("--no-token", action="store_true", help="with --host: no token (only behind a port that is itself private, as ./wq gui on a Mac)")
    ap.add_argument("--new-token", action="store_true", help="a new token: the links given out before stop working (the token is otherwise kept across restarts)")
    ap.add_argument("--no-browser", action="store_true")
    A = ap.parse_args()
    probe_env()
    threading.Thread(target=link_loop, daemon=True).start()
    local = A.host in ("127.0.0.1", "localhost", "::1")
    if (A.tailscale or not local) and not A.no_token:
        TOKEN = load_token(A.new_token)
    srv = Server((A.host, A.port), Handler)
    names = {"127.0.0.1", "localhost"}
    if not local:
        names |= {A.host, socket.gethostname()}
        try:
            names |= set(socket.gethostbyname_ex(socket.gethostname())[2])
        except OSError:
            pass
        for extra in (os.environ.get("WQ_HOSTS") or "").split(","):
            if extra.strip():
                names.add(extra.strip())
    srv.hosts = names
    url = f"http://127.0.0.1:{A.port}/"
    print(f"Wuji Quartet Studio: {url}", flush=True)
    tok = f"?token={TOKEN}" if TOKEN else ""
    if A.tailscale:
        ip, name = tailscale_address()
        if not ip:
            sys.exit("--tailscale: Tailscale is not running on this computer (`tailscale ip -4` gave no address)")
        if local:                  # a second listener on the tailnet address only: not reachable from the Wi-Fi this computer is on
            ts = Server((ip, A.port), Handler)
            ts.hosts = names
            threading.Thread(target=ts.serve_forever, daemon=True).start()
        print(f"  from your other Tailscale devices: http://{ip}:{A.port}/{tok}" + (f"\n                                 or: http://{name}:{A.port}/{tok}" if name else ""), flush=True)
    elif not local:
        print(f"  from another computer: http://<this computer's address>:{A.port}/{tok}", flush=True)
    print(f"  python {ENV['python']} · " + " · ".join(f"{k} {'ok' if ENV[k] else 'missing'}" for k in ("mujoco", "sdk", "mediapipe", "ffmpeg")), flush=True)
    if not (A.no_browser or ENV["docker"]):
        threading.Timer(0.6, lambda: webbrowser.open(url)).start()
    # Started in the background (nohup, a launcher, `&`) a process inherits "ignore Ctrl-C", and so would every script the
    # studio starts: Stop would then do nothing. Taking the signal here gives the scripts their normal Ctrl-C back.
    signal.signal(signal.SIGINT, signal.default_int_handler)

    def on_term(*_):          # a kill or a closed terminal ends the studio the same orderly way as Ctrl-C
        raise KeyboardInterrupt
    for sig in (signal.SIGTERM, getattr(signal, "SIGHUP", signal.SIGTERM)):
        signal.signal(sig, on_term)
    try:
        srv.serve_forever()
    except KeyboardInterrupt:
        print("\nclosing: stopping jobs ...", flush=True)
    finally:
        release_hand()
        for j in M.active():
            j.stop()
        end = time.time() + 40
        while M.active("hand") and time.time() < end:      # a hand job gets the time to switch off and confirm
            time.sleep(0.2)
        if M.active("hand"):
            print("!!! a hand job did not end: run python scripts/hand_off.py", flush=True)


if __name__ == "__main__":
    main()
