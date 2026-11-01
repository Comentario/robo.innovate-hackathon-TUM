# Teaching baseline — taught poses and continuous arc motion

The direct approach to task 2: hand-guide the arm to real positions, record them, fit a grid through
them to generate the rest, and move between targets along one continuous curve. It talks to the
Franka Research 3 through libfranka, without ROS in the motion path.

## Contents

| Folder | What is in it |
|---|---|
| [`teaching/`](teaching/) | The position catalog, the grid generator, the motion planner and the executables. [Full reference](teaching/README.md). |
| [`quick_test/`](quick_test/) | A hardware check that is deliberately separate from the application: cameras, robot state, and seven small joint moves. [Details](quick_test/README.md). |

## The position catalog

`teaching/positions.json` is the single source of truth. For every point it stores the target XYZ in
robot-base coordinates, the configured end-effector orientation, the seven measured joint angles, the
elbow configuration and the tool transforms. Targets start out equal to the measured poses.

From 15 taught anchors, `teaching/generate_stack.py` fits the input stack and produces **300 brick
targets**, identified as `a_<ridge>_<brick>_<layer>` with the ridge 0 to 5, the brick 0 to 4, and the
layer 0 to 9 counted from the bottom. The grid uses 31.8 mm center pitches, exact 9.6 mm layer steps,
a shared center, and alternating 0 / 90 degree orientations.

```bash
/usr/bin/python3 -s teaching/generate_stack.py --write --plot    # no robot connection needed
```

The fit differs from the taught anchors by up to **0.89 mm in XY and 1.14 mm in Z**, and every
generated grasp remains physically unverified. The tool rejects stale generated data if the anchors
or the configuration change.

## Recording a position

Position the arm by hand, hold it still, then:

```bash
source /opt/ros/humble/setup.bash
/usr/bin/python3 -s teaching/record.py 4 --label 'description'
```

Recording is read-only and **never moves the arm**. It needs a stationary, fault-free arm and an
available FCI connection. Use `--replace` only to deliberately reteach an existing point.

## Moving

```bash
/usr/bin/python3 -s teaching/move_xyz.py 1             # preview only
/usr/bin/python3 -s teaching/move_xyz.py 1 --execute   # MOVES THE REAL ARM
```

One move is a single continuous quintic Bezier arc with vertical tangents at both endpoints, so
position, velocity and acceleration all stay continuous and reach zero at the ends. `motion_config.json`
holds the 100 mm departure and arrival guide offsets, the motion limits, and the operator-cleared
bounding box around all 15 poses.

Nominal duration is `max(1 s, 10 s * (distance / 1.1252945911088104 m)^(1/3))`, where the reference
distance is the cleared workspace diagonal. Configured maxima are 0.4 m/s, 0.75 m/s², 0.5 m/s³,
0.3 rad/s, 1 rad/s², 5 rad/s³, and 1.0 rad/s per joint.

Every move plans a continuous joint spline using the URDF exported from the connected robot, and
checks joint bounds and Jacobian margins **across the whole curve**, including between samples.

### Grasping

```bash
/usr/bin/python3 -s teaching/move_xyz.py a_0_0_9 --grasp --execute
```

This transfers to the upper pose and then executes the saved 15 mm descent to the grasp reference. It
sets and verifies the 20 mm approach opening before the transfer and **leaves the hand open**; it does
not close automatically. Gripper widths live in `motion_config.json`: 20 mm approach, 14 mm close
target. A closing width alone is never counted as a picked brick.

### A sequence

```bash
/usr/bin/python3 -s teaching/visit_top_layer.py --execute
/usr/bin/python3 -s teaching/visit_top_layer.py --resume teaching/sequences/<directory>
```

## What stops a motion

Endpoint errors above 1 mm or 1 degree, active callback gaps above 20 ms, joint bounds, and tracking
or envelope violations all stop the motion. Requests, frozen starts, progress, traces and outcomes are
saved per run. No gripper or recovery commands are sent on a stop.

If preflight blocks a route, nothing is sent: hand-guide to a suitable regular posture or review a
different clearance path. **Do not lower the margins to force passage.** Robot faults need operator
inspection and Desk recovery before retrying; these tools never clear them automatically.

## Measured results

| What | Result |
|---|---|
| Endpoint audit over all generated targets | **315 / 315** have a model-feasible configuration |
| Layer-9 traversal, 2026-10-25 | all **30** upper poses verified, ending at `a_5_4_9` |
| Arc to `a_0_0_9` | completed in 7.3 s, **0.533 mm** endpoint error, no faults |
| 15 mm grasp descent | **0.592 mm** endpoint error |
| 1 mm upward jog | **0.753 mm** error, max callback period 1 ms |
| Two corner bricks | picked, carried to pose #1, releases camera-verified; contact near 15.2 mm |

The endpoint audit is **model feasibility, not physical reachability**: it is not a collision or
clearance test. Cable, camera and full-arm clearance still need physical verification for any new
joint configuration. The yaw-flipped transfer to `a_5_4_9` was never physically validated.

## Real-time notes

The controller is pinned to CPU 6, trajectory logging memory is prefaulted and locked, and a
stationary startup requires 0.5 s of stable timing within 2 s before the curve begins. libfranka
joint-position rate limiting was enabled after a packet-loss-associated motion-generator
discontinuity during the layer-9 traversal.

Two attempts stopped on callback gaps of 8 ms and 7 ms under the original 5 ms guard; the guard was
raised to 10 ms and then 20 ms at the operator's request. Changing the CPU governor needs
administrator action (`sudo cpupower frequency-set -g performance`) followed by verification of
callback timing. **None of these tools changes governor or IRQ settings.**

## Build the helpers

```bash
source /opt/ros/humble/setup.bash
bash teaching/build_motion.sh
```

---

Per-move logs, pick records and read-only capture history stay in the team's private repository.
[`teaching/README.md`](teaching/README.md) is the complete engineering reference, including every
calibration decision and its date.
