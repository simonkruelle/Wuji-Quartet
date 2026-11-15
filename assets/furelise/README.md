# FürElise dataset, piece 15 (Mozart K.265)

From the [FürElise dataset](https://huggingface.co/datasets/rcwang/for_elise) (Wang, Xu, Shi, Schumann, Liu: "FürElise: Capturing and Physically Synthesizing Hand Motions of Piano Performance", [arXiv 2410.05791](https://arxiv.org/abs/2410.05791)). Licence: **CC BY-NC 4.0, non-commercial use only.**

| File | Content |
|---|---|
| `15/midi.mid` | the recorded performance as MIDI, unchanged. We play the melody (notes from B4 up) of the first 35 seconds |
| `15/wrist_u.npz` | derived by us: the pianist's right wrist position along the keyboard, one value per melody note |
| `15/theme_analysis.json` | derived by us: which finger the pianist used for which note |

| `midi/<id>.mid` · `metadata.json` | the recorded MIDI of all 153 performances (5 MB), unchanged, and their composer, title and length. The studio lists them under Library › Pianists |

The dataset: 15 pianists, 153 pieces, 11.9 hours. Mostly classical (Chopin 34, Schumann 21, Bach 19, ...), a few jazz standards (All Blues, Slow Boat to China), Gershwin, and scales and exercises. No pop.

The motion capture itself (50 GB for all pieces; `15/motion.pkl` alone is 590 MB) is not in this repo. Fetch it with `python scripts/furelise_peek.py assets/furelise`.
