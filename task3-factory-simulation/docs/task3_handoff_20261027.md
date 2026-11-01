> **Current Greenfield 37 update:** use [the functional-layout handoff](greenfield37_layout_handoff.md). The revision-36 notes below are retained as historical context.

# Task 3 — production simulation and Unreal handoff

Current handoff: revision 36 offline demo, revision 37 source work in progress,
native Unreal project and NVIDIA Brev VM tooling. The earlier revision 14
checkpoint remains in `task3_checkpoint/`; its guide is preserved in
`docs/task3_revision14_handoff.md`.

## Open the latest recorded demo

From the repository root, Python 3.10 or newer:

```bash
python3 scripts/open_cart_checkpoint.py
```

Open `artifacts/greenfield_36/index.html` in a WebGL browser. The HTML is
self-contained; no server, GPU VM or Python packages are needed to play it.
The compressed original HTML and both replay caches are preserved in
`task3_checkpoint/greenfield_36/`. Allow 200 MB for extraction.

The existing revision 36 audit is preserved in
`task3_checkpoint/greenfield_36/audit/report.md`, together with images and
audit scripts. It reports known geometry, mixing and occupancy issues;
preserving the demo does not establish that those issues are resolved.
Some historical audit scripts retain their original local paths.

## Latest source: revision 37, in progress

`greenfield/cart_model.js`, `logistics.js`, `viewer_cart.js` and
`viewer_cart.html` contain the latest local work. `scripts/cart_demo.py`
packages them into `artifacts/greenfield_37/index.html`:

```bash
python3 scripts/cart_demo.py
```

There is no recorded revision 37 replay in this handoff. Without a replay
cache, that page runs the current JavaScript model in the browser; it is not
the validated revision 36 checkpoint. The packaging script is Python; the
current cart simulation itself runs in JavaScript. The earlier SimPy models
remain available in `greenfield/` and `plant_sim/`.

## Unreal and NVIDIA VM

Start with `unreal/README.md`, `docs/unreal_native_goal.md`,
`docs/unreal_continuous_film.md` and `docs/unreal_four_gpu_vm.md`.
`unreal/Brickflow/` contains the editable Unreal 5.8.4 project, C++ simulation,
materials and geometry. `unreal/tools/` contains build, package, render,
collection, replication and restored-workspace verification scripts.
`cinematic/` retains the Blender/cloud workflow.

The native Unreal reference is pinned to revision 30, independently of the
newer browser revisions. VM names and paths are documented for the owner;
credentials, engine installation and billing access are not included.
The four-GPU smoke test establishes adapter assignment, not full-render speedup.
Migration notes describe a checkpoint, not a new live VM status check.

Large deliverables are attached to the
[simulation handoff release](https://github.com/Programmercloud-cmd/robo.innovate26/releases/tag/simulation-handoff-20261027):
Linux native build, historical pitch, continuous 1080p film and split 4K master.
Download both `brickflow-continuous-4k.mp4.part-*` files into one directory and
join them in order:

```bash
cat brickflow-continuous-4k.mp4.part-00 brickflow-continuous-4k.mp4.part-01 > brickflow-continuous-4k.mp4
sha256sum -c SHA256SUMS
```

The release includes checksums for both parts and the reconstructed master.
`task3_checkpoint/unreal_evidence/` preserves local reports, traces and review
images; `simulation_handoff_provenance.json` identifies the source commit and
uncommitted files included in this snapshot.

## Reproduce the preserved native comparison

`task3_checkpoint/unreal_reference_30/` preserves the immutable replay caches,
native outputs and original JavaScript pose model. Compare numeric results:

```bash
python3 scripts/open_unreal_reference.py
python3 tests_native/compare_reference.py \
  --native-dir task3_checkpoint/unreal_reference_30 \
  --reference-dir artifacts/greenfield_30 \
  --output artifacts/native-comparison.json
```

This checks preserved outputs; rebuilding/rerunning Unreal requires the documented
engine and VM environment. Legacy SimPy tests need `simpy==4.1.2` from
`plant_sim/requirements.txt`.

## Evidence limits

Inputs and production assumptions are synthetic; recipes are team heuristics,
not official factory requirements. Kinematic motion and synthetic acknowledgements
do not establish independent physical or visual validation. Preserve producer
groups and scores at the perception intake; no manual reclassification workflow
or extra integration score filter is introduced.
