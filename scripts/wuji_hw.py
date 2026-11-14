"""Wuji Hand 2 hardware helpers (mirrors wuji-sdk examples 2.publish.py / 8.position_mode.py, SDK v2026.11.9)
plus a FakeHand with first-order joint lag so every script runs with --dry-run and no hardware.

Joint order = SDK flat-20 = MJCF actuator order (thumb 0-3, index 4-7, middle 8-11, ring 12-15, pinky 16-19)."""
import math, os, threading, time, signal
import numpy as np

os.environ.setdefault("WUJI_TELEMETRY_DISABLE", "1")
JOINTS = 20
# joint limits from docs.wuji.tech control-guide joint table (= MJCF ranges), rad
LO = np.array([-1.187, -1.484, -1.047, -1.047] + [-1.047, -0.698, -1.047, -1.047] * 4)
HI = np.array([1.291, 0.698, 1.57, 1.57] + [1.57, 0.698, 2.094, 1.57] * 4)
HI[1] = 0.42; HI[5] = 0.56     # stops measured on our hand, 14 Nov (thumb sideways stalls at 0.44, index sideways at 0.56-0.62): beyond them the motor only pushes
MAX_EFFORT_A = 1.5             # hard limit set by the team: never ask the hand for more current than this


def side_of(sn):
    """'left' / 'right' from the serial number: Wuji Hand 2 encodes the side in the 4th character (J = left, K = right; wuji-sdk Handedness)."""
    return {"J": "left", "K": "right"}.get(str(sn)[3:4].upper())


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
def _interrupt(*_): raise KeyboardInterrupt


def check_effort_limit(read_back, want):
    """The current limit is what keeps a stalled finger harmless: refuse to enable if the hand reports a higher one than we set."""
    try: got = np.array([np.nan if v is None else float(v) for v in np.atleast_1d(np.asarray(read_back, dtype=object))])
    except Exception: got = np.array([np.nan])
    if np.isnan(got).all(): print("  WARNING: could not read the current limit back; watch the first motion closely"); return
    print(f"  current limit read back: {np.nanmin(got):.2f} to {np.nanmax(got):.2f} A")
    if np.nanmax(got) > want + 0.05: raise SystemExit(f"hand reports a current limit of {np.nanmax(got):.2f} A, we asked for {want} A: refusing to enable")


class Session:
    """with Session(mode="mit"|"position", ...) as s: s.ramp_to(q); s.stream(cmd); ... Always disables on exit."""
    def __init__(self, mode="mit", kp=3.0, kd=0.05, effort=0.8, effort_scale=0.8, cutoff=40.0, dry_run=False, sn=None, log_states=True, side=None):
        """sn / side ("left" | "right") choose the hand when more than one is connected; with one hand connected neither is needed."""
        self.mode, self.kp, self.kd, self.effort, self.effort_scale, self.cutoff = mode, kp, kd, effort, effort_scale, cutoff
        self.dry, self.sn, self.log_states, self.side = dry_run, sn, log_states, side
        self.states = []; self._stop = threading.Event(); self.restore = []; self._hit = False; self._prev = {}

    def _on_signal(self, *_):
        """Ctrl-C, a closed terminal or a kill: the FIRST one starts the orderly stop (ramp aborted, hand switched off and confirmed).
        Further ones change nothing: a second Ctrl-C must not cut the switch-off short."""
        if self._hit: return
        self._hit = True; raise KeyboardInterrupt

    def __enter__(self):
        if self.mode == "mit" and self.effort > MAX_EFFORT_A: raise SystemExit(f"current limit {self.effort} A is above the hard limit of {MAX_EFFORT_A} A: refusing")
        if self.dry:
            self.sdk = None; self.JC = _FakeCmd; self.hand = FakeHand(); self.manager = None; self.nid2i = FakeHand.nid_to_joint_index
            print("[dry-run] fake hand, first-order lag 30 ms")
        else:
            import wuji_sdk
            self.sdk = wuji_sdk; self.JC = wuji_sdk.JointCommand; self.manager = wuji_sdk.SdkManager.instance()
            hands = [d for d in self.manager.scan() if d.device_type == wuji_sdk.DeviceType.WujiHand2]
            for d in hands: print(f"  found SN={d.sn} ({side_of(d.sn) or 'side unknown'}) ip={d.ip} fw={d.firmware_version}")
            if self.sn: hands = [d for d in hands if d.sn == self.sn]
            if self.side: hands = [d for d in hands if side_of(d.sn) in (self.side, None)]      # a serial number we cannot read counts as a candidate
            want = " ".join(x for x in (self.side and f"{self.side} hand", self.sn and f"SN {self.sn}") if x)
            if not hands: raise SystemExit(f"no Wuji Hand 2 found{' for: ' + want if want else ''} (Ethernet link? same subnet? PSU on?)")
            if len(hands) > 1: raise SystemExit(f"{len(hands)} hands match ({', '.join(d.sn for d in hands)}): choose one with --sn or --side; refusing to guess")
            self.sn = hands[0].sn                                     # from here on (reconnect included) only this hand
            if side_of(self.sn) is None and self.side: print(f"  WARNING: cannot read left/right from SN {self.sn}; taking it as the {self.side} hand")
            self.side = side_of(self.sn) or self.side
            self.hand = self.manager.connect(sn=self.sn, device_name="piano")
            self.nid2i = wuji_sdk.WujiHand2.nid_to_joint_index
        online = int(self.hand.online_joints_count().get())
        if online != JOINTS: self.close(); raise SystemExit(f"{online}/20 joints online, refusing to move")
        for sig in ("SIGINT", "SIGHUP", "SIGTERM"):      # Ctrl-C, a dropped SSH session or a kill must all disable the hand, once
            try: self._prev[sig] = signal.signal(getattr(signal, sig), self._on_signal)
            except Exception: pass
        self._configure()
        # read the pose first, then enable while already commanding that pose: the hand must not move at the moment of enabling
        self._sub = self.hand.joint_states().subscribe()
        self._reader = threading.Thread(target=self._read_loop, daemon=True); self._reader.start()
        t_ = time.monotonic()
        while self.latest() is None and time.monotonic() - t_ < 2.0: time.sleep(0.01)
        if self.latest() is None or np.isnan(self.latest()).any(): self.close(); raise SystemExit("no complete joint_states within 2 s")
        self.q_before = self.latest(); self.pub = self.hand.joint_command().publish()
        try: self.send(self.q_before); self.hand.enable(); self._wait_enabled(); self.send(self.q_before)
        except BaseException: self.close(); raise      # anything going wrong while switching on (Ctrl-C included) ends with the hand disabled
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
            check_effort_limit(h.effort_limit().get(), self.effort)

    def _wait_enabled(self, timeout=5.0):
        sub = self.hand.joint_diagnostics().subscribe(); deadline = time.monotonic() + timeout; seen = en = 0
        try:
            while time.monotonic() < deadline:
                t_ = time.monotonic(); frame = None
                while time.monotonic() - t_ < 0.2: self.send(self.q_before); time.sleep(0.002)      # keep holding the pose while the joints switch on
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
            if sent % 100 == 0 and self.states and time.monotonic() - self.states[-1][0] > 0.5:
                raise RuntimeError("no joint states from the hand for 0.5 s: connection lost, stopping")
            if on_tick: on_tick(i)
            w = t0 + k / rate - time.monotonic()
            if w > 0: time.sleep(w)
        return t0, dict(sent=sent, skipped=late)

    def _enabled_count(self, hand, wait=0.4):
        """How many joints report 'switched on'. None if the hand does not answer."""
        try: sub = hand.joint_diagnostics().subscribe()
        except Exception: return None
        frame = None; t_ = time.monotonic()
        try:
            while time.monotonic() - t_ < wait + 1.0:
                x = sub.recv()
                if x is not None: frame = x; continue
                if frame is not None and time.monotonic() - t_ > wait: break
                time.sleep(0.01)
        except Exception: frame = None
        finally:
            try: sub.close()
            except Exception: pass
        if frame is None or not len(frame.joints): return None
        return sum(1 for e in frame.joints if e.status_word.ext_state == 2)

    def _switch_off(self, tries=20):
        """Motors off, confirmed by the hand. If the connection dropped, the first try does not arrive and the hand keeps
        holding its last pose (seen on 15 Nov, firmware 3.0.0): reconnect and repeat until the hand confirms."""
        try: self.hand.disable()
        except Exception: pass
        if self.dry or self.manager is None: return True
        n = self._enabled_count(self.hand)
        if n == 0: return True
        print(f"switch-off not confirmed ({'no answer from the hand' if n is None else str(n) + ' joints still on'}): reconnecting to switch it off ...", flush=True)
        for k in range(tries):
            time.sleep(1.0)
            try:
                try: self.manager.disconnect_all()
                except Exception: pass
                hands = [d for d in self.manager.scan() if d.device_type == self.sdk.DeviceType.WujiHand2 and (not self.sn or d.sn == self.sn)]
                if not hands: continue
                self.hand = self.manager.connect(sn=hands[0].sn, device_name="piano")
                self.hand.disable(); n = self._enabled_count(self.hand)
                if n == 0: print(f"hand switched off after reconnecting (try {k + 1})", flush=True); return True
            except Exception: pass
        print("\n!!! THE HAND IS STILL SWITCHED ON and holds its last pose: the connection is gone.\n"
              "!!! Check the network cable, then run scripts/hand_off.py, or unplug the hand's power.\n", flush=True)
        return False

    def close(self):
        self._stop.set()
        old = {}
        for sig in ("SIGINT", "SIGHUP", "SIGTERM"):      # nothing may interrupt the switch-off: a second Ctrl-C would leave the hand in an unknown state
            try: old[sig] = signal.signal(getattr(signal, sig), signal.SIG_IGN)
            except Exception: pass
        try: self._close()
        finally:
            for sig, h in old.items():                    # Ctrl-C works again for whatever the script does next; after an interrupt the script
                try: signal.signal(getattr(signal, sig), signal.SIG_IGN if self._hit else self._prev.get(sig, h))    # is on its way out: let it save its log
                except Exception: pass

    def _close(self):
        for f in (lambda: self.hand.disable(), lambda: self.pub.close(), lambda: self._sub.close()):
            try: f()
            except Exception: pass
        try: self.off_confirmed = self._switch_off()
        except BaseException: self.off_confirmed = False; print("\n!!! switch-off was interrupted: check that the hand is off (scripts/hand_off.py)\n", flush=True)
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
