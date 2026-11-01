# Stock-pad contact feedback benchmark

The stock-pad positive-contact and reopening diagnostic passes independent audit
**1755**, after preserving two earlier failures. This is a fixture test, not a
perception-driven pick, dynamic grasp, extraction, calibrated physical force
measurement or proof of matching real-robot feedback availability.

| Attempt | Capture / audit Pueue | Measured steps | Outcome |
|---|---|---:|---|
| Initial B0, `f9496b3` | 1751 / not submitted | 0 | Pre-play geometry exporter expected Mesh; actual stock colliders are Cubes |
| Contact round 1, `922a0d6` | 1752 / 1753 | 36 | Frozen gate failed at first ~2 mN contacts because coupon scalars were negative |
| Contact round 2, `3f0f9c9` | 1754 / 1755 | 100 | All 27 independent checks pass; both pads confirm contact and reopen |
| Final contact round 3, `5e8ba6c` | 1756 / 1757 (partial only) | 0 | Supplied-tip query fails normalized vertex/plane consistency before contact; D/R skipped |

All eight composed stock finger colliders are USD Cubes; `collisions/mesh_3` is
the pad on each finger, with separate white-finger boxes. The Cube exporter uses
actual sizes and composed transforms, without changing physical shapes. Contact
points are checked against these surfaces, not against the visible new STL.

The round-1 scalar validity assumption was unsupported: the installed API's own
example contains negative coefficients and defines vector force as signed scalar
× normal. Unmodified products in the failed trial matched pair matrices,
reciprocal forces and dt scaling. Round 2 therefore preserves signed vectors and
uses absolute magnitudes for threshold/abort and **all** force-carrying point
checks, including negative coupon reports. It does not fit gains, flip selected
forces or relax thresholds. The failed 1753 audit remains immutable; it did not
establish negative-coupon point ownership or the positive/reopen gate.

## Passed check and limits

A declared kinematic native 2×4 coupon starts near stationary pads, with 0.25 mm
clearance per side derived from actual composed stock geometry. The seven arm
command targets stay nominal. Initial finger opening changes only before play;
there is one declared coupon placement before measurement. This is test setup,
not a truth-fed online pick or attachment.

Both pads exceed 0.2 N for three fresh samples at step 49. Peak magnitudes are
0.224462 N left and 0.224318 N right. Force release below 0.01 N for three samples
first occurs at step 70; the controller finishes returning to its initial opening
at step 100. These are distinct completion observations. All substantive signed
contacts, including coupon-side negative coefficients, are uniquely compatible
with the stock pads. Reciprocal, vector/matrix, buffer, sign and unit checks pass.

The full background remains 300 bricks / 301 native parts / 930 links, with PGS
and source actor32/4. Existing 15 N / 2000 N/m / 100 N s/m hand actuator values,
material bindings, mass/inertia and native physical rules are unchanged. Actual
stock pad friction2.5/2.0 is not physically calibrated.

Command ramps are capped at 1 mm/s and travel at 1 mm per finger (+2 µm numerical
allowance). Sampled actual joint speed above 2 mm/s, normal magnitude above 2 N,
or hand drift beyond 2 mm/2° aborts. Actual speed and force are recorded; sampled
abort bounds are not guaranteed physical caps. The budget is 360 steps / 180 s.
An unsafe/incomplete-data failure halts physics; it does not claim reopening or
recovery. Successful contact explicitly reopens and verifies release.

The run logs existing SDK warnings about zero-velocity writes to a kinematic
coupon during initialization. Its pose/state checks pass; this API warning was
not hidden or changed during the signed-coefficient correction.

## Reproduction and evidence

```bash
python experiments/stage2_contact_20261025/submit.py
```

Submission freezes committed code/configuration and uses default Pueue with the
existing `unitree_sim_env`. Run array evaluation through the frozen queued audit
launcher, never directly. Earlier snapshots preserve their original contracts.

- [1754 source/input manifest](../../runs/20261025T032638.185262Z-stage2-contact-B0-stock/manifest.json)
- [1754 geometry](../../runs/20261025T032638.185262Z-stage2-contact-B0-stock/output/geometry.json)
- [1754 controller trace](../../runs/20261025T032638.185262Z-stage2-contact-B0-stock/output/trace.jsonl)
- [1755 audit launcher](../../runs/20261025T032653.179734Z-stage2-contact-B0-R2-evaluation/launch.sh)
- [1755 independent audit](../../runs/20261025T032653.179734Z-stage2-contact-B0-R2-evaluation/output/evaluation.json)
- [All outcomes, hashes and earlier failed artifacts](results.json)

The supplied STL remains visual-only in the shared workcell. Final round 3
attempted one experiment-local convex-decomposition collision representation:
32 hulls, 64 vertices/hull, 1M voxels, 1% error, 0.1 mm minimum thickness and
shrink-wrap. Job 1756 stopped after 13.373 s during the first tip query because
normalized cooked planes did not contain their reported vertices within the
frozen 0.1 µm representation check. This does not by itself identify the cause
or prove physical CAD invalidity. The raw left-tip data are retained; the right
tip, union/CAD fidelity acceptance, initialized source/property checks, centered
contact and reserved +2 mm test remain untested.

All three contact improvement rounds are now closed. There is no automatic
recook, tolerance change or fourth configuration. Independent partial-data
audit 1757 is descriptive only and cannot promote this failed G phase. Seventeen
of 32 retained left hulls exceed the frozen 0.1 µm vertex/plane check; maximum
normalized residual is 48.703 µm and maximum own-polygon residual is 49.344 µm.
The maximum outer-bound difference is 0.102881 mm against the frozen 0.1 mm
limit. These observations do not establish the cause or full CAD/union fidelity.
The audit takes 0.064 s, for 13.437 s capture plus audit within the 180 s phase
budget. Right-tip, initialized-source/property and contact checks remain untested.

[1757 audit and per-hull evidence](../../runs/20261025T040920.106029Z-stage2-contact-R3-G-partial-evaluation/output/evaluation.json),
[reproducible audit launch](../../runs/20261025T040920.106029Z-stage2-contact-R3-G-partial-evaluation/launch.sh).

```bash
python experiments/stage2_contact_20261025/submit.py --proxy-stage G
```

The executed snapshot and input hashes are in
[1756 manifest](../../runs/20261025T040508.534018Z-stage2-contact-R3-G/manifest.json);
see the [failure](../../runs/20261025T040508.534018Z-stage2-contact-R3-G/output/failure.json)
and [raw partial geometry](../../runs/20261025T040508.534018Z-stage2-contact-R3-G/output/proxy_geometry.json).
This command documents the failed attempt; do not run it again as a retry.
No grasping, extraction or hardware control was performed.

## Saved-data representation reassessment

Pueue **1758**, source `10177e6`, performs one read-only analysis of the retained
left-tip data in 0.109 s (60 s limit). All 32 indexed surfaces have closed,
consistent, nondegenerate triangle topology, but only 16 meet the original
convexity precision. Maximum indexed polygon nonplanarity is 144.508 µm; maximum
fan convexity excess is 115.407 µm. They cannot be assumed to be exact planar
faces for our earlier halfspace/union audit.

The reference STL confirms all 27 fixed bore probes free. The vertex-derived
hull candidate puts all 27 outside, supplied SDK planes put 26 outside and one
unknown, and conservative indexed winding leaves all 27 unknown. This is
representation ambiguity, not evidence that the actual collider blocks the bore
or proof that it is usable. The original 102.881 µm versus 100 µm bounds failure,
missing right-tip evidence and closed R3 remain unchanged.

The [SDK API](https://docs.omniverse.nvidia.com/kit/docs/omni_physics/107.3/extensions/runtime/source/omni.physx/docs/api/python.html)
exposes vertices, indexed polygons and planes without establishing the earlier
0.1 µm agreement requirement. The matching-family
[PhysX cooking source](https://github.com/NVIDIA-Omniverse/PhysX/blob/107.3-physx-5.6.1/physx/include/cooking/PxCooking.h)
describes scale-dependent near-plane handling. These contracts motivate direct
observation of active collision shapes; they do not retroactively pass G.

[Machine-readable results, versions and source references](reassessment/results.json),
[per-hull and per-probe evidence](../../runs/20261025T042001.531758Z-tip-representation-reassessment/output/evaluation.json),
[exact queued command](../../runs/20261025T042001.531758Z-tip-representation-reassessment/launch.sh).

The reviewed next diagnostic uses one unchanged-proxy, motion-free active-shape
query setup with fixed ray/overlap controls. It is not a fourth contact tuning
round, new CAD proxy or authorization to run D/R.
