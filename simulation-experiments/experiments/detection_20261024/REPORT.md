# Historical pretrained detection experiment — 24 October 2026

**Status: closed historical experiment.** The real-image comparison is
complete; the full-stack simulation comparison was not executed because layer
translations were unresolved. This directory preserves the original evidence
and standalone reproduction commands. Its pretrained detector scripts are not
part of the new known-layout perception system's execution path.

**Subsequent reference audit:** the 48 historical stud marks below are not
validated geometric centers. Independent crop inspection found many on cap
rims/highlights. All reported 4/48 matches and pixel distances are conditional
on those unchanged marks; the original center interpretation and 2 px stud
uncertainty are unsupported. Face-polygon measurements remain a separate track.
See the [audit evidence](../known_layout_20261024/results/reference_audit/audit.json).

**Recommendation: require further work.** Neither tested Studwise weight pair
reliably separates individual bricks in these dense-lattice photographs. A
small stud-count/PCA filter does not recover the missed instances. This result
does not justify starting robot manipulation, training, or a broader perception
project as part of this experiment.

## Scope and inputs

All **18 uploaded JPEGs** in `resources/realsense_d435i_lego/` were processed.
They are 1280×720 wrist-camera images, with no supplied intrinsics, mounting
extrinsics, depth frames or capture metadata. The user confirmed that layers
were removed between views and corrected the original input count to
**10 layers × 6 × 6 = 360 bricks**, superseding the original 250-brick request.

The independent reference subset is `img_1`, `img_3`, `img_7`, `img_10`,
`img_13`, and `img_16`. It covers rotation, different visible layer directions,
shadows, same-color neighboring bricks and glare. These are correlated views
of four descriptive arrangement groups, not six independent stacks or a
random train/test split.

References contain **166 visual exposed top faces**, **14 ambiguous cell
regions excluded**, **23 non-exhaustive lower-layer fragments**, and **48
manually marked stud centers**. Polygons were drawn from manually inspected
strip corners and four-stud groups; interpolation is a drawing convenience.
Approximate annotation uncertainty is 3–5 px at boundaries and 2 px for studs.
These labels establish neither calibrated top height nor physical gripper
accessibility. Visible brick counts are not forced to equal the original full
layer inventory in the partly disassembled photographs.

## Methods

[Brickssifier Studwise](https://github.com/MiguelDiLalla/Brickssifier_Studwise)
was pinned to commit `3aef8aade8cb74a04780d5e809e49dfa1fc57a47`.

| Method | Published brick and stud checkpoints |
| --- | --- |
| January | `Brick_Model_best20250123_192838t.pt`, `Stud_Model_best20250124_170824.pt` |
| March | `bricks_model_kaggle50epoch_10032025.pt`, `studs_model_kaggle50epoch_10032025.pt` |

Both use identical OpenCV decoding and Ultralytics preprocessing. Brick input
size is 1280; stud-on-predicted-brick-crop input size is 640. Confidence is 0.25,
NMS IoU is 0.5, FP32, no augmentation. An independent full-frame stud baseline
uses size 1280 and `max_det=1000`. Raw brick boxes, crop-conditioned stud boxes,
full-frame stud boxes and optional image-space PCA summaries are saved
separately. No reference annotation, simulator truth or shade label is used as
a perception input.

The small refinement requires exactly eight predicted studs and an elongated
PCA distribution. It estimates an undirected image angle only. Eight studs do
not establish a single instance, exposure or a metric pose.

[Xuanyi's assembled-LEGO YOLOv3 repository](https://github.com/XuanyiZhao/Lego_bricks_object_detection)
was investigated within the approximately 20-minute limit and skipped. Its
checked tree has no trained LEGO checkpoint, the notebooks reference absent
local backup files, and both published YOLO ZIP links returned HTTP 404.
Generic COCO weights were not substituted. No Darknet/CUDA-8 framework port or
training was attempted. Evidence is in [model availability](upstream/model_availability.md).
The older [Duplo/UR5 project](https://github.com/tomsep/robot-lego-assembler)
remains reference material; none of its system was ported.

## Measurements on the six annotated real views

| Method | Top references | Matched | Missed | Merged boxes | Duplicate boxes | Individually selected labeled lower fragments | Outside stack ROI |
| --- | ---: | ---: | ---: | ---: | ---: | ---: | ---: |
| January | 166 | 1 (0.60%) | 165 | 1 | 0 | 0 | 2 |
| March | 166 | 0 (0%) | 166 | 8 | 0 | 0 | 4 |

There were 14 raw January brick boxes and 43 raw March brick boxes across all
18 images. Those totals are not recall or independent evidence of accuracy.
The table above evaluates only the six annotated views.

Matching uses one-to-one axis-aligned-box IoU ≥0.50 against the manual polygon
envelopes. Before matching, a box is labeled a merge if it contains the centers
and at least 50% of the area of two or more confirmed top references; merged
boxes cannot count as individual-brick true positives. Additional matches to
an already matched instance are duplicates. Unmatched centers inside labeled
lower fragments are lower-layer target errors. Ambiguous references are
excluded; remaining unresolved regions are not automatically called background
hallucinations. Full rules, per-image matches and IDs are in
[evaluation.json](results/real_evaluation/evaluation.json).

**Zero labeled-lower-fragment selections is not evidence of correct exposure
filtering:** neither model predicts a layer/exposure class, lower labels are
non-exhaustive, and the March merge boxes span both top faces and visible lower
surfaces. Outside-ROI detections also include loose bricks as well as cables;
they are not all false brick detections, but they are unsuitable stack targets.
The zero duplicate count applies only to the separate non-merge duplicate
category. Some March merge boxes overlap one another and are redundant.

| Measurement | January | March |
| --- | --- | --- |
| Image orientation on matched individual instances | 0.334° error, **n=1** | Not measurable, n=0 |
| Selected reference studs found through predicted brick crops | 4/48; median error 4.59 px, n=4 | 0/48; error not measurable |
| Selected reference studs found independently on full frames | 4/48; median error 6.44 px, n=4 | 0/48; error not measurable |
| Eight-stud/PCA-filtered individual-brick matches | 1/166 | 0/166 |

Stud matches are one-to-one within 8 px, with crop duplicates within 3 px
deduplicated. Unmatched reference points count as missed. Error statistics
describe matched points only; they must not hide the poor coverage. The 48
points are selected references, so unannotated predicted studs cannot support
a stud precision claim. Image orientations are modulo 180°, not calibrated
robot-frame yaw. No masks, metric poses or mechanical accessibility are
produced or established here.

Visual review supports the quantitative failure modes: January often detects
no stack brick; March frequently encloses multiple strips or most of the
stack. The January filter retains its one correctly matched reference but
does not recover other bricks. Therefore neither unchanged reuse nor the
tested small refinement is supported for target selection.
Across all 18 images, January's eight-stud filter passes six detections:
two stack-corner bricks and four loose background bricks. The latter are real
brick detections but unsuitable stack targets; the filter does not establish
which layer or source structure a brick belongs to.

## Simulation geometry gate

**The real-image experiment is complete; the required full-stack simulated
comparison is blocked by unresolved layer translations.** No smaller stack,
48-brick rendering, or invented full-stack geometry is presented as a result.

The user confirmed alternating 90° layers, a one-stud stagger and layer removal
between photographs. The exact translation axes, phase and repetition rule
remain unconfirmed. Alternating orientations alone does not determine the
visible lower-layer studs or native connection graph. For example, a
common-center rotation of 24×22 and 22×24 stud layer footprints would use
horizontal origin `(0,1)` and vertical origin `(1,0)`; other origins produce
different overlaps while retaining all 360 bricks.

The partly removed photographs do not independently establish the full original
inventory or every hidden layer's origin. See the specific alternatives in
[geometry audit](simulation/geometry_audit.md). The requested clarification is
whether all layer centers coincide, or whether layers also slide sideways.
A stud-grid sketch of the two repeating footprints would resolve a different
pattern. Missing camera calibration is separate: any subsequent camera matching
must be labeled approximate.

| Method | Required full-stack simulated result |
| --- | --- |
| January | N/A — no confirmed full geometry, no simulated inference |
| March | N/A — no confirmed full geometry, no simulated inference |

A parameterized experiment-specific renderer is prepared but not claimed as
runtime-validated. It refuses unknown origins before submitting a job. It
reuses the FR3/BrickSim scene, requires 360 bricks connected to the anchored
plate, and checks a 361-part component. It separates RGB detector inputs from
depth/projection/identity evaluation truth. It would use the same inference
script unchanged. No real/sim failure-pattern or calibrated digital-twin
equivalence is claimed without those results.

## Artifacts and reproducibility

- [Manual annotations](reference/annotations.json), [inventory and image hashes](reference/inventory.json),
  [reference overlays](reference/reference_contact_sheet.jpg), and [annotation methodology](reference/README.md).
- [Compact measured results](results/real_evaluation/summary.csv) and
  [per-image evaluation](results/real_evaluation/evaluation.json).
- [Side-by-side reference and prediction gallery](results/prediction_contact_sheet.jpg).
- [Canonical prediction metadata](results/inference_provenance.json),
  [all-image counts](results/all_image_counts.csv), and
  [saved inference logs](results/inference_pueue_logs.json).
- [Canonical machine-readable detections and overlays](results/real_predictions/inference_run.json):
  sibling `studwise_january/` and `studwise_march/` directories contain separate
  `raw_bricks`, `raw_studs`, `raw_studs_full`, `refinement` and `overlays` outputs.
- Canonical predictions: Pueue **1666**,
  `runs/20261023T223848.668564Z-detection-real/predictions/`, with JSONs and
  brick/stud/refinement overlays for both methods on all 18 images.
- Initial inference: Pueue **1665**,
  `runs/20261023T223642.271685Z-detection-real/`; retained for provenance. Job
  1666 adds the independent full-frame stud baseline and is the reported run.
- Runtime: existing Python 3.11, Torch 2.7.0+cu128, torchvision 0.22.0+cu128,
  NumPy 1.26.0, OpenCV 4.10.0.84, Pillow 11.3.0. Isolated packages:
  `ultralytics==8.3.221`, `ultralytics-thop==2.0.18`. Weight SHA-256s, settings
  and dependency versions are recorded in the canonical
  `predictions/inference_run.json`; source/model/input hashes are in its
  snapshot `manifest.json`.

From this repository root, inference is submitted—not executed directly—with:

```bash
/home/faps/miniforge3/envs/unitree_sim_env/bin/python \
  experiments/detection_20261024/scripts/submit_inference.py --domain real
```

The isolated dependency setup, if this experiment's `.deps` is absent, is:

```bash
/home/faps/miniforge3/envs/unitree_sim_env/bin/python -m pip install \
  --no-deps --target experiments/detection_20261024/.deps \
  ultralytics==8.3.221 ultralytics-thop==2.0.18
```

The four checkpoint filenames above are downloaded unchanged from
`https://raw.githubusercontent.com/MiguelDiLalla/Brickssifier_Studwise/3aef8aade8cb74a04780d5e809e49dfa1fc57a47/models/<filename>`
into `experiments/detection_20261024/models/`. Verify their SHA-256s against
`results/inference_provenance.json`. These setup steps do not perform inference
or change the shared Conda environment.

After that job completes, the lightweight evaluation command is:

```bash
/home/faps/miniforge3/envs/unitree_sim_env/bin/python \
  experiments/detection_20261024/scripts/evaluate_predictions.py \
  --annotations experiments/detection_20261024/reference/annotations.json \
  --predictions runs/<new-detection-real-snapshot>/predictions \
  --output experiments/detection_20261024/results/reproduced_evaluation
```

Model inference used only the default Pueue queue, stable snapshots and the
existing runtime. No shared environment was modified. No training, robot
control, manipulation development, ROS integration or broad appearance/data
pipeline was undertaken. The experiment stops at these findings and the
explicit geometry limitation.
