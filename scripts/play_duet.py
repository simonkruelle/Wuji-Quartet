"""Two hands, two plans, one start: plays plan A on one Wuji Hand 2 and plan B on the other, in step.

  python scripts/play_duet.py plans/ode_level_stroke90_s0 plans/ode_accomp_left_s0 --effort 1.0          # a right and a left hand
  python scripts/play_duet.py <plan A> <plan B> --sn-a WH2K... --sn-b WH2K...                             # two right hands: name them
  python scripts/play_duet.py <plan A> <plan B> --dry-run                                                 # no hardware
  python scripts/play_duet.py <plan A> <plan B> --only a                                                  # one hand alone, same timing

Each hand is driven by its own play_on_hand.py process (same checks, same current limit, same confirmed switch-off);
this script gives both the same start time and stops the other hand if one fails. The hand for each plan is chosen by the
plan's side (left / right, read from the serial number) unless --sn-a / --sn-b name it.
Ctrl-C at any time: both hands stop and switch off."""
import argparse, os, signal, subprocess, sys, threading, time
import numpy as np
HERE = os.path.dirname(os.path.abspath(__file__))
ap = argparse.ArgumentParser(); ap.add_argument("plan_a"); ap.add_argument("plan_b")
ap.add_argument("--sn-a", default=None); ap.add_argument("--sn-b", default=None)
ap.add_argument("--effort", type=float, default=0.5, help="current limit for both hands, A (first try 0.5; hard limit 1.5)")
ap.add_argument("--tempo", type=float, default=1.0, help="0.5 = half speed"); ap.add_argument("--countdown", type=float, default=15.0, help="seconds from launch to the first command of the piece")
ap.add_argument("--only", default=None, choices=["a", "b"], help="play one of the two parts alone"); ap.add_argument("--yes", action="store_true"); ap.add_argument("--dry-run", action="store_true")
A = ap.parse_args()
npz = lambda p: p if p.endswith(".npz") else os.path.join(p, "theme_q_1khz.npz")
P = {}
for k, p in (("a", A.plan_a), ("b", A.plan_b)):
    Z = np.load(npz(p)); P[k] = dict(path=npz(p), side=str(Z["side"]) if "side" in Z.files else "right", t0=float(Z["piece_t0"]) if "piece_t0" in Z.files else 0.0,
                                      dur=float(Z["t"][-1]), notes=len(Z["notes"]), name=os.path.basename(os.path.dirname(os.path.abspath(npz(p)))), sn=getattr(A, f"sn_{k}"))
if P["a"]["side"] == P["b"]["side"] and not (A.sn_a and A.sn_b) and not A.dry_run and not A.only:
    sys.exit(f"both plans are for a {P['a']['side']} hand: name the two hands with --sn-a and --sn-b (python scripts/hand_info.py lists them)")
t00 = min(P["a"]["t0"], P["b"]["t0"]); use = [k for k in ("a", "b") if A.only in (None, k)]
for k in use: print(f"  {k.upper()}: {P[k]['name']} · {P[k]['side']} hand{' ' + P[k]['sn'] if P[k]['sn'] else ''} · {P[k]['notes']} notes · enters {(P[k]['t0'] - t00) / A.tempo:.2f} s after the start")
print(f"  current limit {A.effort} A, tempo x{A.tempo}, first command {A.countdown:.0f} s after launch")
if not (A.yes or A.dry_run): input("hands clear of both robots? Enter = start, Ctrl-C = abort ")
T0 = time.time() + A.countdown; procs = {}; off = {}; played = {}; hit = []


def once(*_):          # the first Ctrl-C stops both hands; more of them change nothing
    if not hit: hit.append(1); raise KeyboardInterrupt


signal.signal(signal.SIGINT, once)


def relay(k, pr):
    for line in pr.stdout:
        line = line.rstrip("\n")
        if "hand switched off" in line: off[k] = "confirmed" in line and "NOT" not in line
        if line.startswith("streamed "): played[k] = True
        print(f"[{k.upper()}] {line}", flush=True)


for k in use:
    cmd = [sys.executable, "-u", os.path.join(HERE, "play_on_hand.py"), P[k]["path"], "--effort", str(A.effort), "--tempo", str(A.tempo), "--yes",
           "--start-at", repr(T0 + (P[k]["t0"] - t00) / A.tempo)]
    if P[k]["sn"]: cmd += ["--sn", P[k]["sn"]]
    if A.dry_run: cmd += ["--dry-run", "--log", os.path.join("/tmp", f"duet_dry_{k}.npz")]
    procs[k] = subprocess.Popen(cmd, stdout=subprocess.PIPE, stderr=subprocess.STDOUT, text=True)
    threading.Thread(target=relay, args=(k, procs[k]), daemon=True).start()
stopped = False
try:
    while any(pr.poll() is None for pr in procs.values()):
        for k, pr in procs.items():
            if pr.poll() is not None and not played.get(k) and not stopped and any(o.poll() is None for o in procs.values()):
                time.sleep(0.2)                                   # let its last lines arrive
                if played.get(k): continue
                stopped = True; print(f"!!! {k.upper()} stopped before the end of its part: stopping the other hand", flush=True)
                for o in procs.values():
                    if o.poll() is None: o.send_signal(signal.SIGINT)
        time.sleep(0.05)
except KeyboardInterrupt:
    print("\ninterrupted: both hands stop and switch off ...", flush=True)      # the children got the same Ctrl-C from the terminal
    for pr in procs.values():
        if pr.poll() is None:
            try: pr.send_signal(signal.SIGINT)
            except Exception: pass
    for pr in procs.values(): pr.wait()
time.sleep(0.3)
bad = [k for k in use if not off.get(k)]
print("both hands switched off: confirmed" if not bad and len(use) == 2 else "hand switched off: confirmed" if not bad else
      f"!!! switch-off NOT CONFIRMED for {', '.join(b.upper() for b in bad)}")
if bad and not A.dry_run:
    print("running scripts/hand_off.py ...", flush=True); subprocess.call([sys.executable, os.path.join(HERE, "hand_off.py")])
sys.exit(1 if bad or stopped or any(pr.returncode for pr in procs.values()) or len(played) < len(use) else 0)
