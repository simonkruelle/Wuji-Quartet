"""Two-hand pieces for two hands that each stay in one place: every hand plays five neighbouring white keys.
Writes one MIDI file per hand (and one with both, for listening) into assets/duets/.

  python scripts/make_duet.py ode            # Ode to Joy (Beethoven): melody C5..G5, broken-chord accompaniment C3..G3
  python scripts/make_duet.py jingle         # Jingle Bells chorus (Pierpont, 1857) with the same accompaniment figure
  python scripts/make_duet.py korobeiniki    # Korobeiniki (Russian folk tune, known from Tetris), first phrase, four times, faster each time;
                                             # D minor: melody D5..A5, accompaniment D3..A3 (both hands one key right of the C position)
  python scripts/make_duet.py chopsticks     # Chopsticks (E. Allen, 1877), first strain: the hands sit next to each other, B3..F4 and G4..D5
  python scripts/make_duet.py canon          # Pachelbel's Canon (in C), ground bass + the first two melody lines; both thumbs reach one key further

The second hand's part is the same notes whether a left or a second right hand plays it; only the fingers differ.
All tunes are public domain. Then plan each part with sbto_piano.py (docs/RUNBOOK.md, "Two hands")."""
import argparse, os, sys
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from midi_io import write_notes, note_name
R = None


def seq(part, bpm, t0=0.0, gate=0.8, vel=72):
    """part: list of (pitch | (pitches) | None, beats). Returns notes and the end time."""
    beat = 60.0 / bpm; t = t0; out = []
    for p, b in part:
        for k in (() if p is None else p if isinstance(p, tuple) else (p,)): out.append(dict(on=t, off=t + gate * b * beat, pitch=k, vel=vel))
        t += b * beat
    return out, t


def alberti(chords, low):
    """chords: one letter per beat, 'I' or 'V' (or 'i'): two eighth notes per beat, bottom note on the beat, top key (thumb of a left hand) off the beat.
    low = lowest of the five keys. I: 1-5-3-5, V7: 2-5-4-5 (major position: C G E G / D G F G)."""
    k = [low, low + 2, low + 4, low + 5, low + 7]; out = []
    for i, c in enumerate(chords):
        bottom = {"I": (k[0], k[2]), "V": (k[1], k[3])}[c][i % 2]
        out += [(bottom, .5), (k[4], .5)]
    return out


def ode():
    C, D, E, F, G = 72, 74, 76, 77, 79
    O1 = [(E, 1), (E, 1), (F, 1), (G, 1), (G, 1), (F, 1), (E, 1), (D, 1), (C, 1), (C, 1), (D, 1), (E, 1)]
    rh = (O1 + [(E, 1.5), (D, .5), (D, 2)] + O1 + [(D, 1.5), (C, .5), (C, 2)] +
          [(D, 1), (D, 1), (E, 1), (C, 1), (D, 1), (E, .5), (F, .5), (E, 1), (C, 1), (D, 1), (E, .5), (F, .5), (E, 1), (D, 1), (C, 1), (D, 1), (G, 2)] +
          O1 + [(D, 1.5), (C, .5), (C, 2)])                       # = make_melody.py ode
    A = "IIII" "IIIV" "IIVI"                                      # harmony per beat under E E F G | G F E D | C C D E
    lh = (alberti(A + "IIVV" + A + "VVII" + "VVII" "VIII" "VIIV" "IVVV" + A + "VV", 48) + [((48, 52, 55), 2)])   # ends on the full C chord
    return "Ode to Joy, two hands", [(108, rh, lh)], dict(right_five="72,74,76,77,79", center_right=76, low_keys=[48, 50, 52, 53, 55])


def jingle():
    C, D, E, F, G = 72, 74, 76, 77, 79
    J1 = [(E, 1), (E, 1), (E, 2), (E, 1), (E, 1), (E, 2), (E, 1), (G, 1), (C, 1.5), (D, .5), (E, 4),
          (F, 1), (F, 1), (F, 1.5), (F, .5), (F, 1), (E, 1), (E, 1), (E, .5), (E, .5)]
    rh = J1 + [(E, 1), (D, 1), (D, 1), (E, 1), (D, 2), (G, 2)] + J1 + [(G, 1), (G, 1), (F, 1), (D, 1), (C, 4)]     # = make_melody.py jingle
    H1 = "IIII" "IIII" "IIII" "IIII" "VVVV" "VIII"               # F bars: the V7 figure D G F G carries the F
    lh = alberti(H1 + "IVVI" "VVVV" + H1 + "VVVV", 48) + [((48, 52, 55), 4)]
    return "Jingle Bells, two hands", [(120, rh, lh)], dict(right_five="72,74,76,77,79", center_right=76, low_keys=[48, 50, 52, 53, 55])


def korobeiniki():
    d = [74, 76, 77, 79, 81]; s1, s2, s3, s4, s5 = d                 # D minor five-finger position, white keys only
    rh = [(s5, 1), (s2, .5), (s3, .5), (s4, 1), (s3, .5), (s2, .5), (s1, 1), (s1, .5), (s3, .5), (s5, 1), (s4, .5), (s3, .5),
          (s2, 1.5), (s3, .5), (s4, 1), (s5, 1), (s3, 1), (s1, 1), (s1, 1), (R, 1)]
    k = [50, 52, 53, 55, 57]                                          # D3 E3 F3 G3 A3
    V = [(k[1], .5), (k[4], .5), (k[3], .5), (k[4], .5)] * 2          # A7 without its third: E A G A
    I = [(k[0], .5), (k[4], .5), (k[2], .5), (k[4], .5)] * 2          # D minor: D A F A
    lh = V + I + V + I[:4] + [(k[2], 1), ((k[0], k[4]), 1)]
    last = (rh[:-2] + [((s1, s3, s5), 2)], lh[:-4] + [(k[2], 1), ((k[0], k[2], k[4]), 2)])        # last time: both hands end on the full chord
    return ("Korobeiniki, two hands, faster each time", [(120, rh, lh), (150, rh, lh), (180, rh, lh), (200, last[0], last[1])],
            dict(right_five="74,76,77,79,81", center_right=77, low_keys=k))


def chopsticks():
    lf, le, ld, lc = 65, 64, 62, 60; rg, ra, rb, rc = 67, 69, 71, 72
    A = [(lf, rg)] * 6 + [(le, rg)] * 6 + [(ld, rb)] * 6 + [(lc, rc)] * 3
    pairs = A + [(lc, rc), (ld, rb), (le, ra)] + A + [(lc, rc), R, R]
    rh = [(p[1] if p else R, 1) for p in pairs]; lh = [(p[0] if p else R, 1) for p in pairs]
    return ("Chopsticks, first strain", [(168, rh, lh)],
            dict(right_five="67,69,71,72,74", center_right=71, low_keys=[59, 60, 62, 64, 65], beats_per_bar=3))


def canon():
    # in C major (Pachelbel wrote it in D): bass C G A E F C F G; line 1 E D C B A G A B; line 2 C B A G F E F D
    bass = [(60, 2), (55, 2), (57, 2), (52, 2), (53, 2), (60, 2), (53, 2), (55, 2)]     # E3 F3 G3 A3 under the fingers, the thumb reaches C4
    l1 = [(76, 2), (74, 2), (72, 2), (71, 2), (69, 2), (67, 2), (69, 2), (71, 2)]       # G4 A4 (thumb) B4 C5 D5 E5
    l1b = [(76, 1), (72, 1), (74, 1), (71, 1), (72, 1), (69, 1), (71, 1), (67, 1), (69, 1), (72, 1), (67, 1), (72, 1), (69, 1), (72, 1), (71, 1), (74, 1)]   # quarter notes: chord tones
    rh = [(R, 16)] + l1 + l1b + [((72, 76), 4)]; lh = bass * 3 + [((52, 60), 4)]
    return ("Pachelbel's Canon in C, two hands", [(72, rh, lh)],
            dict(right_five="69,71,72,74,76", right_also="67:0", center_right=72, low_keys=[52, 53, 55, 57, 60], left_only=True))    # a left hand: its thumb takes C4


PIECES = dict(ode=ode, jingle=jingle, korobeiniki=korobeiniki, chopsticks=chopsticks, canon=canon)
if __name__ == "__main__":
    ap = argparse.ArgumentParser(); ap.add_argument("piece", choices=sorted(PIECES)); ap.add_argument("--tempo", type=float, default=1.0, help="scales every tempo, e.g. 0.8")
    ap.add_argument("--gate", type=float, default=0.8, help="sounding fraction of each note"); ap.add_argument("--out-dir", default=None); A = ap.parse_args()
    title, sections, info = PIECES[A.piece](); t = 0.0; RH = []; LH = []; bpb = info.get("beats_per_bar", 4)
    for bpm, rh, lh in sections:
        br = sum(b for _, b in rh); bl = sum(b for _, b in lh)
        assert abs(br - bl) < 1e-9 and abs(br / bpb - round(br / bpb)) < 1e-9, f"{A.piece}: right hand {br} beats, left hand {bl} beats, {bpb} per bar"
        a, t1 = seq(rh, bpm * A.tempo, t, A.gate); b, _ = seq(lh, bpm * A.tempo, t, A.gate, vel=60); RH += a; LH += b; t = t1
    d = A.out_dir or os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "assets/duets"); os.makedirs(d, exist_ok=True)
    bpm0 = sections[0][0] * A.tempo
    for name, notes in (("right", RH), ("left", LH), ("both", sorted(RH + LH, key=lambda n: n["on"]))):
        write_notes(os.path.join(d, f"{A.piece}_{name}.mid"), notes, bpm=bpm0)
    lo = info["low_keys"]; lk = sorted({n["pitch"] for n in LH}); rk = sorted({n["pitch"] for n in RH})
    gap = lambda N: min(b["on"] - a["on"] for a in N for b in N if b["pitch"] == a["pitch"] and b["on"] > a["on"] + 1e-9)
    print(f"{title}: {t:.1f} s, tempo {' -> '.join(f'{s[0] * A.tempo:g}' for s in sections)} bpm")
    print(f"  right hand {len(RH)} notes on {[note_name(k) for k in rk]}, left part {len(LH)} notes on {[note_name(k) for k in lk]}")
    print(f"  fastest repeat of one key: right {gap(RH) * 1000:.0f} ms, left {gap(LH) * 1000:.0f} ms")
    lf = ",".join(str(k) for k in reversed(lo)); r2 = ",".join(str(k) for k in lo)
    print(f"  right hand: --five {info['right_five']} --center {info['center_right']}" + (f" --also {info['right_also']}" if "right_also" in info else ""))
    print(f"  second hand, a LEFT hand:  --side left --five {lf} --center {lo[2]}")
    print("  second hand, a RIGHT hand: " + ("not arranged (the bass needs the thumb on the high side)" if info.get("left_only") else f"--five {r2} --center {lo[2]}"))
    print(f"  files: {d}/{A.piece}_right.mid, _left.mid, _both.mid")
