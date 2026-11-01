# Saved SAM mask dimension filter and seam splitting

Applied to all 18 images using only the saved **“LEGO brick”** masks and original
RGB images. Raw SAM outputs remain unchanged. No model inference, training,
simulation or manipulation was run. This is a separate postprocessing result,
not a replacement of the historical SAM experiment or active task controller.

**The filter removes most merged/fragment detections, with a recall cost.
Splitting recovers four previously missed faces but introduces duplicates.**
Automatic apparent-size estimation fails in one view and abstains in two;
the output cannot guarantee physical 2×4 identity or exposed-layer selection.

## Rule applied

The filter measures each binary mask's oriented minimum-area rectangle. It
estimates a normal short/long pixel size per image from the dominant coherent
cohort of compact, mostly connected masks with projected aspect 1.45–2.8.
At least six supporting masks and a 1.5× support margin over the next disjoint
size cohort are required. These are frozen engineering assumptions, not
calibration or proof that the cohort consists of complete bricks.

- Retain a mask when **both side lengths are within ±25%** of that estimate.
- Reject a significantly different short side or unsupported long side.
- A matching short side and a length near **2–6 normal lengths** can nominate
  a split. The length ratio must be within 0.20 of an integer.
- Search near each expected junction (±0.18 normal length), requiring grayscale
  derivative support at a **common cut line across the central 70% of width**.
  At least 65% of that width must support it above the fixed robust noise test;
  isolated stud-edge peaks at different positions do not suffice.
- Every seam and every resulting child's dimensions must pass. Otherwise omit
  the parent from final candidates and retain its unchanged source plus an
  explicit rejection/uncertainty reason. There is no equal-spacing fallback.

Accepted children partition the original foreground without adding, losing or
overlapping pixels within their parent. Cuts have image evidence, not manually
validated seam truth. Retained masks keep original model boxes; child boxes
are explicitly derived from their masks. Child confidence is inherited from
the parent and is not a calibrated per-child score. No duplicate suppression
or image-specific threshold tuning was added. Full settings: [config](config.json).

## Measured results

All 18 outputs contain **1062 raw masks → 432 retained single masks → 465 final
masks**, including 33 children from nine accepted split parents. Of 41 long
parents tested for seams, 25 lacked adequate seam evidence and seven failed
child-dimension checks. There were 477 rejected and 144 uncertain raw parents;
uncertain parents include all 112 masks from the two ambiguous-scale views.

The table uses the same **six annotated views / 166 visual-face references**
as before. Matching and ambiguity/lower-fragment rules are unchanged; raw scores
reproduce the prior experiment exactly.

| Stage | Matched / missed | Merges | Duplicates | Lower-center flags | Conditional ROI precision | Recall |
| --- | ---: | ---: | ---: | ---: | ---: | ---: |
| Raw SAM masks | 124 / 42 | 26 | 0 | 19 | 36.5% | 74.7% |
| Dimensions only | 113 / 53 | 0 | 0 | 1 | 80.1% | 68.1% |
| Dimensions + seam splits | 117 / 49 | 0 | 10 | 1 | 75.5% | 70.5% |

Final scored-view outputs total 166: 117 matched, ten duplicates, one lower
fragment-center flag, 27 other unresolved detections and 11 ambiguous exclusions.
There are no outside-ROI outputs. Precision excludes ambiguous and outside-ROI
cases; unresolved regions are not all background hallucinations. Lower labels
are sparse image-plane fragments, not a physical-layer classifier. The views
are correlated observations of one disassembly sequence.

Final global matching recovers **four** previously unmatched faces (two each
in img_13/16) and loses **11** originally matched faces. Fourteen split children
occur in annotated views: eight receive matched assignments and six duplicate
assignments. Eight matched children do not mean eight new recoveries because
some take assignments from retained masks. Final ten duplicates include those
assignment changes; separately, 14 mask-overlap pairs across all 18 views have
IoU ≥0.8 and all involve children. Both kinds of redundancy remain visible.

## Important failures and overlays

[Before / size-filtered / split overlays](results/representative_overlays.jpg)
include successful cleanup, strip splitting and the failed scale estimate.

Most estimated normal sizes are about 40–49 by 78–99 px. In **img_10**, the
dominant eligible cohort is instead **20×44 px**, a fragment-sized hypothesis;
the filter loses all four previously matched faces there. **img_11/12** have
ambiguous competing cohorts and produce empty filtered outputs, explicitly
recorded as uncertain rather than verified absence. No manual replacement
scale was inserted to improve these results.

Apparent mask size alone cannot resolve these scale ambiguities. Perspective,
partial visibility and weak same-color seams also cause misses. This version
demonstrates the requested filtering/splitting operations, but reliable use
needs a trustworthy expected image scale or calibration. No additional scale
heuristic or automatic deduplication was tried after seeing these results.

## Artifacts and reproduction

Default Pueue **job 1674** succeeded in about 18 seconds, source checkpoint
**`70118a2`**, with unchanged global queue concurrency. Stable snapshot:

`runs/20261024T084549.641504Z-sam3-size-filter/`

`output/processed/img_N/retained_only/` and `final/` contain mask PNGs,
machine-readable `raw.json` detections and full-resolution `overlay.png`.
Each image's `diagnostics.json` records all source-parent decisions, scale
cohorts/support, side residuals, seam lines/evidence, child IDs and residual
pixel checks. Original inputs are copied with hashes under `inputs/brick/`;
no rejected or uncertain raw mask was deleted.

- [Final img_13 overlay](../../runs/20261024T084549.641504Z-sam3-size-filter/output/processed/img_13/final/overlay.png)
- [Final img_16 records](../../runs/20261024T084549.641504Z-sam3-size-filter/output/processed/img_16/final/raw.json)
- [Img_10 failed-scale audit](../../runs/20261024T084549.641504Z-sam3-size-filter/output/processed/img_10/diagnostics.json)
- [Compact summary](results/summary.json), [per-image CSV](results/by_image.csv),
  [independent scores](results/evaluation.json), [provenance and full-result hash](results/provenance.json).

The evaluator uses a byte-identical copy of the historical SAM scorer and
unchanged reference labels. Full implementation diagnostics remain in the
hashed run evaluation rather than being duplicated into the compact results.
References are passed only to the separate scoring process. Runtime is the
existing Python 3.11.15, OpenCV 4.10.0, NumPy 1.26.0, SciPy 1.15.3 environment;
no dependencies were installed or changed.

From the repository root, with a clean committed experiment tree:

```bash
python3 experiments/sam3_sizefilter_20261024/submit.py
```

The wrapper validates the old input hashes, snapshots code/configuration and
submits the complete mask-processing/scoring batch through default Pueue.
Small synthetic checks cover ambiguous-scale abstention, common-line seam
support, no seam on flat input, exact mask partitioning and unchanged matching.
An independent evaluator and reviewer inspected results and failure overlays.
Only this frozen postprocessing run was performed.
