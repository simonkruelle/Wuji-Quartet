"""Background work for the studio: every action that takes time is a Job with a log.

Three groups:
  compute  optimiser and video runs. One at a time, the rest wait in a queue.
  hand     anything that moves a hand (real or fake). Only one may run; a second request is refused.
  util     short read-only checks and the camera tracker.

Stopping a job sends ONE Ctrl-C to its process group, exactly as a person at the terminal would: the hand scripts react
to it by switching the hand off and confirming that. A hand job is never killed harder than that from here.
"""
import json
import os
import signal
import subprocess
import threading
import time
import uuid

REPO = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
STATE_DIR = os.path.join(REPO, "out", "gui")
MAX_LOG = 6000


class Busy(Exception):
    pass


def _signal_group(p, sig):
    """Send a signal to a process and its children (the process alone where groups do not exist)."""
    try:
        if hasattr(os, "killpg"):
            os.killpg(p.pid, sig)
        else:
            p.send_signal(sig)
    except (OSError, ValueError):
        pass


class Job:
    def __init__(self, kind, title, group, run, meta=None):
        self.id = uuid.uuid4().hex[:8]
        self.kind, self.title, self.group, self._run = kind, title, group, run
        self.state = "queued"
        self.created = time.time()
        self.started = self.ended = None
        self.log, self.log_base = [], 0
        self.progress = None          # 0..1, or None when unknown
        self.phase = ""
        self.eta = None               # seconds left, or None
        self.meta = meta or {}
        self.proc = None
        self.procs = []               # further processes of this job (camera follower ...)
        self.stop_requested = False
        self.ctrl_c_on_stdin = False  # ssh -tt: Ctrl-C travels as a character
        self.error = None
        self.lock = threading.Lock()

    # ---- log
    def say(self, line):
        with self.lock:
            self.log.append(line)
            if len(self.log) > MAX_LOG:
                drop = len(self.log) - MAX_LOG
                del self.log[:drop]
                self.log_base += drop

    def lines(self, start=0):
        with self.lock:
            start = max(start, self.log_base)
            return self.log[start - self.log_base:], self.log_base + len(self.log)

    # ---- processes
    def exec(self, argv, on_line=None, env=None, stdin=False, ctrl_c_on_stdin=False, quiet=False):
        """Run one command of this job to its end. Returns its exit code (None if it could not start)."""
        if self.stop_requested:
            return None
        if not quiet:
            self.say("$ " + " ".join(_show(a) for a in argv))
        e = dict(os.environ, PYTHONUNBUFFERED="1", WUJI_TELEMETRY_DISABLE="1")
        e.update(env or {})
        try:
            p = subprocess.Popen(argv, cwd=REPO, stdout=subprocess.PIPE, stderr=subprocess.STDOUT,
                                 stdin=subprocess.PIPE if (stdin or ctrl_c_on_stdin) else subprocess.DEVNULL,
                                 start_new_session=True, env=e, text=True, errors="replace", bufsize=1)
        except OSError as ex:
            self.say(f"could not start: {ex}")
            return None
        self.proc, self.ctrl_c_on_stdin = p, ctrl_c_on_stdin
        if self.stop_requested:       # Stop arrived while the process was starting
            self._interrupt(p)
        for raw in p.stdout:
            line = raw.rstrip("\r\n")
            if "\r" in line:
                line = line.split("\r")[-1]
            self.say(line)
            if on_line:
                try:
                    on_line(line)
                except Exception as ex:      # a parser must never end the job
                    self.say(f"[studio] could not read that line: {ex}")
        p.wait()
        return p.returncode

    def _interrupt(self, p):
        try:
            if self.ctrl_c_on_stdin and p.stdin:
                p.stdin.write("\x03")
                p.stdin.flush()
            else:
                _signal_group(p, signal.SIGINT)
        except (OSError, ValueError):
            pass

    def stop(self):
        """One Ctrl-C. Compute jobs that ignore it are terminated after a few seconds; hand jobs are left to finish switching off."""
        first = not self.stop_requested
        self.stop_requested = True
        ps = [p for p in [self.proc] + self.procs if p is not None and p.poll() is None]
        if first:
            self.say("[studio] stop requested")
            for p in ps:
                if p is self.proc:
                    self._interrupt(p)
                else:
                    _signal_group(p, signal.SIGINT)
            if self.group != "hand":
                def harder():
                    for p in ps:
                        if p.poll() is None:
                            _signal_group(p, signal.SIGTERM)
                threading.Timer(5.0, harder).start()
        return first

    def wait(self, seconds):
        """Sleep that ends early when the job is stopped. True if the full time passed."""
        end = time.time() + seconds
        while time.time() < end:
            if self.stop_requested:
                return False
            time.sleep(0.05)
        return True

    def info(self):
        return dict(id=self.id, kind=self.kind, title=self.title, group=self.group, state=self.state, created=self.created,
                    started=self.started, ended=self.ended, progress=self.progress, phase=self.phase, eta=self.eta, meta=self.meta,
                    error=self.error, lines=self.log_base + len(self.log), stopping=self.stop_requested and self.state == "running")


def _show(a):
    a = str(a)
    return a if a and all(c.isalnum() or c in "@%+=:,./_-~" for c in a) else "'" + a.replace("'", "'\\''") + "'"


class Manager:
    def __init__(self):
        self.jobs = {}
        self.order = []
        self.lock = threading.Lock()
        self.queue = []
        self.hand = dict(state="unknown", text="not used yet", time=None)     # last word on whether the hand is off
        self.history = self._load_history()
        threading.Thread(target=self._compute_loop, daemon=True).start()

    # ---- submit
    def submit(self, job):
        with self.lock:
            if job.group == "hand" and any(j.group == "hand" and j.state in ("queued", "running") for j in self.jobs.values()):
                raise Busy("a hand job is running: stop it first")
            self.jobs[job.id] = job
            self.order.append(job.id)
            if job.group == "compute":
                self.queue.append(job)
            else:
                threading.Thread(target=self._run, args=(job,), daemon=True).start()
        return job

    def _compute_loop(self):
        while True:
            job = None
            with self.lock:
                if self.queue:
                    job = self.queue.pop(0)
            if job is None:
                time.sleep(0.2)
            elif job.stop_requested:
                job.state, job.ended = "stopped", time.time()
                self._remember(job)
            else:
                self._run(job)

    def _run(self, job):
        job.state, job.started = "running", time.time()
        try:
            ok = job._run(job)
            job.state = "stopped" if job.stop_requested else ("done" if ok or ok is None else "failed")
        except Exception as ex:
            job.error = str(ex)
            job.say(f"[studio] {type(ex).__name__}: {ex}")
            job.state = "stopped" if job.stop_requested else "failed"
        job.ended = time.time()
        if job.state == "done":
            job.phase = "Done"
            if job.progress is not None:
                job.progress = 1.0
        job.eta = None
        self._remember(job)

    # ---- access
    def get(self, job_id):
        return self.jobs.get(job_id)

    def active(self, group=None, kind=None):
        return [j for j in self.jobs.values() if j.state in ("queued", "running") and (group is None or j.group == group) and (kind is None or j.kind == kind)]

    def snapshot(self, limit=40):
        live = [self.jobs[i].info() for i in reversed(self.order)]
        old = [h for h in self.history if h["id"] not in self.jobs]
        return (live + old)[:limit]

    def stop(self, job_id):
        job = self.jobs.get(job_id)
        if not job or job.state not in ("queued", "running"):
            return False
        job.stop()
        return True

    def stop_all(self, group=None):
        for j in self.active(group):
            j.stop()

    def set_hand(self, state, text):
        self.hand = dict(state=state, text=text, time=time.time())

    # ---- history on disk (so a restart of the studio keeps the list and the logs)
    def _load_history(self):
        try:
            with open(os.path.join(STATE_DIR, "jobs.json")) as fh:
                rows = json.load(fh)
            for r in rows:
                if r.get("state") in ("queued", "running"):
                    r["state"] = "lost"       # the studio was closed while this ran
            return rows
        except Exception:
            return []

    def _remember(self, job):
        try:
            os.makedirs(os.path.join(STATE_DIR, "logs"), exist_ok=True)
            with open(os.path.join(STATE_DIR, "logs", job.id + ".log"), "w") as fh:
                fh.write("\n".join(job.log) + "\n")
            with self.lock:
                rows = [self.jobs[i].info() for i in reversed(self.order) if self.jobs[i].state not in ("queued", "running")]
                rows += [h for h in self.history if h["id"] not in self.jobs]
                with open(os.path.join(STATE_DIR, "jobs.json"), "w") as fh:
                    json.dump(rows[:60], fh)
        except Exception:
            pass

    def old_log(self, job_id):
        if not all(c in "0123456789abcdef" for c in job_id):
            return None
        try:
            with open(os.path.join(STATE_DIR, "logs", job_id + ".log")) as fh:
                return fh.read().splitlines()
        except OSError:
            return None
