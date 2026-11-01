# Align simulation with the current real teaching stack

**Current result:** shared-source implementation and ideal-backend audit pass;
Isaac validation is incomplete. The four-job case is closed at 255.736105687 s.
See [the result report](REPORT.md) for failures, supported behavior and remaining
work. Submission examples below record the historical procedure.

Authoritative real source: `task2/jacob` at **13f37dad1980bcbc4491b7f27d8962602e49fea0**.
The selected source, motion policy, exported robot model and canonical catalog
are preserved byte-for-byte under `vendor/jacob_teaching`, with file hashes.
No hardware binaries, SSH commands or robot transport are supplied to the
simulation entry point. The remote branch is unchanged.

This branch is a deterministic teaching/motion baseline, not a complete LEGO
sorting application. Its control path is Python `move_xyz → arc_motion →
safe_motion` followed by a certified joint spline in C++. The simulation now
runs the **same unchanged Python front end, target resolution, kinematic
planner, candidate search, durations and policy** through a small local backend.
It does not replace the real planner with the older simulation DLS controller.
The previous perception, destination-planning and failed contact experiments
remain separate records; none is silently counted as successful manipulation.

## Shared behavior and backend differences

| Behavior | Alignment |
|---|---|
| Target catalog | Real `positions.json`: upper poses plus separate −15 mm `grasp_reference`; not the old already-offset Markdown export |
| Frames | Robot-base `O`, configured EE using actual `F_T_EE` (nominal hand Z 103.4 mm); old 117.56 mm model grip is separate |
| Motion | Exact real Python planner/policy; original C++ Plan/Model core reused for the offline check |
| Callback | Backend mirrors real spline, nested smootherstep, first-command rebase, measured/desired guards, startup and endpoint rules |
| Rate limiting | Network-free official libfranka 0.20.0 joint-position math and URDF-dependent velocity bounds; real binary has SONAME 0.20, exact patch unknown |
| Clock | Healthy 1 kHz simulation ticks; no claim about network loss or host callback scheduling |
| Servo | Existing Isaac implicit position PD/gravity compensation; not the embedded Franka impedance/firmware |
| Feedback | Actual public joint position/velocity/target readbacks; configured EE measured from actual root/hand transforms |
| SDK width | Sum of simulated finger joints; 20 mm opening / 14 mm command, not a custom-pad gap target |
| Gripper completion | Blocking simulated move boundary, then the source 100 ms stable / 2 s verification; loaded contact completion remains unvalidated |
| Held flag | Unavailable in the first Isaac baseline; approach abstains rather than infer object presence from width |
| Host policies | CPU affinity, performance profile, hardware faults and network statistics are unavailable/backend-specific |

The shared source opens to 20 mm before `--grasp`, reaches the upper target,
re-reads and verifies state, then directly descends and **leaves the hand open**.
Close/release are separate position commands. The old 1.5 N admission,
30-command dwell, custom-gap conversion and 5 mm diagnostic lift are not part
of this control path. The branch's recorded two transfers used a temporary
12 mm descent; current 15 mm was restored afterward. Those records do not
independently validate the restored depth, and later operator confirmations
remain separate provenance.

This aligns application logic and supported command/feedback semantics. It
cannot establish identical plant dynamics or make simulation outcomes hardware
commands. Base-to-table registration, held-brick offset, loaded gripping,
clutch extraction and insertion remain separate unresolved requirements.

## Small validation and compute bounds

Phase A builds only offline Eigen and limiter math, runs the unchanged real
front end on an explicitly ideal backend, and audits its curve, timing, guard
rejections, fixed-model check and limiter cases. It is not an Isaac result.

Only a passing phase A admits phase B: a fresh full **300-brick / 301-part /
930-native-connection** workcell at 1 kHz PGS, initialized from recorded point
#3 joints and SDK width 20 mm. It runs one NOOP release-width verification and
one canonical **+1 mm base-Z jog**, with the full source startup and `T+0.8 s`
settle. It changes no native threshold, geometry or contact parameter. No
post-initialization state writes, target teleportation, pick or classification
is allowed. Source poses/connection truth are recorded exclusively for evaluation.

Prospective default-Pueue limits: phase A **90 s**, phase B **180 s**, aggregate
**270 s**, one baseline per phase, no automatic retries or budget extensions.
Fresh source/frame compatibility must be within 100 µm / 0.001 rad before motion;
measured completion uses the unchanged 1 mm / 1° limits. Source evaluation keeps
301/930 unchanged, drift ≤0.5 mm / 0.005 rad, and zero reported external robot
contact points. Failure is preserved and stops this baseline.

```bash
# Invented fixtures only; no real planner or simulator batch.
/home/faps/miniforge3/envs/unitree_sim_env/bin/python -m unittest discover -s tests -p test_jacob_control.py -v
/home/faps/miniforge3/envs/unitree_sim_env/bin/python -m unittest discover -s tests -p test_control_alignment_audit.py -v

# Hardware-intensive work always uses immutable default-queue snapshots.
python3 experiments/control_alignment_20261026/submit.py --phase A
python3 experiments/control_alignment_20261026/submit.py --phase B --predecessor runs/<passing-phase-A-snapshot>
```

No shared dependencies were installed. Existing runtime: Python 3.11.15,
Pinocchio 2.7.0, NumPy 1.26.0, SciPy 1.15.3, Isaac Sim 5.1 / Isaac Lab.
`SharedStack` restores module imports/argv and changes only vendor modules'
process facade. Unknown commands and native robot helpers are rejected. A
simulation-only C++ checker has no libfranka transport link. SDK math source
retains its Apache-2.0 license and pinned provenance.

## Preserved setup failure and bounded repair

Offline job **1834**, source `0c4890b`, compiled both network-free native helpers,
then stopped before planning because Pinocchio 2.7 exposes a frame's parent-joint
index as `Frame.parent`, while the source uses `Frame.parentJoint`. Full Pueue
cost was **4.537392625 s**. No simulation or hardware command ran.

One reviewed setup correction adds that accessor alias only inside `SharedStack`
and restores it on normal exit or failure. It does not use `previousFrame`, edit
vendor code, install packages or change FK/IK/planner mathematics. Metadata
records the API compatibility step without claiming Pinocchio 3 runtime identity.

The failed attempt remains counted. Exactly one explicitly submitted corrected
phase A is allowed **≤85 s**, followed conditionally by phase B **≤180 s**:
4.537392625 + 85 + 180 = **269.537392625 s**, within the unchanged 270 s ceiling.
There is no automatic retry loop. On this checkout, submit the reviewed repair as:

```bash
python3 experiments/control_alignment_20261026/submit.py --phase A --corrected-from runs/20261026T004924.746380Z-control-alignment-a
```

The installed simulation clock accumulates physics callback `step_size`; its
float32 representation may differ slightly from the requested 1 ms tick. The
independent audit accounts prospectively for that numerical clock representation;
controller phases, periods and all physical bounds remain unchanged.

## Preserved wall-time censoring and recording-only repair

Isaac job **1836**, source `c982548`, was stopped by its 175 s process timeout
(exit 124; **175.262344722 s** full Pueue cost), before completion metadata or a
complete independent audit. Its full data remains preserved; no endpoint,
terminal-source or controller-success credit is inferred from the prefix.

The evaluation recorder originally fetched all 300 actors individually on every
step. One reviewed instrumentation repair replaces only those reads with a
public batched rigid-body view. It verifies the exact 300 actor paths and row
permutation, world frame, XYZW→WXYZ conversion, copied buffers, and a no-step
startup comparison against the old reader. The auditor recomputes that proof.
Every-tick 300-pose, native301/930, contact and clock coverage stays unchanged.
No controller, SDK flag, command, physics, native threshold or acceptance limit
changes; the source-admission bridge permits only the reviewed recorder/audit
and administrative deltas from the passing offline snapshot.

Retained full cost is **190.055350904 s**. Exactly one explicitly submitted
recording-corrected Isaac run is allowed **≤70 s**, for a maximum
**260.055350904 / 270 s** across all four jobs. Completion in that allowance is
unproven. It does not create another retry or tuning pool.

```bash
python3 experiments/control_alignment_20261026/submit.py --phase B \
  --predecessor runs/20261026T005722.162481Z-control-alignment-a \
  --corrected-from runs/20261026T005933.268008Z-control-alignment-b
```
