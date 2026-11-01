# Operator working-grasp reference

**Latest datum clarification:** use #3 as the trustworthy source anchor. The
needle touched the flat brick body top; #11 is an uncertain recording and is
retired as a cross-plate height reference. The tenth-layer body top is **96 mm**
above the baseplate's brick-supporting surface. With the needle approximately
10 mm below the pads, the taught upper **pad bottoms** are approximately
**106 mm** above that surface. After the already-applied 15 mm descent they are
approximately **91 mm**, giving about **5 mm body engagement**. These are
approximate pad heights, not configured-EE coordinates: #3's exported grasp
EE Z is 82.427 mm in robot base, and its saved upper EE Z is 97.427 mm there.
No plate thickness, world registration or physical pad transform is fitted.
The prior #11 discrepancy below is retained as history, not a current blocker.

Data-only import of the supplied pose export and annotated workcell photo. The
operator reports **20 mm approach opening, 14 mm closing request, 15.8 mm loaded
readback, and straight upward extraction**, with the inferred input-stack poses
tested. This supplements the preserved failed simulation retention experiments;
it does not change the active model, controller, width targets or workcell.

The original Markdown/photo are retained byte for byte under `source/`, with
attachment hashes in `reference_registry.json`. The export-declared original
`positions.json` SHA is separate: that original JSON file was not supplied or
independently verified. Raw validation flags remain unchanged; the later
operator attestation is separate provenance, not instrumented test logs.

## Frame and width interpretation

The export names `robot_base_O` and `configured_end_effector_EE`, metres and
column-major transforms. The **15 mm downward base-Z offset is already applied**.
Its configured flange-to-EE transform includes −45° about flange Z and 103.4 mm
axial translation. The pinned USD flange-to-hand joint and hardware URDF verify
the nominal frame relationship. The current MODEL grip frame is hand +117.557561
mm, not a measured physical pad-contact point. Conversion is:

```
T_hand_EE = inverse(T_flange_hand) @ T_flange_EE
T_base_model_grip = T_base_EE @ inverse(T_hand_EE) @ T_hand_model_grip
```

This yields about **14.158 mm farther toward the brick** for the downward poses;
using the exported EE translation as the current grip target would be wrong.
Neither this conversion nor the photograph establishes base-to-table/plate
registration or the actual pad–brick engagement depth. At the time of the original audit, the saved upper reference's relation to
the physical brick top was unspecified; the latest clarification above resolves
the touched surface and approximate pad engagement.

The old model relation is `custom_gap = q_left + q_right + 2.81338 mm`.
**Conditionally**, if the 15.8 mm display readback equals SDK joint sum and the
physical mount matches this model, it predicts an 18.61338 mm model gap. That
challenges those assumptions together for a gripped 2×4 brick; it does not
identify which assumption is wrong or justify fitting a new offset. No new
width, friction or engagement-depth parameter is selected here.

The inferred export uses 31.8 mm center spacing and 9.6 mm height increments.
The native scene uses a 32 mm stud-grid pitch. Preserve both; do not deform the
native connected lattice or assume imported IDs already map to scene IDs.
Reference coordinates/identities are not online perception inputs.

## Reproduce

No dependency installation or shared runtime changes. Uses existing Python,
NumPy and SciPy. The submitter copies every pinned input, code and protocol to
an immutable `runs/…-hardware-grasp-reference/` snapshot and records its commit
and hashes. The original paths of copied USD/URDF context are provenance only.

```bash
/home/faps/miniforge3/envs/unitree_sim_env/bin/python experiments/hardware_grasp_reference_20261025/test_synthetic.py
python3 experiments/hardware_grasp_reference_20261025/submit.py
```

The first command checks only invented transforms and JSON. The second submits
the full 315-pose numerical audit through **default Pueue**, with a 10 s process
timeout plus 2 s kill grace. It starts no Isaac/Kit, rendering or physics. Audit
outputs preserve the authoritative embedded JSON and provide separate derived
MODEL-frame transforms and a comparison report. Nearest recorded/inferred pose
residuals are descriptive, not asserted physical correspondences or accuracy.

The needle clarification resolves the approximate upper-reference/brick-surface
relation. Contact reproduction still needs a defensible physical width/mount mapping. Existing retention criteria and
closed three-round experiments remain unchanged.

## Result — reference checks passed

**Pueue 1831**, source `a885f97`, snapshot
`runs/20261025T214646.773393Z-hardware-grasp-reference`: all **18 data checks pass**
for 315 targets (15 recorded, 300 inferred). Full scheduled duration was
**0.490 s**; Python 3.11.15, NumPy 1.26.0, SciPy 1.15.3. No simulation ran.

Internal lattice arithmetic is consistent with the exported 31.8 mm pitch,
9.6 mm layer step and alternating 90° orientations. This is export consistency,
not physical pose accuracy. All 315 `motion_validated` flags remain false;
300 inferred `grasp_physically_validated` flags remain false and that field is
absent for the 15 recorded poses. The later operator report remains separate.

The derived model-frame offset is **14.15756 mm along configured EE-local Z**
(approximately downward for these poses). No second 15 mm offset was applied.
The current gap mapping remains conditional and uncalibrated. Independent
source and result review accepted these limited conclusions. Old retention
failures, budgets and downstream unproven stages are preserved.

Artifacts: [comparison](artifacts/comparison.json),
[authoritative extracted poses](artifacts/authoritative_poses.json),
[derived model-frame references](artifacts/transformed_reference_poses.json),
and [job/provenance record](results.json).

## Earlier needle and thin-baseplate clarification (superseded in part)

The operator used a held needle projecting **approximately 10 mm below the pad
bottoms** to teach the reference positions. Together with the already-applied
15 mm base-Z descent, this conditionally puts the pad bottoms about **5 mm
below the needle-touch surface**. That is not yet measured body-side engagement:
a stud-top touch and a flat-body-top touch give different results. The actual
needle extension/projection has no supplied numeric tolerance. The nominal
1.7 mm model stud height must not be presented as a new physical measurement.
This clarification does not independently justify deepening the current grip.

The operator identifies #11 as a working grasp on the gray plate and
`a_0_0_9` as layer ten above the white plate. Their exported configured-EE
heights differ by **76.845 mm**, versus **86.4 mm** for nine 9.6 mm body-height
increments, conditional on equal support elevation and the same teaching and
engagement datum. The approximately **9.555 mm discrepancy was left open at that time**;
it is not a measured plate offset or grounds to renumber the stack. The later
operator withdrawal of #11 as a trustworthy reference retires this comparison.

Both physical plates are thin LEGO baseplates. The old native scene's 3.2 mm
plate-body assumption is not a measured physical thickness. No replacement
thickness, pose offset or brick-grid origin is inferred from the four-stud
location description. The block's 9.6 mm body height is retained separately.

See the [unaltered operator evidence and conditional reasoning](operator_clarification_20261025.json).
The original 1831 audit and inputs remain unchanged. This is a documentation
addendum only; no further batch processing, simulation or hardware command ran.
