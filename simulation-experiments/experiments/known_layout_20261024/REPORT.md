# Known-layout perception — evaluated baseline and pause

**Retain v1; demonstration acceptance is not met.** The selected, manually
assisted baseline confirms 37/112 development faces and 21/54 held-out faces
on nominal images, with no measured incorrect confirmations in scored regions.
Most remaining faces are uncertain. Nominal missing-face correctness is 0/6.
Two later changes increased coverage but confidently confirmed a misregistered
candidate under a small initialization shift; both were reverted.

The implementation agent, independent evaluator and independent reviewer agree
to pause algorithm changes for verified geometry/calibration and better
references. Held-out results were inspected only after v1 was selected; no
subsequent algorithm or threshold tuning was performed.

## What exists

`perception.algorithm.analyze` uses the existing Python/OpenCV/NumPy runtime:
manual global four-corner registration, supplied approximate observed layout,
projected brick/stud sites, bounded global translation refinement, grayscale
radial-stud and edge evidence, approximate lower-pattern counter-evidence, and
`present` / `missing` / `uncertain` decisions with scores and overlays.

V1 changes only the v0 circular-gradient feature to same-annulus radial
coherence. Its implementation commit is **`4106bdc`**; final restored evaluation
checkpoint is **`12dd890`**. The algorithm at that checkpoint is byte-for-byte
the selected v1. Active configuration: `perception/configs/baseline_v1.json`.
V2/v3 remain reproducible from their commits and saved configurations, rather
than remaining active fixes. See [the iteration record](ITERATIONS.md).

Inputs do not include reference instance polygons, historical stud marks,
pretrained detections, shade labels or simulator truth. The approximate image
window is six strips × five visible four-stud groups, **not** a smaller
simulation benchmark or a reconstruction of the original current top layer.
Registration/orientation is substantially supplied by the operator. Every
candidate retains `layer_verified=false`; presence is visual-face evidence,
not physical exposure, accessibility or a robot-frame pose. In held-out img_13,
the nominal camera fit fails its reprojection guard, so lower-plane
counter-evidence is unavailable even where visual presence is confirmed.

The old pretrained comparison is [closed historical evidence](../detection_20261024/REPORT.md),
checkpoint `2a3431a`; it is outside this execution path. Existing FR3/BrickSim,
runtime, scheduler and workcell code remain in place. No neural training,
shade classification, ROS, manipulation or hardware control was added.

## Fixed evaluation and results

Four development views (img_1/3/7/10) contain 112 positive visual-face
references, eight excluded ambiguous regions, six supplementary clear
missing-face slots and 15 sparse lower fragments. Two held-out group-D views
(img_13/16) contain 54 positives, six excluded ambiguous regions and eight
lower fragments, **no missing-face references**. These are correlated views of
one stack/disassembly sequence, not independent-stack generalization.

Labels, manual global anchors, splits and rules were frozen before evaluation.
Matching is one-to-one envelope IoU ≥0.50; a box covering half of two reference
faces and their centers is an ineligible merge. Duplicate and sparse lower
fragment checks are separate. Missing output and uncertainty reduce coverage;
they never count as correct absence. See the [frozen protocol](../../perception/evaluation/protocol.json)
and [measurement definitions](../../perception/evaluation/README.md).

| Version / nominal split | Correct present | Positive uncertain / unmatched | Incorrect present / wrong missing | Correct missing | Decision |
| --- | ---: | ---: | ---: | ---: | --- |
| v0 development | 0/112 (0%) | 106 / 6 | 0 / 0 | 0/6 | Reject zero coverage |
| v1 development | 37/112 (33.0%) | 69 / 6 | 0 / 0 | 0/6 | Retain working baseline |
| v2 development | 48/112 (42.9%) | 58 / 6 | 0 / 0 | 0/6 | Reject sensitivity regression |
| v3 development | 52/112 (46.4%) | 54 / 6 | 0 / 0 | 0/6 | Reject sensitivity regression |
| Selected v1 held out | 21/54 (38.9%) | 33 / 0 | 0 / 0 | Not measurable | Audit only; retain unchanged |

Nominal v1 misses 75 development and 33 held-out faces as confirmed targets.
All six nominal missing slots stay uncertain. Held-out scored present precision
is 21/21, but **two additional present decisions fall in excluded ambiguous
regions and are unscored**. These small, correlated counts cannot establish
perfect reliability. No nominal merges, duplicates or labeled-lower-fragment
selections were measured. Sparse negatives and a fixed candidate grid do not
establish complete layer discrimination.

All versions used identical ten-case batches per view: nominal, brightness
×0.7/×1.3, coherent image/registration/reference rotations ±5°, registration-only
x/y shifts ±4 px, and flat-image sanity. Synthetic perturbations are not new
independent photographs. Counts below are **correct present**, in the stated
minus/plus order; all flat tests produced zero present confirmations.

| Version / split | Dark / bright | Rotation −5° / +5° | Initial x −4 / +4 px | Initial y −4 / +4 px |
| --- | ---: | ---: | ---: | ---: |
| v0 development, /112 | 0 / 0 | 0 / 0 | 0 / 0 | 0 / 0 |
| v1 development, /112 | 17 / 47 | 29 / 30 | 42 / 27 | 33 / 25 |
| v2 development, /112 | 24 / 58 | 40 / 41 | 49 / 39 | 48 / 39 |
| v3 development, /112 | 52 / 53 | 49 / 50 | 56 / 53 | 56 / 46 |
| Selected v1 held out, /54 | 18 / 22 | 21 / 21 | 24 / 11 | 12 / 21 |

V2 removes the mean-stud gate; v3 instead changes only contrast weighting while
retaining all v1 gates. Each produces one incorrect present decision at
img_10/c1r4 with +4 px x initialization: precision 39/40 and 53/54 respectively.
Its spatial discrepancy exceeds the 3–5 px face-boundary annotation uncertainty.
The predeclared no-confident-error-regression condition rejects both changes;
their lighting/coverage gains do not justify a special exception. V1 has no
measured incorrect confirmations in these scored sensitivity cases. It correctly
marks only 1/6 missing slots in the bright, +4 x and +4 y cases, and 0/6 otherwise.

One held-out rotated case flags a conservative lower-fragment envelope overlap
(img_16, −5°, c4r3: 55.3%, center outside). It also matches a positive face;
rotated axis-aligned envelopes can overlap. This is a proxy flag, not proof
of physical lower-layer selection. V3 has a similar development proxy flag.

Nominal long-axis error, over all geometric matches including uncertain ones,
has median/p90 0.124°/0.564° (development n=106) and 0.191°/0.954° (held out n=54).
These largely reflect manual registration. Projected-site residual medians
are 6.31 px (32 development marks) and 4.99 px (16 held-out marks); observed
peaks match only 14/32 and 6/16 within 8 px. Independent [reference audit](results/reference_audit/audit.json)
found many marks on rims/highlights: none of these distances establishes
true stud-center accuracy. Original references and raw measurements stay frozen.

Acceptance required ≥95% scored present precision **and ≥80% positive coverage**,
at least 5/6 correct nominal missing decisions, and zero flat confirmations.
V1 fails coverage and missing-decision targets. It is not a verified three-way
occupancy system or a picking demonstration.

## Reproducibility and artifacts

Existing runtime: Python 3.11, NumPy 1.26.0, OpenCV 4.10.0.84; no shared package
changes. This geometric baseline has no trained weights. Historical neural
versions and weight hashes remain in the separate detector report.

| Pueue job | Purpose | Evaluated source |
| --- | --- | --- |
| 1667 | v0 development, 40 observations | `2ccb3ac` |
| 1668 | Evaluation-only v0 marked-point diagnostic | `94cd781` |
| 1669 | v1 development, 40 observations | `4106bdc` |
| 1670 | v2 development, 40 observations | `1554d5c` |
| 1671 | v3 development, 40 observations | `e8ab714` |
| 1672 | Selected-v1 held out, 20 observations | `12dd890` |

All batches used default Pueue with stable code/config/input snapshots; global
concurrency was unchanged. Source, file hashes, settings, job IDs, summaries and
full scored results are in [results/](results/). Predictions/overlays for each
run remain in the ignored `runs/` directory named by its provenance/manifest.
The final held-out snapshot is
`runs/20261024T001228.831310Z-known-layout-v1-heldout/`.

From the repository root, on a clean committed perception tree, the following
commands submit reproduction jobs and print their IDs:

```bash
python3 perception/evaluation/submit_evaluation.py \
  --config perception/configs/baseline_v1.json --tag v1 --split development
python3 perception/evaluation/submit_evaluation.py \
  --config perception/configs/baseline_v1.json --tag v1 --split heldout
```

For rejected versions, inspect their source commit in an isolated checkout and
use the saved evaluated configuration; do not silently run v2/v3 through v1.
The submitter selects the existing Conda runtime. Seven small geometry/sanity
tests and five independent scorer tests passed. Final changes after job 1672
are reporting only.

Representative overlays: [held-out img_13](results/v1_heldout/overlays/img_13__nominal.jpg),
[held-out img_16](results/v1_heldout/overlays/img_16__nominal.jpg), and the
[rotated proxy case](results/v1_heldout/overlays/img_16__rotation_m05.jpg).
Green is present, amber uncertain, red missing; labels retain manual/nominal
calibration disclosure. Machine-readable per-candidate predictions include
polygons, image orientations, stud sites, scores, reasons and layer uncertainty.

## Pause and the next decision

Remaining confidence changes repeatedly promote a wrong spatial hypothesis.
Further threshold patches or per-strip warps are not justified by this evidence.
Before another bounded perception iteration, obtain:

1. A verified reference footprint/current visible layer description for the
   inspection view, plus independently checked geometric stud-center marks and
   clear complete/missing-face examples. The irregular outer strip needs a
   physical layer/phase explanation rather than a label-fitted warp.
2. D435i intrinsics at the actual RGB resolution and a fixed baseplate/reference
   frame (a small nearby marker board is one possible later choice). Wrist
   housing offsets alone do not define an optical transform. No close-range
   depth or metric pose accuracy is inferred from these JPEGs.
3. For simulation, two explicit repeating layer origins on a stud grid. The
   original stack is **ten 6×6 layers, 360 bricks**, alternating 90°. Alternation
   alone does not determine the one-stud translation axes/sign/phase or whether
   they repeat. Current photographs were taken after layer removal.

The [full-stack geometry gate](../detection_20261024/simulation/geometry_spec.json)
remains blocked: no guessed origins, smaller final stack, simulated detections
or real/sim equivalence are presented. The eventual renderer must preserve
native inter-brick/baseplate connections and feed only rendered pixels to the
same perception function; identities/poses are evaluation-only.

The next decision is whether to supply this small geometry/calibration/reference
capture set for a separately scoped iteration. No further algorithm work,
simulation, training, ROS integration or manipulation follows automatically.
