# RGB ridge chains with interior gaps

**Completed:** [measured comparison, limitations and artifacts](REPORT.md).
Perception/scoring job 1675; saved-overlay-only job 1676. No follow-on trial.

Bounded experiment fitting fixed 2×4 image-space footprints along independently
detected ridges. The [agreed plan](PLAN.md) and global `config.json` are frozen
before one batch. The selected edge-proposal variant does not require a SAM mask
for a ridge; saved SAM and size-filter outputs are comparison baselines only.
It does not rerun SAM, train a detector or change earlier experiments.

The chain program receives original RGB and the same global configuration for
all 18 images. It receives no annotation polygons, historical manual registration,
labels, stud reference points, camera/robot poses or simulator state. A local
projective strip and image-supported pitch/count/phase are hypotheses, not
calibrated metric dimensions. Unknown extent, ridge identity and phase remain
explicit; a gap never restarts an accepted chain's indexing.

On a clean committed experiment source tree, from the repository root:

```bash
python3 experiments/ridge_chains_20261024/submit.py
```

This submits original-image processing and separate fixed-protocol scoring via
`pueue add` in the default queue. The timestamped `runs/` snapshot contains code,
global settings, RGB hashes and evaluation-only reference/baseline fixtures.
The existing Python/OpenCV/NumPy runtime is reused; no packages or global queue
settings are changed. `chains.json` and `overlay.png` are written for every view.

The [evaluation protocol](protocol.json) preserves original six-view labels and
adds the existing six supplemental absence cases only as a separate scoring
track. It distinguishes present-only instance matching from joint slot
decisions and reports missing output as no-match, never correct absence.
All images are correlated views of one stack/disassembly sequence.

Stop after reporting this experiment. No automatic second method, simulation,
training, ROS integration, manipulation or hardware control is included.
