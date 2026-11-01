# Startup pose-reader diagnosis

**Closed:** actual corrected-class startup proof passes; clean shutdown remains
unverified. See [results, artifacts and limits](REPORT.md). Commands below
document the frozen procedure; the submitter rejects repeated stages.

User-authorized continuation after the previous control-alignment case closed.
Brev remains paused. This case diagnoses the evaluation reader only; it does
not run the task controller, gripper commands, a new trajectory or training.

Use the exact failed1837 full300 workcell initializer, including its existing
nominal robot initialization and301parts/930native links. At its startup reader
hook, compare the cached Isaac Lab property, fresh per-asset PhysX getters and
a fresh batched PhysX getter. Retain raw float32 arrays, copied WXYZ conversions,
actor paths/permutation, cache timestamps and clocks/step index. Save partial
packets before structural validation. Never invalidate caches, refresh/update
the scene, step physics or rewrite bodies to make the comparison pass.

All three pair residuals retain1nm/1e-7rad gates. A cache-only difference is an
observation, not a physics failure. Only fresh direct/batched agreement supports
using the direct getter as the reader-equivalence oracle. Even that does not
establish absolute pose accuracy or successful robot control.

Separate case ceiling:180s total scheduler wall time; one capture<=90s,
independent saved-data audit<=15s, and at most one reviewed corrected startup
check<=75s. No automatic retry or old-case credit. Full previous costs remain
255.736105687/270s, closed and incomplete. The submitter retains immutable
source/configuration manifests and uses only the default Pueue queue.

```bash
# Small invented fixtures only, no saved scene arrays or simulator.
/home/faps/miniforge3/envs/unitree_sim_env/bin/python -m unittest discover -s tests -p test_batched_source.py -v
/home/faps/miniforge3/envs/unitree_sim_env/bin/python -m unittest discover -s experiments/pose_reader_20261026 -p test_evaluation.py -v

# Commit reviewed source first; each command reports its default-queue job ID.
python3 experiments/pose_reader_20261026/submit.py --stage capture
python3 experiments/pose_reader_20261026/submit.py --stage audit --capture runs/<capture-snapshot>
# Only after independent data diagnosis and source review:
python3 experiments/pose_reader_20261026/submit.py --stage confirm --capture runs/<capture-snapshot> --audit runs/<audit-snapshot>
```

The capture runner reuses1837's unchanged `run_sim` initializer. It substitutes
only that process's startup reader entry, and exits via the initializer's
control-only completion exception before `IsaacIO`, `JointExecutor` or
`SharedStack` can be constructed. Those constructors are explicitly forbidden
in this probe. `capture_complete.json` records saved observations;
`process_complete.json` separately records normal shutdown. A timeout does not
become process-completion credit because capture data exists.

The manifest records the current diagnostic commit and exact copied historical
files. It overlays only this experiment and its reader/test changes. The
independent audit verifies manifest hashes, the historical base manifest,
raw conversions and residuals without importing the production reader.

Capture1838 saved a complete no-step observation, then shutdown timed out.
Independent queued audit1839 passes: fresh direct/batch readings agree exactly,
while cached/direct and cached/batch positions differ by up to3.725290298461914nm
(angle0). All300 path/layout checks, unchanged arm/clock/step and301/930 native
graph checks pass. This establishes a cache-versus-fresh observation difference;
the exact cause of the nanometre representation difference is not established.

The reviewed correction generates an explicitv2 startup proof from the actual
reader class, comparing fresh per-asset and batch getters at the same unchanged
limits. It retains cached poses and both failed cached comparisons as diagnostic
evidence. V1 audit semantics and original failures remain preserved. Per-step
batch reading, control, physics and source-drift thresholds are unchanged.
Confirmation saves this actual class proof and its initial array, then runs the
independent saved-data audit as a foreground child BEFORE the unchanged teardown.
It remains inside the same75s confirmation job. Reader proof and shutdown results
will be reported separately; a teardown timeout cannot become a process pass.
