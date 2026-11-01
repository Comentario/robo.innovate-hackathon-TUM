# Stage2: idle physics smoke only

The unchanged full300 workcell is initialized by the existing private renderer:
its configured nominal robot pose, source root restoration,930 genuine native
connections and strict pre-dynamics pose checks are reused. An optional callback
then advances120 physics steps at1/120s while holding the existing nominal joint
targets. It returns before the static capture path and never writes root/joint
states after initialization, resets bodies, reduces the scene or tunes settings.

`protocol.json` declares the test before execution. Every step checks all301
source-part states and robot states are finite, the original301-part/930-link
component remains exact with no breakage, and maximum position/orientation drift
stays within2mm/2degrees. Final speeds must be at most.02m/s linear and.2rad/s
angular. These are smoke-test tolerances, not production or manipulation claims.
The first failed invariant is recorded and stops the run. No recovery is tried.

`idle_trace.jsonl` records each check; NPY files preserve initial/final or failed
source states. `idle_report.json` and `idle_complete.json` refer only to idle
validation. No RGB capture or sensor equivalence is claimed. The custom supervisor
uses the existing bounded child cleanup and reports shutdown separately.

Stock collision/friction remains the contact baseline. The user-supplied updated
fingertips are visual meshes only; this test does not validate their physical
fit, force limits, contact geometry, grasping or insertion. Automatic assembly
detection stays disabled for the explicit graph, and breakage detection stays on.

After source/protocol review and freeze, the orchestrator submits the foreground
supervisor through the default Pueue queue and reports its job ID:

```sh
python experiments/stage2_idle_20261025/supervise_idle.py \
  --python /home/faps/miniforge3/envs/unitree_sim_env/bin/python --output OUTPUT
```

Only syntax and tiny numerical contract fixtures run outside the queue:

```sh
python experiments/stage2_idle_20261025/run_idle.py --self-test
```

## One unchanged-physics breakage diagnostic

The initial smoke failed at step7: two connections to brick_9_0_3 broke, reducing
930 links to928 while position drift was only.171mm. `diagnose_breakage.py` reuses
the same native initializer and runs at most8 steps, stopping at the first failed
invariant. Only `BreakageThresholds.debug_dump` changes to true; every other public
threshold is snapshotted and compared exactly. Gravity, preload, friction,
compliance, cooldown, dt and breakage enablement remain unchanged.

The diagnostic records public per-link utilization for all930 original links,
the top values, connections836/837, native ID mappings and solver debug dumps.
`TMPDIR` points to the owned output/native_debug_tmp directory before native code
loads. A missing/unmapped utilization is−1, not zero. Cooldown delays break
selection; its timing is not evidence of the failure's cause.

`diagnostic_complete.json` means observations were collected, including an
expected first failure; it explicitly does not mean idle stability passed.
Use the same frozen default-queue workflow, replacing supervise_idle.py with
supervise_diagnostic.py. No physics tuning, solver rebuild or recovery is tried.


## Coupled numerical-epsilon diagnostic

The installed native binary already accepts process `OSQP_EPSILON`; no rebuild
or dependency change is needed. One explicit default control at `1e-4` and one
variant at `1e-6` are bounded to eight steps/first failure. This setting couples
OSQP absolute/relative tolerances, the G lower bound and the stage2 capacity
interior margin. It is **not** an isolated solver-termination test, a physical
clutch-strength change, or an idle pass. The supervisor sets only the owned
child environment before native import and saves the requested value. Full
120-step idle mode rejects this diagnostic-only flag. The numerical value must
also be used when interpreting any serialized stage2 constraint gap.

```bash
python3 experiments/stage2_idle_20261025/submit_idle.py --diagnostic --osqp-epsilon 1e-4
python3 experiments/stage2_idle_20261025/submit_idle.py --diagnostic --osqp-epsilon 1e-6
```

Both retain all physical thresholds, native break selection, geometry and
nominal robot pose. Surviving eight steps would establish sensitivity only;
it would not pass the one-second idle gate or authorize an extraction claim.


## Measured outcome: idle gate failed

Initial full120-step baseline **1725** stops at step7: native connections836/837
on top-edge brick `brick_9_0_3` break without task motion. The source component
changes301→300parts and930→928links. Maximum source drift is0.170776mm, and the
nominal arm joints remain held. Debug-only rerun **1727** exactly repeats that
failure and collects7native solver dumps. Analyses **1731–1732** distinguish
allowed capacity relaxation from numerical residuals.

The explicit numerical-epsilon pair **1733–1734** also breaks the same two links
at step7. All serialized solver stages converge. Paired offline analysis **1735**
uses each recorded epsilon, with the existing reader and no solver rerun:

| Coupled epsilon | Break step | Clutch836 utilization | Clutch836 relaxed-bound violation |
|---|---:|---:|---:|
| 1e-4 | 7 | 1.00009789 | 5.52e-5 |
| 1e-6 | 7 | 1.00004254 | 5.72e-9 |

At1e-6 the native normalized relaxation remains positive (clutches836/837:
4.2731e-5/8.6916e-5). Tighter numerical epsilon improves constraint feasibility
but is not sufficient to prevent the break. The experiment changes coupled
numerical settings, so it is not a pure termination-tolerance causal test.
Underlying load/contact origin remains unresolved. Logged J/H are momentum
accounting quantities, not independent contact-force measurements.

- [Baseline first-failure report](../../runs/20261025T002411.589299Z-stage2-full300-idle/output/idle_report.json)
- [Paired analysis, explicit default](../../runs/20261025T010002.112809Z-stage2-epsilon-pair-analysis/output/default_1e4/REPORT.md)
- [Paired analysis, numerical variant](../../runs/20261025T010002.112809Z-stage2-epsilon-pair-analysis/output/variant_1e6/REPORT.md)
- [Machine-readable outcome and snapshots](results.json)

Independent evaluator and reviewer agree to close this bounded round with the
failed idle gate intact. No preload, friction, dt, cooldown or break-threshold
tuning follows. No source-size reduction, fixed-support substitution, scripted
attachment, teleportation or extraction/transfer/stacking claim is made.
Further contact/angular-load-accounting work needs a new narrow hypothesis;
controller development cannot treat spontaneous disassembly as a successful pick.


## Contact observation: API queries completed, load origin unresolved

Source `2d759ad`, Pueue **1738**, runs the same full source for at most eight
postassembly steps, stopping on first failure. Direct tensor views reuse native
zero-threshold reporters for six watched bodies, with all 319 scene actor/static
paths requested and a fixed 1024-entry capacity per view. No material, contact,
clutch, solver, nominal joint or geometry parameter changes. The process-local
`/physics/disableContactProcessing` setting changes from true to false; this is
potentially perturbing and requires measured baseline equivalence.

Independent queued audit **1739** passes all frozen equivalence checks against
1733: initial and terminal source-state files are byte-identical, available
per-step drift/speed/joint/time metrics agree, and the same connections 836/837
break at step 7. The tiny quaternion angular self-distance is numerical rounding.
All 42 body-step records are finite and report **zero normal and zero friction
entries**; all-partner and filtered normal totals also report zero. Native code
suppresses contacts within a connected LEGO component. There is no independently
verified positive contact-reporting control, so completeness, signs and substep
timing remain unknown. These zeros do not prove absence of physical load.
Native J/H causal comparison is withheld. This is diagnostic completion, not an
idle, contact-sensor calibration or extraction pass. No API retry was used.

```bash
python experiments/stage2_idle_20261025/submit_idle.py --diagnostic --osqp-epsilon 1e-4 --contact-observer
# Audit is also queued; the exact frozen command is in the evaluation launch.sh.
```

- [Frozen observation protocol](contact_analysis_protocol.json)
- [Observation snapshot](../../runs/20261025T014802.480148Z-stage2-native-contacts-1e-4/manifest.json)
- [Independent audit](../../runs/20261025T014929.925825Z-stage2-contact-evaluation/output/contact_evaluation.json)
- [Audit summary](../../runs/20261025T014929.925825Z-stage2-contact-evaluation/output/REPORT.md)

The bounded contact-observation round is closed without a physical-parameter
change or a diagnosed load origin. Further work needs a separate reviewed
hypothesis and remains within the existing three-round stage limit.


## Round 2: source velocity-iteration sensitivity — failed

Frozen source `1debd6e`, Pueue **1740**, changes only the source-brick authored
velocity iteration count from 4 to 16; position iterations remain 32. It retains
the full 300-brick/930-link initial source, original 120-step idle gate, timestep,
nominal joint targets, epsilon 1e-4 and physical/native break settings. An
experiment-local factory wrapper leaves the shared factory and default settings
unchanged. The installed dynamic-control extension is activated only in the
queued process, for readback; no runtime setter or dependency installation is
used. A separate completion marker requires terminal verification.

Independent audit **1741** passes all 25 integrity checks. All 300 source actors
read back 32/16 initially and finally; plate/robot controls remain 16/1. The
actual USD scene is TGS, with velocity clamps 0–255 and position clamps 1–255.
Historical baseline 32/4 is pinned authored evidence, not a historical runtime
getter measurement. Executed island iteration counts are unavailable.

| Configuration | First break | Remaining source parts / links | Idle gate |
|---|---:|---:|---|
| Baseline authored 32/4 (1725) | Step 7, links 836/837 | 300 / 928 | Failed |
| Variant runtime 32/16 (1740) | Step 7, links 836/837 | 300 / 928 | Failed |

Initial 301-body state files are byte-identical to both 1725 and 1733. Every
recorded per-step aggregate drift/orientation/speed metric through step 7 agrees
with 1725. This does not establish identical unrecorded per-body trajectories or
loads. Load/utilization changes were not measured in this idle runner.
The experiment shows no measured benefit; it does not identify the cause.
There is no promotion of 16, further parameter sweep, reserved-case execution,
or extraction/placement claim. Reserved H_mix remains unexecuted for dynamics;
it is a historically known perception layout, not independent-stack evidence.

```bash
python experiments/stage2_idle_20261025/submit_idle.py --velocity16 --osqp-epsilon 1e-4
```

- [Round 2 protocol and limits](round2_velocity16_protocol.json)
- [1740 snapshot](../../runs/20261025T020034.012576Z-stage2-round2-source-velocity16/manifest.json)
- [1740 failed idle report](../../runs/20261025T020034.012576Z-stage2-round2-source-velocity16/output/idle_report.json)
- [1741 independent audit](../../runs/20261025T020255.062438Z-stage2-round2-evaluation/output/evaluation.json)

Stage 2 has used two improvement rounds (coupled epsilon and velocity iterations),
both unsuccessful. The maximum of three is a cap, not an obligation to try a
third knob. Further work must test a concrete load/source-model hypothesis.
