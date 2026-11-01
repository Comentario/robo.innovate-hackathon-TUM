# SAM mask size filter and seam splitting

**Applied and evaluated:** [results, limitations and overlays](REPORT.md),
Pueue job 1674. The raw masks remain unchanged.

One bounded postprocessing experiment on the saved “LEGO brick” outputs from
Pueue job 1673. No new SAM inference or changes to raw predictions, AimAssist,
the existing known-layout baseline, shared packages or historical annotations.

Use apparent mask dimensions to estimate a normal brick-sized image region from
a consistent per-image size cohort. Reject significantly mismatched dimensions.
Only a matching short side and a long side near an integer multiple may nominate
a split; each cut must have common-line grayscale seam evidence. Weak scale or
unsupported seams cause rejection with an audit record, never an invented cut.
This is approximate image geometry, not calibrated metric dimensions or layer
identification. Perspective, partial masks and low-contrast seams can cause misses.

Parameters and scoring are frozen before one all-18-image run. Raw, retained-only
and final split results use the same six-view historical references. Parent IDs,
size residuals, scale support, seam evidence and rejection reasons remain visible.
No duplicate suppression is added: overlapping children and existing detections
are counted by the evaluator.

After the source checkpoint, submit from the repository root:

```bash
python3 experiments/sam3_sizefilter_20261024/submit.py
```

The existing default Pueue queue runs a stable code/config/RGB/mask snapshot in
the existing host Python/OpenCV/NumPy environment, then a separate independent
scoring process. References are not passed to the filter. No training, simulation,
ROS or manipulation follows automatically.
