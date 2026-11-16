# The studio

One window for the whole project, in the browser. It starts the same scripts you would type in a terminal, so nothing works only here.

```bash
python gui/app.py        # opens http://127.0.0.1:8770
./wq gui                 # the same inside the Docker image (Linux: can drive the hand; Mac: simulation only)
```

From another of your devices (MacBook, phone) over Tailscale:

```bash
python gui/app.py --tailscale    # prints a link with a token: open that link on the other device
```

- It listens on this computer and on its Tailscale address only: the Wi-Fi it is on cannot reach it.
- The other device is only the screen. The search, the camera and the connection to the hand all run where the studio runs.

Starting it needs Python only. Pages that need more say so: MuJoCo to optimise, `wuji-sdk` to drive a hand from this computer, `pip install -r requirements-camera.txt` for the camera.

**Status, 16 Nov 2026: Play has driven the real hands through the robot computer, one hand and two hands (five pieces with both hands on 15 Nov). Teach has run lessons on the real right hand (Ode to Joy, 16 Nov, current limit 1.0 A down to 0.3 A). Camera has not moved the real hand from the studio yet.**

## Pages

| Page | What you do there |
|---|---|
| **Library** | pieces on the left, the chosen one on the right: listen, its plans (▶ Play), Retarget ›. Tabs: Ours · Duets · Christmas (14 songs, `assets/songs/`) · Pianists (the 153 FürElise performances) · Mine (what you imported or cut on this computer, in `assets/library/`; the tab appears once there is something). **+ Import a MIDI file** under the list |
| **3D view** | any plan, or two plans for two hands (pick it at the top, or **3D** next to ▶ Play in the Library): the robot hand(s) in simulation over the keyboard (drag to turn, scroll to zoom, 25-100 % speed, sound), the SBTO search that made the plan (cost per 0.5 s step before/after, notes before → after on ten setups, or which plan's search it reuses), and where the hand sits and which finger plays which key. When the piece comes from a FürElise recording whose hands are prepared (`assets/furelise/<id>/hands.npz`; today K.265 = piece 15), the pianist's two hands play on the same keyboard and clock (Pianist / Robot / Both) with a wrist chart. The robot takes the notes, their timing and (wrist "like the pianist") the wrist path from the pianist; SBTO finds the finger motion. The server simulates a plan once (`scripts/plan_view.py`, 3-6 s) and keeps it in `out/gui/views/` |
| **Retarget** | piece, hand (**Both hands** for a two-hand piece: the melody on the right hand and the accompaniment on the left, each at its own place, two runs from one Start, then ▶ Play both hands; also from Library › Duets › Retarget both hands), wrist; then Reuse / Draft / Standard / Fine, with the time before you start. Everything else under More. While a search runs, its cost per step (before / after the tries) is drawn under the runs |
| **Hands** | both real hands side by side: does each answer (pinged from the robot computer every 10 s), through which port, serial number, firmware, joints online. The robot computer has one Ethernet port: the second hand goes through a USB-Ethernet adapter in a USB-A port (not USB-C), and **Set up the adapter** routes it (`scripts/hand_adapter.sh`; again after a reboot or replug). **Move one finger** per hand (index finger 9° and back, 0.5 A) as the first motion. *Ready for two hands?* lists what is left before Play › Two hands. *Where the hands go, song by song* groups every playable plan by where its hand sits (songs on one line need no move), with the move from the Ode to Joy position |
| **Play** | One hand · Two hands · Teach (one phrase or all, slower, several times). **Where the hand goes** (one or two hands): the keyboard from above as you stand in front of it, the flange centre (sideways, cm in front of the key fronts, cm above the keys, tilt), each finger's key, and the fingertips at the plan's first frame, the start pose the hand moves to before it plays (mm above the key under each tip, mm behind its front edge; `gui/startpose.py`, MuJoCo), plus the move from the Ode to Joy position. Notes fall onto a keyboard in step with the hand; **Notes \| 3D** shows the plan's hand in 3D instead, following the run on the same clock |
| **Camera** | the hand follows your hand in front of the webcam (Sebas's tracking) |
| **Settings** | which hand, the robot computer, default current limits |

The hand (fake, this computer, robot computer) is chosen at the top right and holds for every page.

With a real hand chosen, a band over the page says whether it is there:

| Band | Means |
|---|---|
| green, **Hand connected** | the hand answers (the robot computer pings it every 10 s while a page is open; it never sends the hand a command) |
| red, **Hand not found** | the robot computer answers, the hand does not: power, network cable, eth0 address (`bash scripts/hand_net.sh` there) |
| red, **Robot computer not reachable** | SSH to the robot computer fails: is it on, and on Tailscale? |
| grey | not checked yet. **Check now** checks at once; for the hand on this computer it runs Find the hand (reads only), since a home Wi-Fi on 192.168.1.x could answer a ping in the hand's place |
| blue, **Real hand moving** | a job is driving the hand; Stop is the red button at the top right |

Settings › Find the hand adds the serial number and how many of the 20 joints are online.

### Any song on one hand: "One hand, simplified"

The hand has no arm yet, so its wrist stays in place and it reaches five neighbouring keys (six where the thumb also
takes the key below, as for Pachelbel's Canon). Most songs use more. Library › a FürElise piece (or any piece that is
too wide, such as an imported MIDI file) › choose where to start, 10/20/40 s or to the end, and a version:

| Version | What you get | Plays on |
|---|---|---|
| **One hand, simplified** | the tune, fitted into one hand position | the real hand (wrist fixed) |
| Melody | the top line as played (highest note of each chord from middle C up) | simulation: the wrist has to move |
| All notes | both hands | simulation: the wrist has to move |

How the simplified version is made (`gui/simplify.py`):

1. **Melody:** the highest note of every chord, from middle C up.
2. **Tempo:** optional, 75 % or 50 %.
3. **Thinning:** notes closer than 150 ms are left out, short ones first. Ornaments go; the tune stays. 150 ms is Korobeiniki, the fastest optimised plan.
4. **Keys:** inside a phrase, every step between two notes stays exact: a tune is recognised by its steps, not by its pitch names.
   - Where a phrase does not fit the five keys, the tune moves to another key, preferably where a phrase starts. The preview says how often.
   - The first version kept pitch names and folded notes by octaves. On the real hand, 15 Nov, Fly Me to the Moon and Stille Nacht were not recognisable that way: it kept only 39 % and 64 % of their steps.
   - A note the hand cannot reach takes the nearest key that still goes up or down as the tune does.
   - Hand positions of shared plans come first, so Reuse works and the result needs no search.
5. **Repeats:** a key struck again within 250 ms is left out. 250 ms is Jingle Bells' repeated E.
6. **One finger, two keys:** where the thumb owns two keys, it changes key only with 0.3 s between notes and lets go 0.1 s early.
7. **Chords (At once: up to 2 or 3):** pianists strike two to four notes together.
   - Under each melody note go the hand's keys that carry a note the pianist struck at the same moment, with either hand.
   - Exact pitch names only, the bass note first, never two keys a step apart, one key per finger.
   - The melody stays on top.

The page shows the result before you save it: notes, keys, how many keep their pitch, how many were too fast. Listen plays exactly that version. **Make it › Retarget** saves it to `assets/library/` and opens Retarget, with the wrist fixed and Reuse ready.

Tested with the fake hand:

| Piece | Excerpt | Result |
|---|---|---|
| Mozart K.265, the theme | 0:00, 20 s | 40 notes on G4–E5, 4 repeats too fast (first version) |
| Chopin Nocturne Op. 27 No. 2 | 0:30, 40 s, 75 % | 112 notes. Reuse: 24 s; 94–106 of 112 on the training setups; played on the fake hand, Stop confirmed (first version) |

Chords, Reuse only (no search), simulation on the five training setups and five unseen ones:

| Excerpt | Notes | Training | Unseen | Wrong keys |
|---|:--:|:--:|:--:|:--:|
| K.265 theme, one key | 40 | 35–40 | 39–40 | 0 |
| K.265 theme, up to 2 (19 chords) | 59 | 45–59 | 57–59 | 0 |
| Clair de Lune from 1:00, one key | 35 | 29–34 | 29–34 | 0–1 |
| Clair de Lune from 1:00, up to 3 (21 chords) | 60 | 49–56 | 51–56 | 0–4 |

A checker over eight pieces × three settings found no finger asked to be in two places and no key struck again too soon.

### Christmas songs

Fourteen songs, each verse 1 as a hymnbook setting: the tune is part 1 ("Melodie"), the setting's other parts accompany it, and the lyrics' first line shows under the title.
- **Sources:** CC0 settings from Wikimedia Commons and public-domain files from the Open Hymnal. Every melody is public domain; the list with links is in [assets/songs/README.md](../assets/songs/README.md).
- **One hand, simplified, Like Ode (real hand):** 77–89 % of each tune's steps stay exact; the tune moves key 3–10 times per verse.
- **Tested:**
  - Stille Nacht, Kling Glöckchen and Fly Me to the Moon on the Ode position, one key at a time: 39, 48 and 52 notes, all of them on all ten setups (Reuse).
  - Stille Nacht: "Stille Nacht, heilige Nacht" is played on exactly its notes (F G F D F G F D). Later phrases keep their steps but start on other keys.
  - The Open Hymnal files of Stille Nacht and O Come All Ye Faithful open with a 6 s and an 8 s organ intro; the song files start after it.

### Pop songs: MIDI files of a whole band

A MIDI file of a pop song (from the Lakh MIDI dataset, a MIDI shop, or a digital piano) usually holds a whole band.
**+ Import a MIDI file**, then in the one-hand panel:

- **Tune:** which instrument plays the tune. The studio guesses, marked ♪.
  - The guess favours a part that plays one note at a time, moves mostly by step, lasts most of the song and sits in the singing range. A name like "vocal" or "melody" counts extra.
  - Listen tells you whether it is right.
- **Drums** (MIDI channel 10) are always left out.
- **Chords** under the tune come from every instrument that strikes a note at that moment.

Imports and cut parts live in `assets/library/`, which git ignores: someone else's arrangement of a song under copyright stays on your computer.

Tested: Fly Me to the Moon, Sinatra arrangement from the Lakh MIDI dataset (14 instruments, one track).

| Step | Result |
|---|---|
| Tune guess | the sung tune, on channel 16 ("guitar" sound, 122 notes) |
| 40 s from 0:12, up to 3 at once | 68 notes, 14 chords (first version) |
| Reuse | 66–67 of 68 on four training setups, 50 on one; 62–67 unseen; 1–4 wrong keys |
| Fake hand | Play and Stop confirmed |

**Hand: Best fit or Like Ode (real hand).**
- **Best fit** may choose a position the real hand has never played in (Fly Me to the Moon: G4–E5, with the thumb also on G4). The hand then has to be moved.
- **Like Ode (real hand)** keeps C5–G5, where the real hand already played Ode to Joy, Jingle Bells and Saints.

Fly Me to the Moon on C5–G5, 40 s from 0:12, one key at a time:

| Measure | Result |
|---|---|
| Notes | 52 |
| Steps between notes kept exactly | 65 %, with 18 key moves; Best fit 71 % |
| Reuse | 52/52, 0 wrong on all ten setups |
| Real hand, 15 Nov | the first version was not recognisable; this version not played yet |

The Play page shows where each plan needs the hand (its middle finger's key) and warns when that is not where the hand plays Ode to Joy.

## How detailed is the search

| Level | Tries per round × rounds | Estimate for Ode to Joy, 62 notes, 10 processes |
|---|:--:|:--:|
| Reuse | no search: takes over what the search learned on Ode to Joy, per finger | 17 s |
| Draft | 24 × 3 | 4.5 min |
| Standard | 48 × 6 (every optimised plan in this repo) | 16 min |
| Fine | 96 × 8 | 42 min |
| Custom | your numbers, plus the knot spacing of a moving wrist | shown before you start |

The estimate starts from the reference computer (an 8-core desktop) and uses this computer's own speed after the first search here. Measured: estimate 53 s, run 38 s (Saints, 16 × 1); the committed Ode run of Standard size took 17 min.

## Which hand

Chosen at the top right.


| Choice | What moves | Needs |
|---|---|---|
| **Fake hand** | nothing. Same playback at 1000 commands per second, sound from the browser | nothing |
| **Hand on this computer** | a Wuji Hand 2 on this computer's network port | `wuji-sdk` here |
| **Hand on the robot computer** | a hand on another computer, through SSH | Settings: address, folder, Python there; key login without a password |

With a real hand the top bar turns red and every start asks first.

## What the studio does for safety

- **Stop** is the red button in the top bar. It sends one Ctrl-C to the playing script, which switches the hand off and confirms it.
- A run counts as finished only after `hand switched off: confirmed`. If that line is missing, the page says so and offers **Switch the hand off**.
- Current limit: 1.5 A at most, here and again in `scripts/wuji_hw.py`.
- One hand run at a time. A second start is refused.
- A real hand needs a yes in a dialog that opens on Cancel; Enter never confirms it.
- The server listens on this computer only. With `--tailscale` or `--host` every other computer needs the token link. The token is kept in `out/gui/token`, so a restart keeps the link; `--new-token` ends every link given out before. Requests from other web pages are refused.
- Closing the studio stops running hand jobs the same way as Stop.

## Camera: how Sebas's code is used

```
webcam ─► scripts/camera_track.py ─► "T <time> <20 joint angles>" per frame ─► scripts/hand_follow.py ─► hand
          MediaPipe landmarks +                                                 at most 3 rad/s, 200 Hz,
          features() and retarget()                                             our hand session (limits, confirmed switch-off)
          from scripts/teleop.py
```

- `scripts/teleop.py` is Sebas's file, updated 2026-11-15. The angle maths moved to `scripts/hand_features.py`, which needs no Wuji SDK.
  `c` now also calibrates MediaPipe's straight-finger bend offset. Spread is measured between neighbouring fingers. The ring-follows-middle coupling is reduced, and the thumb tip moving across the palm now counts.
  The finger spread sign was reversed (spreading drove the robot fingers into each other); fixed the same day.
  Run on its own, it still needs his `handlib` module from the folder above the repo. It uses the same model in `assets/mediapipe/`.
- `camera_track.py` imports his tracking and mapping functions and replaces his window with a picture stream for the page.

### Calibrate (guided)

**Calibrate** shows four poses over the camera picture. Each pose gives you 1.5 s to get into it, then records it for 3 s:

| Pose | What you do | What it sets |
|---|---|---|
| Open hand | flat, fingers together, thumb next to the index finger | the zero point of every joint (as the old one-press calibration did) |
| Fist | all four fingers curled as far as they go | finger base, middle and tip: your full curl gives the robot's full curl (1.3 / 1.4 / 1.1 rad) |
| Spread wide | fingers and thumb as far apart as they go | finger spread (index 0.4, ring −0.3, pinky −0.5 rad) and thumb swing (−1.0 rad) |
| Thumb across | thumb tip on the base of the little finger | thumb base (1.2 rad) |

- Each joint gets one gain: the robot angle the pose should reach, divided by the angle your hand gave in that pose (the median of its frames). This is `fit_calibration()` and `CAL_POSES` in `scripts/teleop.py`.
- A gain outside 0.5–3 is treated as a pose not held, or as a tracking error: that joint keeps gain 1, and the result says **redo** for its pose.
- The result is saved to `out/camera_calibration.json`, with the raw medians of each pose. The camera loads it at the next start.
- **More › Open hand only** is the old one-press calibration: it resets only the zero point.
- Tested with a recorded video (not a live person): the steps, the recording, the fit and the save work. Whether the gains improve the mapping is not checked yet.
- `hand_follow.py` replaces his hand connection with ours, so the camera mode has the same current limit and switch-off check as playing.
- Anything that prints `T` lines can drive the hand: a recorded session, or a learned mapping later.
- The hand can be on another computer: the page pipes the lines through SSH.

## What is saved, and what it could teach

| Where | What |
|---|---|
| `out/teleop/<date>/landmarks.npz` | per frame: 21 hand points (camera and metric), the 20 joint targets |
| `out/teleop/<date>/hand.npz` | targets and measured joint angles, ten times a second |
| `plans/*/theme_q_1khz.npz`, key `P` | per note: when down, when up, how deep, sideways, forward, as found by the search |
| `plans/*/hw_*.npz` | commanded and measured joint angles of every real run |

Can the search improve the camera mode? Partly. It does not make the camera see fingers better. It can replace the fixed angle mapping: record people playing library pieces in front of the camera with the keyboard's MIDI running, pair each frame with the joint angles of the plan that plays the same notes, and fit a mapping on those pairs. That needs many sessions; today there are none.

## Files

| File | Role |
|---|---|
| `gui/app.py` | the server: pages, the actions behind every button |
| `gui/jobs.py` | background runs with logs; one search at a time, one hand run at a time |
| `gui/library.py` | finds pieces and plans |
| `gui/planner.py` | hand positions for a piece, the optimiser command, the time estimate |
| `gui/static/` | the pages (plain HTML, CSS, JavaScript; no build step) |
| `gui/settings.local.json` | this computer's settings, not in git |

## Not tested

| What | Why |
|---|---|
| The camera with a live webcam | the test computer has none: tested with a picture file |
| The robot computer over real SSH | tested against a stand-in on one computer |
| A second device over Tailscale | tested through the Tailscale address from the same computer, not from another device |
| Teaching: what a learner gains | lessons ran on the real hand at 1.0 A down to 0.3 A; nobody has measured the effect. The defaults (1.0 A, 50 % speed) are still a guess |
| macOS and Windows | written for them, run on Linux only |
