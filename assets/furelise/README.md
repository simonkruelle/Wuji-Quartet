# FürElise dataset, piece 15 (Mozart K.265)

From the [FürElise dataset](https://huggingface.co/datasets/rcwang/for_elise) (Wang, Xu, Shi, Schumann, Liu: "FürElise: Capturing and Physically Synthesizing Hand Motions of Piano Performance", [arXiv 2410.05791](https://arxiv.org/abs/2410.05791)). Licence: **CC BY-NC 4.0, non-commercial use only.**

| File | Content |
|---|---|
| `15/midi.mid` | the recorded performance as MIDI, unchanged. We play the melody (notes from B4 up) of the first 35 seconds |
| `15/wrist_u.npz` | derived by us: the pianist's right wrist position along the keyboard, one value per melody note |
| `15/theme_analysis.json` | derived by us: which finger the pianist used for which note |

The motion capture itself (`15/motion.pkl`, 590 MB) is not in this repo. Fetch it with `python scripts/furelise_peek.py assets/furelise`.
