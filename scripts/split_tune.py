"""One tune, two hands side by side: the left hand takes the lower five white keys, the right hand the five above, thumbs on
neighbouring keys. Ten keys instead of five, so a tune wider than one hand keeps most of its notes exactly; Library › Duets then
shows the two halves as a pair (Retarget › Both hands, ▶ Play both hands).

  python scripts/split_tune.py assets/library/Fly_Me_to_the_Moon.mid --part 0:15 --start 0 --length 65 --name fly_me_to_the_moon --fill --ending
  -> assets/duets/<name>_left.mid, <name>_right.mid (+ .json beside each: where it came from, how faithful it is)
  --splice 0:33.1,33.1:55.86,22.76:33.1 --repeat 2: only these stretches of the tune (s after its first note), back to back,
  and the whole twice: a verse on repeat without the song's ending; with --fill the band's turnaround leads back to the start
  --gap 1: one free key between the hands. With the thumbs on neighbouring keys the two thumbs touch in simulation
  (Fly Me to the Moon, 15 Nov: 81 % of the steps); a free key, or the two mounts moved apart, keeps them clear.

1. the tune: the instrument --part (or the top line), from --start for --length seconds (gui/library.cut, as the Studio's excerpts)
2. where: the transposition (prefer none) and the ten neighbouring white keys that keep the most notes on their own key
3. a note beyond the ten keys takes its own pitch an octave up or down when that is among them (the harmony stays right: a
   cadence's G stays a G); any other (black keys) moves to the nearest key, the one that keeps the tune's direction (up or down).
   --black: the black keys between a hand's five white keys are played too, each by a neighbouring finger (the one that is
   free around those notes); the .json lists them as `also` = "key:finger", for the plan (sbto_piano.py --also). A tune's
   sharps are often its most telling notes: Fly Me to the Moon's G sharp and C sharp played as G and C sound wrong
4. a key struck again sooner than 0.25 s (the real hand needs that long to lift and press again) is struck a little later
   (at most 0.12 s), as long as the tune leaves room; otherwise dropped, as gui/simplify.py does
5. --fill: where the tune rests 0.9 s or longer, the hands play the band's chord there: on each beat of the rhythm section
   (the bass and the busiest accompanying instrument; not the solo lines above, whose runs carry passing notes) one note of
   their chord, broken upward, in the left hand when it has two chord notes; nothing within 0.3 s of the tune's return
6. --ending: the last note becomes a held chord, the triad on it with the third the band plays (major when the band has it)
7. --legato: every note is held until the next one starts (plus 0.08 s: the key needs that long to come up, so there is no
   hole between two notes); the tune file's own notes stop a third of a beat early, which sounds chopped on a robot that plays
   every note alike. Where the tune rests longer than 0.45 s the note is held up to a quarter second before the next phrase
8. every note goes to the hand whose five keys hold it
"""
import argparse, json, os, sys

HERE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(HERE, "gui")); sys.path.insert(0, os.path.join(HERE, "scripts"))
import library as L                                   # noqa: E402
from midi_io import write_notes, note_name            # noqa: E402

MIN_SAME = 0.25       # s between two strikes of one key (gui/simplify.py)
SHIFT_MAX = 0.12      # s a too-early repeat may move later instead of being dropped
FILL_REST = 0.9       # s of silence in the tune that gets the band's chords (--fill)
BEAT_MIN = 0.4        # s between two fill notes: at most one per beat of the band
CLEAR = 0.3           # s kept free before the tune comes back
HOLD = 1.5            # s the final chord rings (--ending)
CROSS = 0.45          # s a finger needs between its own key and a black key beside it (--black)
LEGATO = 0.45         # s: a silence up to this long after a note is closed (--legato); longer ones are rests between phrases
OVERLAP = 0.08        # s a held note stays down after the next one starts (in simulation a key is back up 0.06 s before its note's end)
BREATH = 0.26         # s of silence kept before a new phrase
WHITES = [k for k in range(21, 109) if not L.is_black(k)]


def hands(i, gap):
    """The left hand's five white keys from WHITES[i] up, then `gap` free keys, then the right hand's five."""
    return WHITES[i:i + 5], WHITES[i + 5 + gap:i + 10 + gap]


def inner_blacks(five):
    """The black keys between a hand's five white keys."""
    return [k for k in range(min(five) + 1, max(five)) if L.is_black(k)]


def place(ps, gap=0, black=False):
    """(transpose, index of the lowest white key) keeping the most notes on their own key; ties: no transposition, then nearest middle C."""
    best = None
    for t in range(-12, 13):
        q = [p + t for p in ps]
        for i in range(len(WHITES) - 10 - gap):
            keys = set(sum(hands(i, gap), []))
            if black: keys |= set(sum((inner_blacks(h) for h in hands(i, gap)), []))
            score = (sum(x in keys for x in q), -abs(t), -abs(WHITES[i + 5] - 60))
            if best is None or score > best[0]:
                best = (score, t, i)
    return best[1], best[2]


def nearest(prev, p, nxt, keys):
    """The key for pitch p: its own pitch an octave away when the hands have it, else the nearest key that keeps the steps' directions."""
    octave = [k for k in (p - 12, p + 12) if k in keys]
    if octave:
        return min(octave, key=lambda k: abs(k - prev) if prev is not None else 0)
    d = min(abs(k - p) for k in keys)
    cands = [k for k in keys if abs(k - p) == d]
    sign = lambda x: (x > 0) - (x < 0)
    def kept(k):
        return (prev is None or sign(k - prev) == sign(p - prev)) + (nxt is None or sign(nxt - k) == sign(nxt - p))
    return max(cands, key=lambda k: (kept(k), -k))


def spliced(ns, wins, t00, times=1):
    """Notes [on, off, pitch] on the file's clock -> the windows (s after t00) back to back, the whole `times` times; (notes, length of one round)."""
    one, o = [], 0.0
    for a, b in wins:
        one += [[on - t00 - a + o, min(off - t00 - a, b - a - 0.02) + o, p] for on, off, p in ns if a - 1e-6 <= on - t00 < b - 1e-6]
        o += b - a
    return sorted([on + k * o, off + k * o, p] for k in range(times) for on, off, p in one), o


def band_notes(piece, part, start, length, t0, cut=None):
    """(rhythm section, its chord instrument alone) in the window, on the tune's clock (the excerpt starts at its first tune note):
    the bass and the busiest accompanying instrument. The chord comes from the chord instrument: a walking bass passes through
    notes that are not in the chord. Without instrument parts in the file: every note that is not the tune's, twice."""
    parts = [p for p in (L.piece(piece).get("parts") or []) if p.get("part") != part]
    win = cut or (lambda ns: [[n[0] - t0, n[1] - t0, n[2]] for n in ns if start <= n[0] < start + length + 2])
    if part and len(parts) >= 2:
        bass = min(parts, key=lambda p: p.get("median", 60))
        comp = max((p for p in parts if p is not bass and p.get("median", 60) <= 66), key=lambda p: p.get("n", 0), default=None)
        if comp:
            c = win(L.piece_notes(piece, comp["part"]))
            return c + win(L.piece_notes(piece, bass["part"])), c
    tune = {(round(n[0], 3), n[2]) for n in L.piece_notes(piece, part)} if part else set()
    rest = win(n for n in L.piece_notes(piece) if (round(n[0], 3), n[2]) not in tune)
    return rest, rest


def beats(band, a, b):
    """The band's onsets between a and b, at least BEAT_MIN apart."""
    out = []
    for on in sorted({round(n[0], 2) for n in band if a <= n[0] < b}):
        if not out or on - out[-1] >= BEAT_MIN:
            out.append(on)
    return out


def chord_at(band, t):
    """(pitch classes sounding at t, the lowest one's pitch class)."""
    snd = [n for n in band if n[0] <= t + 0.08 and n[1] > t + 0.02]
    return ({n[2] % 12 for n in snd}, min(snd, key=lambda n: n[2])[2] % 12) if snd else (set(), None)


def main():
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    ap.add_argument("piece"); ap.add_argument("--part", default=None, help="instrument 'track:channel' that carries the tune")
    ap.add_argument("--start", type=float, default=0.0); ap.add_argument("--length", type=float, default=60.0)
    ap.add_argument("--name", required=True, help="file stem in assets/duets"); ap.add_argument("--title", default=None)
    ap.add_argument("--private", default=None, help="a note for the .json: why these files stay on this computer")
    ap.add_argument("--gap", type=int, default=0, help="free white keys between the two hands (thumbs on neighbouring keys touch in simulation)")
    ap.add_argument("--fill", action="store_true", help="the band's chords in the tune's rests")
    ap.add_argument("--ending", action="store_true", help="end on a held chord")
    ap.add_argument("--legato", action="store_true", help="hold every note until the next one starts")
    ap.add_argument("--splice", default=None, help="stretches of the tune to keep, 'from:to,from:to' in s after its first note, played back to back (instead of --start / --length)")
    ap.add_argument("--repeat", type=int, default=1, help="with --splice: play the whole this many times")
    ap.add_argument("--black", action="store_true", help="play the black keys between a hand's five white keys too")
    A = ap.parse_args()
    cut = None
    if A.splice:
        wins = [tuple(float(x) for x in w.split(":")) for w in A.splice.split(",")]
        whole = L.piece_notes(A.piece, A.part); t0 = min(n[0] for n in whole)
        notes, period = spliced(whole, wins, t0, A.repeat)
        cut = lambda ns: spliced(list(ns), wins, t0, A.repeat)[0]
        A.start, A.length = wins[0][0], period * A.repeat
    else:
        notes, info = L.cut(A.piece, A.start, A.length, mode="melody", part=A.part)
        raw = [n for n in L.piece_notes(A.piece, A.part) if A.start <= n[0] < A.start + A.length]
        t0 = min(n[0] for n in raw)                       # library.cut starts the excerpt at its first note
    t, i = place([n[2] for n in notes], A.gap, A.black)
    left, right = hands(i, A.gap); keys = left + right
    blacks = inner_blacks(left) + inner_blacks(right) if A.black else []
    reach = keys + blacks
    ps = [n[2] + t for n in notes]
    mapped = []
    for j, p in enumerate(ps):
        mapped.append(p if p in reach else nearest(mapped[-1] if mapped else None, p, ps[j + 1] if j + 1 < len(ps) else None, reach))
    moved = sum(k != p for k, p in zip(mapped, ps))
    octaves = sum(k != p and (k - p) % 12 == 0 for k, p in zip(mapped, ps))
    steps = sum(mapped[j + 1] - mapped[j] == ps[j + 1] - ps[j] for j in range(len(ps) - 1))
    out, dropped, shifted, last = [], 0, 0, {}
    for j, ((on, off, _), k) in enumerate(zip(notes, mapped)):
        if k in last and on - last[k][0] < MIN_SAME:
            later = last[k][0] + MIN_SAME
            nxt = notes[j + 1][0] if j + 1 < len(notes) else 1e9
            if later - on <= SHIFT_MAX and later + 0.1 < nxt:
                last[k][1][1] = min(last[k][1][1], later - 0.05)      # the earlier strike lets go first
                on, off, shifted = later, max(off, later + 0.1), shifted + 1
            else:
                dropped += 1
                continue
        n = [on, off, k, "tune"]
        last[k] = (on, n)
        out.append(n)
    fills, chord = 0, []
    if A.fill or A.ending:
        band, comp = band_notes(A.piece, A.part, A.start, A.length, t0, cut)
        harmony = lambda at: (chord_at(comp, at)[0] or chord_at(band, at)[0], chord_at(band, at)[1])     # the chord; the bass note under it
    if A.fill:
        tune = list(out)
        for a, b in zip(tune, tune[1:]):
            if b[0] - a[1] < FILL_REST:
                continue
            step, prev = 0, None
            for bt in beats(band, a[1] + 0.05, b[0] - CLEAR):
                pcs, bass = harmony(bt)
                cands = sorted(k for k in keys if k % 12 in pcs)
                if len([k for k in cands if k in left]) >= 2:
                    cands = [k for k in cands if k in left]
                if not cands:
                    continue
                if step == 0 and bass in {k % 12 for k in cands}:
                    step = [k % 12 for k in cands].index(bass)          # a broken chord starts on the band's bass note when it can
                k = cands[step % len(cands)]; step += 1
                if k == prev and len(cands) > 1:                          # a broken chord moves on, it does not strike one key twice
                    k = cands[step % len(cands)]; step += 1
                if any(n[2] == k and abs(n[0] - bt) < MIN_SAME for n in out):
                    continue
                out.append([bt, min(bt + 0.45, b[0] - 0.05), k, "fill"]); fills += 1; prev = k
    if A.ending:
        fin = max((n for n in out if n[3] == "tune"), key=lambda n: n[0])
        pcs = harmony(fin[0] + 0.3)[0] | harmony(fin[0] + 0.8)[0] | {fin[2] % 12}
        under = {harmony(fin[0] + 0.3)[1], harmony(fin[0] + 0.8)[1]}                 # the bass under the last note
        def triad_on(r):
            third = (r + 4) % 12 if (r + 4) % 12 in pcs or (r + 3) % 12 not in pcs else (r + 3) % 12
            return {r, third, (r + 7) % 12}
        # the chord the band plays there: the last note is its root, its third or its fifth (a verse ends on the third: E over C major)
        root = max(((fin[2] - d) % 12 for d in (0, 4, 3, 7)), key=lambda r: (len(triad_on(r) & pcs), r in under, r == fin[2] % 12))
        triad = triad_on(root)
        end = fin[1] + HOLD; fin[1] = end
        out = [n for n in out if not (n[3] == "fill" and n[0] > fin[0] - MIN_SAME)]
        for five in (left, right):
            cands = [k for k in five if k % 12 in triad and k != fin[2] and not any(n[2] == k and fin[0] - n[0] < MIN_SAME for n in out)]
            for k in (cands if len(cands) <= 2 else [cands[0], cands[-1]]):
                out.append([fin[0], end, k, "ending"]); chord.append(k)
    out.sort(key=lambda n: (n[0], n[2]))
    held = 0
    if A.legato:
        ons = sorted({n[0] for n in out})
        for n in out:
            nxt = next((o for o in ons if o > n[0] + 1e-6), None)
            if nxt is None or nxt - n[1] <= -OVERLAP: continue
            new = nxt + OVERLAP if nxt - n[1] <= LEGATO else nxt - BREATH
            again = next((m[0] for m in out if m[2] == n[2] and m[0] > n[0] + 1e-6), None)      # the same key again: up before that
            if again is not None: new = min(new, again - 0.02)
            if new > n[1] + 1e-6: n[1] = new; held += 1
    title = A.title or L.piece(A.piece).get("title") or A.name.replace("_", " ")
    src = os.path.relpath(os.path.abspath(A.piece), HERE) if os.path.exists(A.piece) else A.piece
    extra = (", the band's chords in the rests" if A.fill else "") + (", ends on a held chord" if A.ending else "") + (", notes held into the next (legato)" if A.legato else "") + (", with its black keys" if blacks and any(n[2] in blacks for n in out) else "") + (f", the chosen stretches {A.repeat} times round" if A.splice else "")
    for side, five in (("left", left), ("right", right)):
        part = [n for n in out if min(five) <= n[2] <= max(five)]
        order = sorted(five, reverse=side == "left")                     # thumb .. pinky (the thumbs are the inner fingers)
        also = []
        for b in sorted({n[2] for n in part if n[2] in blacks}):         # a black key goes to the neighbouring finger that is free around it
            slack = lambda w: min([abs(m[0] - n[0]) for n in part if n[2] == b for m in part if m[2] == w] or [1e9])
            w = max((b + 1, b - 1), key=slack)                           # the finger whose own notes are furthest away in time
            also.append(f"{b}:{order.index(w)}")
            print(f"{side} hand: {note_name(b)} x{sum(n[2] == b for n in part)} with the {('thumb', 'index', 'middle', 'ring', 'pinky')[order.index(w)]} "
                  f"(its own key {note_name(w)} is never struck within {slack(w):.2f} s of it" + ("" if slack(w) >= CROSS else f": LESS than the {CROSS} s the finger needs") + ")")
        rel = f"assets/duets/{A.name}_{side}.mid"
        write_notes(os.path.join(HERE, rel), [dict(on=a, off=b, pitch=k, vel=72 if kind == "tune" else 56) for a, b, k, kind in part])
        side_info = dict(title=title, role="tune, low half" if side == "left" else "tune, high half",
                         version=f"{side} hand: the tune's {'lower' if side == 'left' else 'upper'} five keys {note_name(five[0])}–{note_name(five[-1])}, "
                                 f"{int(A.start // 60)}:{int(A.start % 60):02d}–{int((A.start + A.length) // 60)}:{int((A.start + A.length) % 60):02d}, the other hand plays the rest"
                                 + (f", {A.gap} free key{'s' if A.gap > 1 else ''} between the hands" if A.gap else "") + extra,
                         source=src, part=A.part, start=A.start, length=A.length, transpose=t, gap=A.gap, keys=[note_name(k) for k in keys],
                         n_notes=len(part), n_tune=len(notes), moved=moved, octave=octaves, dropped=dropped, shifted=shifted,
                         fills=sum(n[3] == "fill" for n in part), legato=bool(A.legato), also=also, splice=A.splice, repeat=A.repeat, ending=[note_name(n[2]) for n in part if n[3] == "ending"],
                         exact=round(1 - moved / len(notes), 3), steps=round(steps / (len(ps) - 1), 3))
        if A.private: side_info["private"] = A.private
        with open(os.path.join(HERE, rel[:-4] + ".json"), "w") as fh:
            json.dump(side_info, fh, ensure_ascii=False)
        print(f"{rel}: {len(part)} notes on {' '.join(note_name(k) for k in five)} "
              f"({sum(n[3] == 'tune' for n in part)} tune, {sum(n[3] == 'fill' for n in part)} fill, {sum(n[3] == 'ending' for n in part)} final chord)")
    print(f"tune: {len(notes)} notes, transposed {t:+d}; {len(notes) - moved} keep their own key ({(1 - moved / len(notes)) * 100:.0f} %), "
          f"{moved} moved ({octaves} by an octave, {moved - octaves} to a neighbouring key); {shifted} quick repeats struck "
          f"up to {SHIFT_MAX * 1000:.0f} ms later, {dropped} dropped")
    print(f"steps between notes exact: {steps}/{len(ps) - 1} ({steps / (len(ps) - 1) * 100:.0f} %)")
    if A.fill: print(f"rests filled with the band's chords: {fills} notes")
    if A.legato: print(f"legato: {held} of {len(out)} notes held longer, until the next note starts")
    if A.ending: print(f"final chord: {' '.join(note_name(k) for k in sorted(chord + [fin[2]]))}, held {HOLD} s")


if __name__ == "__main__":
    main()
