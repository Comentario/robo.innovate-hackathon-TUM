# One BODY contact-margin sensitivity

Readback1823 found1.3625mm contact offsets in all returned finger/coupon slots,
with zero runtime rest offsets. Free-coupon retention fails under both original
and position-only timing. This experiment tests one contact-generation margin
hypothesis; it does not assume that margin caused those failures.

The unchanged1822 trial is imported. A small Tool subclass authors100µm contact
offset on exactly the left/right `collisions/mesh_3` BODY prims before reset.
No rest/material/geometry/mass/inertia/drive/width/controller/trajectory/admission
or threshold change. The coupon and WHITE/HEAD offsets stay unchanged. Thus the
body–coupon offset-sum descriptor becomes about1.4625mm, not100µm. Runtime
initial/terminal multisets must show exactly one100µm slot and four baseline
slots per finger; coupon slots, materials and rest offsets stay baseline. Shape
row mapping stays UNKNOWN; no index assignment by expected value is made.

PhysxCollisionAPI declaration may expose three specific unauthored defaults:
automatic restOffset (`-inf` in schema metadata,0 at runtime), torsional radius0
and minimum torsional radius0. These are permitted only as the pinned schema's
fallback metadata. Only contactOffset may gain an authored value; every other
authored attribute is unchanged. No arbitrary attribute exemption is allowed.

A NEW1500-step matched stationary control precedes a fresh conditional1500-step
position-only14mm/30-endpoint/three-fresh-window pick. Every original2N/speed/
plane/normal/WHITE/HEAD/native/raw/source/support gate remains. Holding still
requires≥4mm actual rise,5mm commanded lift,30hold and≤1mm/3° admission-relative
change with support separation. No success from disappearance of one bad point.
The full source300bricks/301parts/930edges remains, plus the isolated free coupon.
Known-fixture retention is not sensor-selected native extraction or hardware
readiness. Prior1821/1822 failures and1823 observations remain unchanged.

This is fixture improvement2of2: timing was1, contact margin is2. No hidden
counter reset, third offset, squeeze change, sweep or retry. Failure closes this
comparison for reassessment. ONE default-Pueue control/pick/audit job,≤300s,
prospectively raising the aggregate ceiling2500→2800s while retaining every
2403.718485308 prior second (worst2703.718485308s). Pick is skipped if control/
configuration fails or less than130s remains. Capture total cap220s, each audit
cap50s, all sharing the300s limit.

After independent source review and commit:

```bash
python3 experiments/stage2_body_margin_20261025/submit.py
```

Same installed unitree_sim_env/Isaac5.1/BrickSim, no new dependencies. Existing
validated reset/targeted mass restoration remains initialization, while this
new offset opinion is explicit and frozen before measurement. All physical
simulation and captured-array evaluation use the foreground default queue.

## Result — Pueue1824: early-motion censored

Source `4d257f3`; snapshot `runs/20261025T163329.924990Z-stage2-body-margin`.
The fresh1500-step control and initial/terminal configuration proofs pass. The
new authored offset and prescribed unordered runtime multisets are verified;
no other physical-property change is accepted. Pick admission450 is the same
30-command position candidate.

At488, only38 lift samples later, the actual-finger-speed guard stops the run.
Fingers open at2.042803/2.077678mm/s against2mm/s while commanded targets stay
frozen. TCP actual speed0.855mm/s, tracking error0.153mm and peak loads1.364/
1.360N stay within their bounds. No plane/native/mapping violation occurs in
this SHORT prefix. Relative coupon error is0.197mm/0.938°, final rise0.077mm;
there is no completed5mm lift,30hold or terminal support-clearance verdict.

This is CENSORED, not a passed retention test or a demonstrated mechanical
retention failure. The prior later failures cannot be called fixed merely
because this run stopped earlier. Independent reviews close improvement2of2
without retry/offset/threshold tuning. The next reassessment is source-only:
what should the actual passive finger-response cutoff mean separately from the
unchanged1mm/s command limit and implicit drive dynamics? A revised criterion
would need an independent engineering justification;2.1mm/s fitted to this
crossing is not proposed.

Full Pueue190.508734634s is retained, yielding2594.227219942/2800s total;
205.7728s remains. Machine-readable result/provenance: `results.json`.
