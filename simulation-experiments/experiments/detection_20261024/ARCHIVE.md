# Historical experiment checkpoint

This directory records the completed real-image pretrained-detector comparison
and its incomplete simulation comparison. It is retained as historical evidence,
not the current perception implementation.

## Retained evidence

- `REPORT.md`: scope, measurements, limitations and conclusions.
- `reference/annotations.json`, `inventory.json`, `counts.json`, `README.md`,
  `build_reference.py`: independently specified references and source hashes.
- `results/real_evaluation/`: fixed matching protocol and measured errors.
- `results/inference_provenance.json`, `inference_pueue_logs.json`,
  `all_image_counts.csv`: checkpoint identifiers, weight/version hashes,
  commands and jobs 1665/1666.
- `scripts/`: standalone historical inference, evaluation and gated render
  reproduction; none will be imported by the new geometric perception package.
- `simulation/`: explicit missing-geometry dependency for the original
  360-brick, ten-layer stack. No smaller stack substitutes for that benchmark.
- `artifact_hashes.json`: locations and hashes of the larger local artifacts.

Large artifacts remain on disk without being added to the checkpoint commit:
`models/` (published weights), prediction overlays, individual reference PNGs,
and downloaded upstream notebooks. Small raw prediction JSONs are checkpointed;
the complete local prediction directory is `results/real_predictions/`.
The immutable source runs remain at
`runs/20261023T223642.271685Z-detection-real/` and
`runs/20261023T223848.668564Z-detection-real/`.
All 18 original photographs remain at `resources/realsense_d435i_lego/`, with
SHA-256 values in `reference/inventory.json` and inference provenance. The
input files are preserved; their absence from a source-only checkout must be
reported instead of generating substitute observations.

The new system will live under `perception/` with separate configurations,
evaluation records and execution commands. It may reuse reference annotations
and generic geometry mathematics, but does not reuse pretrained outputs as
inputs or silently claim the historical simulation comparison was completed.
