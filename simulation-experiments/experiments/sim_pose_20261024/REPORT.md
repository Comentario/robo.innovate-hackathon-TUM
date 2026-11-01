# RGB pose refinement on the corrected simulation views

**The frozen method did not produce a supported top-brick pose.** Execution and
independent evaluation completed, but every candidate remained uncertain.
This is a failed manipulation-perception baseline, not evidence that RGB pose
estimation or the camera itself cannot work.

The input is the existing 300-brick scene: ten layers of six ridges with five
bricks each. Five correlated 1280×720 renders contain 30 complete visible top
faces each. Each image receives 60 intended-layout hypotheses: 30 in layer 9
and 30 in the immediately lower layer 8. No additional render or model was run.

| View | Nominal fits attempted, top/lower | Offset-prior fits attempted, top/lower | Accepted top poses | Misses per condition |
|---|---:|---:|---:|---:|
| Overhead | 5 / 6 | 2 / 1 | 0 / 30 | 30 |
| Small X tilt | 5 / 6 | 5 / 3 | 0 / 30 | 30 |
| Small Y tilt | 7 / 5 | 3 / 2 | 0 / 30 | 30 |
| Front oblique | 9 / 14 | 6 / 12 | 0 / 30 | 30 |
| Side oblique | 11 / 1 | 10 / 4 | 0 / 30 | 30 |
| Total across views | 37 / 32 | 26 / 22 | 0 / 150 per condition | 150 |

A numerical fit attempt follows the image-feature gates but precedes fit-quality
and conditioning gates. It is not an accepted detection. The front oblique
view supplies more attempts overall; the side oblique supplies the most
nominal top-seeded attempts. Neither establishes a successful view for control.

Per condition, accepted-face recall and top-target coverage are **0%**; precision
is undefined because there are no accepted declarations. All 150 top hypotheses
remain uncertain. Accepted merges, duplicates and lower-layer selections are
zero because the method abstains completely; those zeros do not demonstrate
reliable instance separation or layer recognition. All lower-seeded candidates
also remain uncertain. Five mean-solid negative controls yield zero fits and
zero accepted declarations, verifying feature dependence only.

## Rejected fit errors and prior comparison

Actual simulator root poses and camera records are evaluator-only. Prior/fit
association uses nearest metric identity independently of supplied slot IDs.
The following numbers include rejected top-seeded fits; they are diagnostics,
not localization accuracy for an accepted system.

| Condition / estimate | N | Median position error | P90 position error | Median yaw error, modulo 180° |
|---|---:|---:|---:|---:|
| Nominal intended-layout prior | 150 | <0.00003 mm | <0.00003 mm | ≈0° |
| Nominal image fits, rejected | 37 | 6.34 mm | 9.93 mm | 1.37° |
| Offset intended-layout prior | 150 | 1.06 mm | 1.33 mm | 0.30° |
| Offset image fits, rejected | 26 | 6.51 mm | 9.99 mm | 0.76° |

These rows have different sample counts: priors cover all top hypotheses, while
fit rows include only candidates with enough feature evidence to attempt fitting.
Paired per-candidate errors are retained in the machine-readable evaluation.
The offset prior's largest position error is 1.53 mm; the rejected fits do not
recover that small misregistration. The nominal prior is nearly exact because
it comes from the same scene design, not because a detector localized the bricks.

Median rejected top-fit XY / absolute-Z errors are **3.00 / 5.43 mm** nominal
and **3.68 / 5.04 mm** with the offset prior. Nominal lower-seeded rejected fits
have median position error 5.51 mm (N=32); offset lower-seeded fits have
5.28 mm (N=22). Continuous height is retained, never snapped to a layer.

| Nonexclusive rejection reason among attempted fits | Nominal, N=69 | Offset, N=48 |
|---|---:|---:|
| Height conditioning above frozen limit | 69 | 48 |
| XY conditioning above frozen limit | 68 | 48 |
| Active optimizer bound | 60 | 42 |
| Reprojection RMS >1.5 px | 60 | 42 |
| Height inconsistent with a nominal layer | 43 | 36 |
| Yaw conditioning above frozen limit | 33 | 22 |

Before fitting, weak or insufficient distributed stud evidence removes many
other hypotheses. The saved feature maxima are gradient-pattern observations,
not validated geometric stud centers. Their inconsistent offsets can drive
scale/height and lateral corrections to search bounds. The one-pixel noise-floor
conditioning test is a frozen engineering assumption, not measured camera
uncertainty. These results do not justify relaxing it to manufacture acceptance.

Independent review found no camera-axis, stud ordering, root-origin or stud-cap
height convention mismatch. The feature/pose failure therefore remains the
reported outcome. Both independent evaluation and final interpretation review
accepted this negative result; no further method run was requested.

## Method and scoring

RGB is rectified at each nominal layer's stud-cap plane. The unchanged
`perception.algorithm.Evidence` radial-coherence feature searches around the
intended stud sites. Six of eight supported studs, both long ends, mean evidence,
contrast and edge support are required. A robust bounded fit estimates upright
body-bottom-center X/Y/Z and yaw from the observed image points. Roll/pitch,
footprint, layout, camera calibration and candidate search layers are supplied
priors; this is not arbitrary object detection or free six-DOF recovery.

All views use the same [frozen settings](config.json). Conditions: nominal prior;
one fixed registration change of +0.8 mm X, −0.6 mm Y and +0.3° yaw about the
plate center; and each image's per-channel-mean solid RGB control. No NMS is
applied. There is no SAM inference, learned model, training, depth input,
manual image registration or annotation input in perception.

Primary scoring uses historical one-to-one face-envelope IoU ≥0.50 rules,
with merged boxes ineligible, then duplicate/lower/ambiguity/unresolved categories.
The independent metric association gate is 8 mm, **an identity gate rather than
an insertion tolerance**. All image-matched pose errors and prior-associated
rejected fits remain available without discarding gross errors through that gate.
Lower-face visibility references use eight depth samples, not exact visible masks.
The [protocol](evaluation/protocol.json) freezes the reference counts, association
rules and limitations before processing.

Calibration is derived only from intended scene geometry and virtual camera
presets, through existing design helpers. It is an easy, nearly exact synthetic
calibration assumption, not measured D435i intrinsics/hand–eye calibration.
The images all show the same fully occupied static stack. There are no real
missing-brick cases, independent-stack samples, grasp-accessibility validation,
held-brick transform measurements, contact steps or insertion trials here.

## Artifacts and reproduction

Representative uncertainty overlays:

- [Nominal overhead](results/predictions/nominal/top/overlay.png)
- [Nominal front oblique](results/predictions/nominal/oblique_front/overlay.png)
- [Offset-prior side oblique](results/predictions/perturbed/oblique_side/overlay.png)

Yellow outlines/points are uncertain candidate fits or priors, never accepted
robot targets. `L9->9` means a fitted nearest-layer hypothesis; it does not
mean the fit passed. Blue would mean supported lower surface, green supported
top; neither occurs. Candidates with fewer than three supported studs are
omitted from overlays but retained in JSON.

All 15 per-view/condition prediction JSONs, feature observations, continuous fits,
reasons, conditioning estimates and overlays are under [results/predictions/](results/predictions/).
The [full independent evaluation](results/evaluation/evaluation.json) includes
per-candidate prior/fit errors, associations and raw failure counts.
[Provenance and hashes](results/provenance.json) identify every packaged artifact.

Execution used **default Pueue job 1683**, source **64a1df8**, snapshot
`runs/20261024T123115.523960Z-sim-rgb-pose`; it succeeded. Original method/config
freeze: **0a616f1**. Job [1682](attempts/1682.json) completed perception but failed
while serializing a NumPy scalar in the evaluator's JSON report. The retry
changed only result serialization and reporting counters. All 15 prediction
JSON files are byte-identical across the two jobs; algorithm, settings,
calibration, geometry and Evidence source are unchanged. Both runs remain saved.

Runtime: Python 3.11.15 at
`/home/faps/miniforge3/envs/unitree_sim_env/bin/python`, OpenCV 4.10.0,
NumPy 1.26.0, SciPy 1.15.3. No shared dependency or scheduler changes.

```bash
python3 experiments/sim_pose_20261024/submit.py
pueue log <reported-job-id> --lines 30
```

The submitter requires committed scoped source/settings, verifies RGB hashes,
and freezes inference inputs separately from evaluation truth. All batch
processing/evaluation uses `pueue add` in the default queue.

## Recommendation

**Require further work; this per-brick RGB feature/height fit is unsuitable for
feeding grasping or stacking control.** Keep it as an auditable failed baseline.
The next small investigation should verify actual stud-center measurements and
estimate one observed layer plane over a wider feature baseline, then test
per-brick in-plane refinement against it. That proposal follows the observed
feature and depth-conditioning failures; it has not been implemented or proven.
Real calibration and the held-brick transform remain separate requirements.
No automatic follow-up experiment, training or manipulation is started.
