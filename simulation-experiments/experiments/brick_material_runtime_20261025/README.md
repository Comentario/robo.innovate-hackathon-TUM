# Startup verification of declared brick materials

This is one bounded configuration check of the opt-in authoring helper tested
in job 1827. It reuses the immutable 1822 initializer and startup-only 1823
readback. Only the isolated coupon's Body/Top physics-material bindings are
authored before initialization. The 300-brick source stack and fingers are not
changed. The original trial hook is replaced with getters; no closing, lifting
or postassembly measured physics step is authorized.

The expected coupon material values are the existing declared Body
`[0.5, 0.4, 0.1]` and Top `[1, 0.8, 0.2]`, compared as an unordered float32
multiset. Shape-row-to-collider identity remains UNKNOWN. Finger material rows
and all contact/rest offsets must match job 1823; geometry, properties, native
inventory and readback-time state must remain unchanged. Unavailable or invalid
readbacks cannot verify the correction.

This uses the pre-margin initializer for a direct comparison with 1823. It does
not adopt a new retention model or alter the closed 1825 grasp result. Inherited
reset/preassembly steps and targeted mass restoration remain disclosed. A pass
would establish effective configuration values at startup, not pair friction,
physical calibration, retention or a native extraction.

One default-Pueue job, maximum **60 s**, including capture and independent audit.
The retained prior cost is **2682.945582478 s**, within the unchanged **2800 s**
case ceiling. No automatic retry, alternative coefficient or fourth fixture
trial is permitted. Submit only after final source review and commit:

```bash
python3 experiments/brick_material_runtime_20261025/submit.py
```

The helper and new wrapper are copied into a stable snapshot; older source and
readback artifacts are pinned. Shared environments and the BrickSim source are
unchanged.


## Result — startup values verified by separate saved-data adjudication

Job **1828** (source `1955636`) captured the expected material rows and passed
all runtime comparisons, but its original audit **failed** three metadata
oracle checks. USD inserted `MaterialBindingAPI` before the existing API, and
the new Scope exposed its built-in empty `proxyPrim` relationship. That failed
audit is preserved unchanged.

The separately reviewed semantic correction permits only that one API insertion
while retaining all prior APIs/order, and only that new Scope's empty built-in
relationship. Extra, duplicate or missing APIs and other/nonempty relationships
remain failures. Job **1829** (source `85ffe4c`) re-audits the pinned saved JSON
with no simulator rerun; all original input hashes match before and after.
All **75 contract checks and 15 runtime comparisons** pass.

| Exact one-body runtime readback | Material triples, unordered |
|---|---|
| Previous 1823 coupon | `[0.5, 0.5, 0]`, `[0.5, 0.5, 0]` |
| Corrected coupon at startup | `[0.5, 0.4, 0.1]`, `[1, 0.8, 0.2]` |
| Fingers / all contact and rest offsets | Unchanged from 1823 |

Values above are rounded for display; raw float32 values are retained. Row-to-
Body/Top assignment remains UNKNOWN, as does effective pair traction. Source
301 parts / 930 connections, coupon singleton / zero connections, state, fixture,
properties and settings are unchanged. Inherited initialization remains; no
postassembly measured trial steps, closure or lift occurred.

Full scheduler costs are **14.646749434 s** for 1828 and **0.538284444 s** for
1829. The retained aggregate is **2698.130616356 / 2800 s**. This verifies the
isolated coupon's startup configuration, not retention or global workcell
adoption. Original grasp failures and the three-round stopping decision remain.

Artifacts: [original failed audit](artifacts/original_evaluation.json),
[separate adjudication](artifacts/adjudication_evaluation.json),
[raw readback](artifacts/readback.json), [authoring delta](artifacts/binding_authoring.json),
and [compact result/provenance](results.json).
