# Wuji Hand 2 model (subset)

A subset of [wuji-technology/wuji-description](https://github.com/wuji-technology/wuji-description), cloned on 10 Nov 2026. MIT licence, © 2025 Wuji Technology, see [LICENSE](LICENSE). Files are unchanged.

| Kept | Path |
|---|---|
| MuJoCo models (left, right, with cover, with glove) | `hand2/hand2_{1,2}/body/mjcf/` |
| URDF models | `hand2/hand2_{1,2}/body/urdf/` |
| Right-hand meshes | `hand2/hand2_{1,2}/body/meshes/right/` |
| Left-hand meshes, Hand 2.2, the 27 files its MuJoCo model loads | `hand2/hand2_2/body/meshes/left/` |
| Flange and mount drawings (PDF) and STEP files | `hand2/hand2_{1,2}/attachment/` |

Left out to keep the repo small: the Hand 2.1 left-hand meshes and the left-hand cover meshes, USD files, full-hand STEP assemblies, the first-generation hand and the glove. The Hand 2.2 left-hand MuJoCo model (`mjcf/left.xml`) loads. The other left-hand files (with cover, with glove, Hand 2.1) will not load without their meshes. Get everything with:

```bash
git clone --depth 1 https://github.com/wuji-technology/wuji-description
```
