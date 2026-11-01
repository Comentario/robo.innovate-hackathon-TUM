# Stage1: frozen R3 frame integration

This experiment connects RGB/axial-depth observations to a small candidate
interface and explicit Challenge1 mocks. It does not establish detector
reliability, calibrated real-camera poses, physical accessibility or robot control.

Development states are intact I_mix, interior H_mix and endpoint E_mix, each with
the two unchanged final-workcell diagnostic views. P_mix and T_mix are reserved
for the frozen interface audit; these known historical patterns are not new
generalization evidence. Three development sensor controls use intact images:
all-NaN depth in each view, and top-view NaN patch [600,280,680,360]. Missing depth
does not mean physical absence.

`upstream/` is byte-identical frozen R3, verified by `upstream_hashes.json`.
Only the source-plate ROI is translated from the previous workcell coordinates
to table X/Y [-.128,.128] meters. No threshold, confidence or source change is
permitted. Camera calibration derives from configured scene design and presets;
saved actual camera or brick truth is not an input.

The queued orchestrator keeps three directories separate:

- `sensors/`: online package containing frames.json, calibration.json, opaque
  sensor paths and frozen R3 copies. No state labels or evaluation truth.
- `inference/`: per-frame raw r3.json, candidates.json and overlays, plus mocks.
- `evaluation_truth/`: private state/view mappings, actual simulator records and
  references, available only to independent evaluation.

The candidate contract reports table XY, shared-ridge yaw and an
`estimated_body_top_from_selected_band_m` assumption. It provides evidence and
abstention reasons with no calibrated covariance, physical layer identity,
grasp accessibility, tracking identity or full 6D/root-pose claim. Geometric
candidate IDs are meaningful only together with their frame ID.

Challenge1 mocks use one sensor-supported PRESENT candidate selected without
truth. Four separate fixtures exercise good-selected, good-unselected, faulty
and unknown results. Exact frame/candidate joins are required; non-present,
missing, duplicate, unknown or mismatched joins abstain. Destination strings are
declarative mock outcomes, not robot commands or a routing scheduler.

The integration gate requires at least one correct PRESENT in at least one view
of each ordinary development state, with zero false-confident/lower/gap claims.
Independent evaluation also reports all coverage, uncertainty and pose errors;
sparse abstention is allowed. Failure is reported rather than changing R3 or
tuning camera views. Reserved frames are processed only after interface freeze.

Commands below belong inside the existing default-Pueue frozen-job workflow.
The orchestrator owns submission, snapshots, reserved isolation and job IDs.

```sh
python experiments/stage1_20261025/render_stage.py --case H_mix \
  --benchmark experiments/stage1_20261025/benchmark.json \
  --geometry experiments/final_workcell_20261024/geometry.json \
  --cameras experiments/final_workcell_20261024/cameras_realism.json \
  --appearance experiments/final_workcell_20261024/appearance_config.json \
  --views all --output CAPTURE --headless --enable_cameras --device cpu
python experiments/stage1_20261025/calibration.py --geometry GEOMETRY \
  --cameras CAMERAS --output calibration.json
python experiments/stage1_20261025/prepare_inputs.py --sources PRIVATE_SOURCES \
  --calibration calibration.json --output sensors
python experiments/stage1_20261025/online.py --inputs sensors --output inference
```

The only tests run outside the queue are syntax and tiny contract fixtures;
actual sensor preparation, inference, rendering and evaluation require Pueue.

## One workspace-preprocessing comparison

The first development batch produced no candidates: the top view selected a
robot surface inside the source XY ROI, while the oblique view had sparse
top-band support. After inspecting that result, `workspace_v1.json` declares one
table-Z working volume [-.005,.20]m, based on the known approximately.10m tower
with margin. This is a post-baseline physical prior, not a tuned R3 threshold or
truth-derived pose. The optional `online.py --workspace workspace_v1.json`
backprojects axial depth using configured K/R/t and sets invalid/outside-volume
returns to NaN. Raw RGB/depth remain unchanged; processed_depth.npy and
preprocessing.json preserve the filtered input and counts separately.

Without the flag the original depth goes directly to unchanged R3. This is one
frozen development comparison, with no camera, detector or bounds sweep. Filtering
cannot recover pixels occluded by the robot or fix small brick image scale.
Removed returns remain unknown and cannot establish physical absence. If the
integration gate still fails, report the blocker rather than tune more parameters.

## Separate fixed source-scale camera experiment

After the distant-view development baselines yielded zero raw candidates,
`source_views_v1.json` defines one reviewed close-view pair. It copies
`cameras_realism.json` except for the two eye/target/up records. The configured
full-design reference remains table `(0,0,.1009)`m for every intact or partial
state. K, image dimensions, lights, geometry, appearance, R3 and the workspace
prior remain unchanged. Closer sampling is an experiment, not a measured camera
calibration or a guaranteed fix. The original benchmark/protocol stay intact;
`benchmark_source_views_v1.json` and
`evaluation/protocol_source_views_v1.json` preserve their cases and metric rules
while pinning the new cameras.

The following submitters create frozen default-Pueue jobs after scoped changes
are reviewed and committed. `--include-intact` captures I alongside H/E/P/T with
the same camera configuration. Reserved P/T images remain sealed until this
interface/configuration version is frozen. No reserved-result tuning is allowed.

```sh
python3 experiments/stage1_20261025/submit_render.py \
  --cameras source_views_v1.json --benchmark benchmark_source_views_v1.json \
  --include-intact
python3 experiments/stage1_20261025/submit_inference.py \
  --render-snapshot runs/RENDER_SNAPSHOT \
  --intact runs/RENDER_SNAPSHOT/render_output/development/I_mix \
  --split development --workspace experiments/stage1_20261025/workspace_v1.json \
  --cameras source_views_v1.json --benchmark benchmark_source_views_v1.json \
  --protocol evaluation/protocol_source_views_v1.json
```

New configuration paths are relative to this Stage1 experiment. Custom camera,
benchmark or protocol options require an explicit matching `--intact` capture;
the old distant I image must not be silently reused. Omitting the new options
preserves the original submission defaults.


## Measured results

| Version / split | Pueue | Confirmed / visible | Result |
|---|---:|---:|---|
| Wide-view unchanged R3, development | 1723 | 0/171 | No candidates |
| Wide-view unchanged R3, reserved | 1724 | 0/64 | No candidates |
| Fixed Z workspace, development | 1726 | 0/171 | Correct overhead band; all fragments rejected |
| Fixed closer views + same workspace, development | 1729 | 41/176 | Ordinary integration smoke passes |
| Fixed closer views + same workspace, reserved | 1730 | 19/66 | Sparse-remnant gate fails |

Jobs1722/1728 render the respective camera configurations. All confirmed
close-view candidates come from overhead: I15/H13/E13, T19/P0. No confident
false/lower/merge/duplicate target is measured, but raw geometry includes two
unconfirmed lower fragments. Development misses135 occurrences (127 matched
uncertain and8 no-match). New views change visibility171→176;38 previously
visible occurrences are newly confirmed,3 confirmed occurrences are newly
visible,0 prior confirmations are lost. No thresholds or R3 source change.

The mock four-class join and four abstention guards pass only after close-view
PRESENT candidates exist. Challenge1 remains **mocked**, not integrated.
Sparse residual failures remain; no tuning follows reserved results.

- [Close-view development results](../../runs/20261025T003437.436801Z-stage1-development-workspace_v1/evaluation/evaluation.json)
- [Close-view reserved results](../../runs/20261025T003437.726220Z-stage1-reserved-workspace_v1/evaluation/evaluation.json)
- [Overhead overlay](../../runs/20261025T003437.436801Z-stage1-development-workspace_v1/inference/f000/overlay.png)
- [Overall demo gates and limitations](../../docs/demo_progress.md)
