# Fixed saved-data retention reassessment

One retrospective report, no new physics or controller/geometry changes. It reads
exactly eight frozen samples from failed extraction1819 and the matching closing
endpoint from1818. Native target identity and pose enter offline evaluation only.
Previous failures and the closed one-round pick experiment remain unchanged.

The report measures relative brick/TCP motion and contact migration, retaining
all loaded contact points. Authored tip-edge distances describe geometry; they
are not a new cooked-surface validation. Normal and raw friction-vector streams
stay separate; unverified friction sign, net target wrench and absent native
utilization are UNKNOWN. No fitted friction, capacity or successful grasp follows.

One default-Pueue job, at most30s, charged to2054.2607472610234/2200s. No automatic
retry or new physical run. Sources and55 input hashes are frozen before execution.
The result must identify one concrete next hypothesis or an unresolved dependency,
not initiate a broader diagnostic pipeline.

After independent source review and commit:

```bash
python3 experiments/stage2_retention_review_20261025/submit.py
```

Runtime: existing `unitree_sim_env` Python/NumPy/SciPy; no dependency changes.

## Result — Pueue1820

Source `dee7419`; snapshot `runs/20261025T152631.480348Z-stage2-retention-review`.
All nine samples and raw-stream/normal reciprocity checks complete. Job1818's
closing endpoint matches1819's admission contact values. The brick initially
follows the lift: sampled peak rise is1.139 mm above admission, retreating to
0.418 mm by the abort while TCP rises1.904 mm. Relative vertical difference is
1.486 mm. The original audit's final0.110 mm rise used initialization as its
reference; it must not be confused with admission-relative motion.

The remaining nominal-band descriptor is1.597 mm, so exhausted engagement depth
is not established. Two left BODY observations near the authored distal edge
become nonlateral at the final frame. Some right reported anchors lie beyond
the authored tip even before lifting; these are not precise surface coordinates.
Both target edges remain throughout. Friction sign and native utilization stay
UNKNOWN; this is not a measured traction-versus-clutch capacity comparison.

Independent evaluator/reviewer accept the limited result. Their next practical
recommendation is one free-brick retention fixture at the same position command
and gripping band, passively supported before lifting. That can separate grip
retention from native release load; it is not a successful task extraction and
has not been run. No physical retry or parameter change follows automatically.

Full Pueue duration0.844714157 s (inner0.385212063 s) is retained, yielding
2055.105461418/2200 s total. Reproduction is the one-shot submit command above;
its guard prevents automatic resubmission. Machine-readable provenance/outcome:
`results.json`; detailed evidence: the snapshot's `output/retention_review.json`.
