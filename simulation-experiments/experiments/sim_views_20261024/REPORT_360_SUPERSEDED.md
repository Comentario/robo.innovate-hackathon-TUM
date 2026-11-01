> Superseded by the user’s correction to six ridges of five bricks per layer (300 total). These historical 360-brick renders are preserved unchanged. See [current report](REPORT.md).

# Full-stack simulation views

Five **1280×720 RGB views** and a [comparison panel](results/panel.png) are available.
The full stack has **360 bricks: ten layers of 6×6**, alternating by 90°, with
two-stud gaps between parallel rows. All views share one unchanged initialized
state and lighting. The panel combines images for inspection; no perception
or multi-view fusion was run.

| View | RGB image | Purpose |
|---|---|---|
| `top` | [Overhead](results/images/top.png) | Straight-down view of the ridges and openings |
| `near_top_x` | [Slight X tilt](results/images/near_top_x.png) | Small change in occlusion from overhead |
| `near_top_y` | [Slight Y tilt](results/images/near_top_y.png) | Orthogonal small change in occlusion |
| `oblique_front` | [Front oblique](results/images/oblique_front.png) | Top surfaces and stack sides |
| `oblique_side` | [Side oblique](results/images/oblique_side.png) | Perpendicular ridge direction and sides |

The user's close-up supports the local one-stud crossing/stagger: horizontal
layer origin `(1,0)`, perpendicular layer origin `(0,1)`, on a four-stud pitch.
This supersedes the earlier rough common-center interpretation. The photograph
establishes the local phase; the complete ten-layer inventory comes from the
user's specification. The computed per-interface contact totals are one brick
with one engaged stud, ten with two, and 25 with four; this does not claim every
hidden corner has one. [Geometry and evidence hash](geometry_360_superseded.json) preserve
that distinction.

| Check | Result |
|---|---|
| Bricks / connected parts including source plate | 360 / 361 |
| Genuine native links | 1,125: 1,089 interlayer + 36 baseplate |
| Each adjacent-layer interface | 121 single-stud overlap patches |
| Maximum actual PhysX position / orientation error | 1.86×10⁻⁸ m / 2.98×10⁻⁸ rad |
| Maximum actual USD position / orientation error | 1.40×10⁻¹⁶ m / 0 rad |
| Actual velocities | Zero |
| State, graph and physics time across all views | Unchanged |
| Post-connection physics steps | Zero |

Independent review and evaluation accepted the capture. The evaluator checked
all 360 body/stud bounding corners against each saved camera: every stack corner
lies inside every image. Five distinct camera poses produced five distinct RGB
files; the combined panel is a labeled tiling of those views.

These are **static initialized renders**, with native connections present.
Load-bearing stability, clutch forces, grasping and disassembly are unvalidated.
Camera settings are nominal virtual pinhole parameters, not measured D435i
intrinsics or calibrated wrist poses. Materials/colors and lighting are visual
placeholders. Visibility sampling in the separate evaluation truth is not
detector output, pixel-exact segmentation or physical accessibility.

Execution used **default Pueue job 1680**, source checkpoint `f7b9fd4`, snapshot
`runs/20261024T103123.341921Z-sim-views`. The validated-capture marker was written
after all images, graph and pose checks. Normal Isaac application cleanup then
stalled; the orchestrator stopped the job to release the queue. Consequently
Pueue records **Killed**, while capture validation passed. Clean shutdown is
not claimed. [Shutdown record](results/shutdown.json) records this separately.

Earlier jobs remain explicit diagnostics: [1677](attempts/1677.json) was stopped
for geometry clarification; [1678](attempts/1678.json) failed native graph
initialization; [1679](attempts/1679.json) created diagnostic images but was
rejected for reset-induced geometry drift. No rejected frame is packaged here.

Reproduce from the repository root using the existing runtime:

```bash
python3 experiments/sim_views_20261024/submit.py --views top
python3 experiments/sim_views_20261024/submit.py --views top,oblique_front
python3 experiments/sim_views_20261024/submit.py --views all
pueue log <reported-job-id> --lines 30
```

Each submission freezes source, dependency and configuration hashes in a new
run directory and queues inference-free rendering with `pueue add` in the default
queue. Source/config changes must be committed first. [Camera settings](cameras.json)
contain the five editable presets. If cleanup stalls after
`CAPTURE_COMPLETE_VALIDATED`, inspect `output/run_complete.json` and
`output/shutdown.json` in that run, then stop only that job with
`pueue kill <reported-job-id>`. A killed job without validated outputs is not a
successful capture.

The existing FR3 scene, stock gripper, assets and runtime were reused. Versions:
Isaac Sim 5.1.0.0, Isaac Lab 2.3.2, BrickSim
`0.1.0.dev645+gcbd5de3`, Torch `2.7.0+cu128`, NumPy 1.26.0 and Pillow 11.3.0;
Python `/home/faps/miniforge3/envs/unitree_sim_env/bin/python`, RTX 5070 rendering
with CPU physics. No dependency or global queue settings changed.

[Capture manifest](results/manifest.json), [actual placement checks](results/placement_checks.json),
[provenance and image hashes](results/provenance.json), and separate
[camera truth](results/evaluation_truth/cameras.json) /
[native graph](results/evaluation_truth/native_graph.json) are packaged alongside
the RGB files. Raw depth arrays, full USD, visibility samples and frozen physics
state remain under the snapshot's `output/evaluation_truth/` directory.
