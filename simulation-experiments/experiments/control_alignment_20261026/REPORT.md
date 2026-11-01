# Real-stack control alignment: implementation and validation status

Follow-up: the [startup reader-only case](../pose_reader_20261026/REPORT.md)
resolved the cached-versus-fresh reference mismatch and independently confirmed
the corrected class. Shutdown and full control validation remain incomplete.
The original four-job results below are unchanged.

The real Python teaching planner, canonical targets and motion policy are now
reused unchanged by a simulation adapter. **Execution alignment is incomplete:**
the independent ideal-backend replay passes, but neither Isaac run completed
the required physical validation. This is not an accepted pick/place result.

Source: `Programmercloud-cmd/robo.innovate26`, branch `task2/jacob`, commit
`13f37dad1980bcbc4491b7f27d8962602e49fea0`. Exact selected files and SHA-256
identifiers are in `vendor/jacob_teaching/SOURCE.json`. The real branch was not
modified. No native robot helper, including its nominal preview mode, was run.

## What is shared

The adapter runs the real `move_xyz → arc_motion → safe_motion` Python code,
including IK candidate search/cache, duration, policy and target resolution.
It uses the canonical upper-pose catalog and separate −15 mm grasp reference,
avoiding a second offset on the older grasp-only export. The configured EE is
the real `F_T_EE`, distinct from the old simulation grip frame.

The local executor mirrors the C++ joint spline, nested blend, first-command
rebase, measured/desired-state guards, startup and endpoint rules. The original
C++ Plan/Model core supplies an offline checker. Joint rate limiting uses
network-free official libfranka 0.20.0 mathematics; the real binary identifies
SONAME 0.20, but its exact patch remains unknown. Existing Pinocchio 2.7 is kept
with a temporary, restored `parentJoint` accessor alias; vendor source and
shared environments are unchanged.

Isaac feedback uses actual measured joints, accepted joint targets and actual
base/hand transforms. Its implicit PD servo is not the Franka embedded servo.
Networking, hardware faults and host timing are explicitly unavailable.

## Frozen validation and results

The minimal Isaac case uses the existing full 300-brick workcell, native
301 parts / 930 connections, point 03 initialization, SDK 20 mm release verification
(expected NOOP), then a +1 mm base-Z jog. It does not attempt a pick.
Truth is used only to audit scene preservation. No post-initialization pose
writes, native threshold changes or contact tuning are permitted.

| Pueue | Snapshot source | Test | Outcome | Scheduler seconds |
|---|---|---|---|---:|
|1834|`0c4890b`|Initial offline replay|Setup failure: missing Pinocchio accessor|4.537392625|
|1835|`c982548`|Corrected offline replay and independent audit|PASS, ideal backend only|10.255613557|
|1836|`c982548`|Full-workcell Isaac case|Timeout; incomplete motion/settle and no terminal audit|175.262344722|
|1837|`b07f930`|Same case with batched evaluation pose reads|Startup equality failure before control; shutdown timed out|65.680754783|

Total **255.736105687 / 270 s**. The four-job case is closed. No remaining
budget is interpreted as authorization for another Isaac attempt. Original
snapshots and failures are preserved, and no pass threshold was relaxed.

Job 1835 independently checked 2302 callbacks, 1001 C++ curve/model samples,
12 SDK limiter vectors and three rejected guard cases. Maximum C++/independent
FK difference was approximately 6e−16 m; limiter vector difference was 0. These
are numerical source/parity checks on an ideal backend, not physical accuracy.
The compact original audit and job receipts are in `artifacts/`.

Job 1836's prefix does not establish endpoint completion, final source stability
or successful control. Job 1837 rejected cached per-object versus fresh batched
source poses. The constructor did not preserve the raw comparison before
raising, so the residual magnitude and cause are **unknown**. Cache-versus-fresh
read semantics are a diagnostic lead, not a demonstrated explanation. A later
logging-only revision preserves that proof on future failure; it has only
invented-fixture coverage and has not been executed in Isaac.

## Remaining alignment work

1. Establish why the two source-pose readers differ, retaining raw comparisons,
   before accepting a faster recorder. Reassess a bounded validation allowance
   and repeat only the unchanged free-space case after that diagnosis.
2. Resolve SDK position-mode gripper feedback. Current Isaac `is_grasped` is
   UNKNOWN; the shared approach guard therefore refuses the grasp sequence.
   Real position-mode logs can report false while holding a brick. A future
   SDK-latch emulation must remain distinct from physical object presence.
3. Validate actual 20/14 mm blocking gripper behavior and supported completion
   semantics separately. The current test exercises only a 20 mm NOOP; SDK width
   is the finger-joint sum, not a calibrated custom-pad gap.

Base/table registration, loaded grasp/extraction and insertion are still
unverified. Earlier contact failures are not repaired by sharing the planner.
The destination helper and perception pipeline remain separate; neither was
silently inserted into the real teaching catalog or declared validated.

## Reproduction

Runtime: existing `unitree_sim_env`, Python 3.11.15, Pinocchio 2.7.0,
NumPy 1.26.0, SciPy 1.15.3, Isaac Sim 5.1 / Isaac Lab. No new shared packages.
Source/build/config hashes and commands are retained inside each immutable
snapshot (`manifest.json`, `pipeline.sh`, `launch.sh`, `submission.txt`):

```text
runs/20261026T004924.746380Z-control-alignment-a
runs/20261026T005722.162481Z-control-alignment-a
runs/20261026T005933.268008Z-control-alignment-b
runs/20261026T010941.404058Z-control-alignment-b
```

All four jobs used `pueue add` in the default queue, with foreground processes
and hard timeouts. Queue concurrency was unchanged. README submission commands
document the historical run procedure; the submitter rejects further baseline
attempts once these snapshots exist. Large traces/native binaries stay local;
tracked provenance and compact audits are available in Git.

All 16 lightweight invented-fixture tests passed after the logging revision
(no robot or simulator process):

```bash
/home/faps/miniforge3/envs/unitree_sim_env/bin/python -m unittest discover -s tests -p test_jacob_control.py -v
/home/faps/miniforge3/envs/unitree_sim_env/bin/python -m unittest discover -s tests -p test_control_alignment_audit.py -v
/home/faps/miniforge3/envs/unitree_sim_env/bin/python -m unittest discover -s tests -p test_batched_source.py -v
```
