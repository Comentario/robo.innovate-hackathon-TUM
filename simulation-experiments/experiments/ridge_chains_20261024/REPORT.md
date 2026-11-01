# RGB ridge chains — bounded experiment result

**This variant does not improve overall instance recovery or demonstrate
missing-brick handling.** It produces useful local chains without requiring
every seam, but confirms only **35/166 faces (21.1% recall)**. Conditional
present precision is 92.1%; that selectivity must be read alongside the low
coverage. It declares **no missing slots** and falsely calls one of the six
supplementary absence regions present. No tuning or second perception method
was attempted after this result.

## Frozen method and inputs

All 18 original RGB JPEGs were processed. The planner and independent reviewer
agreed on the [small method](PLAN.md), and the [global settings](config.json)
were committed before batch evaluation. This selected variant uses RGB line
segments for ridge proposals; it does not require SAM ridge masks. Saved raw
SAM, dimension-only and dimension/seam-split outputs are unchanged comparison
baselines. SAM was not rerun.

Collinear image segments form paired-side ridge quadrilaterals. Each ridge is
locally projectively rectified, then width-constrained stud-profile periodicity
and an explicit half-pitch alias check supply an approximate scale. A small
count/phase search uses current end-line evidence and distributed cap/side/cross
evidence. All surviving segment endpoints contribute the ridge's perpendicular
side-fit residual; that term is constant across count/phase alternatives,
while longitudinal count consistency uses separate integer/end residual gates.
There is no calibrated camera model or shared baseplate grid.

Slot positions follow one fixed phase and four-stud period across the current
window. Internal seams verify boundaries; they do not individually trigger
splits. Disconnected collinear windows lose phase certainty rather than
independently establishing new certain indexing. Missing runs can use nearest
present anchors on both sides without shifting subsequent slots. Present needs
distributed cap/parallel-side evidence and a perpendicular-continuation veto;
missing also needs an observable parallel-footprint break. Weak or ambiguous
evidence remains uncertain.

No annotation polygon, historical manual registration, stud mark or label is
read by the chain program. References and old scored results are separate
evaluation inputs. Every original full extent/count stays unknown, including
when both current visible ends are supported; no six-brick count or missing
end brick is imposed. These are image-space hypotheses, not physical layer,
metric pose or accessibility estimates.

## Comparison on six annotated views

The unchanged reference contains **166 visual faces, 14 ambiguous regions and
23 sparse lower fragments**. Present declarations use the exact historical
one-to-one box-envelope IoU ≥0.50 scoring and merge/duplicate/category rules.
Precision excludes outside-ROI and ambiguous detections; recall includes every
unmatched reference as a miss.

| Method | Matched / missed | Merges | Duplicates | Lower-center flags | Unresolved | Precision | Recall |
| --- | ---: | ---: | ---: | ---: | ---: | ---: | ---: |
| Raw SAM “LEGO brick” | 124 / 42 | 26 | 0 | 19 | 171 | 36.5% | 74.7% |
| Dimensions only | 113 / 53 | 0 | 0 | 1 | 27 | 80.1% | 68.1% |
| Dimensions + seam splits | 117 / 49 | 0 | 10 | 1 | 27 | 75.5% | 70.5% |
| RGB ridge chains | 35 / 131 | 0 | 0 | 0 | 3 | 92.1% | 21.1% |

The chain method makes 39 present declarations in these views: 35 matches,
three unresolved and one historically ambiguous exclusion. That excluded call
is separately identified as false-present by the supplementary absence track;
the high primary precision does not hide that failure. Zero sparse-lower flags
is not complete lower-layer discrimination.

Global matched-reference sets recover/lose, versus raw SAM: **11/100**;
versus dimension-only: **13/91**; versus seam-split: **9/91**. Recovery is counted
per image/reference, not by changes in detection ownership. The large lost-face
counts outweigh those local recoveries.

## Missing slots, uncertainty and chain failures

Joint geometric matching of all slot decisions gives:

| Reference track | Present | Missing | Uncertain | No matched slot |
| --- | ---: | ---: | ---: | ---: |
| 166 positive faces | 35 | 0 | 32 | 99 |
| 6 supplementary absent faces | 1 (wrong) | 0 | 0 | 5 |

Positive decisive coverage is 21.1%. Absence decisive coverage is 1/6, entirely
incorrect; correct absence coverage is **0/6**. Missing precision is undefined
because there are no missing declarations, and no unverified missing claims.
Five unmatched absence references are not correct missing decisions. The three
old baselines make only present declarations and have no successful missing
calls either. The absence cases are correlated, sparse image-plane references,
not known hidden physical occupancy.

Across all 18 views: **749 ridge proposals → 64 accepted ridge hypotheses**,
with **264 slots: 116 present, 148 uncertain, zero missing**. Of those chains,
43 have selected phase and 21 ambiguous phase; 51 windows have open/partial
ends and 13 have bounded current ends. All 64 retain unknown original extent.
Most proposals are rejected at periodicity/alias checks: 631 weak-periodicity,
436 half-alias and 90 ambiguous-peak reason tags overlap among 685 rejections.
No bilateral present anchors are available for missing classification in 145
slot reason records. These are failure diagnostics, not new ground truth.

Existing face IDs support only a conditional visual-strip proxy: **19/36 strip
groups have no geometrically matched chain slot**. No fragmentation/mixing is
measured among covered groups, but that does not validate the uncovered chains
or original brick counts. There is no independent full-chain-count reference.

For the **67/166 geometrically matched positive slots**, including 32 uncertain
ones, longitudinal center displacement has median 0.041 reference lengths.
Face-end midpoint displacement has median/p90 **4.20/6.15 px** for 83 ends tagged
observed and **5.98/9.77 px** for 51 tagged inferred. These are alignment proxies
against approximate polygons, counting shared ends per face. They do not
establish true stud-center accuracy, observed seam truth or successful phase
estimation across all ridges. Historical stud marks were not used.

## Overlays and concrete cases

[Before/after comparison](results/representative_overlays.jpg) shows the three
old outputs and new chains. Green is present, amber uncertain, cyan a boundary
with cross-line support and magenta a model-inferred boundary. White absence
reference outlines are added **only for evaluation display**, after inference.

- **Img_13:** 18/28 faces confirmed; brighter strips support useful equal-size
  chains. Two five-present-slot chains include inferred boundaries: one current
  end and one internal boundary. The latter illustrates that a strong internal
  seam is not required everywhere. This is partial success, not complete ridge
  recovery.
- **Img_1:** slot `ridge_line0063_line0014_s02` falsely presents absence reference
  `c5r1` (IoU 0.540). Its seven cap responses and side evidence were insufficient
  to distinguish the lower-surface explanation. No successful real missing-slot
  example exists to show.
- **Img_7:** three of four chains have ambiguous phase; only one face is
  confirmed. **Img_9:** all 49 proposals fail pitch checks, producing no slots.

Tiny synthetic tests demonstrate unchanged coordinates/indexing across two
consecutive missing slots, alias rejection and uncertainty across unlinked
windows. They do not establish real gap recovery. The photographs show the
remaining proposal/scale/phase and occupancy failures directly.

## Artifacts and reproduction

Perception/scoring used default **Pueue job 1675**, successfully completed from
source checkpoint **`80db102`**. Saved-overlay composition only used default
**job 1676**; it performs no new perception. Concurrency and shared packages
were unchanged. Runtime: existing Python 3.11.15, OpenCV 4.10.0, NumPy 1.26.0,
and SciPy 1.15.3 for the unchanged assignment scorer; no new framework or model.

Stable perception snapshot:
`runs/20261024T092702.536426Z-rgb-ridge-chains/`.
Each `output/predictions/img_N/chains.json` contains source and merged ridge
segments, rejection reasons, quadrilaterals/transforms, pitch alternatives,
joint count/phase alternatives and margins, extent ambiguity, slot polygons,
decisions, evidence, and boundary provenance. `model_line_xy` separates the
fixed-chain boundary from the supported observed `line_xy`. Evidence scores
are not calibrated probabilities. Every view has an `overlay.png`.

- [Img_13 chain records](../../runs/20261024T092702.536426Z-rgb-ridge-chains/output/predictions/img_13/chains.json)
- [Img_1 gap-failure records](../../runs/20261024T092702.536426Z-rgb-ridge-chains/output/predictions/img_1/chains.json)
- [Full independent evaluation](results/evaluation.json), [summary](results/summary.json),
  [all-view counts](results/all18.csv), [settings](results/settings.json),
  [source/input/output hashes and paths](results/provenance.json),
  [gallery provenance](results/gallery_provenance.json).

From the repository root, after committing the experiment source:

```bash
python3 experiments/ridge_chains_20261024/submit.py
```

This snapshots original RGB, fixed source/configuration and evaluation-only
fixtures, then submits all processing/scoring through default Pueue. The exact
saved-overlay job is recorded under
`runs/20261024T093227.814548Z-ridge-comparison-gallery/` with a stable script,
input hashes and launch command. All previous predictions and experiments are
preserved. No parameter changes followed batch results.

**Conclusion:** local model-based partitioning works, but this one-shot variant
does not improve the overall separation/coverage tradeoff enough and provides
no demonstrated missing-brick handling. Stop here as authorized; no automatic
new perception method, simulation, training, ROS or robot development follows.
