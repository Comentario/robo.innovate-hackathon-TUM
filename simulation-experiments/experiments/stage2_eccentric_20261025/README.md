# Eccentric native-weld bookkeeping diagnostic

This is one two-actor diagnostic using the installed BrickSim binary. It is not
an alternative to the required 300-brick workcell benchmark, which still fails
its idle gate. There is no robot, manipulation, training or hardware control.

A kinematic native 2×4 lower brick supports one dynamic native 2×4 upper brick,
rotated 90°, with one stud of overlap. Existing connection geometry determines
the relative pose and interface frames. One genuine native link is initialized
before measurement; no attachment or pose is edited during measurement.

The run is capped at eight steps, first native/finite/pose failure, and 180 seconds.
Default timestep, source solver counts 32/4, epsilon 1e-4, native clutch strengths,
materials and break rules are retained. Only native debug output is enabled.
All execution and array evaluation require the default Pueue queue and frozen
snapshots. One documented prestep metadata-export repair is recorded below; no
further retry, second geometry, parameter sweep or native build is planned.

Only the dynamic upper brick's **external impulse after native weld subtraction**
is compared with the gravity-only reference: linear impulse m·g·dt and angular
impulse about its actual COM of zero, conditional on the observed damping,
reference frame and timing. A legitimate eccentric weld reaction moment is not
an error. Raw observations, assumptions and descriptive SI/normalized residuals
must stay distinct; no percentage threshold establishes calibrated physical
correctness. The kinematic lower reaction is outside this criterion.

Passing would not validate redundant lattice constraints, stability of the full
source, sensing, extraction or insertion. A native break alone is not proof of
bookkeeping error or incorrect one-stud capacity.

## Measured outcome

Capture **1743** and independent audit **1744** complete eight steps without a
break. All 36 audit integrity checks pass. The linear external-impulse residual
against gravity is 9.24e-12 N s. The native external angular impulse is constant
[5.65056e-6, 5.65056e-6, approximately 0] N m s, despite zero measured angular
velocity and angular-momentum change. Its norm is 7.99110e-6 N m s. The actual
COM agrees with the logged native COM within 0.93 nm. Damping coefficients are
recorded; no raw weld force measurement is available.

The first launch **1742** failed before measured step 0 while exporting an SDK
infinite scalar attribute. Its snapshot and the prepared, unsubmitted audit are
preserved. A reviewed metadata-only fix tags nonfinite USD scalar attributes;
physical arrays and strict JSON remain unchanged. The protocol explicitly allowed
one final attempt after those zero measured steps. No further retry is planned.

[Machine-readable result](results.json),
[1743 capture](../../runs/20261025T022336.537932Z-stage2-eccentric-diagnostic/manifest.json),
[1744 audit](../../runs/20261025T022352.760544Z-stage2-eccentric-evaluation/output/REPORT.md).

## Focused source hypothesis

The physical one-stud interface frame is at [-0.012, 0.004, 0.0096] m. This is
**not the weld solver's reporting point**: BrickSim creates the weld with an
identity child-local transform, placing its reporting point at the upper COM.
For d = COM_upper - COM_lower = [-0.016, 0.016, 0.0096] m, the measured native
angular residual matches -2 d × J_gravity. It must not be described as twice the
physical interface-to-COM lever arm.

Independent source reviews find a matching expression in the public
[PhysX 107.3 / 5.6.1 TGS writeback](https://github.com/NVIDIA-Omniverse/PhysX/blob/107.3-physx-5.6.1/physx/source/lowleveldynamics/src/DyTGSContactPrep.cpp#L2565-L2595):
its linear-row torque reconstruction and reference-point transport reinforce
rather than cancel for this fixture. This supports a TGS force-reporting
hypothesis. Exact correspondence between that public tag and the loaded vendor
binary is not proven. BrickSim's subsequent point-to-COM transport follows the
public reporting convention; removing its lever-arm term is unsupported.

The corresponding
[PGS writeback](https://github.com/NVIDIA-Omniverse/PhysX/blob/107.3-physx-5.6.1/physx/source/lowleveldynamics/src/DySolverConstraints.cpp#L577-L607)
uses a different torque reconstruction. One separately frozen PGS workaround
trial is being prepared as Stage 2 improvement round 3, with a fixture gate before
the full source and reserved checks. No native patch, build or parameter sweep
is justified by the present result.

The diagnostic does not reset the Stage 2 improvement budget. Full300 idle,
extraction, insertion and the six-stage goal remain unvalidated.
