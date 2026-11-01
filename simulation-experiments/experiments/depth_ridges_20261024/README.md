# Uppermost ridge direction from depth

Completed: [results and direction overlays](REPORT.md). Job 1684 succeeded:
five supported original simulated-depth views, maximum angular error below
0.112°, and all ten invalid/flat controls uncertain. This is orientation only.

Bounded task: infer the undirected direction of the highest visible ridge layer
from the five existing depth images of the corrected 300-brick scene. No brick
pose fitting, training, rendering, ROS integration or hardware control.

Depth is now an explicitly authorized sensor input. Its files were originally
stored under the renderer's `evaluation_truth/` directory, but their role here
is optical-axis distance in meters. Simulator brick poses, identities and known
layer orientation remain evaluator-only.

Perception receives depth, configured nominal camera intrinsics/extrinsics, and
an approximate source-plate XY region. RGB is used only for display overlays.
No stack height, brick count, layer number, stud lattice or brick yaw is passed
to the estimator. World-height selection handles perspective instead of taking
the nearest depth pixel. Individual elongated components establish ridge axes;
global footprint PCA can choose the transverse stack direction and is avoided.

Frozen method: sample every second depth pixel, keep near-horizontal surfaces
within 20° and neighboring height jumps below 4 mm, then find the highest
supported downward 3 mm band using 1 mm bins. Support must occupy at least 1%
of the configured plate ROI. Rasterize at 1 mm and apply 3×3 closing, then use
elongated connected-component PCA and long-edge Hough agreement. At least two
elongated components/lines, axial concentration 0.8 and agreement within 10°
are required. The angle remains continuous and undirected modulo 180°.
All settings are fixed in [config.json](config.json); [protocol.json](protocol.json)
defines the independent scoring.

Five original rendered depth maps and invalid/flat-plane controls use the same
code. Internal condition `real` means the unmodified rendered input, not a
physical D435i capture. Invalid/flat controls should abstain. These exact
renderer depth maps do not model or validate real-camera depth noise.

All batch depth/image processing and scoring use `pueue add` in the default
queue with an immutable source/configuration/input snapshot. The existing
OpenCV/NumPy runtime is reused. No shared environment or scheduler changes.

After committing scoped source/settings:

```bash
python3 experiments/depth_ridges_20261024/submit.py
```

The submitter freezes sensor inputs, calibration and code separately from
evaluation-only simulator roots/manifest, then reports the snapshot and Pueue
job ID. The batch saves direction JSON, top-band masks/height visualization and
RGB direction arrows per view; RGB never enters the direction estimator.
