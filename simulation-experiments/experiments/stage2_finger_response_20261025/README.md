# Final fixture reassessment: fixed-target finger response

1824's verified100µm BODY-margin trial was censored after38 lift samples by
actual finger opening2.043/2.078mm/s, with targets frozen and other observed
gates passing. The2mm/s bound came from an earlier1mm/s normal-contact command
diagnostic. It was not an FR3-calibrated lift-response limit; units and indices
are correct.1824 remains FAIL/CENSORED, not numerical noise or a passed hold.

This explicitly frozen third/final fixture improvement changes only that
observation criterion. CLOSE/control retain2mm/s. LIFT/HOLD, only after validated
admission with both last commanded float32 targets bitwise frozen, use per-finger
`min(20mm/s, actual runtime asset velocity limit)`. Unknown phases, nonfinite or
missing limits, wrong joint types/units or changed targets fail closed. The
public startup max-velocity/type readback is preserved; URDF guesses are not used.
The implicit PD drive stays active.20mm/s is a declared engineering response
scale;2N/100N·s/m motivates a scale but is not a net-force bound, mechanical
guarantee, fitted2.1mm/s cutoff or hardware calibration.

Commanded closing1mm/s, nominal14mm target/30-endpoint admission,2N force limit,
actual travel/TCP/arm limits, BODY100µm margin, materials, geometry, drives,
plane/normal/WHITE/HEAD/native/raw/source/support and1mm/3° holding criteria all
remain. Actual robot qdot is never hidden or altered. Per-row ceilings and every
old2mm/s crossing are logged separately as reference evidence. Raising this
ceiling cannot itself establish success: actual≥4mm coupon rise,5mm commanded
lift,30hold and support separation remain required.

The unchanged1824matched1500-step control is reused only through exact old
protocol/audit/capture pins and live physics/q/fixture/observer/margin identity,
plus source/AST evidence that the measured control path still uses2mm/s. The
1822trial source differs only in the declared guard leaf, readonly startup
limit/type queries and evidence logging; the BODY-margin Tool class is unchanged.
This is a known centered fixture, not perception/native extraction or hardware
readiness. Earlier results and the closed margin comparison are retained.

ONE≤150s pick/audit in the SAME2800s aggregate budget, retaining2594.227219942s
(worst2744.227219942s). Max1500physics steps, capture100s/audit40s, no retry,
increasing-ceiling sequence or fourth fixture improvement. Any failure requires
reassessment; no threshold, motion, force or material tuning follows.

After final source review and commit:

```bash
python3 experiments/stage2_finger_response_20261025/submit.py
```

Same installed runtime/dependencies. All simulation and captured-array audit
runs in one foreground default-Pueue job with stable source/configuration hashes.


## Result — third/final fixture comparison closed

Pueue **1825**, source `9c8dbb4`, snapshot
`runs/20261025T165816.000989Z-stage2-finger-response`: **retention failed**.
This result is no longer censored by the old finger-speed cutoff.

| Observation | Result |
|---|---:|
| Position-only lift admission | Step 450, after 30 endpoint commands |
| Capture stop | Step 740, unqualified right contact |
| Relative-retention violations | 151 frames |
| Maximum coupon–TCP translation drift | 1.861 mm |
| Maximum relative rotation | 7.946° |
| Final initialization-relative coupon rise | 0.854 mm |
| Maximum lift finger speeds, left/right | 3.947 / 3.991 mm/s |
| Peak pad normal loads, left/right | 1.617 / 1.711 N |
| Full 5 mm lift, 4 mm rise and 30-step hold | Not completed |

All startup, model, margin, named-DOF units/limits and reused-control checks
pass. Twelve lift frames exceed the historical 2 mm/s cutoff and remain
reference evidence; all satisfy the prospective 20 mm/s criterion. No native
mapping or selected BODY/coupon pairing failure is reported. The final
right-contact plane test fails independently. Material-row identity remains
UNKNOWN; these results do not establish a friction or offset cause.

The evaluator and independent reviewer accept this negative result. It does
not contradict the real successful Desk 14 mm closure: the simulated custom-pad
gap convention and 3.083 mm gripping band are not calibrated equivalents of
that hardware grasp. Reconcile those quantities using existing physical/CAD
evidence before more physics. Keep the simple position primitive; no fourth
fixture variant, stronger squeeze, tilt, transfer or hardware action follows.

Full scheduler duration is **88.718362536 s**, including overhead beyond the
88.469319111 s inner pipeline. The retained aggregate is
**2682.945582478 / 2800 s**. No retry. The compact machine-readable record is
[results.json](results.json); the immutable capture and independent audit remain
in the local snapshot. Audit SHA-256:
`4f890683374ba76f9f7e6d91c59f58bb779f2ac125f45fe71e6de01544f79a10`.
