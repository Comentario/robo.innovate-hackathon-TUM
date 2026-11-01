# Upper-layer ridge direction from depth

**Depth identifies the highest visible ridge direction in all five views.**
The ridges run along **world Y**, approximately **90° modulo 180°**. They appear
vertical in the overhead image and horizontal from the oblique side camera.
The estimator found six elongated ridges from depth in each view; six was not
an input or acceptance requirement.

| View | Estimated world direction | Angular error | Elongated ridges | Data-selected height band |
|---|---:|---:|---:|---:|
| Overhead | 90.048° | 0.048° | 6 | 98–101 mm |
| Small X tilt | 90.015° | 0.015° | 6 | 98–101 mm |
| Small Y tilt | 90.044° | 0.044° | 6 | 98–101 mm |
| Front oblique | 89.889° | 0.111° | 6 | 99–102 mm |
| Side oblique | 90.024° | 0.024° | 6 | 99–102 mm |

Median angular error: **0.044°**; maximum: **0.112°** (rounded upward).
All five directions passed the frozen support checks. Five invalid-depth
controls and five flat-plane controls returned uncertainty: **0/10 false
supported directions**. These are correlated views of one static full stack,
not ten additional physical scenes or independent-stack generalization.

[Overhead direction arrow](results/predictions/real/top/overlay.png) ·
[Side-view arrow](results/predictions/real/oblique_side/overlay.png) ·
[Extracted overhead ridge mask](results/predictions/real/top/elongated_ridges_world_xy.png) ·
[Top-band height visualization](results/predictions/real/top/top_height_visualization.png)

The axes are undirected: +Y and −Y describe the same ridge orientation. The
arrow is a layer-direction annotation, not a selected brick or grasp target.
Internal directory/condition `real` means **unmodified simulated depth**; there
was no physical D435i depth capture in this experiment.

## How the direction is measured

1. Unproject optical-axis depth in meters using configured camera intrinsics
   and extrinsics. Crop to the known source-plate XY region. No layer count,
   stack height, brick yaw, lattice arrangement or instance identity is supplied.
2. Keep locally near-horizontal surfaces and find the highest sufficiently
   supported 3 mm band from the depth population. Its height is measured from
   the sensor input, not copied from the scene design.
3. Rasterize the selected points in world XY at 1 mm resolution to remove
   perspective. A 3×3 closing joins small surface/seam gaps.
4. Fit axes to individual elongated connected components and compare their
   axial consensus with long mask-edge directions. Global footprint PCA is
   avoided: the near-square stack outline can point across the ridges.
5. Return an angle only with enough elongated/edge support, coherent axes and
   agreement between the complementary checks; otherwise return uncertainty.

The independent evaluator alone reads actual simulator brick poses. The true
highest-layer direction is 90°, body-top height 99.20 mm and stud-top height
100.90 mm. The depth-selected band contains both heights in every view,
consistent with isolating the upper layer rather than the perpendicular lower
surfaces visible through its openings. The reported median selected-surface
heights range from 99.15 to 99.27 mm; a band statistic is not a calibrated
brick pose or insertion height.

All settings and scoring rules were frozen before depth processing:
[config](config.json), [protocol](protocol.json). Invalid and flat controls
exercise abstention, not physical missing-brick accuracy. At least two elongated
components are required, so this version can abstain on short or very sparse
remaining upper-layer fragments. The known ROI and level horizontal workcell
are explicit assumptions.

## Execution and saved outputs

**Default Pueue job 1684 succeeded**, source checkpoint **179ee02**, snapshot
`runs/20261024T125255.987070Z-depth-ridge-direction`. Sensor processing for all
15 original/control cases took approximately 0.65 seconds in the existing
runtime. No new render, learned model, training, robot command or shared
configuration change was made.

Perception receives only depth, nominal configured camera calibration and XY
ROI; RGB is opened after analysis for drawing. The original depth files lived
under the render's `evaluation_truth/` directory, but the user's instruction
explicitly authorized them here as sensor observations. Actual brick poses and
reference orientation remain in the separate scoring directory.

All 15 direction JSONs, component axes, band masks, derived height arrays and
overlays are in [results/predictions/](results/predictions/). See the
[full independent evaluation](results/evaluation/evaluation.json) and
[provenance/artifact hashes](results/provenance.json). Original inputs came from
corrected 300-brick render job 1681; their hashes are frozen in the run manifest.

Runtime: Python 3.11.15,
`/home/faps/miniforge3/envs/unitree_sim_env/bin/python`, OpenCV 4.10.0,
NumPy 1.26.0. Reproduce with committed scoped source/settings:

```bash
python3 experiments/depth_ridges_20261024/submit.py
pueue log <reported-job-id> --lines 30
```

Independent source and artifact reviews accepted the results. This supplies a
useful upper-layer orientation cue for subsequent brick localization. It does
not establish individual brick poses, accessibility or stud-aligned placement.
The maps are ideal rendered depth with nominal synthetic calibration; physical
D435i noise, working-distance effects and camera/robot calibration remain
untested. No follow-up perception or manipulation step starts automatically.
