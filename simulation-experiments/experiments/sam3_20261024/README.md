# Fixed SAM 3 text-only experiment

**Completed:** [compact measured results and artifacts](REPORT.md), Pueue job
1673. No prompt tuning or follow-on development is included.

A subsequently authorized [dimension-filter/seam-split experiment](../sam3_sizefilter_20261024/REPORT.md)
uses these saved raw masks without rerunning SAM or changing this experiment.

Bounded comparison of four independently reset text prompts on all 18 uploaded
wrist-camera JPEGs. This experiment does not change the active known-layout
baseline, AimAssist, shared dependencies or model weights. No manual prompts,
geometry refinement, grid fitting, prompt tuning, training or simulation.

`config.json` fixes the requested prompts and existing SAM settings.
`upstream/sam3_candidates.py` is a byte-for-byte copy of AimAssist's adapter;
`upstream/provenance.json` records its origin and hashes. The cached container
is pinned by immutable image ID and the local checkpoint by SHA-256. No native
virtual environment is created. The inference container has no network and
cannot see evaluation references. Raw masks, model boxes and scores are saved
before additional filtering or deduplication. The existing processor confidence
threshold remains 0.5; these outputs are not unfiltered network logits.

From the repository root, after committing the experiment source:

```bash
python3 experiments/sam3_20261024/submit.py
```

The wrapper copies code, images, configuration and scoring references into an
ignored timestamped `runs/` snapshot, then prints the default Pueue job ID.
It runs foreground Docker inference followed by separate scoring in the existing
host runtime. No global queue settings are changed. Inputs and source hashes
are frozen before inference; generated artifacts remain at the reported path.

See [evaluation definitions](EVALUATION.md) and the frozen [protocol](protocol.json).
Whole-stack ROI localization, individual-face box matching and supplementary
mask overlaps are separate measurements. Only six views have reference labels;
all 18 receive predictions. Correlated views do not establish generalization.
