# Marmon Challenge 2: FR3 LEGO sorting

The current priority is [alignment with the real `task2/jacob` control stack](experiments/control_alignment_20261026/REPORT.md),
pinned at `13f37da`. The unchanged real Python planner, canonical targets and
motion policy now have an Isaac backend. Offline parity checks pass. The
[startup pose-reader mismatch is resolved](experiments/pose_reader_20261026/REPORT.md)
and independently confirmed on all 300 bricks. Isaac shutdown and full-motion
execution validation remain incomplete. This backend is separate from the legacy DLS/RL scaffold.
Loaded gripper behavior and the full grasp sequence are not yet aligned or validated.

The current simulation demo uses the frozen depth-guided R3 candidate pipeline
and an opt-in pregrasp LEGO color handoff. The [measured progress](docs/demo_progress.md)
and [stage protocol](docs/demo_stage_protocol.md) describe the active work.
The saved handoff replay (1826) passes. The corrected-material regression (1830)
passes its fresh stationary control but still fails free-brick retention; native
extraction and transfer/stacking remain unproven. The operator has now supplied
[working-grasp poses and width observations](experiments/hardware_grasp_reference_20261025/README.md):
20 mm approach, 14 mm closing request and 15.8 mm loaded readback, followed by
straight upward extraction. Their data-only frame comparison does not change
the active simulation or establish pad-gap/engagement-depth calibration. See
the [closed regression](experiments/declared_material_retention_20261025/README.md).


The separate [B/C/D destination planner](experiments/destination_plan_20261025/README.md)
implements the confirmed four-ridge-by-three-brick fill pattern, color routing
and caller-confirmed placement counts. It exports nominal base-frame targets;
it does not establish held-brick compensation, insertion or robot readiness.

The manually assisted, known-layout **v1** under `perception/` is a preserved
real-image baseline; see its [results and stopping decision](experiments/known_layout_20261024/REPORT.md).
It is not an accepted sorting demonstration.
The [pretrained-detector comparison](experiments/detection_20261024/REPORT.md)
is a closed historical experiment with separate execution and artifacts.
The corrected simulation input has **300 bricks**: ten layers, each with six
parallel ridges of five bricks, alternating by 90°. Five corrected
[simulation views and their panel](experiments/sim_views_20261024/REPORT.md) are available;
the [earlier 360-brick views](experiments/sim_views_20261024/REPORT_360_SUPERSEDED.md)
are preserved as superseded geometry. These static renders do not validate
load-bearing dynamics. The legacy 48-brick scene below is separate.

The separate [fixed-prompt SAM 3 experiment](experiments/sam3_20261024/REPORT.md)
is complete. It records raw masks and measured failure modes without changing
the active known-layout baseline.

The [RGB ridge-chain experiment](experiments/ridge_chains_20261024/REPORT.md)
is also complete, with explicit uncertainty, missing-slot evaluation and
comparison to the saved SAM outputs. It does not replace the active baseline.

The [RGB pose experiment on five corrected simulation views](experiments/sim_pose_20261024/REPORT.md)
is complete. Its frozen known-layout feature/pose method accepted no targets;
rejected fits and prior baselines are retained. It is unsuitable for manipulation
control and does not replace the current baseline.

The [depth-only upper-layer ridge direction](experiments/depth_ridges_20261024/REPORT.md)
works on all five simulated views, with maximum angular error below 0.112° and
all ten invalid/flat controls uncertain. It provides a layer orientation cue,
without individual brick poses or physical grasp/placement validation.

The [depth-assisted individual-brick experiment](experiments/depth_bricks_20261024/REPORT.md)
uses that orientation and measured ridge extents to propose all top footprints
in the five views. Depth/RGB checks confirm 27/150 correlated observations
with no observed false matches; 123 remain uncertain. This is selective
candidate confirmation, without complete-coverage or physical-control claims.

Isaac Sim 5.1 / Isaac Lab workcell for the **Franka Research 3**, using native
[BrickSim](https://github.com/intelligent-control-lab/BrickSim) interlocking-brick
physics. The robot type follows the team's confirmed hardware. The supplied
slides refer to a ViperX 300 S for the LEGO demo.

The legacy scaffold described below contains a fixed table, FR3 with its
parallel gripper, a mixed input stack connected to an anchored studded baseplate,
output baseplates and a scrap tray. The alternating lattice layers approximate
the setup photos. Dimensions and layouts are configurable estimates, not a reconstruction calibrated from
images. The default input contains 48 standard 2x4 bricks in three layers.

## Legacy scaffold use

The existing workstation runtime is
`/home/faps/miniforge3/envs/unitree_sim_env/bin/python`. No shared Conda packages
or files in `~/dev/resources/BrickSim` were modified. This project keeps its
pinned prebuilt BrickSim wheel in `.deps/`.

```bash
# Only necessary if .deps is absent. Download/install, no simulation.
bash scripts/setup_dependencies.sh

# Lightweight, simulator-independent task and coordinate checks.
/home/faps/miniforge3/envs/unitree_sim_env/bin/python -m unittest discover -s tests -v

# All commands below submit to the DEFAULT Pueue queue and print a job ID.
python3 scripts/submit.py --mode smoke --steps 180
python3 scripts/submit.py --mode smoke --steps 120 --capture
python3 scripts/submit.py --mode preview --steps 1800
python3 scripts/submit.py --mode smoke --recipe single_shade --steps 180

# Small learning curriculum: start with one brick before scaling up.
python3 scripts/submit.py --mode train --cells 1 --layers 1 --timesteps 100000
python3 scripts/submit.py --mode train --cells 1 --layers 2 --timesteps 200000 \
  --checkpoint runs/<previous-training-snapshot>/policy.zip

# Full workcell training; this is an experiment, not a pretrained solution.
python3 scripts/submit.py --mode train --timesteps 1000000
python3 scripts/submit.py --mode evaluate --steps 5400 \
  --checkpoint runs/<training-snapshot>/policy.zip

pueue status
pueue log <job-id> --full
pueue kill <job-id>
```

Preview holds the arm and displays the workcell for the requested number of
control steps. Training runs PPO on CPU with one CPU PhysX environment. The
native connection solver is not a GPU-vectorized RL backend. Do not scale this
to thousands of cloned environments without a separate compatibility study.

Each submission copies the code, effective configuration, checkpoint (if any)
and BrickSim package into `runs/<timestamp>-<mode>/`. `manifest.json` records
SHA-256 hashes. Jobs run from that snapshot in the foreground, so subsequent
edits do not change queued experiments. The launch wrapper requires
`run_complete.json` because Kit can otherwise exit with code zero after a Python
exception. Runs export `workcell.usda` and smoke/evaluation runs write
`result.json`. `--capture` also checks CUDA arithmetic and saves `overview.png`,
`bricks.png` and `cuda_check.json` using RTX rendering. Physics and PPO remain
on CPU for the native connection backend. Generated runtime files and the supplied resources are not
automatically committed.

## Legacy scaffold task contract

- Actions: seven values, `[dx, dy, dz, rx, ry, rz, gripper]`, normalized to
  `[-1, 1]`. Each control step requests at most 10 mm translation and 0.08 rad
  rotation through differential IK. A positive gripper action opens the hand.
  The arm uses ideal gravity compensation; bricks retain gravity and contact
  loads. This is a control assumption, not a validated FR3 torque controller.
- Observations: 46 values for the default five labels: joint positions and
  velocities (9 each), TCP pose (7), current brick bottom-center pose (7), desired
  brick pose (7), label one-hot (5), detached flag and completed fraction (2).
  Positions use meters, Z points up, and quaternions use WXYZ.
- A deterministic planner selects an exposed brick, then assigns a bottom-up
  output slot. `mixed` uses one output. `single_shade` uses one plate per accepted
  shade. Mixed mode fills a mixed stack in arrival order; it does not enforce a
  requested color ratio or sequence.
- A good transfer requires native connection to the intended output plate,
  position and orientation tolerance, an open hand and low brick velocity for
  ten consecutive control steps. Scrap must be released inside the tray and
  settle. Rewards include reach/transport shaping and detach/transfer bonuses.
- Initial connections are created on reset. During an episode the code never
  removes a connection to claim a successful pick, attaches a brick to the hand,
  or teleports a brick to its destination. Native physics determines breakage
  and insertion.
- Detaching an unrelated clutch or moving an unprocessed neighboring brick by
  more than 15 mm terminates the episode. Full success requires every source
  brick to be transferred. Idle stability is not sorting success.

The legacy RL scaffold's color labels come from **simulator ground truth**;
it is not the sensor-driven color classifier for the current demo. Challenge 1
concerns industrial bricks and is separate from this LEGO task. The current
plan is local RGB color classification from the selected pre-grasp segmentation
region, with optional C920 confirmation after visibility/focus checks. That LEGO
classifier is implemented with limited saved-render evidence (1806), and its
final-selection handoff is replay-tested (1826). It has no new real-image,
held-object, or live manipulation validation; see the
[handoff result and limitations](experiments/stage1_handoff_20261025/README.md).
In `configs/workcell.json`, the two reject categories preserve the element IDs stated in slide 24. Their RGB values
are placeholders; they are not verified LEGO element-to-color mappings. A real
detector must provide a brick identity/pose and shade/quality estimate in the
robot base frame, with timestamp and confidence. Keep its estimates separate
from simulator truth when measuring classification and routing errors.

## Layout and physical calibration

Edit `configs/workcell.json` and submit again. The robot base is `(0, 0, 0)` at
table height. The source plate center is `(0.45, -0.16)` m, the mixed output
plate is `(0.45, 0.16)` m, and the scrap tray is `(0.30, 0)` m. The three shade
plates use centers `(0.37, 0.16)`, `(0.59, 0.16)`, `(0.37, 0.38)` m. These are
candidate placements within the nominal workspace, not collision-free reachability
guarantees. Check approach and twist clearance before moving real hardware.

Brick grid pitch is 8 mm and body height is 9.6 mm, with a 3.2 mm model
baseplate. The baseplate is a rigid kinematic LEGO part fixed to the table. Every
bottom brick has a clutch connection to it. Adjust the plate dimensions to the
supplied floor. Verify whether the real plate itself is clamped before treating
it as an immovable anchor.

The starting clutch preload (3.5 N), friction (0.2) and insertion force (1 N)
are upstream defaults, not measurements of your bricks. Measure pull-off force
and peeling torque on representative bricks and connections, including wear.
Validate those distributions, gripper pad friction, TCP, masses and insertion
depth before using simulation to rank grippers or transfer a policy.

## Paper tool comparison

The supplied [paper](https://arxiv.org/abs/2309.02354) describes a passive,
stud-engaging tool with insert-and-twist manipulation and CMA-ES tuning of
motion duration, twist angle and pivot offsets. It is not another actuated
parallel hand. Its reported experiments used FANUC and Yaskawa arms.

`configs/paper_tool.interface.json` records the required adapter/tool interface.
`--tool paper` deliberately stops before launching simulation until validated
CAD, attachment transforms and physical connection geometry exist. There is no
proxy gripper whose success could be mistaken for an implementation of that
tool. See [the comparison plan](docs/gripper_comparison.md).

## Scope and evidence

This is a training environment and experiment launcher. It does not contain a
trained sorting policy, a validated physical gripper comparison, or a real-robot
controller. The full industrial kiln-cart simulation requested in slide 25 is
a separate scale/model: industrial bricks do not have LEGO clutch connections.

Local sources: `resources/UTUM Brick Coloration.pptx` (slides 18, 20, 23–25),
`resources/2309.02354v3.pdf` (section 3, figure 2, section 4), and all five photos
in `resources/setup_images/`. [Validation notes](docs/validation.md) distinguish
the checks actually run from pending manipulation validation.
