"""Writes a melody as a MIDI file in the five-finger position C5..G5, so the hand that stays in one place can play it
(thumb C5, index D5, middle E5, ring F5, pinky G5; same mount as Ode to Joy). All tunes are traditional / public domain.

  python scripts/make_melody.py jingle [--bpm 120]      # Jingle Bells, chorus (J. Pierpont, 1857)
  python scripts/make_melody.py saints                  # When the Saints Go Marching In
  python scripts/make_melody.py mary                    # Mary Had a Little Lamb
then plan it:  python scripts/sbto_piano.py --piece assets/melodies/jingle.mid --wrist fixed ...  (see docs/RUNBOOK.md, step 6)"""
import argparse, os, sys
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from midi_io import write_notes
C, D, E, F, G, R = 72, 74, 76, 77, 79, None          # R = rest
J1 = [(E, 1), (E, 1), (E, 2), (E, 1), (E, 1), (E, 2), (E, 1), (G, 1), (C, 1.5), (D, .5), (E, 4),
      (F, 1), (F, 1), (F, 1.5), (F, .5), (F, 1), (E, 1), (E, 1), (E, .5), (E, .5)]
TUNES = dict(
    jingle=("Jingle Bells", 120, J1 + [(E, 1), (D, 1), (D, 1), (E, 1), (D, 2), (G, 2)] + J1 + [(G, 1), (G, 1), (F, 1), (D, 1), (C, 4)]),
    saints=("When the Saints Go Marching In", 120,
            [(R, 1), (C, 1), (E, 1), (F, 1), (G, 4), (R, 1), (C, 1), (E, 1), (F, 1), (G, 4), (R, 1), (C, 1), (E, 1), (F, 1),
             (G, 2), (E, 2), (C, 2), (E, 2), (D, 4), (R, 1), (E, 1), (E, 1), (D, 1), (C, 3), (C, 1), (E, 2), (G, 2), (G, 1), (F, 3),
             (R, 1), (E, 1), (F, 1), (G, 2), (E, 2), (C, 2), (D, 2), (C, 4)]),
    mary=("Mary Had a Little Lamb", 108,
          [(E, 1), (D, 1), (C, 1), (D, 1), (E, 1), (E, 1), (E, 2), (D, 1), (D, 1), (D, 2), (E, 1), (G, 1), (G, 2),
           (E, 1), (D, 1), (C, 1), (D, 1), (E, 1), (E, 1), (E, 1), (E, 1), (D, 1), (D, 1), (E, 1), (D, 1), (C, 4)]))
ap = argparse.ArgumentParser(); ap.add_argument("tune", choices=sorted(TUNES)); ap.add_argument("--bpm", type=float, default=None)
ap.add_argument("--gate", type=float, default=0.8, help="sounding fraction of each note"); ap.add_argument("--out", default=None); A = ap.parse_args()
title, bpm, seq = TUNES[A.tune]; bpm = A.bpm or bpm; beat = 60.0 / bpm; t = 0.0; notes = []
for p, b in seq:
    if p is not None: notes.append(dict(on=t, off=t + A.gate * b * beat, pitch=p, vel=72))
    t += b * beat
assert abs(t / beat / 4 - round(t / beat / 4)) < 1e-9, f"{t / beat} beats is not a whole number of 4/4 bars"
out = A.out or os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), f"assets/melodies/{A.tune}.mid")
os.makedirs(os.path.dirname(out), exist_ok=True); write_notes(out, notes, bpm=bpm)
print(f"{out}: {title}, {len(notes)} notes, {t / beat / 4:.0f} bars, {t:.1f} s at {bpm:g} bpm, shortest note {min(n['off'] - n['on'] for n in notes) * 1000:.0f} ms")
