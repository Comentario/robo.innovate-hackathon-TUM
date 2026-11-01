# SAM 3 fixed text-only experiment — 24 October 2026

**Complete; no further inference or development follows this experiment.**
SAM 3 finds many individual visible faces with “LEGO brick”, but none of these
four fixed conditions establishes reliable exposed-brick selection. The generic
prompt also returns lower surfaces, merged rows and nested whole-stack masks.
AimAssist, its weights and shared dependencies were kept unchanged.

All 18 original 1280×720 JPEGs received all four exact prompts independently:
**72 image/prompt outputs**, with no manual prompts, crops, geometry refinement,
grid fitting, training or prompt tuning. Image features are encoded once per
image; the unchanged adapter resets all prompts between queries. No outputs
were pooled or passed through its candidate deduplication function. “Raw” means
processor-accepted binary masks, original model boxes and scores at the existing
confidence threshold **0.5**, not every network logit.

## Compact results

Raw-output totals cover all 18 views. All other columns below cover only the
**six annotated views**, containing 166 visual-face positives, 14 ambiguous
regions excluded and 23 sparse lower-fragment references. Repeated views are
correlated observations of one disassembly sequence, not independent stacks.

| Fixed prompt | Raw outputs, all 18 | Whole-stack localization /6 | Matched /166 | Missed faces | Merges | Duplicates | Lower-center flags |
| --- | ---: | ---: | ---: | ---: | ---: | ---: | ---: |
| stack of LEGO bricks | 14 | 5 | 0 | 166 | 5 | 0 | 0 |
| LEGO brick | 1062 | 5 | 124 | 42 | 26 | 0 | 19 |
| 2x4 LEGO brick | 11 | 0 | 1 | 165 | 2 | 0 | 0 |
| top surface of a LEGO brick | 3 | 0 | 0 | 166 | 2 | 0 | 0 |

Whole-stack localization means **any original model box has IoU ≥0.50 with
the approximate historical stack-ROI envelope**. It is separate from individual
matching and is not full-stack segmentation accuracy. The stack prompt returns
an output in 14/18 images; this is an output count, not 14 verified localizations.
Its stack-scale masks are expected for that prompt and count as merges only
when evaluated against the different, individual-brick objective.

For “LEGO brick”, 353 outputs occur in the six annotated views: 124 individual
matches, 26 merges, 19 unmatched lower-fragment-center flags, 171 other
unmatched/unresolved, 12 ambiguity exclusions and one outside-ROI detection.
Conditional scored ROI instance precision is **124/(353−12−1) = 36.5%**;
visual-face recall is **74.7%**. Unresolved detections include real unannotated
surfaces and other object scales, so they are not all background hallucinations.
Zero strict duplicates does not mean no redundant overlap: nested row/stack
masks are classified as merges first. None of these scores proves actual
current-top height, physical accessibility or a calibrated metric pose.

## What the masks show

[Representative overlays](results/representative_overlays.jpg) show img_1,
img_10 and img_16 under every fixed prompt. They are thumbnails of the unchanged
full-resolution overlays; no mask was repaired or refined.

- “LEGO brick” often separates visible faces, including surfaces through lattice
  gaps. It also returns whole-stack and row-scale masks alongside them.
- In img_10, “2x4 LEGO brick” returns two row-length masks and “top surface of a
  LEGO brick” returns one row-length mask, each spanning multiple bricks.
- The more specific phrases mostly yield no outputs on the other views; adding
  “top surface” did not provide an exposure classifier.

Supplementary pixel overlaps compare unchanged masks with the coarse historical
face polygons; those polygons are not exact full-object mask ground truth.
For “LEGO brick”, the **124 successful box matches only** have median
mask/polygon IoU **0.867**, reference coverage 0.916 and prediction coverage 0.945.
These statistics exclude the misses and unmatched masks and cannot represent
overall segmentation quality. Separately, 26 raw masks cover at least half of
two or more positive face polygons, and 24 cover at least half of a labeled
lower fragment. The 24 mask-overlap flags differ from the 19 unmatched-box-center
flags by definition; neither is physical layer classification.

Primary matching preserves the previous annotation experiment's rules:
one-to-one box-envelope IoU ≥0.50; detections containing centers and covering
at least half of two positive boxes are ineligible merges; unmatched nonmerge
matches to already matched references are duplicates. Box-center ROI, lower
and ambiguity checks use the unchanged historical polygons. Masks do not
replace model boxes or change matches. See [the frozen protocol](protocol.json),
[measurement definitions](EVALUATION.md), [full results](results/evaluation.json)
and [all-image counts](results/all18_counts.csv).

## Reproduction and artifacts

**Pueue job 1673**, default queue, completed successfully in about 48 seconds;
global concurrency remained one. Frozen source commit: **`99e8fdb`**. Stable
snapshot:

`runs/20261024T082019.190658Z-sam3-fixed-prompts/`

Its `output/predictions/<prompt_id>/img_N/` directories contain `raw.json`,
byte-identical raw mask PNGs and `overlay.png` for every image/prompt, including
empty outputs. `adapter_raw/` preserves the adapter's original manifests/masks.
Prompt IDs are `stack`, `brick`, `brick_2x4`, `top_surface`.
The [provenance](results/provenance.json) gives absolute paths and hashes; the
run's `artifact_hashes.json` identifies every generated prediction artifact.
Large masks/overlays remain in the ignored run rather than being duplicated
into Git. Representative full-resolution outputs include:

- [Generic brick, img_1](../../runs/20261024T082019.190658Z-sam3-fixed-prompts/output/predictions/brick/img_1/overlay.png)
- [2x4 phrase, img_10](../../runs/20261024T082019.190658Z-sam3-fixed-prompts/output/predictions/brick_2x4/img_10/overlay.png)
- [Top-surface phrase, img_10](../../runs/20261024T082019.190658Z-sam3-fixed-prompts/output/predictions/top_surface/img_10/overlay.png)
- [Generic brick raw records, img_16](../../runs/20261024T082019.190658Z-sam3-fixed-prompts/output/predictions/brick/img_16/raw.json)

Runtime was the existing cached Docker image
`sha256:ae4ae0cfc9d41eadf32bf9ac689252fccd3a1f804bb69d088b65e47d91cad317`:
Python 3.12.11, Torch 2.10.0+cu128, TorchVision 0.25.0+cu128,
NumPy 1.26.4, OpenCV headless 4.11.0.86, Pillow 11.3.0. Inference used the
RTX 5070, BF16, resolution 1008, no compilation or interactive predictor;
peak PyTorch allocation/reservation was 5.13/6.52 GiB. The queued runner took
37.65 seconds including model/hash setup and artifact writes; this is not a
latency benchmark. Independent scoring ran afterwards in the existing host
Python environment, not inside the inference process.

SAM source revision: `660a5e9e1b8b4c02c0ad97229b88a09a6e4ff5b7`.
Checkpoint: `facebook/sam3`, revision
`3c879f39826c281e95690f02c7821c4de09afae7`, `sam3.pt`, SHA-256
`9999e2341ceef5e136daa386eecb55cb414446a00ac2b55eb2dfd2f7c3cf8c9e`.
Cached bytes and hash were verified inside the queued job; nothing was downloaded.
AimAssist's adapter is copied unchanged with provenance under `upstream/`.
Its existing container supplies the SAM runtime; the absent native `.venv`
was not recreated. The container had no network and mounted RGB/software/weights
read-only; scoring annotations were excluded from its mounts.

From this repository root, on a clean committed experiment tree:

```bash
python3 experiments/sam3_20261024/submit.py
```

This freezes and queues a reproduction; it does not execute inference directly.
Small scoring-contract and syntax checks passed. The evaluator and independent
reviewer checked the measured counts and representative failure patterns; no
scoring, model or prompt changes followed the results. The current known-layout
baseline remains unchanged. **Conclusion: useful raw candidate masks, further
work required for reliable exposed-brick selection.** No simulation,
manipulation or additional experiment was started.
