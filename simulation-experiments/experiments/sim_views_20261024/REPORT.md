# Symmetric 300-brick simulation views

The user corrected the layout to **six parallel ridges of five bricks per
layer**: 30 bricks per layer, ten layers, **300 total**. Successive layers
rotate by 90°, with two-stud gaps between parallel ridges. The 20×22 / 22×20-stud
footprints now share a center. The earlier [360-brick report and images](REPORT_360_SUPERSEDED.md)
are superseded and preserved unchanged.

The corrected [five-view panel](results_300/panel.png) and individual 1280×720
RGB images are complete, using the same camera presets and lighting:

| View | Corrected image |
|---|---|
| `top` | [Overhead](results_300/images/top.png) |
| `near_top_x` | [Small X tilt](results_300/images/near_top_x.png) |
| `near_top_y` | [Small Y tilt](results_300/images/near_top_y.png) |
| `oblique_front` | [Front oblique](results_300/images/oblique_front.png) |
| `oblique_side` | [Side oblique](results_300/images/oblique_side.png) |

Each layer center is `(16,16)` studs on the 32-stud source plate. The local
photo-supported phase remains horizontal origin `(1,0)` / perpendicular origin
`(0,1)`, with a five-stud border. There are 100 single-stud crossing patches per
adjacent layer interface. Whole-brick contact totals are two studs for ten
outer-ridge bricks and four for twenty other bricks, per interface; a one-stud
crossing patch is distinct from the complete contact of one brick.

| Validation | Result |
|---|---|
| Actual source brick assets / spawned brick roots | 300 / 300 |
| Surplus square-factory assets removed before spawning | 60 |
| Connected parts including source plate | 301 |
| Genuine native connections | 930: 900 interlayer + 30 baseplate |
| Maximum actual PhysX position / orientation error | 2.99×10⁻⁸ m / 2.98×10⁻⁸ rad |
| Maximum actual USD position / orientation error | 1.32×10⁻¹⁶ m / 0 rad |
| Brick/baseplate velocities | Zero |
| Physics state, time and native graph between views | Unchanged |
| Post-connection physics steps | Zero |

Independent review and evaluation passed. The evaluator confirmed 30 actual
brick roots in each of ten layers, coincident centers, the native graph and
dual pose checks, and full stack framing in all five distinct views.

These are **static initialized renders**, not load-bearing dynamics validation.
Native links are present, but clutch forces and stability remain untested.
Cameras use approximate virtual pinhole settings, not calibrated D435i/wrist
poses. Colors/materials are placeholders. No perception, fusion, training or
manipulation was run. The panel is a display-only tiling of the individual views.

Execution: **default Pueue job 1681**, source checkpoint `53053fb`, snapshot
`runs/20261024T104724.316246Z-sim-views`. Validated capture completed before
Isaac application cleanup stalled. The orchestrator then stopped cleanup to
release the queue, so Pueue records **Killed**; clean shutdown is not claimed.
[Attempt](attempts/1681.json) and [shutdown record](results_300/shutdown.json)
preserve that distinction.

The existing FR3 scene, stock gripper, BrickSim and runtime are unchanged.
Versions remain Isaac Sim 5.1.0.0, Isaac Lab 2.3.2, BrickSim
`0.1.0.dev645+gcbd5de3`, Torch `2.7.0+cu128`, NumPy 1.26.0, Pillow 11.3.0;
Python `/home/faps/miniforge3/envs/unitree_sim_env/bin/python`, RTX 5070 rendering
and CPU physics. No shared environment or scheduler settings changed.

Reproduce from the repository root with a committed source/configuration:

```bash
python3 experiments/sim_views_20261024/submit.py --views all
python3 experiments/sim_views_20261024/submit.py --views top
python3 experiments/sim_views_20261024/submit.py --views top,oblique_front
```

Every submission freezes source/configuration/dependency hashes and reports its
default Pueue job ID. [Geometry](geometry.json), [camera settings](cameras.json)
and [execution/cleanup instructions](README.md) define the small experiment.
[Capture manifest](results_300/manifest.json), [dual placement checks](results_300/placement_checks.json)
and [provenance/image hashes](results_300/provenance.json) are packaged alongside
the images. Separate [camera truth](results_300/evaluation_truth/cameras.json)
and [native graph](results_300/evaluation_truth/native_graph.json) are for
evaluation only. Raw depth, full USD, visibility samples and frozen physics
state remain under the snapshot's `output/evaluation_truth/` directory.
