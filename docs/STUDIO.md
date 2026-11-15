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

**Status, 15 Nov 2026: every page was tested with the fake hand in a browser. Play has driven the real right hand through the robot computer (one hand, from the Ode position); Two hands, Teach and Camera have not yet.**

## Pages

| Page | What you do there |
|---|---|
| **Library** | pieces on the left, the chosen one on the right: listen, its plans (▶ Play), Retarget ›. Tabs: Ours · Duets · Christmas (14 songs, `assets/songs/`) · Pianists (the 153 FürElise performances) · Mine (what you imported or cut on this computer, in `assets/library/`; the tab appears once there is something). **+ Import a MIDI file** under the list |
| **Retarget** | piece, hand, wrist; then Reuse / Draft / Standard / Fine, with the time before you start. Everything else under More |
| **Play** | One hand · Two hands · Teach (one phrase or all, slower, several times). Notes fall onto a keyboard in step with the hand |
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

- `scripts/teleop.py` is Sebas's file, unchanged. It needs his `handlib` module and a model under `scripts/models/`, which are not in this repo, so it does not run here by itself.
- `camera_track.py` imports his tracking and mapping functions and replaces his window with a picture stream for the page.
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
| Any real hand from the studio | the tests used the fake hand only |
| The camera with a live webcam | the test computer has none: tested with a picture file |
| The robot computer over real SSH | tested against a stand-in on one computer |
| A second device over Tailscale | tested through the Tailscale address from the same computer, not from another device |
| Teaching: current limit and mount height | the defaults (1.0 A, 50 % speed) are a guess. Set them to what you used |
| macOS and Windows | written for them, run on Linux only |
