# One corrected-material retention regression

Jobs 1827–1829 established that the brick's pre-existing declared material
values had not been bound as physics materials, and verified the corrected
values at startup. This experiment tests that correction with the unchanged
1825 free-brick fixture and position-controlled primitive. It is one correctness
regression, not another coefficient choice or a fourth fixture improvement.
The previous three improvement rounds and all failures remain closed records.

Only the isolated coupon's Body/Top bindings change. All six declared values
are copied, including Body dynamic friction decreasing from the old runtime
0.5 to the declared 0.4. The 300-brick native source, geometry, mass/inertia/COM,
drives, nominal 14 mm custom-pad gap, 3.083 mm gripping band, 100 µm BODY contact
offsets, position-only 30-command admission, phase-specific finger-response
limits, 2 N sampled force bound, motion and contact/native/holding gates stay
unchanged. This does not reproduce or calibrate the physical Desk 14 mm grasp.

The immutable 1825 trial and margin wrapper are reused. Initial and terminal
readbacks must verify the corrected coupon material multiset together with the
existing 100 µm finger-offset model, unchanged rest/finger materials and five
exact material-schema paths. Shape-row-to-collider identity remains UNKNOWN.

One job first runs and independently audits a **fresh 1500-step stationary
control** on this corrected model. Only a passing same-job, current-protocol,
content-bound control permits one conditional pick from a fresh initialization.
Older material-model controls cannot admit the pick. No benchmark reduction,
control reuse, retry or additional improvement variant is allowed.

Success requires the existing full 5 mm commanded lift, at least 4 mm actual
coupon rise, 30 hold steps, support separation and admission-relative 1 mm / 3°
retention, plus every unchanged contact, reciprocal native mapping and source
invariant. A pass establishes bounded free-coupon retention only; perception,
native tower extraction, transfer, insertion and hardware remain unproven.
Failure ends this regression and requires a different evidence-based assessment.

The prospective resource amendment retains **2698.130616356 s** already spent.
One **≤300 s** shared control/pick/audit job fits an amended **3000 s** aggregate
ceiling (worst 2998.130616356 s), up from 2800 s. It creates no new tuning pool.
The supervisor stops if the control fails or fewer than 145 s remain for the
conditional pick. All stages use the default Pueue queue and stable snapshots:

```bash
python3 experiments/declared_material_retention_20261025/submit.py
```

No shared dependencies, native source, camera layout, gripper geometry or
physical hardware are changed.


## Result — closed negative regression

Pueue **1830** (source `2f20f7a`) completes its fresh 1500-step control with
all 175 control checks passing. The same-job bridge and combined material /
100 µm offset / schema / property / native checks also pass. The pick admits
at step 450 after 30 endpoint commands, then aborts at step **716** on an
unqualified right contact.

| Measure | Corrected-model result |
|---|---:|
| Relative-retention violating frames | 129 |
| Maximum relative translation / rotation | 1.687 mm / 6.80° |
| Final initialization-relative coupon rise | 0.766 mm |
| Peak sampled pad normal loads, left/right | 1.482 / 1.690 N |
| Maximum lift finger speeds, left/right | 3.292 / 3.327 mm/s |
| Completed 5 mm lift and 30-step hold | No |

This is a retention failure, not force/speed censoring. The material correction
is real, but does not establish holding. Job 1825 stopped later (step 740), so
smaller observed error maxima here do not show an improvement. Neither run
completed the required lift/hold. The free coupon has no native clutch edges;
clutch resistance therefore cannot be the sole bottleneck.

Full Pueue cost is **216.692133457 s**, including capture, audits and overhead.
The retained total is **2914.822749813 / 3000 s**. This one-off baseline is closed,
with zero further tuning variants or retries. Source color handoff, configuration
proof and a stationary control cannot establish held identity or authorize
transfer. No tower extraction, insertion or integrated sorting was demonstrated.

The next dependency is a reference for the successful real grasp, relating the
Desk command/readback to actual custom-pad gap and engagement depth. Existing
CAD and open-gripper photos do not supply that operating condition. No new
width/depth/force/offset/controller variant follows from this negative result.

Artifacts: [control audit](artifacts/control_evaluation.json),
[pick audit](artifacts/pick_evaluation.json), [fresh-control bridge](artifacts/control_bridge.json),
[authoring proof](artifacts/binding_authoring.json), [initial configuration](artifacts/combined_initial.json),
[terminal configuration](artifacts/combined_terminal.json), and [compact provenance](results.json).
