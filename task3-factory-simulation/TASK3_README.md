# Task 3 — latest production model handoff

The latest completed offline package is **Greenfield 37**. This update includes
its recorded replay, frozen packaged source, review evidence, the latest local
source, Unreal 37 exploration assets and updated NVIDIA VM handoff tools.
Earlier checkpoints and the October 27 guide remain available.

## Open the completed revision 37 package

From the repository root with Python 3.10 or newer:

```bash
python3 scripts/open_cart37_checkpoint.py
```

Open `artifacts/greenfield_37/index.html` in a WebGL browser. No server,
GPU VM or extra Python packages are required for the recorded playback.
Allow 250 MB for extraction. The extraction refuses to overwrite an existing file.

The frozen package and matching replay live in `task3_checkpoint/greenfield_37/`.
`provenance.json` records hashes, the source commit and the difference between
recorded package and later local source. `packaged_source/` contains the exact
model, logistics and rendering scripts extracted from that HTML.

## Verify the recorded model

```bash
python3 scripts/verify_cart37_checkpoint.py task3_checkpoint/greenfield_37/combined-ccaf03c52e40aaca.json.gz
```

The validator checks material conservation, pallet identity, mixed recipes in
three dimensions, category-specific orders, rejection interlocks and synchronized
layer transfers. Evidence in `evidence/` includes the earlier browser checks and
review images; those historical checks are distinct from checks rerun at handoff.

## Latest editable source

The root `greenfield/` includes subsequent local changes to row accumulation,
retention stops and rendering that are newer than the recorded package. They
are preserved without claiming that the older replay validates them. In particular,
the source fingerprint differs from the replay fingerprint; see provenance.
`python3 scripts/cart_demo.py` packages that current source, and only embeds a
cache matching its fingerprint. Without such a cache it runs the browser model.
The packaging tool is Python; the cart model runs in JavaScript. The earlier
SimPy models and their tests remain available.

## Revision 36 and older deliveries

`python3 scripts/open_cart_checkpoint.py` still extracts revision 36. Its audit
and known issues remain under `task3_checkpoint/greenfield_36/audit/`.
See `docs/task3_handoff_20261027.md` for the prior guide and
`docs/task3_revision14_handoff.md` for the original SimPy checkpoint.

## Jacob VM: current model installed

The completed revision 37 package and editable source snapshot from commit
`5661f11` are installed at `~/workspace/brickflow-final-model/` on
`brickflow-cinematic-jacob-4gpu`. See `docs/jacob_final_model.md` for the
Brev tunnel command, local demo URL and verification scope. This is the
browser model deployment; it does not complete a native Unreal 37 port.

## Unreal and NVIDIA VM

Start with `unreal/README.md`, `docs/unreal_native_goal.md`,
`docs/unreal_continuous_film.md` and `docs/unreal_four_gpu_vm.md`.
`unreal/Brickflow/` contains the editable Unreal 5.8.4 project, C++ simulation,
materials and geometry. `unreal/tools/` contains build, package, render,
collection, replication and restored-workspace verification scripts.
`cinematic/` retains the Blender/cloud workflow.

The Unreal 37 candidate exports, source snapshots and review reports are in
`task3_checkpoint/unreal_migration37/`; read `docs/unreal_greenfield37_review.md`
for their dated limits. They are exploration assets, not a completed native port.
Updated VM evidence is in `task3_checkpoint/unreal_four_gpu/` and
`task3_checkpoint/unreal_jacob_four_gpu/`. No credentials are included.

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
