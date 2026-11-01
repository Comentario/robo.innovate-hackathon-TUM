# Known-layout geometric evidence baseline

This is the new perception path. The pretrained detector experiment remains
historical under `experiments/detection_20261024/` and is not imported here.

`algorithm.analyze(image_bgr, registration, config)` accepts pixels, a manually
supplied **global** four-corner registration and an observed-window layout.
It never reads reference instance polygons, manual stud labels, neural model
predictions, or simulator identities/poses. The frozen independent evaluator
owns those reference files and the development/held-out split.

The current photographed window is six parallel strips with five visible
four-stud groups, spanning 22 by 20 stud units. This supplied window is not a
replacement for the original 360-brick input or an invented description of its
hidden layers. It is a deliberately approximate image-space reference: the
first outer strip is irregularly spaced in some photographs and may belong to
a lower layer. No separate per-strip registration is used to force alignment.

## Baseline v0

1. Rectify the supplied global footprint to 24 pixels per stud. Manual anchors
   determine the initial registration; this is not automatic localization.
2. Evaluate projected stud locations with radial gradient concentration,
   angular coverage and grayscale contrast. Three radii surround the known
   nominal stud radius of 0.3 times the 8 mm pitch. Polarity is ignored so the
   test does not depend on shade or the direction of the highlight.
3. Refine only a bounded **global translation** using the median displacement
   of sufficiently supported stud features. Sixteen inliers, about two bricks'
   worth of studs, are required. The maximum correction is 0.15 stud; the
   consensus radius is 0.075 stud. It cannot fit individual labels or strips.
4. Score long and short outline gradients independently. Long edges receive
   more weight because the gaps often expose them; same-color touching end
   seams are not required to be strong.
5. Fit an approximate planar camera using nominal intrinsics, then project a
   local orthogonal brick counter-pattern one and two 9.6 mm body heights
   behind the reference plane. This is a counter-hypothesis, not a recovered
   hidden layer or calibrated metric pose. If the fit cannot reproduce the
   supplied quad within 8 image pixels, lower-plane evidence is unavailable.
6. Return `present`, `missing` or `uncertain` with all feature scores. Present
   requires at least six of eight supported stud sites, including both end
   rows, plus weak edge support and no stronger lower-pattern explanation.
   Missing requires strong orthogonal lower evidence and weak expected-top
   support. Blank/low-contrast regions become uncertain, never present merely
   because a grid cell exists.

All thresholds are global, frozen before batch evaluation. They are initial
design choices, not demonstrated calibrated operating limits. Observability
is a clipped local 90th–10th intensity-percentile range. The initial 35-level
contrast scale and decision thresholds are judged against fixed development
evaluation, rather than tuned for individual images.

## V1: radial-coherence feature correction

The v0 development evaluation confirmed zero present instances among 112
reference faces. Diagnostic Pueue job 1668 then evaluated the unchanged v0
feature at 32 historical development stud marks: all fixed-mark scores
were zero despite median observability 0.786. The radial mean divided by the
whole-patch gradient mean plus 2 was always below 1 (maximum 0.669), so the
subsequent subtraction and clamp erased the evidence at those locations. The patch mean included
strong seams and shadows away from the sampled ring.

Subsequent independent visual audit found that some historical stud marks lie
on cap rims/highlights rather than validated centers. They remain frozen for
consistent comparison, but distances to them are not a calibrated stud-center
accuracy measurement. The diagnostic must not be described as probing true
centers. V1's measured visual-face coverage gain is separate evidence and
does not depend on relabeling these marks.

V1 changes only the circular-gradient evidence model:

```
coherence = sum(abs(gradient dot radial_direction)) / sum(gradient_magnitude)
circle_alignment = clip((coherence - 2/pi) / (1 - 2/pi), 0, 1)
support = fraction(radial_gradient > max(median_local_gradient, 0.5))
stud_score = circle_alignment * support * sqrt(observability)
```

The normalization compares directions on the same annulus. `2/pi` is the
expected absolute radial alignment of isotropic gradient directions. Angular
support limits the response to a straight seam intersecting only a few ring
angles. The local median avoids the demonstrated seam-contaminated mean;
0.5 intensity level is a fixed weak-gradient/noise floor, an initial global
design choice rather than a required Sobel quantization limit. These are
global feature definitions, not fitted per-image thresholds.

`configs/baseline_v1.json` retains **all** v0 radius, search, registration and
decision settings unchanged. Its explicit `feature_model=ring_coherence_v1`
selects the correction; `baseline_v0.json` selects `whole_patch_radial_v0`
and retains the exact old formula. Old unversioned configurations also default
to the v0 model, rather than silently changing a historical result. V1 is the
selected working baseline after independent development evaluation: 37/112
visual faces confirmed, zero measured incorrect confirmations, and 0/6 missing
faces confirmed on nominal inputs. It does not meet demonstration acceptance.
Later v2/v3 changes were rejected and reverted after sensitivity regressions.
See the [experiment report](../experiments/known_layout_20261024/REPORT.md)
for the final held-out audit, limitations and stopping decision. Nonzero feature
scores alone do not establish success.

`decision=present` establishes only supported **visual face presence** under
the supplied window. `layer_hypothesis` expresses top/lower compatibility;
`layer_verified` stays false because actual top height, full geometry and
camera extrinsics have not been established. This is not a pickability,
robot-frame pose, calibrated height, or grasp-accessibility result.

## Registration format

The canonical coordinates use `u` across six strips and `v` along the five
four-stud groups. Four `canonical_quad_xy` anchors map `(0,0)`, `(22,0)`,
`(22,20)`, `(0,20)` in stud units to image pixels. Thus horizontal and vertical
views have different corner ordering. The operator supplies these global
anchors and the visible window orientation; the algorithm does not infer them
from evaluation labels. Current physical layer indices remain null.

## Execution and evaluation

The existing Python 3.11 runtime supplies OpenCV and NumPy. No packages are
installed into the shared environment. `python -m perception.run` is the
evidence-only batch entry point and requires the Pueue snapshot environment.
The independent evaluator submits fixed nominal/lighting/rotation/registration
perturbation cases to the default Pueue queue. Evaluator-owned references are
used only after prediction. The program does not import Isaac, ROS or Torch,
or start hardware control, simulation, training or manipulation.

Simulation evaluation remains blocked until the original repeating layer
origins are confirmed. No smaller final benchmark or guessed 360-brick geometry
is substituted. Any later simulation uses the same image evidence code and
keeps simulator truth exclusively in evaluation.
