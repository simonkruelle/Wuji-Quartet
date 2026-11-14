"""Writes assets/ode_to_joy/ode_to_joy.mid: the "Ode to Joy" melody (Beethoven, Symphony No. 9, public domain)
in C major, in the five-finger position C5..G5, so a hand that stays in one place can play it:
thumb C5, index D5, middle E5, ring F5, pinky G5. One finger per key, no stretch, no black keys.

The melody's single low G (bar 12) is outside that position and is played one octave up (G5).
To play it at middle C instead, hold the hand one octave lower: the finger plan is the same.

  python scripts/make_ode_to_joy.py [--bpm 108]"""
import argparse, os, sys
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from midi_io import write_notes
ap = argparse.ArgumentParser(); ap.add_argument("--bpm", type=float, default=108.0); ap.add_argument("--gate", type=float, default=0.8, help="sounding fraction of each note")
ap.add_argument("--out", default=os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "assets/ode_to_joy/ode_to_joy.mid")); A = ap.parse_args()
C, D, E, F, G = 72, 74, 76, 77, 79
A_ = [(E, 1), (E, 1), (F, 1), (G, 1), (G, 1), (F, 1), (E, 1), (D, 1), (C, 1), (C, 1), (D, 1), (E, 1)]
BARS = (A_ + [(E, 1.5), (D, .5), (D, 2)] +                                   # bars 1-4
        A_ + [(D, 1.5), (C, .5), (C, 2)] +                                   # bars 5-8
        [(D, 1), (D, 1), (E, 1), (C, 1), (D, 1), (E, .5), (F, .5), (E, 1), (C, 1),
         (D, 1), (E, .5), (F, .5), (E, 1), (D, 1), (C, 1), (D, 1), (G, 2)] +  # bars 9-12 (low G played as G5)
        A_ + [(D, 1.5), (C, .5), (C, 2)])                                    # bars 13-16
beat = 60.0 / A.bpm; t = 0.0; notes = []
for p, b in BARS:
    notes.append(dict(on=t, off=t + A.gate * b * beat, pitch=p, vel=72)); t += b * beat
assert abs(t - 64 * beat) < 1e-9, "16 bars of 4 beats"
os.makedirs(os.path.dirname(A.out), exist_ok=True); write_notes(A.out, notes, bpm=A.bpm)
print(f"{A.out}: {len(notes)} notes, {t:.1f} s at {A.bpm:g} bpm, shortest note {min(n['off'] - n['on'] for n in notes) * 1000:.0f} ms")
