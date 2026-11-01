# Depth-assisted individual brick detection

Completed: [results and overlays](REPORT.md). Job 1685 succeeded. Raw geometry
matches all 150 top-face observations, while the stricter checks confirm 27
with no observed false matches; 123 remain uncertain. Raw slots are not
automatically confirmed detections.

Bounded task: use the successful depth-selected upper surface and ridge direction
to identify individual 2×4 brick hypotheses on the five existing corrected-stack
views. No new rendering, training, learned model, ROS or hardware control.

Reuse the unchanged depth-band/ridge module and calibration. Perception receives
only original depth/RGB, camera calibration, source-plate ROI and nominal 32×16 mm
brick footprint. No scene layout, brick count, layer number, known yaw, actual
brick poses or annotations are input. RGB stud features are presence evidence,
not a new unconstrained per-brick Z/PnP pose fit.

Measured ridge ends and metric length establish an integer chain; five bricks
per ridge is not hard-coded. Collinear segments share phase across gaps. A slot
is a hypothesis until its own depth/RGB evidence passes; weak or unobserved
regions remain uncertain. Current observed extent does not reveal missing end
bricks. Internal boundaries retain observed-seam versus inferred-model status.

All parameters and independent evaluation rules are frozen before one default
Pueue batch. Original simulated sensors plus invalid-depth/flat-plane controls
use identical code. These fully occupied views do not test real missing bricks,
independent-stack generalization or insertion accuracy.

Frozen method: group collinear top-band mask fragments; check the measured
ridge width against 16±4 mm. Both current ends need inside top coverage ≥0.6,
outside top coverage ≤0.2 and actual observed lower-depth support ≥0.5.
An integer number of 32 mm footprints must explain the measured span within
4 mm. No candidate is present unless it has ≥70% closed depth-derived top-band
mask coverage, at least
four supported RGB studs distributed across both ends/rows, and long-side edge
support ≥0.12. RGB cross-edges within ±2 mm may verify a boundary; their absence
does not automatically shift or reset the chain. Settings and scoring are fixed
in [config.json](config.json) and [evaluation/protocol.json](evaluation/protocol.json).

Positions use the common depth-measured surface plane and ridge axis, not
independent per-brick six-DOF pose estimates. The nominal 32×16 mm stud footprint
is a class/geometry prior, not a measured manufactured-brick envelope.

After committing scoped source/settings:

```bash
python3 experiments/depth_bricks_20261024/submit.py
```

The submitter verifies the upstream depth code/settings against successful job
1684, freezes all inputs and prints the default Pueue job ID. Perception and
evaluation truth are staged in separate directories. Internal condition `real`
means original simulated depth/RGB; invalid and flat-plane controls are also
processed. Physical camera validation is outside this experiment.
