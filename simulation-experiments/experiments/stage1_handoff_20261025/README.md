# Pregrasp source-color handoff

This connects the existing LEGO color function to the final selected source
candidate. The frozen Lab classifier, settings and observed-RGB reference
medians from job 1806 stay unchanged. No extra detector, camera motion or physics
experiment is included.

The adapter accepts the same close-view BGR image, axial depth, calibration,
frame timestamp and final candidate used for selection. It records content
hashes and preserves the classifier's decision, evidence and UNKNOWN outcomes.
An observation describes a source brick. Held identity remains UNKNOWN and
transfer stays disabled. A stale/mismatched observation invalidates the current
handoff; abort/slip invalidation preserves the original source-color evidence.

The single saved-data replay compares all candidate outputs from the five
original frames with job 1806, including the zero-candidate frame. It also
replays the actual final sensor-selected candidate from job 1819 and invalidates
that historical attempt on its recorded abort. Untimed original frames receive
no freshness claim. The replay tests plumbing and association, not new color
accuracy or manipulation success. The original 35 correct non-reference
observations / 98 visible observations remain the coverage limit; views are
correlated and use ideal rendered RGB-D.

Small source/synthetic checks use the existing runtime. All saved-image replay
and evaluation run together through `pueue add` in the default queue, from a
committed stable snapshot: one job, at most 30 seconds, no automatic retry or
parameter tuning. Submission after final independent review:

```bash
python3 experiments/stage1_handoff_20261025/submit.py
```

Source-only grasp reassessment is separate. The completed fixture comparison
remains closed, and physical Desk-to-custom-pad gap/depth mapping remains
unverified. No source color can unblock a failed grasp or authorize transfer.


## Result

Pueue **1826**, source `2882ac3`, completed in **2.683540874 s**. All
1,276 independent checks pass.

| Check | Result |
|---|---:|
| Exact prior classifier outputs | 116 / 116 |
| Raw known / UNKNOWN, including calibration examples | 41 / 75 |
| Invalid/stale/abort/slip controls denied | 10 / 10 |
| Zero-candidate frame processed | Yes |
| Saved final Stage 2 selection | tan; then INVALIDATED on recorded abort |
| Held identity / transfer permission | UNKNOWN / false |

The selected tan brick was an original calibration-reference brick, excluded
from the prior accuracy score. It demonstrates source association plumbing,
not a new held-out correct classification. The original 35 correct non-reference
observations / 98 visible observations remains unchanged. The optional live
runner hook has only source/synthetic checks; no fresh simulator capture,
grasp, extraction or transfer was executed.

Artifacts: [full transactions](artifacts/replay.json),
[independent audit](artifacts/evaluation.json),
[selected source overlay](artifacts/selected_source_overlay.png), and
[compact result/provenance](results.json). The overlay marks a source region;
it does not show a held brick. No additional compute or tuning follows.
