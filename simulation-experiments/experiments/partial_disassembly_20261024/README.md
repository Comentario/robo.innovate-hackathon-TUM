# Bounded partial-disassembly simulation benchmark

Planning/configuration is frozen before implementation in `benchmark.json`
and `evaluation/protocol.json`. The original 300-brick design remains intact
as the source geometry. Each static case removes only specified layer-9 bricks,
retaining all lower layers and genuine native connections.

Ten state/color configurations use the same fixed overhead and oblique-side
cameras. Eight configurations are development data; scattered removals and
three isolated remnants are reserved as entire geometry groups, including
both views. Paired intact and adjacent-removal palettes test color effects
without a full factorial expansion. Five development sensor-corruption controls
need no additional rendering.

The unchanged detector/configuration must run first. At most three subsequent
improvement rounds each address one observed development failure with one
minimal independently reviewed change. Each round is frozen and queued before
processing; recovered/lost faces and confidence errors are compared explicitly.
The ledger in `rounds.json` records this budget and final release.

Reserved sensor images, predictions and scores remain outside implementation
decisions until the final method selection is frozen. Baseline and retained
versions are then evaluated on reserved configurations without further tuning.

All methods are stateless and views are evaluated independently. Combined-view
and temporal results are explicitly not measured. No training, manipulation,
ROS integration, hardware control, dependency installation or scheduler changes.
All rendering and batch perception/evaluation uses `pueue add` in the default
queue with stable source/configuration/input snapshots and reported job IDs.

Static initialized native graphs are validated; load-bearing dynamics are not.
Simulator inventory, removal state, identities, colors and actual poses are
confined to rendering/evaluation. Perception receives sensor observations,
nominal calibration and allowed geometric class priors only.

## Reproduction and outputs

Use `/home/faps/miniforge3/envs/unitree_sim_env/bin/python` for queued jobs.
Submission helpers perform only lightweight freezing/copying and call
`pueue add` in the default queue. Commit scoped changes before submission.
Never run their generated `launch.sh` directly outside Pueue.

Recorded submission pattern (before reserved release; the completed ledger
deliberately prevents starting another development batch):

```bash
python3 experiments/partial_disassembly_20261024/submit_render.py
python3 experiments/partial_disassembly_20261024/freeze_dataset.py --render-run <completed-render-snapshot>
python3 experiments/partial_disassembly_20261024/submit_perception.py --version B0
python3 experiments/partial_disassembly_20261024/submit_perception.py --version R1 --previous-evaluation <B0-snapshot>/output/evaluation/evaluation.json
python3 experiments/partial_disassembly_20261024/submit_perception.py --version R2 --previous-evaluation <R1-snapshot>/output/evaluation/evaluation.json
python3 experiments/partial_disassembly_20261024/submit_perception.py --version R3 --previous-evaluation <R2-snapshot>/output/evaluation/evaluation.json
```

Reserved evaluation adds `--split reserved`, after final method selection is
committed; parent reports must come from the reserved split. The submission
helper enforces the round budget and release guard. Do not rerun development
or choose parameters after release.

Each immutable `runs/*-partial-*` snapshot contains `manifest.json`, exact
source/configuration/input hashes, `submission.txt`, and a foreground
`launch.sh`. Perception outputs retain `detections.json`, overlays and
world-XY masks for each opaque observation ID. Case mapping is retained by
sensor preparation and scoring, and truth is retained for scoring; neither is
passed to perception. Quantitative results and evaluation-only references are
in `output/evaluation`.

The reporting helper `evaluation/summarize.py` aggregates saved associations
without rescoring. `package_report.py` makes before/after panels from saved
images. Both require a queued execution. The configuration manifest, tables,
exact run/job registry and final artifact location are recorded after the
bounded experiment completes.

## Development results and method selection

Development contains 16 primary views (eight configurations), 410 visible
current-layer face occurrences and 10 observable bracketed gap occurrences.
The five sensor controls are reported separately. Counts across views, colors
and removal states are correlated observations of the same design.

| Version | Confirmed faces | Wrong present claims | Present precision / recall | Correct observable gaps | Raw face locations matched |
|---|---:|---:|---:|---:|---:|
| B0 unchanged | 144/410 | 10 lower-layer | 93.5% / 35.1% | 0/10 | 408/410 |
| R1 band support | 144/410 | 0 | 100% / 35.1% | 0/10 | 408/410 |
| R2 compact singleton | 144/410 | 0 | 100% / 35.1% | 0/10 | 410/410 |
| R3 strict interior absence | 144/410 | 0 | 100% / 35.1% | 9/10 | 410/410 |

R1 lowers only the band-support area threshold to 128 mm², admitting the
isolated upper brick instead of selecting the much larger lower layer. It
removes ten wrong confirmations through abstention. R2 adds one narrowly
guarded 2×4 component exception, while retaining the original Hough checks;
both singleton locations become uncertain hypotheses. R3 can relabel only an
existing uncertain, internally bracketed slot using actual finite lower-depth
returns. It preserves every present decision and chain coordinate.

All versions retain the same 144 correctly confirmed primary face IDs and nine
correct NaN-patch face IDs: zero recovered or lost confirmed faces. R3 has
266 uncertain physical targets, nine correct missing decisions and one
uncertain observable gap. Its nine missing calls have no wrong, wrong-height
or unverified call. No version declares absence from the NaN patch. The four
all-invalid/flat controls produce no supported claims.

Both views correctly select the next perpendicular layer when the entire upper
layer is removed. R2/R3 support the correct current-layer direction in all 16
development views; singleton confidence still fails RGB evidence overhead and
end/coverage evidence obliquely. The removed endpoint remains extent-unknown.
No endpoint or original-full-stack absence success is credited.

RGB evidence remains color/view dependent: intact mixed versus tan confirms
11 versus 15 overhead, but seven versus four obliquely; the adjacent-removal
mixed versus repeated pattern confirms 11 versus 24 overhead and six versus
11 obliquely. These are paired comparisons of the same geometry, not a claim
that any palette is universally easier.

The selected method is a useful conservative surface/chain/gap hypothesis
generator. Confirmed-face recall did not improve and it is insufficient as a
complete autonomous partial-disassembly perception solution. Rendered depth
is ideal, camera calibration is nominal, native graphs are static, and
conditional metric errors do not establish physical grasp or insertion
accuracy. Combined-view and temporal results are not measured.

## Reserved results (opened after final selection)

Final selection was committed at `d7c5b47` before reserved release (`7dbc98a`).
No algorithm, threshold or version-selection change followed that release.
The reserved set contains two geometry groups, four views, 54 positive face
occurrences and eight observable bracketed gaps.

| Version | Confirmed faces | Missed faces | Precision / recall | Correct gaps | Wrong / unverified missing |
|---|---:|---:|---:|---:|---:|
| B0 | 27/54 | 27 | 100% / 50% | 0/8 | 0 / 0 |
| R1 | 27/54 | 27 | 100% / 50% | 0/8 | 0 / 0 |
| R2 | 27/54 | 27 | 100% / 50% | 0/8 | 0 / 0 |
| R3 | 27/54 | 27 | 100% / 50% | 6/8 | 0 / 0 |

All methods confirm the same 27 positive face occurrences: 17/24 overhead and 10/24
obliquely in scattered removals. R3 finds all four observable gaps overhead
and two of four obliquely. Two side-view gaps remain phase-uncertain because
the endpoint checks do not support a selected chain phase.

The three isolated remnants fail direction support in both views for every
version, despite selecting their correct height: six physical target
occurrences have no candidate, and six reference ridges are uncovered. The
single-component fallback intentionally does not accept three separate
compact components. The other 21 positive targets are matched uncertain
hypotheses. Raw geometry matches 48/54; it is not 48 confirmed detections.

There are no confident merges, duplicates, lower-layer, height-inconsistent or
unresolved extra detections on the reserved set. No confirmed faces are
recovered or lost globally versus B0 or between rounds. There are no reference
ridge splits or mixed-ridge parent chains; conditional phase errors and all
unresolved decisions remain in the saved tables. These measures do not test
unknown original extent or hidden physical surfaces. Sensor-supported boundary
labels mean measured depth/edge evidence, not independently verified seam truth.

Rendering used job **1686**; development B0/R1/R2/R3 used **1687–1690**;
reserved B0/R1/R2/R3 used **1691–1694**. Exact snapshots, commits and score
hashes are listed in `executions.json`. Source snapshots preserve every
previous result and all raw outputs. All jobs used the default Pueue queue.

Recommendation: retain R3 for conservative simulation hypotheses and observed
interior-gap decisions. It improves false-layer rejection and absence handling,
but does not improve confirmed-face recall and does not detect sparse multiple
remnants. This bounded experiment is complete; no broader perception method,
simulation expansion, training or robot work follows automatically.

## Final artifacts and runtime

- [Image panels and compact tables](../../runs/20261024T155602.872659Z-partial-final-report/output/index.html)
- [All metrics and artifact paths](../../runs/20261024T155602.872659Z-partial-final-report/output/tables/summary.json)
- [Configuration/source manifest](../../runs/20261024T155602.872659Z-partial-final-report/output/configuration_manifest.json)
- [Completion, dependency versions and Pueue IDs](completion.json)
- [Exact perception/evaluation snapshots](executions.json)

Report packaging used job **1695**. Its immutable foreground `launch.sh`
contains the exact aggregation/panel commands. All ten jobs completed
successfully; default concurrency remained one. Every render, prediction,
mask, reference and baseline result remains in its original run directory.

The reused runtime is Python 3.11.15, Isaac Sim 5.1.0.0, Isaac Lab repository
2.3.2 (its extension/distribution version is 0.54.3), BrickSim
0.1.0.dev645+gcbd5de3, NumPy 1.26.0 and OpenCV 4.10.0. No dependencies were
installed or shared environments changed. Exact dependency/source identifiers
are in `completion.json`; rendering used the snapshotted project `.deps`.

Isaac's post-capture cleanup stalled on these initialized scenes. The bounded
supervisor first validated each capture, then terminated only its owned
process group after the cleanup deadline. This is recorded separately in each
capture's `supervisor.json`; accepted images have strict native graph,
PhysX/USD pose and unchanged-state validation. No load-bearing connection
dynamics or physical camera calibration was validated.
