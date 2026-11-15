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

**Status, 15 Nov 2026: every page was tested with the fake hand in a browser. No page has moved the real hand yet.**

## Pages

| Page | What you do there |
|---|---|
| **Library** | pieces on the left, the chosen one on the right: listen, its plans (▶ Play), Retarget ›. Tabs: Ours · Duets · Pianists (the 153 FürElise performances) · Excerpts |
| **Retarget** | piece, hand, wrist; then Reuse / Draft / Standard / Fine, with the time before you start. Everything else under More |
| **Play** | One hand · Two hands · Teach (one phrase or all, slower, several times). Notes fall onto a keyboard in step with the hand |
| **Camera** | the hand follows your hand in front of the webcam (Sebas's tracking) |
| **Settings** | which hand, the robot computer, default current limits |

The hand (fake, this computer, robot computer) is chosen at the top right and holds for every page.

### A piece from the FürElise dataset

The 153 performances are minutes long and use both hands across the whole keyboard; one robot hand learns an excerpt. Library › Pianists › a piece: choose where to start, 10, 20 or 40 seconds, and the right-hand melody (the highest note of each chord, from middle C up) or all notes. **Make the excerpt › Retarget** saves it to `assets/library/` and opens Retarget. Most excerpts span more than five keys, so the wrist has to move: simulation only until there is an arm.

Tested: K.265 from 0:30, 20 s, melody: 152 notes, a tiny search (8 tries × 1 round) took 56 s and hit 75 to 81 of 152 on the training setups. A useful plan needs Standard or more and a slower excerpt.

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
- The server listens on this computer only. With `--tailscale` or `--host` every other computer needs the token link. Requests from other web pages are refused.
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
