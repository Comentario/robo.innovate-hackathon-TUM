# Startup pose-reader mismatch resolved

The startup reference mixed a cached Isaac Lab property with fresh PhysX
observations. On the full 300-brick workcell, the cached property differed by
up to **3.725290298461914 nm** from both fresh readers; the two fresh readers
agreed exactly. The corrected class compares fresh per-asset PhysX poses against
its own fresh batch view. The independent actual-class confirmation passes.

The exact mechanism producing the nanometre difference is not established.
Installed source shows that root-pose writes update the property cache before
calling PhysX, and property reads refresh only after their simulation timestamp
advances. This supports distinguishing cached and fresh engine data; it does not
establish absolute pose accuracy or physical calibration.

## Change and checks

- Keep the existing **1 nm / 1e-7 rad** reader-equivalence limits.
- Generate an explicit v2 proof with raw direct/batch arrays, actor paths and
  permutation, converted poses, and cached poses with both cached residuals.
- Preserve v1 proof semantics and historical failures. The independent audit
  handles the new reference explicitly; cached disagreement remains visible.
- Leave the per-step batched getter, controller, gripper, physics settings,
  workcell geometry and physical source-drift thresholds unchanged.

The actual corrected class was instantiated in Isaac, and `reader.read()`
provided the saved initial array. The independent audit verified this class
proof against separately captured three-reader observations. All 300 actor
identities, row ordering, XYZW/WXYZ conversion and world-frame declarations
passed. Arm joints, simulation clock/step and the 301-part/930-connection native
graph were unchanged. No task-control command ran.

## Results

| Pueue job | Source | Result |
|---|---|---|
|1838|`c1e6805`|Complete three-reader capture saved; shutdown timed out (124)|
|1839|`c1e6805`|Independent capture audit passed: cache-only discrepancy|
|1840|`edd0642`|Actual corrected-class proof and independent audit passed; shutdown timed out (124)|

| Comparison, all 300 bricks | Maximum position difference | Maximum angle difference |
|---|---:|---:|
| Cached property ↔ fresh per-asset |3.725290298461914 nm|0 rad|
| Cached property ↔ fresh batch |3.725290298461914 nm|0 rad|
| Fresh per-asset ↔ fresh batch |0 m|0 rad|

**Reader startup compatibility is resolved. Clean Isaac shutdown is not.** Both
Isaac jobs saved their evidence before teardown, but neither wrote a normal
process-completion marker. The confirmation audit ran as a foreground CPU child
inside the same queued job before unchanged `app.close`; its pass is separate
from the scheduler timeout. No lifecycle, full-motion, grasp or hardware-control
success follows from these reader results.

This case is closed at **146.644905343 / 180 s** total scheduler wall time,
including both shutdown timeouts. The previous control case remains closed and
incomplete at 255.736105687 / 270 s; its results were not promoted or replaced.
All jobs used the default Pueue queue with immutable snapshots and finite limits.
Brev setup was not resumed.

## Artifacts and reproduction

`artifacts/results_summary.json` records exact scheduler receipts, source
commits, manifest hashes and artifact hashes. `audit_1839.json` and
`audit_1840.json` contain the independent checks. The full captures and actual
class confirmation are preserved byte-for-byte as deterministic `.json.gz`
archives, with uncompressed SHA-256 identifiers in the summary.

```text
runs/20261026T080242.039903Z-pose-reader-capture
runs/20261026T080531.349802Z-pose-reader-audit
runs/20261026T081119.596157Z-pose-reader-confirm
```

Each snapshot retains `manifest.json`, `pipeline.sh`, `launch.sh`, `job.json`
and `submission.txt`. The initializer is the unchanged failed-1837 workcell;
manifests bind the precise copied runtime and explicit diagnostic/audit overlays.
The existing `unitree_sim_env` and isolated BrickSim dependencies were reused.
No dependencies or shared environments changed.

All **24 targeted invented-fixture tests** passed: 10 reader tests, 8 control
audit tests and 6 standalone diagnostic-audit tests. These include accepting
and retaining a 3.725 nm cache-only difference while rejecting the same
difference between fresh readers. Commands and frozen stage limits are in
[README.md](README.md) and [protocol.json](protocol.json). Existing submissions
prevent additional automatic runs of this closed case.

The next alignment work remains clean shutdown, the unchanged free-space
controller check, and gripper feedback/completion compatibility. None was added
to this reader-only experiment.
