# Independent SAM 3 evaluation

The protocol was agreed and frozen before prediction inspection. Its reference
SHA-256 identifies the unchanged historical annotations: six correlated views,
166 visual faces, 14 excluded ambiguous regions and 23 sparse lower fragments.
The 18 photographs are observations of one stack/disassembly sequence.

Each of the four exact text prompts is an independent condition. The evaluator
uses the model's original image-coordinate boxes and processor-accepted masks,
before any additional deduplication. It never pools prompts or changes model
thresholds. "Raw" here means the existing adapter's processor outputs, already
subject to its confidence threshold, rather than every model logit.

Primary individual-instance scores reproduce historical box-envelope matching,
merge exclusion and unmatched-category precedence. Box centers outside the
approximate stack ROI are reported separately. An unmatched box inside a known
lower fragment is a sparse conservative flag, not a calibrated layer decision.
Other unmatched detections may include unannotated surfaces. Ambiguous reference
regions are excluded and their otherwise-unmatched detections ignored.

Whole-stack localization is measured separately against the approximate ROI
envelope on the six annotated views. A coarse whole-stack hit does not count as
an individual-brick match. The ROI is not a full-stack segmentation reference.

Mask overlaps are supplementary: unchanged masks against rasterized historical
face polygons, sparse lower-fragment polygons and the ROI. These polygons are
approximate visible-face references, not full object masks. Mask multi-face
coverage and box merges remain separate diagnostics. No mask-derived box
replaces a model box and no mask-overlap result changes primary matching.
There is no inferred stud center, orientation, physical exposure, metric pose,
quality classification or gripper accessibility result.

The queued inference launcher invokes scoring as a separate host-runtime
process after container inference, with scoring references excluded from the
inference process. All image-batch scoring must use default Pueue with a stable
snapshot. The five-line CLI interface is:

```bash
ROBO_PUEUE_JOB=1 /home/faps/miniforge3/envs/unitree_sim_env/bin/python \
  scoring_only/evaluation.py --predictions predictions \
  --reference scoring_only/annotations.json --output evaluation
```

`protocol.json` must be beside `evaluation.py`. The output is
`evaluation/evaluation.json`: all 72 condition/image counts, per-prompt totals,
correlation-group totals and detailed six-view box/mask diagnostics. Missing
prediction files or incorrect mask dimensions cause a failure rather than a
silently reduced benchmark. Tiny assignment/merge checks may run outside the
queue with `evaluation.py --self-test`; they process no uploaded images.
