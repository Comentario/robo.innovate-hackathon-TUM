# Fixed known-layout evaluation

This is independent evaluation code, separate from `perception.algorithm`.
The prediction subprocess reads only the image, four coarse global registration
anchors, supplied layout/plane hypothesis and algorithm configuration. It does
not load the scoring references. `evaluate.py` reads labels only after
predictions have been saved.

## Frozen references and split

The original historical labels remain unchanged: 166 visible complete 2×4
faces, 14 ambiguous regions, 23 selected lower-layer fragments and 48 manual
stud centers across six images. The annotations establish visual faces, not
calibrated current-top height, physical occupancy or gripper accessibility.

- Development: `img_1`, `img_3`, `img_7`, `img_10` (112 positive faces, eight
  ambiguous regions, 15 lower fragments, 32 historical marked points).
- Held out: arrangement group D, `img_13`, `img_16` (54 positive faces, six
  ambiguous regions, eight lower fragments, 16 historical marked points). These views are
  reserved from implementation tuning. They are still correlated observations
  of the same stack/disassembly sequence, not an independent-stack test.
- Supplementary missing-face track: six clearly incomplete expected face slots
  in development images 1/3/7. Original ambiguous labels stay unchanged and
  excluded from primary positive recall. The supplementary labels mean that a
  complete parallel face is absent in the image-plane slot, not that a hidden
  physical brick is absent. There are no held-out missing-face labels.

`protocol.json`, the two manual registration input files, the supplemental
missing references and their hashes were frozen before the geometric baseline
was evaluated. Do not adjust them to favor a later implementation.

The four-corner inputs are explicitly manual and approximate. The observed
window is six strips × five visible brick-length groups, not a reduced final
simulation of the original 360-brick stack. The outer strip can be a different
height or phase; current top height is unknown. Nominal camera intrinsics are
not D435i calibration, and the stored corners are not a measured robot/baseplate
frame.

## Measurements

All decisions (`present`, `missing`, `uncertain`) are counted. Missing candidate
output does not count as a correct missing decision. Uncertain cases and failed
geometric matches reduce coverage; zero false positives at zero coverage is
not acceptable reliability.

Individual matching uses one-to-one envelope IoU ≥0.50. A candidate covering
at least half of two complete face boxes and containing their centers is a
merge and cannot count as an individual match. Duplicates and lower-fragment
selections are reported separately. The 23 lower fragments are sparse negative
checks; a fixed grid avoiding gaps can score zero there without proving layer
discrimination. Physical current-top accuracy remains unmeasurable.

Image orientation and projected-stud residuals are measured on all geometric
matches, whether selected or uncertain, with their sample counts. They largely
reflect manually assisted registration. Image-derived confirmed stud peaks are measured separately against the historical
marked points, with matched-point coverage. Independent crop inspection found
that these marks often lie on cap rims or highlights rather than geometric
centers. Consequently these distances do not establish stud-center localization
or fine registration accuracy. This caveat also applies to the historical
pretrained detector's 4/48 matched-point count; the original labels and results
remain unchanged for reproducibility.

The fixed cases are nominal, brightness ×0.70/×1.30, image rotation ±5° with
coherently transformed input/reference geometry, initial global registration
offsets ±4 px along each axis, and flat-image sanity. Flat images are a
counterfactual check that supplied geometry cannot invent positive evidence;
they are not photographed absence data.

## Queue and reproducibility

All batch image processing uses the default shared Pueue queue:

```bash
python3 perception/evaluation/submit_evaluation.py \
  --config perception/configs/baseline_v0.json --tag v0 --split development
```

The submitter requires a clean committed `perception/` source tree and copies
the code, effective configuration, selected images, inputs and scoring
references into a timestamped ignored `runs/` snapshot. It records commit and
file hashes. No shared environment changes or model training are involved.
Held-out runs use `--split heldout` only after the selected version is frozen;
held-out performance must not determine image-specific fixes or thresholds.

`test_evaluate.py` contains small scoring-contract tests; it performs no
perception batch inference. `diagnose_studs.py` is an explicitly evaluation-only
development diagnostic at the historical marked points, never a production
perception input. Its earlier true-center interpretation is unsupported by the
subsequent reference audit; see `results/reference_audit` in the experiment
artifacts. The complete-face polygon measurements remain a separate track.
