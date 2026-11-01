# Known-layout perception: bounded implementation plan

This is the current perception work. The pretrained comparison in
`experiments/detection_20261024/` is historical and is not imported by the new
execution path. Historical checkpoint: `2a3431a`.

The implementation planner and independent reviewer explicitly agreed on this
baseline before implementation. An independent evaluation agent owns reference
inputs, protocol and measurement code; the implementation agent owns image
processing and candidate decisions. The orchestrator checkpoints evaluated
states and approves one bounded improvement at a time.

## Baseline

Use the existing Python/OpenCV/NumPy runtime, without detector training or a new
framework. Given an explicitly supplied observed grid window, plane hypothesis
and coarse manual global registration, project the brick/stud geometry, refine
global registration with bounded image-feature consensus, and score expected
faces from grayscale stud-pattern and boundary-edge evidence. Consider local
perpendicular/lower-pattern alternatives and return present/missing/uncertain
with separate conditional layer evidence. Include interpretable overlays.

The initial real-image window describes the photographed six strips and five
visible four-stud groups; it is not a replacement for the original 360-brick
stack. An irregular outer strip is a measured registration/model uncertainty,
not justification for per-strip/per-brick fitting to reference annotations.
Registration inputs must not contain reference instance polygons, stud labels,
model predictions or simulator truth. Manual assistance, supplied layer
information and nominal/approximate calibration must remain visible in outputs.

## Fixed evaluation

Preserve the 166 historical visual-face positives, 14 ambiguous regions, 23
non-exhaustive lower fragments and 48 manually marked studs. These references
do not prove calibrated current top-layer height. The evaluation agent may
freeze independent supplementary complete-face-missing labels before seeing
new outputs; it must not change historical labels to favor the implementation.

Development views: groups A/B/C (`img_1`, `img_3`, `img_7`, `img_10`). Reserve
the entire D arrangement (`img_13`, `img_16`) from implementation tuning.
Held-out evaluation is performed after the best development baseline is chosen.
If comparing frozen versions on held-out views, none may then be selected or
adjusted using those results. Repeated views remain correlated.

Conditional visual-face acceptance targets: at least 95% present-decision
precision with at least 80% positive coverage; missing-face performance must
state its limited observed denominator (proposed five of six clear image-plane
missing cells). An all-uncertain system is not acceptable. A blank-image sanity
case must produce no confirmed-present faces. These are not acceptance criteria
for calibrated exposure, robot-frame pose, insertion or physical accessibility.

Report misses, merged/duplicate candidates, lower-fragment selections, correct
and wrong decisions, uncertainty and coverage. Measure image orientation and
stud registration error only where independent references permit. Fixed
lighting, rotation and small initialization-error sensitivity cases use
consistent transformed observations/references; the exact protocol is frozen
under `perception/evaluation/` before implementation evaluation.

## Iteration discipline

1. Independently evaluate the moderately complete baseline.
2. Identify one dominant measured failure and one testable hypothesis.
3. Obtain independent review of benefit and complexity.
4. Commit the evaluated current source/configuration and small evidence.
5. Implement only that coherent change; repeat the same development evaluation.
6. Accept only with supporting evidence, or revert only the unsuccessful change
   while preserving its record. Do not accumulate image-specific exceptions.

Do not stop at the first evaluation. Continue bounded improvements while a
convincing failure-driven improvement exists. Stop and report the best baseline
when the targets are met, further benefit is unconvincing, new observations or
calibration are needed, or the next meaningful step expands scope.

## Persistent dependencies and exclusions

The original stack is ten layers of 6×6 (360 bricks), with alternating 90°
orientation. Its exact repeating origins, current layer indices and D435i
calibration remain unresolved. The historical geometry gate is retained; no
invented offsets or smaller simulated benchmark is allowed. Real image-plane
work can proceed independently, but true height/exposure claims and the full
simulation comparison remain conditional on those inputs.

All batch perception evaluation, simulation and rendering use `pueue add` in the
default queue with frozen snapshots and reported IDs. No global concurrency or
shared environment changes. No ROS, manipulation, robot motion, neural-network
training or unrelated infrastructure is authorized.
