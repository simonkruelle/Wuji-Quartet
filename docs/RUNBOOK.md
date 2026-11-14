# Runbook: from the first motion to the full piece

**Status, 14 Nov 2026: nothing here has run on a real hand.** Every script passes its dry run against a fake hand (a 30 ms lag model). Expect to fix things on the first real run.

Before you start: [RDK_X5_SETUP.md](RDK_X5_SETUP.md) is done and `./wq hand python scripts/hand_info.py` shows 20 of 20 joints.

Commands are written for the RDK X5. With a native install (Mac, Linux laptop) drop the `./wq hand` prefix.

| Step | Goal | Hand is | Time |
|---|---|---|---|
| 0 | Dry run, no hardware | off | 1 min |
| 1 | How stiff are the real servos? | in the **air** | 10 min |
| 2 | Mount the hand, measure the mount | over the keys, off | 30 min |
| 3 | Plan for our mount and stiffness | | 1 min |
| 4 | Right key? How deep? | over the keys | 10 min |
| 5 | Play: one finger slow → all slow → full tempo | over the keys | 15 min |
| 6 | Optimise for our setup | | 15 to 30 min |

## Safety

- **Ctrl-C stops the stream and disables the hand** in every script. Keep one person on the keyboard of the robot computer.
- The joints go limp when disabled: the hand drops onto the keys. Nothing can break at our forces, but keep fingers and cables out from under it.
- Every script ramps from the current pose to its start pose over 2 seconds.
- Current limit: scripts default to 0.8 A (MIT mode). Wuji suggests 0.5 A for first tests and 1.5 A for gentle holding. Start with `--effort 0.5`.
- If the cable or the program drops out, the hand stops its motors and reports a fault. It does not resume by itself.
- Never plug or unplug the power or network cable while the hand is powered.
- There is no hardware emergency stop on this hand. Software stop only; the wall plug is the last resort.

## 0 · Dry run

```bash
./wq check
./wq sim python scripts/play_on_hand.py plans/k265_fixed/theme_q_1khz.npz --dry-run
```

## 1 · Stiffness (hand in the air, away from the keys)

The simulation only plays well if the real finger servos are at least as stiff as "5×" in our model. This is the biggest open risk, so measure it first. The script makes small steps on six joints, fingers lifting, and finds the simulated stiffness that matches.

```bash
./wq hand python scripts/sysid_step.py plans/baseline_k265_gain5/theme_q_1khz.npz --effort 0.5
./wq hand python scripts/sysid_step.py plans/baseline_k265_gain5/theme_q_1khz.npz --mode position      # only if the firmware supports Position mode
```

It prints `best match: gain xG`. Call that number **G**.

| G | Meaning | Do |
|---|---|---|
| 5 or more | as planned | continue |
| 2.5 to 5 | trills and the pinky stretch will drop out | raise `--kp` (6, then 10) and repeat; or Position mode |
| below 2.5 | the plan will miss most notes | same, and plan at half tempo (`--tempo 0.5`) |

## 2 · Mount and measure

<img src="setup.png" width="760" alt="Mount: flange 10 cm above the white keys, 7 cm in front of the keys, fingertips 25 degrees down">

| Target | Value | Tolerance before notes are lost |
|---|---|---|
| Approach | from the player's side, right hand, thumb toward the bass | |
| Flange centre above the white key tops | 10 cm | about ±2 mm |
| Flange centre in front of the white key fronts | 7 cm | |
| Sideways | above D5 | ±3 mm gives wrong keys |
| Pitch, fingertips down | 25° | ±3° breaks the plan |

The bracket must be rigid and adjustable in height and pitch. Clamp it to the table or the stand, not to the keyboard's lid. Flange drawings and STEP files: `assets/wuji-description/hand2/hand2_2/attachment/`.

Measure what you actually built, in millimetres and degrees. You need four numbers: height, distance in front of the key fronts, pitch, sideways offset from D5.

## 3 · Plan for our mount

```bash
./wq sim python scripts/make_theme.py --gain G --out out/hw \
    --mount-z 0.100 --mount-x 0.220 --theta 25 --mount-dy -0.0235
```

- `--mount-z`: flange height above the white keys, in metres.
- `--mount-x`: 0.15 + distance in front of the key fronts, in metres (7 cm → 0.22).
- `--mount-dy`: sideways offset from E5, in metres, negative toward the bass (−0.0235 = above D5).
- Hand 2.1 instead of 2.2: add `--rev hand2_1`.

Takes about 30 seconds and prints how many of the 80 notes the simulation hits.

## 4 · Key calibration

Each finger slowly presses its home key until the piano reports a note. This tells us whether it is the right key and how deep to press.

```bash
ls /dev/snd/                                         # midiC1D0 or similar = the piano
./wq hand python scripts/calibrate_keys.py out/hw/theme_q_1khz.npz --midi-dev /dev/snd/midiC1D0 --effort 0.5
./wq sim  python scripts/make_theme.py --gain G --out out/hw_cal --calib out/hw/calib.json   # plus the same mount flags as step 3
```

No MIDI: add `--manual` and press Enter when you hear the note.
Wrong key reported: shift the hand sideways and repeat. Do not fix it in software.

## 5 · Play

```bash
./wq hand python scripts/play_on_hand.py out/hw_cal/theme_q_1khz.npz --tempo 0.5 --fingers index --effort 0.5
./wq hand python scripts/play_on_hand.py out/hw_cal/theme_q_1khz.npz --tempo 0.5 --midi-dev /dev/snd/midiC1D0
./wq hand python scripts/play_on_hand.py out/hw_cal/theme_q_1khz.npz --midi-dev /dev/snd/midiC1D0
```

With `--midi-dev` the script prints hit, missed and wrong notes after the run. Without MIDI, record with any app and score the file:

```bash
./wq sim python scripts/score_midi.py recording.mid out/hw_cal/theme_q_1khz.npz
```

Each run writes a log (`hw_<date>_<time>.npz`: commanded and measured joint angles at 1 kHz) next to the plan. Commit the interesting ones: they are how the simulation gets corrected.

## 6 · Optimise for our setup

On a laptop or Henry's machine, not on the RDK X5 (its small processor would need hours):

```bash
./wq sim python scripts/sbto_piano.py --piece k265 --wrist fixed --gain G \
    --mount 0.22,0.10,25,-0.0235 --out out/sbto_hw --workers 8
```

`--mount` is `x,z,pitch,dy` with the same meaning as in step 3. 15 to 30 minutes. Then copy `out/sbto_hw` to the robot computer (commit it under `plans/`, or `rsync`) and play it as in step 5.

## If something goes wrong

| What you see | Likely cause | Do |
|---|---|---|
| `no Wuji Hand 2 found` | network | `bash scripts/hand_net.sh`; cable; power light |
| `x/20 joints online, refusing to move` | a joint did not start | power-cycle the hand; Wuji troubleshooting page |
| `enable timeout` | a joint reports an error | `./wq hand python scripts/hand_info.py`; Wuji troubleshooting page |
| `this plan moves the wrist (needs an arm)` | you picked `plans/furelise_plan` or `plans/k265_human` | use `plans/k265_fixed`, or add `--fingers-only` to see the fingers alone |
| `command faster than 35 rad/s: refusing` | a damaged or hand-edited plan | regenerate it |
| many "skipped" frames | robot computer too busy | close other programs; do not optimise on it while playing |
| notes too quiet or missing at the right key | not deep enough | step 4 again; or raise the hand's stiffness |
| wrong neighbouring keys | sideways error | move the hand, then step 4 |
| everything late by a constant amount | servo lag differs from the model | tell Simon: the per-finger command lead is calibrated in simulation |

## What the simulation does not know yet

| Unknown | Why it matters |
|---|---|
| Real servo stiffness | decides whether fast notes play at all (step 1) |
| Real key weight and where the piano triggers the note | the model uses a generic key; real sensors usually fire before the key bottom, which helps |
| Bracket stiffness | any sway is a height error |
| Position mode behaviour | untested; MIT mode is the default |
