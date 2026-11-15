"""One hand, simplified: fits any melody into the keys one robot hand reaches while its wrist stays in place.

The real hand has no arm yet, so it plays five neighbouring keys (six where the thumb also takes the key below, as in
the Canon plan). A song with a wider melody is fitted into such a hand position:

  1. melody      the highest note of every chord, from middle C up (the right hand's line)
  2. tempo       optionally slower, so fast passages and singers keep up
  3. thinning    notes closer than the hand can play are dropped, short ones first (ornaments go, the tune stays)
  4. keys        every step between two notes stays exact inside a phrase (a tune is recognised by its steps, not by
                 its pitch names); where a phrase does not fit the hand, the tune moves to another key, preferably
                 where a phrase starts. One shortest-path search per hand position. (fold=True: the first version,
                 which kept pitch names and folded octaves: it broke up to 90 % of the steps.)
  5. repeats     a key struck again too soon is dropped
  6. chords      optional (at_once 2 or 3): under each melody note, the keys of the hand that carry a note the
                 pianist struck at the same moment (either hand), so the hand plays two or three keys at once.
                 Only exact pitch names, never two keys a step apart, one key per finger, the bass note first.

The result says how faithful it is: how many notes kept their pitch name, how many kept their direction.
Nothing here needs MuJoCo or numpy.
"""
import bisect
import math

MIN_GAP = 0.15        # s between two notes: Korobeiniki, the fastest optimised plan, has 150 ms
MIN_SAME = 0.25       # s between two strikes of the same key: Jingle Bells' repeated E (250 ms) on the real hand
CHORD = 0.04          # onsets closer than this form one chord
HARMONY_WINDOW = 0.06  # s: the pianist's notes this close to a melody note count as struck with it (hands are never exactly together)
W_PITCH = 4.0         # cost per semitone a note is moved away from its pitch name
W_FLAT = 1.5          # the tune moves, the hand repeats a key
W_TURN = 2.5          # the tune goes up, the hand goes down (or the other way)
W_SPLIT = 3.0         # the tune repeats a note, the hand plays two different keys
W_SIZE = 0.1          # per semitone the step differs in size (up to a fifth)
W_STRETCH = 0.3       # a key the thumb reaches by stretching (the "also" keys)
W_SWITCH = 50.0       # one finger moving to its other key in less than SWITCH_S: practically forbidden
SWITCH_S = 0.3        # s between onsets when one finger changes key (lift, move sideways, press)
MOVE_S = 0.1          # s a finger needs between releasing one key and pressing its other key
UNPROVEN = 0.35       # per note: a hand position no shared plan has used yet
C_PHRASE = 1.0        # exact mode: the tune moves to a new key where a phrase starts
C_BREAK = 3.0         # ... or in the middle of a phrase (this breaks a step the listener hears)
OCTAVE = 0.5          # factor when that move is a whole octave (the tune keeps its key)
PHRASE_GAP = 0.25     # s of rest that ends a phrase; so does a note held 1.75 times the usual length
REGISTER = 0.05       # per note and semitone the hand sits more than a fourth away from the melody's middle
WHITE = [0, 2, 4, 5, 7, 9, 11]


def melody(notes, split=60):
    """[[on, off, pitch]] -> the top line: highest note of each chord from `split` up, notes never overlapping."""
    win = [list(n) for n in notes if n[2] >= split] or [list(n) for n in notes]
    win.sort(key=lambda n: (n[0], -n[2]))
    top, i = [], 0
    while i < len(win):
        j = i
        while j + 1 < len(win) and win[j + 1][0] - win[i][0] < CHORD:
            j += 1
        top.append(max(win[i:j + 1], key=lambda n: n[2]))
        i = j + 1
    for a, b in zip(top, top[1:]):
        a[1] = min(a[1], b[0] - 0.01)
    return [n for n in top if n[1] - n[0] >= 0.03]


def thin(mel, gap=MIN_GAP):
    """Keep notes at least `gap` apart, long notes first: the notes that carry the tune survive, quick ones go."""
    nxt = [mel[i + 1][0] if i + 1 < len(mel) else mel[i][1] for i in range(len(mel))]
    order = sorted(range(len(mel)), key=lambda i: (-(min(nxt[i], mel[i][1] + 2.0) - mel[i][0]), mel[i][0]))
    kept_on, kept = [], []
    for i in order:
        on = mel[i][0]
        k = bisect.bisect_left(kept_on, on)
        if (k > 0 and on - kept_on[k - 1] < gap) or (k < len(kept_on) and kept_on[k] - on < gap):
            continue
        kept_on.insert(k, on)
        kept.insert(k, i)
    return [mel[i] for i in kept]


def _pc_dist(a, b):
    d = (a - b) % 12
    return min(d, 12 - d)


def _sign(x):
    return (x > 0) - (x < 0)


def assign(pitches, gaps, keys, stretch, t, finger=None, iois=None):
    """Shortest path through (note, key): which of `keys` plays each pitch (transposed by t). -> (cost, keys).
    finger: key -> finger; iois: seconds since the previous onset (a finger needs SWITCH_S to change key)."""
    K = len(keys)
    emit = [[W_PITCH * _pc_dist(p + t, k) + (W_STRETCH if k in stretch else 0.0) for k in keys] for p in pitches]
    cost = emit[0][:]
    back = []
    for i in range(1, len(pitches)):
        I = pitches[i] - pitches[i - 1]
        sI, aI = _sign(I), min(abs(I), 7)
        w = 0.5 if gaps[i] > 0.6 else 1.0            # after a pause the tune may start anywhere
        new, bk = [0.0] * K, [0] * K
        for b in range(K):
            best, arg = None, 0
            for a in range(K):
                J = keys[b] - keys[a]
                sJ = _sign(J)
                if sI == sJ:
                    c = W_SIZE * abs(aI - abs(J))
                elif sI == 0:
                    c = W_SPLIT
                elif sJ == 0:
                    c = W_FLAT
                else:
                    c = W_TURN
                if finger and a != b and finger[keys[a]] == finger[keys[b]] and iois[i] < SWITCH_S:
                    c += W_SWITCH
                v = cost[a] + w * c
                if best is None or v < best:
                    best, arg = v, a
            new[b], bk[b] = best + emit[i][b], arg
        cost = new
        back.append(bk)
    b = min(range(K), key=lambda k: cost[k])
    total = cost[b]
    path = [b]
    for bk in reversed(back):
        b = bk[b]
        path.append(b)
    path.reverse()
    return total, [keys[j] for j in path]


def hand_shapes(proven, centre):
    """Candidate hand positions: the ones shared plans use (proven), plus five neighbouring white keys of every
    pattern (C D E F G, D E F G A, ...), each placed in the octave nearest the melody."""
    out = [dict(p, proven=True) for p in proven]
    seen = {tuple(sorted(p["keys"])) for p in out}
    for start_pc in WHITE:
        best = None
        for octave in range(3, 7):
            lo = 12 * (octave + 1) + start_pc
            whites = [k for k in range(lo, lo + 12) if k % 12 in WHITE][:5]
            mid = whites[2]
            if 55 <= whites[0] and whites[-1] <= 88 and (best is None or abs(mid - centre) < abs(best[2] - centre)):
                best = whites
        if best and tuple(best) not in seen:
            seen.add(tuple(best))
            out.append(dict(keys=best, five=best, also=[], stretch=[], proven=False, source="five neighbouring white keys"))
    return out


def phrase_starts(mel):
    """True where a phrase begins: after a rest, or after a note held clearly longer than the others."""
    iois = sorted(b[0] - a[0] for a, b in zip(mel, mel[1:])) or [0.5]
    med = iois[len(iois) // 2]
    return [True] + [(b[0] - a[1] >= PHRASE_GAP) or (b[0] - a[0] >= 1.75 * med) for a, b in zip(mel, mel[1:])]


def assign_exact(pitches, starts, keys, finger, iois):
    """Every note on the key `pitch + T`, so steps inside a stretch of equal T are exact. Shortest path over T:
    changing T costs C_PHRASE at a phrase start, C_BREAK inside a phrase (half that for a whole octave).
    -> (cost, [T per note])."""
    K = set(keys)
    Ts = sorted({k - p for k in keys for p in pitches})
    INF = float("inf")
    cost = [0.0005 * abs(T) if pitches[0] + T in K else INF for T in Ts]
    back = []
    for i in range(1, len(pitches)):
        c = C_PHRASE if starts[i] else C_BREAK
        best_all = min(range(len(Ts)), key=lambda j: cost[j])
        best_res = {}
        for j, T in enumerate(Ts):
            r = T % 12
            if cost[j] < INF and (r not in best_res or cost[j] < cost[best_res[r]]):
                best_res[r] = j
        new, bk = [INF] * len(Ts), [0] * len(Ts)
        for j, T in enumerate(Ts):
            k = pitches[i] + T
            if k not in K:
                continue
            v, b = cost[j], j                                    # stay on the same T: the step is exact
            if v < INF:
                kp = pitches[i - 1] + T
                if kp != k and finger[kp] == finger[k] and iois[i] < SWITCH_S:
                    v += W_SWITCH
            jr = best_res.get(T % 12)
            if jr is not None and jr != j and cost[jr] + OCTAVE * c < v:
                v, b = cost[jr] + OCTAVE * c, jr
            if best_all != j and cost[best_all] + c < v:
                v, b = cost[best_all] + c, best_all
            new[j], bk[j] = v + 0.0005 * abs(T), b
        cost = new
        back.append(bk)
    j = min(range(len(Ts)), key=lambda j: cost[j])
    total, path = cost[j], [j]
    for bk in reversed(back):
        j = bk[j]
        path.append(j)
    path.reverse()
    return total, [Ts[j] for j in path]


def finger_of(shape):
    """key -> finger (0 thumb .. 4 pinky) of a hand position."""
    f = {int(k): i for i, k in enumerate(shape["five"])}
    for a in shape.get("also") or []:
        k, i = a.split(":")
        f[int(k)] = int(i)
    return f


def harmony(out, notes, t, shape, at_once):
    """Add chord notes under the melody. out: melody rows [on, off, key, pitch, original onset, T]; notes: the original
    window; t: the transposition, or None to take each row's own T. -> list of extra [on, off, key]."""
    if at_once <= 1:
        return []
    finger = finger_of(shape)
    keys = sorted(finger)
    src = sorted(notes, key=lambda n: n[0])
    starts = [n[0] for n in src]
    # for every melody note: when each finger is next needed by the melody
    nxt = [[math.inf] * 5 for _ in out]
    later = [math.inf] * 5
    for i in range(len(out) - 1, -1, -1):
        nxt[i] = later[:]
        later[finger[out[i][2]]] = out[i][0]
    last_strike, free_at, last_key, extra = {}, [-math.inf] * 5, [None] * 5, []
    for i, m in enumerate(out):
        on, off, mk = m[0], m[1], m[2]
        lo, hi = bisect.bisect_left(starts, m[4] - HARMONY_WINDOW), bisect.bisect_right(starts, m[4] + HARMONY_WINDOW)
        group = src[lo:hi]
        chosen = []
        if group:
            tt = m[5] if t is None else t
            pcs = {(n[2] + tt) % 12 for n in group}
            bass = (min(n[2] for n in group) + tt) % 12
            cand = sorted((k for k in keys if k < mk and k % 12 in pcs), key=lambda k: (k % 12 != bass, k))
            for k in cand:
                if len(chosen) + 1 >= at_once:
                    break
                f = finger[k]
                end = min(off, nxt[i][f] - 0.1)
                if (f == finger[mk] or any(finger[c[2]] == f or abs(c[2] - k) <= 2 for c in chosen) or abs(mk - k) <= 2
                        or on - last_strike.get(k, -math.inf) < MIN_SAME or (last_key[f] != k and on - free_at[f] < 0.08) or end - on < 0.08
                        or nxt[i][f] - on < MIN_SAME and any(o[2] == k for o in out[i + 1:i + 2])):
                    continue
                chosen.append([on, end, k])
        for c in chosen + [[on, off, mk]]:
            last_strike[c[2]] = on
            free_at[finger[c[2]]], last_key[finger[c[2]]] = c[1], c[2]
        extra += chosen
    return extra


def fit(notes, proven=(), tempo=1.0, split=60, side="right", at_once=1, harmony_src=None, only=None, fold=False):
    """notes [[on, off, pitch]] -> dict(notes=..., hand=..., stats). `proven`: hand positions of shared plans, as
    dict(keys, five, also, stretch, source). at_once: at most this many keys at the same time (1 = melody only).
    harmony_src: the notes chords are taken from (default: `notes`; for a band, every instrument).
    only: one of `proven`: use exactly this hand position (e.g. the one the real hand already plays in).
    fold: the old way (keep pitch names, fold octaves); the default keeps the steps between notes exact inside each
    phrase and moves the tune to a new key between phrases, which keeps a tune recognisable."""
    mel = melody(notes, split)
    if len(mel) < 2:
        raise ValueError("fewer than two melody notes in this window")
    tempo = min(max(float(tempo), 0.25), 1.5)
    at_once = int(min(max(int(at_once), 1), 3))
    t0 = mel[0][0]
    mel = [[(n[0] - t0) / tempo, (n[1] - t0) / tempo, n[2], n[0]] for n in mel]
    n_mel = len(mel)
    mel = thin(mel)
    pitches = [n[2] for n in mel]
    gaps = [0.0] + [b[0] - a[1] for a, b in zip(mel, mel[1:])]
    iois = [9.0] + [b[0] - a[0] for a, b in zip(mel, mel[1:])]
    starts = phrase_starts(mel)
    centre = sorted(pitches)[len(pitches) // 2]
    best = None
    for shape in ([dict(only, proven=True)] if only else hand_shapes(proven, centre)):
        keys = sorted(shape["keys"])
        if fold:
            for t in range(-6, 6):
                c, ks = assign(pitches, gaps, keys, set(shape.get("stretch", [])), t, finger_of(shape), iois)
                mid = sum(keys) / len(keys)
                score = (c / len(pitches) + (0.0 if shape["proven"] else UNPROVEN) + REGISTER * max(0.0, abs(mid - centre) - 5) + 0.002 * abs(t))
                if best is None or score < best[0]:
                    best = (score, ks, [t] * len(ks), shape)
        else:
            c, Ts = assign_exact(pitches, starts, keys, finger_of(shape), iois)
            score = c / len(pitches) + (0.0 if shape["proven"] else UNPROVEN * 0.4)
            if best is None or score < best[0]:
                best = (score, [p + T for p, T in zip(pitches, Ts)], Ts, shape)
    _, ks, Ts, shape = best
    # a key struck again too soon is dropped
    out = []
    for n, k, T in zip(mel, ks, Ts):
        if out and out[-1][2] == k and n[0] - out[-1][0] < MIN_SAME:
            continue
        out.append([n[0], n[1], k, n[2], n[3], T])
    fing = finger_of(shape)
    for a, b in zip(out, out[1:]):
        same_finger_other_key = a[2] != b[2] and fing[a[2]] == fing[b[2]]
        a[1] = min(a[1], b[0] - (MOVE_S if same_finger_other_key else 0.02))
    for n in out:
        n[1] = max(n[1], n[0] + 0.08)
    extra = harmony(out, harmony_src if harmony_src is not None else notes, None, shape, at_once)
    t = out[0][5]
    exact = sum(1 for n in out if _pc_dist(n[3] + t, n[2]) == 0)
    steps = sum(1 for a, b in zip(out, out[1:]) if b[2] - a[2] == b[3] - a[3])
    same_dir = sum(1 for a, b in zip(out, out[1:]) if _sign(b[3] - a[3]) == _sign(b[2] - a[2]))
    jumps = sum(1 for a, b in zip(out, out[1:]) if a[5] != b[5])
    used = sorted({n[2] for n in out})
    return dict(
        notes=sorted([[round(n[0], 4), round(n[1], 4), n[2]] for n in out] + [[round(e[0], 4), round(e[1], 4), e[2]] for e in extra]),
        at_once=at_once, chords=len({e[0] for e in extra}), added=len(extra),
        hand=dict(keys=sorted(shape["keys"]), five=shape["five"], also=shape["also"], proven=shape["proven"], source=shape.get("source", "")),
        transpose=t, used_keys=sorted(set(used) | {e[2] for e in extra}), n_melody=n_mel, n_notes=len(out) + len(extra), dropped=n_mel - len(out),
        exact=round(exact / len(out), 3), steps=round(steps / max(1, len(out) - 1), 3), jumps=jumps, phrases=sum(starts),
        direction=round(same_dir / max(1, len(out) - 1), 3), tempo=tempo, side=side)
