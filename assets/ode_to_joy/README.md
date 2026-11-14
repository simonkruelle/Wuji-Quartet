# Ode to Joy (Beethoven, Symphony No. 9, public domain)

`ode_to_joy.mid` is written by `scripts/make_ode_to_joy.py`: the melody in C major, 62 notes, 16 bars, 108 beats per minute (35.6 s).

It sits in the five-finger position **C5 D5 E5 F5 G5**: thumb, index, middle, ring, pinky, one finger per key. The hand never moves.
The melody's single low G (bar 12) is out of reach and is played one octave up.

To play at middle C, mount the hand one octave lower (16.5 cm to the left). The plan is the same.

## Duet: a person plays the left hand

The robot keeps a fixed tempo and cannot listen, so the person follows the robot. Slower: `play_on_hand.py … --tempo 0.8`.

Simple left hand, one chord per half bar unless one is given for the whole bar:

| Bars | 1 | 2 | 3 | 4 | 5 | 6 | 7 | 8 |
|---|---|---|---|---|---|---|---|---|
| Chord | C | G | C | G | C | G | C | G · C |

| Bars | 9 | 10 | 11 | 12 | 13 | 14 | 15 | 16 |
|---|---|---|---|---|---|---|---|---|
| Chord | G · C | G · C | G · C | C · G | C | G | C | G · C |
