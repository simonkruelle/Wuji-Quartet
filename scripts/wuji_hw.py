"""Wuji Hand 2 hardware helpers (mirrors wuji-sdk examples 2.publish.py / 8.position_mode.py, SDK v2026.11.9)
plus a FakeHand with first-order joint lag so every script runs with --dry-run and no hardware.

Joint order = SDK flat-20 = MJCF actuator order (thumb 0-3, index 4-7, middle 8-11, ring 12-15, pinky 16-19)."""
import math, os, threading, time
import numpy as np

os.environ.setdefault("WUJI_TELEMETRY_DISABLE", "1")
JOINTS = 20
# joint limits from docs.wuji.tech control-guide joint table (= MJCF ranges), rad
LO = np.array([-1.187, -1.484, -1.047, -1.047] + [-1.047, -0.698, -1.047, -1.047] * 4)
HI = np.array([1.291, 0.698, 1.57, 1.57] + [1.57, 0.698, 2.094, 1.57] * 4)


# ------------------------------------------------------------------ fake device
class _Res:
    def __init__(self, v): self.v = v
    def get(self): return self.v
    def set(self, v): self.v = v; return v


class _Entry:
    def __init__(self, nid, p, v, e): self.nid, self.position, self.velocity, self.effort = nid, p, v, e


class _Frame:
    def __init__(self, joints): self.joints = joints


class _Status:
    ext_state = 2


class _Diag:
    def __init__(self, nid): self.nid = nid; self.status_word = _Status()


class FakeHand:
    """First-order lag (tau) toward the last position command; joint_states at 1 kHz on demand."""
    serial_number = "FAKE-0001"
    def __init__(self, tau=0.03, q0=None):
        self.tau = tau; self.q = np.zeros(JOINTS) if q0 is None else np.array(q0, float); self.cmd = self.q.copy(); self.t = time.monotonic()
        self.enabled = False; self.lock = threading.Lock(); self.mode = "Mit"
        self._eff = _Res(1.5); self._mit = _Res((3.0, 0.05)); self._cut = _Res(40.0); self._mode = _Res("Mit")
    def _advance(self):
        now = time.monotonic(); dt = now - self.t; self.t = now
        if self.enabled: self.q += (self.cmd - self.q) * (1 - math.exp(-dt / self.tau))
    @staticmethod
    def nid_to_joint_index(nid): b, n = divmod(nid, 5); return b * 4 + n - 1
    def online_joints_count(self): return _Res(JOINTS)
    def effort_limit(self): return self._eff
    def mit_params(self): return self._mit
    def control_mode(self): return self._mode
    def position_command_low_pass_cutoff_frequency(self): return self._cut
    def enable(self): self.enabled = True
    def disable(self): self.enabled = False
    def emergency_stop(self): self.enabled = False
    def joint_diagnostics(self):
        hand = self
        class S:
            def subscribe(self_):
                class Sub:
                    sent = False
                    def recv(s):
                        if s.sent: return None
                        s.sent = True; return _Frame([_Diag(b * 5 + n) for b in range(5) for n in range(1, 5)])
                    def close(s): pass
                return Sub()
        return S()
    def joint_states(self):
        hand = self
        class S:
            def subscribe(self_):
                class Sub:
                    last = 0.0
                    def recv(s):
                        if time.monotonic() - s.last < 0.001: return None
                        s.last = time.monotonic()
                        with hand.lock:
                            hand._advance(); q = hand.q.copy()
                        return _Frame([_Entry(b * 5 + n, float(q[b * 4 + n - 1]), 0.0, 0.0) for b in range(5) for n in range(1, 5)])
                    def close(s): pass
                return Sub()
        return S()
    def joint_command(self):
        hand = self
        class C:
            def publish(self_):
                class Pub:
                    def send(s, cmds):
                        with hand.lock:
                            hand._advance(); hand.cmd = np.array([c.position for c in cmds], float)
                    def close(s): pass
                return Pub()
        return C()


class _FakeCmd:
    def __init__(self, position, velocity=0.0, effort=0.0): self.position, self.velocity, self.effort = position, velocity, effort


# ------------------------------------------------------------------ connection
class Session:
    """with Session(mode="mit"|"position", ...) as s: s.ramp_to(q); s.stream(cmd); ... Always disables on exit."""
    def __init__(self, mode="mit", kp=3.0, kd=0.05, effort=0.8, effort_scale=0.8, cutoff=40.0, dry_run=False, sn=None, log_states=True):
        self.mode, self.kp, self.kd, self.effort, self.effort_scale, self.cutoff = mode, kp, kd, effort, effort_scale, cutoff
        self.dry, self.sn, self.log_states = dry_run, sn, log_states
        self.states = []; self._stop = threading.Event(); self.restore = []

    def __enter__(self):
        if self.dry:
            self.sdk = None; self.JC = _FakeCmd; self.hand = FakeHand(); self.manager = None; self.nid2i = FakeHand.nid_to_joint_index
            print("[dry-run] fake hand, first-order lag 30 ms")
        else:
            import wuji_sdk
            self.sdk = wuji_sdk; self.JC = wuji_sdk.JointCommand; self.manager = wuji_sdk.SdkManager.instance()
            hands = [d for d in self.manager.scan() if d.device_type == wuji_sdk.DeviceType.WujiHand2]
            if self.sn: hands = [d for d in hands if d.sn == self.sn]
            if not hands: raise SystemExit("no Wuji Hand 2 found (Ethernet link? same subnet? PSU on?)")
            for d in hands: print(f"  found SN={d.sn} ip={d.ip} fw={d.firmware_version}")
            self.hand = self.manager.connect(sn=hands[0].sn, device_name="piano")
            self.nid2i = wuji_sdk.WujiHand2.nid_to_joint_index
        online = int(self.hand.online_joints_count().get())
        if online != JOINTS: self.close(); raise SystemExit(f"{online}/20 joints online, refusing to move")
        self._configure(); self.hand.enable(); self._wait_enabled()
        self.pub = self.hand.joint_command().publish()
        self._sub = self.hand.joint_states().subscribe()
        self._reader = threading.Thread(target=self._read_loop, daemon=True); self._reader.start()
        t_ = time.monotonic()
        while self.latest() is None and time.monotonic() - t_ < 2.0: time.sleep(0.01)
        if self.latest() is None: self.close(); raise SystemExit("no joint_states within 2 s")
        return self

    def _configure(self):
        h = self.hand
        if self.dry: return
        M = self.sdk.ControlMode
        h.disable()
        if self.mode == "position":
            h.control_mode().set(M.Position)
            lim = h.effort_limit().get(); cut = h.position_command_low_pass_cutoff_frequency()
            if any(v is None for v in lim): raise SystemExit("invalid effort limits read back")
            self.restore += [lambda: h.effort_limit().set(list(lim)), lambda c=cut.get(): cut.set(c)]
            h.effort_limit().set([v * self.effort_scale for v in lim]); cut.set(self.cutoff)
            print(f"Position mode: limits x{self.effort_scale} of {np.round(lim, 2).tolist()} N·m, cutoff {self.cutoff} Hz")
        else:
            h.control_mode().set(M.Mit)
            h.effort_limit().set(self.effort); h.mit_params().set((self.kp, self.kd))
            print(f"MIT mode: kp {self.kp} kd {self.kd}, effort limit {self.effort} A")

    def _wait_enabled(self, timeout=5.0):
        sub = self.hand.joint_diagnostics().subscribe(); deadline = time.monotonic() + timeout; seen = en = 0
        try:
            while time.monotonic() < deadline:
                time.sleep(0.2); frame = None
                while (x := sub.recv()) is not None: frame = x
                if frame is None: continue
                seen = len(frame.joints); en = sum(1 for e in frame.joints if e.status_word.ext_state == 2)
                if seen == JOINTS and en == JOINTS: return
        finally: sub.close()
        self.close(); raise SystemExit(f"enable timeout: {en}/{seen} joints enabled")

    def _read_loop(self):
        while not self._stop.is_set():
            fr = self._sub.recv()
            if fr is None: time.sleep(0.0003); continue
            if len(fr.joints) != JOINTS: continue
            q = np.full(JOINTS, np.nan); dq = np.full(JOINTS, np.nan); e = np.full(JOINTS, np.nan)
            for j in fr.joints:
                try: i = self.nid2i(j.nid)
                except Exception: continue
                q[i] = j.position if j.position is not None else np.nan
                dq[i] = j.velocity if j.velocity is not None else np.nan
                e[i] = j.effort if j.effort is not None else np.nan
            self.states.append((time.monotonic(), q, dq, e))
            if not self.log_states and len(self.states) > 2000: del self.states[:1000]

    def latest(self): return self.states[-1][1].copy() if self.states else None

    def send(self, q):
        q = np.clip(q, LO, HI); self.pub.send([self.JC(float(x), 0.0, 0.0) for x in q])

    def ramp_to(self, q_goal, duration=2.0, rate=1000):
        q0 = self.latest(); q0 = np.where(np.isnan(q0), q_goal, q0); n = max(1, int(duration * rate)); t0 = time.monotonic()
        for i in range(1, n + 1):
            a = 0.5 * (1 - math.cos(math.pi * i / n)); self.send(q0 + (q_goal - q0) * a)
            w = t0 + i / rate - time.monotonic()
            if w > 0: time.sleep(w)

    def stream(self, cmd, rate=1000, on_tick=None):
        """Wall-clock locked: sends the frame for the current time, skipping frames when late (keeps musical timing)."""
        t0 = time.monotonic(); n = len(cmd); late = 0; k = 0; sent = 0
        while True:
            i = int((time.monotonic() - t0) * rate)
            if i >= n: break
            if i > k: late += i - k
            self.send(cmd[i]); sent += 1; k = i + 1
            if on_tick: on_tick(i)
            w = t0 + k / rate - time.monotonic()
            if w > 0: time.sleep(w)
        return t0, dict(sent=sent, skipped=late)

    def close(self):
        self._stop.set()
        for f in (lambda: self.hand.disable(), lambda: self.pub.close(), lambda: self._sub.close()):
            try: f()
            except Exception: pass
        for f in self.restore:
            try: f()
            except Exception as e: print("restore failed:", e)
        if self.manager is not None:
            try: self.manager.disconnect_all()
            except Exception: pass

    def __exit__(self, *exc): self.close(); return False


# ------------------------------------------------------------------ MIDI in (raw Linux device, no dependencies)
class MidiIn:
    """Reads /dev/snd/midiC*D* in a thread. t is monotonic time. Use `ls /dev/snd/` or `amidi -l` to find the device."""
    def __init__(self, dev):
        from midi_io import RawMidiParser
        self.dev = dev; self.p = RawMidiParser(); self._stop = threading.Event()
        self.fd = os.open(dev, os.O_RDONLY | os.O_NONBLOCK); self.th = threading.Thread(target=self._loop, daemon=True); self.th.start()
    def _loop(self):
        while not self._stop.is_set():
            try: data = os.read(self.fd, 256)
            except BlockingIOError: time.sleep(0.0005); continue
            if data: self.p.feed(data, time.monotonic())
            else: time.sleep(0.0005)
    def note_ons(self, since=0.0): return [e for e in self.p.events if e["on"] and e["t"] >= since]
    def close(self): self._stop.set(); os.close(self.fd)


def find_midi_dev():
    try: return sorted("/dev/snd/" + f for f in os.listdir("/dev/snd") if f.startswith("midiC"))
    except FileNotFoundError: return []
