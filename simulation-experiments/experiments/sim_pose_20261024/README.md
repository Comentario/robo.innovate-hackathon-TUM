# Bounded simulation RGB pose experiment

Completed: [results and failure analysis](REPORT.md). Job 1683 succeeded in
execution, but the frozen method accepted no poses; all candidates stayed
uncertain. Job 1682's evaluator serialization failure and unchanged retry are
recorded separately.

Scope: use the five existing corrected 300-brick renders to test image-supported
individual-brick pose refinement and layer consistency, with one frozen method
and settings across all views. No new render, learned model, training, robot
control or insertion trial.

This is an assisted known-layout experiment. Intended brick geometry and
configured virtual camera calibration may seed hypotheses. Actual simulator
brick poses, identities, visibility samples, depth and connection state are
reserved for the independent evaluator. Metric error of a configured layout
prior alone is not detection performance.

Conditions are frozen before batch evaluation: nominal design prior; a common
prior registration offset of +0.8 mm X, −0.6 mm Y and +0.3° yaw about the plate
center; and one mean-solid RGB negative control per view with the nominal prior.
The same five images are correlated views of one fully occupied static stack.
Blank controls establish image dependence, not real missing-brick accuracy.

The method searches 60 intended slots in the top and immediately lower layer
only (layers 9/8). It rectifies RGB at each nominal stud plane and reuses the
unchanged `perception.algorithm.Evidence` circular-gradient features. Supported
stud maxima provide measured image points. A bounded robust fit estimates
body-bottom-center X/Y/Z and yaw; roll/pitch remain fixed upright. Continuous
height is retained, with separate nearest-layer classification. Weak evidence,
active optimization bounds, poor conditioning or incompatible height produce
uncertainty. No pose is emitted solely because a slot is projected. No NMS is
applied; duplicates remain visible to evaluation. Settings are frozen in
[config.json](config.json), and independent scoring is fixed in
[evaluation/protocol.json](evaluation/protocol.json).

The linearized uncertainty assumes a one-pixel feature-noise floor and excludes
calibration/model errors. It is a conditioning check, not a calibrated accuracy
guarantee or insertion tolerance. The configured synthetic calibration is much
easier than uncalibrated real wrist images. Perception receives no depth or
saved actual camera/brick poses. The nominal calibration generator reuses
existing scene-design helpers; its source is included in the snapshot.

All batch image processing and evaluation run through `pueue add` in the default
queue, using a stable source/configuration/input snapshot and the existing
OpenCV/NumPy/SciPy runtime. Shared environments and scheduler settings stay intact.

After committing scoped source/configuration, from the repository root:

```bash
python3 experiments/sim_pose_20261024/submit.py
```

The submitter copies RGB and allowed geometry/calibration/features into an
inference directory, while actual simulator truth and the independent evaluator
are staged separately under `scoring_only/`. It prints the immutable snapshot
path and default Pueue job ID. No application shutdown or physics execution is
involved in this image-only batch.
