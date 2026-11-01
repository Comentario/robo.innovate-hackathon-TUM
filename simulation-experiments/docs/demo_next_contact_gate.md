# Next contact gate — historical proposal

Status update: the [stock-pad baseline](../experiments/stage2_contact_20261025/README.md)
now passes. The final supplied-tip geometry attempt failed before contact;
all three contact improvement rounds are closed. Saved-data audit1758 shows
representation ambiguity without establishing active collider suitability. The
active-shape observation1761/1762 subsequently measures local CAD discrepancies
(2left/9right overlaps in CAD-free spheres; millimetre ray-distance differences).
That two-attempt diagnostic is also closed. The next reassessed approach is a
possible explicit CAD-derived convex compound, whose actual parts must be
reviewed before cooking; no new proxy or contact run is implemented.
The original proposal below is retained as planning history.

The initial idle benchmark is closed after three rounds. The tested setting is
PGS, source actor iterations 32/4, with the recorded default native parameters.
No fourth configuration round is proposed. This next task measures a different
prerequisite: supplied-tip collision geometry and observable contact feedback.
It does not count a truth-positioned fixture as a perception-driven pick.

## Existing components to retain

Keep the workcell layout, native full300 source/930 connections, robot joints,
white finger geometry, masses/inertia and the supplied STL visual registration.
The current stock pad collisions are each finger's `collisions/mesh_3` under
`/World/envs/env_0/Robot/fr3_leftfinger` and `fr3_rightfinger`. Only old visual pad
faces were hidden; the new STL has no collision. The wrapper's FingerPad material
uses static friction 2.5 and dynamic 2.0, without physical calibration.

STL registration assumes millimetres and nominal mating/distal planes. Inspect
actual composed collision meshes before replacing only the old pad collisions.
A convex hull adds about 6% volume in the read-only geometry check and can fill
functional concavities. Prefer the existing PhysX decomposition tools only if
the relevant contact features survive; stop if a suitable proxy cannot be
established. No new framework, broad asset refactor or friction fitting is needed.

## Smallest proposed check

First freeze cases, limits, method, positive-control meaning and independent
review. A declared kinematic 2×4 coupon near stationary pads can test nominal
geometry and force reporting while the full source remains an untouched dynamics
guard. It is an initialization/test fixture, not a successful grasp or extraction.
Start with one slow closure and reopen. Proposed ceilings are 1 mm/s, 1 mm travel
per finger and 2 N reported normal force; these values remain unvalidated and
must be agreed before execution. Tangential motion is optional and should not
block the first positive-normal-force result.

Reuse direct tensor contact views and existing reporters. Establish a positive
control, units, sensor/filter order, signs, dt scaling, buffer completeness and
separate friction-anchor points. A commanded drive effort is not pad-force
feedback. All-zero reports stay inconclusive. Preserve real-time step timing,
contact/impulse records and source graph failures. Keep native truth in fixture
initialization and independent evaluation; no robot-frame or perception pick
claim follows from this check.

All cooking, simulation and evaluation use default Pueue with frozen snapshots.
At proposal creation, no contact implementation or experiment had run. The
subsequent stock result is linked above; no supplied-tip mesh cooking or robot
trajectory is established by it. Held-brick transform, extraction pivot, 25°/5 mm
candidates, classification timing and insertion feedback remain later gates.
