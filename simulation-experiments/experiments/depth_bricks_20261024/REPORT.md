# Individual brick detection using the depth-derived ridges

**Depth-guided geometry proposes a footprint for every visible top brick in
these five views. The stricter depth/RGB checks confirm 27 of the 150 brick
observations, with no observed false matches; the remaining 123 stay uncertain.**
This is useful instance-localization progress, with limited verified coverage.

| View | Matching raw footprints / 30 | Confirmed present / 30 | Uncertain | Overlay |
|---|---:|---:|---:|---|
| Overhead | 30 | 11 | 19 | [Image](results/predictions/real/top/overlay.png) |
| Small X tilt | 30 | 9 | 21 | [Image](results/predictions/real/near_top_x/overlay.png) |
| Small Y tilt | 30 | 0 | 30 | [Image](results/predictions/real/near_top_y/overlay.png) |
| Front oblique | 30 | 0 | 30 | [Image](results/predictions/real/oblique_front/overlay.png) |
| Side oblique | 30 | 7 | 23 | [Image](results/predictions/real/oblique_side/overlay.png) |
| Total, correlated view-target observations | 150 | 27 | 123 | |

All 27 confirmed declarations match a reference: **27/27 conditional precision,
18% recall** on this benchmark. There are zero confirmed merges, duplicates,
lower-layer selections or other unresolved false declarations. Five invalid-depth
and five flat-plane controls produce zero hypotheses and zero present claims.
These counts concern one static, fully occupied stack seen repeatedly; they
are not 150 distinct physical bricks or independent-stack generalization.

The 150 raw matches are **geometric hypothesis coverage**, not 150 verified
brick detections. The method knows the 2×4 footprint class. It measures ridge
extents and fits integer 32 mm intervals; internal cuts can remain inferred
where an image seam is weak. A slot does not become present simply because
it lies in that chain.

## What changed

The successful [depth-direction method](../depth_ridges_20261024/REPORT.md)
provides the measured upper surface band and ridge axis. Its code/settings are
reused unchanged and hash-checked against job 1684. The detector then:

1. Groups collinear top-band fragments into ridges, retaining one phase across
   internal gaps. Width must agree with the nominal two-stud width.
2. Checks both current ends using top-mask drop and **actual observed lower
   depth** outside each end. Missing projected returns count as unknown.
3. Searches integer counts around measured span / 32 mm, using both ends to
   establish the current-window phase. The observed spans are approximately
   158–160 mm and yield five candidate slots per ridge; five and six are not
   supplied counts. Original extent and missing end bricks remain unknown.
4. Tests each footprint independently: at least 70% coverage of the closed
   depth-derived top-band mask, four
   supported RGB stud features spread across both ends and rows, and long-side
   edge evidence. Weak evidence remains uncertain.
5. Records RGB cross-edge support near predicted boundaries separately from
   inferred metric cuts. RGB maxima do not move the slot centers. There is
   no independent per-brick Z/PnP fit.

Perception receives original RGB/depth, nominal camera calibration, the known
plate ROI and nominal brick dimensions. It receives no layout, brick count,
layer number, known yaw, actual camera records, brick poses or annotations.
The surface height and axis come from depth. Challenge 1's shade/quality
classification is not duplicated.

## Localization and remaining failures

| Matched stage | N | Median XY error | P90 XY error | Maximum XY error |
|---|---:|---:|---:|---:|
| Raw geometric footprints | 150 | 0.501 mm | 0.709 mm | 1.144 mm |
| Confirmed present subset | 27 | 0.499 mm | 0.693 mm | 0.736 mm |

These are conditional in-plane center errors in the nominal synthetic workcell.
All candidates share the measured ridge yaw and depth surface plane. Raw
median/max shared-axis yaw errors are 0.044°/0.111°; the confirmed subset has
0.024°/0.048°. These are not independent per-brick six-DOF estimates, measured
root heights or insertion tolerances. Nominal stud footprint dimensions are
not a calibrated manufactured-brick envelope.

Nonexclusive uncertainty reasons across 150 hypotheses:

- 75 candidates lack sufficiently observed end/count/phase support. These
  belong to 15 uncertain ridge hypotheses, not 75 separate scenes.
- 53 lack enough supported RGB stud features.
- 51 lack the required distribution of stud evidence across ends/rows.
- 32 fall below the closed top-band mask coverage threshold.

The near-Y and front-oblique views retain all candidates as uncertain because
ridge-end/phase support fails; other reasons can overlap. Overhead is the most
useful tested view for verified detections. No gates were relaxed after seeing
these outcomes. Raw geometric matching alone does not justify promoting the
uncertain candidates, especially without removed-brick/occlusion tests.

The earlier RGB-only per-brick pose experiment accepted 0/150 on the same
rendered views. This method accepts 27/150 after adding authorized depth and a
constrained metric partition; the sensor inputs and method differ. Historical
real-photo ridge-chain scores are not placed in this direct comparison.

## Artifacts and reproduction

All 15 original/control outputs are under [results/predictions/](results/predictions/).
Each `detections.json` retains measured ridge fragments, end support,
count/phase alternatives, raw slots, decisions/reasons, depth/RGB support,
image boxes/polygons, world-XY centers/shared yaw, and boundary provenance.
No instance-mask or physical accessibility claim is made.

Overlay legend: green = confirmed present, yellow = uncertain footprint.
Boundary source records distinguish depth-observed current ends, supported
RGB common cross-edges and inferred metric divisions. Cross-edge support
is not independently labeled physical seam truth. Slot labels `p`/`u` show
present/uncertain, not quality classifications.

[Full independent evaluation](results/evaluation/evaluation.json) ·
[Provenance and output hashes](results/provenance.json) ·
[Fixed settings](config.json) · [Scoring protocol](evaluation/protocol.json)

**Default Pueue job 1685 succeeded**, source checkpoint **3f65e80**, snapshot
`runs/20261024T132747.449952Z-depth-brick-detection`. Sensor processing for all
15 cases took approximately 1.29 seconds. Frozen box-envelope IoU ≥0.50 matching,
merge/duplicate/lower rules are unchanged. Actual simulator roots and reference
faces are evaluator-only, staged separately from perception inputs.

Runtime: Python 3.11.15,
`/home/faps/miniforge3/envs/unitree_sim_env/bin/python`, OpenCV 4.10.0,
NumPy 1.26.0. No model, training, rendering, dependency or scheduler change.

```bash
python3 experiments/depth_bricks_20261024/submit.py
pueue log <reported-job-id> --lines 30
```

Internal condition `real` means original **simulated** sensors, not physical
D435i data. The maps are ideal rendered depth with nominal calibration. The
fully occupied stack does not validate physical gaps, removed ends, noisy
camera depth or missing-slot correctness. Small synthetic tests verify shared
chain indexing, not physical absence detection. Gripper clearance, held-brick
transform, robot calibration and stud-aligned insertion remain separate.

Independent source/result reviews accepted the measurements and limitations.
Keep this as a depth-assisted candidate detector with selective confirmation.
Reliable complete coverage and physical transfer require further validation;
no training, manipulation or follow-up experiment starts automatically.
