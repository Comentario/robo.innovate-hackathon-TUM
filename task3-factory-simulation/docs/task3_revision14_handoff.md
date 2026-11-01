# Task 3 — autonomous brick handling simulation

This branch shares the complete Task 3 source and the latest offline 3D checkpoint (revision 14). Tasks 1 and 2 are independent and are not imported here. No ROS, GPU, Node.js or Isaac Sim is required.

## Open the existing demo first

From the repository root, using Python 3.10 or newer:

```bash
python3 scripts/open_task3_checkpoint.py
```

On Windows, use `python` if `python3` is unavailable. Open `artifacts/task3_checkpoint/index.html` in Edge, Chrome or Firefox with WebGL enabled. The page includes Three.js, equipment images and the recorded simulation; no server or network connection is needed. Use the playback controls, drag to orbit, scroll to zoom and hover/click equipment for its specifications. The inspection panel can be expanded.

The compressed checkpoint is included in Git. Extraction also provides `run.json` for audits or visual-only changes. Allow approximately 450 MB of free disk space. Existing output directories are never overwritten.

## Install and run a new simulation

Run all commands from the repository root:

```bash
python3 -m pip install --target .deps/plant_sim -r plant_sim/requirements.txt
python3 scripts/greenfield_demo.py --config config/greenfield_dual.json --output-dir artifacts/my_task3_run
```

Open `artifacts/my_task3_run/index.html`. Choose a different output directory for each run. SimPy 4.1.2 is the only external Python dependency; Three.js and its license are bundled in `third_party/three`.

## Change only the visualization

```bash
python3 scripts/greenfield_refresh_view.py artifacts/task3_checkpoint --output-dir artifacts/my_task3_view
```

This reuses the recorded material trajectories and KPIs. It does not rerun SimPy. Mechanical or scheduling changes require a new simulation.

## Verify the shared checkpoint

After installing SimPy and extracting the checkpoint, on Linux/WSL/macOS:

```bash
GREENFIELD_MECHANICS_REPORT=artifacts/task3_checkpoint/run.json \
GREENFIELD_FIXED_REPORT=artifacts/task3_checkpoint/run.json \
GREENFIELD_SCENE_REPORT=artifacts/task3_checkpoint/run.json \
GREENFIELD_SCENE_GEOMETRY=artifacts/task3_checkpoint/scene.json \
PYTHONPATH=.deps/plant_sim \
python3 -m unittest discover -s tests_greenfield -v
```

The geometry audit additionally requires a browser-exported scene file and `GREENFIELD_SCENE_GEOMETRY`. Without that file its scene test is skipped; do not describe a skipped audit as a passed collision check. Review `scripts/greenfield_scene_audit.py --help` for the audit interface.

## What this checkpoint demonstrates

Two dehacking lines, eight cells, inspection/rejection, three accepted shade queues, incremental mixed-row formation, same-height reversible surge belts and guided output palletizing. Discard bins are stationary. Reference results are approximately 2,218 conforming shipped bricks/hour for the synthetic finite batch. Partial pallets and work in progress are not counted as shipped.

Fixed challenge inputs: a kiln cart has 28,800 bricks in 36 stacks of 800; each stack is 10 × 4 × 20 and each layer contains 40 bricks. Output pallets contain 10 × 4 × 14 = 560 bricks. **The shared reference run processes only four input stacks (3,200 bricks), not a full kiln cart.** Product weights, defect distributions, timing assumptions and equal-shade recipe are explicitly modeled assumptions, not verified factory measurements.

This is a discrete-event and kinematic proof of concept, not a commissioned plant or rigid-body physics validation. Existing audits do not establish all moving-tool collisions, friction, gripping forces or physical vision accuracy. Higher-capacity continuous transport and alternative mixing mechanisms are under research; 10,000–20,000 bricks/hour are design scenarios, not achieved results.

## Where to contribute

| Area | Files |
| --- | --- |
| Scheduling, queues and mixing | `greenfield/model.py`, `twin.py`, `surge.py` |
| Motion timing | `greenfield/motion.py` |
| 3D geometry and interaction | `greenfield/viewer_dual.js`, `viewer_dual.html` |
| Equipment references and images | `greenfield/catalog.json`, `greenfield/assets/SOURCES.md` |
| Reports and audits | `greenfield/report.py`, `clearance.py`, `interference.py` |
| Current parameters | `config/greenfield_dual.json` |
| Regression tests | `tests_greenfield/` |
| Earlier prototype | `plant_sim/`, `config/plant_demo.json`, `tests_plant/` |

Keep visible demo text in English. Preserve baseline evidence and make small, verified commits. Document whether each change affects only rendering or also simulated behavior and KPIs. Do not remove acceleration, change material accounting or increase declared speeds solely to improve the throughput number.

Historical engineering notes remain in Spanish under `docs/`; start with `docs/flow_optimization_14.md` and `docs/engineering_revision_12.md`. Earlier notes contain superseded checkpoints. `task3_checkpoint/provenance.json` identifies the original source commit. The team repository history is preserved; unrelated work is not replaced.
