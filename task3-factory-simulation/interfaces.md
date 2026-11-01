# Proposed contract v0.1 — pending team agreement

## Planning input

A JSON list of objects with `id` (a non-empty, unique string) and `color_group` (a non-empty string).
Additional attributes, such as `score`, are ignored. The numeric identifiers in the roadmap's
conceptual example have to be converted to strings explicitly in the perception adapter.

Configuration: `rows`, `columns`, `layers` as positive integers. Each cell holds one brick.
Optionally `target_ratios`: a map from category to a finite weight >= 0, with a positive sum. The
weights are normalized; categories that are left out get weight zero and are not selected. Without
explicit weights, the inventory's proportion is kept. If there are not enough eligible bricks, the
whole plan is rejected. If a shade is missing, it is redistributed among the available eligible
shades and the deviation is reported; bricks are never invented.

## Planning output

An object with `schema_version`, `shape`, `blend`, `placements` and `metrics`. `blend` holds the
quantities per category. Each placement has `step` (from 1), `brick_id`, `color_group`, `layer`,
`row` and `column` (indices from 0). A complete layer is executed before the next one, by rows and
columns. `metrics` holds the target and actual proportions, the L1 deviation, and the number of
neighboring pairs of the same shade (including vertical neighbors between layers).

These positions are logical: task 3's integration has to convert them to physical coordinates. They
do not represent poses, orientations, structural stability or safe trajectories. Reject plans that
are incompatible with the real grasp, support or layout.

## Integration

API: `planning.make_plan(inventory, rows=..., columns=..., layers=..., target_ratios=None) -> dict`.
Contract errors: `ValueError`.

CLI: `python3 -m planning INVENTORY --rows R --columns C --layers L [--ratios '{"dark": 1, "light": 1}']`.
On success: JSON and exit code 0; on error: a message on stderr and exit code 2.

## Extension v0.2

`make_plan` additionally accepts `mode="mixed" | "smooth"`,
`tone_values=None | {category: value_between_0_and_1}` and
`shortage_policy="redistribute" | "reject"`. Smooth mode requires finite values for the selected
categories. `reject` requires the quantities to match the recipe rounded by the same incremental
assignment, with no stock limitation. The API keeps `redistribute` for compatibility; the example
configurations use `reject`.

The v0.2 output adds `policy` (mode, shortfall policy and shade scale) and
`metrics.mean_neighbor_tone_distance` (null in mixed mode; 0 when there are no neighbors). The CLI
accepts `--config PATH`; the dimension arguments and `--ratios` take precedence over the JSON.
Unknown keys are rejected.

## Reproducible integration example

See `examples/handoff/`. The v0.2 reference output is a complete plan over a synthetic inventory.
Availability management, reservations, confirmations and partially built pallets are not part of this
API yet; they need coordination with integration before running hardware.

## Optional per-face extension v0.3

See [docs/faces.md](docs/faces.md) and `examples/faces/`. `planning.faces.make_face_plan` consumes
observed faces and allowed orientations, keeps unique physical IDs, and produces placements with
`visible_face` and `orientation_id`. The simulated consumer validates both versions, v0.2 and v0.3.
The earlier API keeps its behavior.

## Local distribution diagnostics (additional fields)

`metrics.distribution` publishes counts per layer and row, the local targets from the recipe and from
the selected blend, and the L1 errors against both. This separates a stock shortage from spatial
accumulation. Mixed assigns blend quotas per layer and row before penalizing equal neighbors. Smooth
keeps its local criterion. The rounding is deterministic and does not guarantee the global visual
optimum.

## Transport-independent execution contract

`execution.compile_job(plan, inventory, cell_config)` translates placements into object-reference
actions; `ExecutionAdapter.perform(command)` acknowledges each action with
succeeded / failed_before_action / unknown. `config/cell.json` defines poses, phases and states. It
does not change the planner's contract and does not require ROS. The ROS `--cell` mode publishes
these same actions and simulated execution states over the optional adapter.

## Task 1 handoff, and integration between tasks

See `examples/perception/snapshot.json`: a versioned snapshot with an ID, a declared origin, the
per-face modality and the item list. Planning does not require poses. Executing a perception origin
requires metric poses per ID in the cell frame; pixels are never reinterpreted as meters. The input
adapter will be adjusted to the real producer when it arrives.

The final evidence uses pallet-observation-0.1, bound to `run_id` and `plan_digest`. Without evidence
the state is `awaiting_observation`, even if execution finishes. The SQLite journal keeps one cycle's
reservations, and the pending and acknowledged actions.

## Explicit recovery of a partial pallet

`cell-reconciliation-0.1` binds complete evidence to the run, the plan and the checkpoint
fingerprint. `integration.recovery.assess_recovery` produces a proposal without motion;
`Journal.recover_simulation` creates a child run with a verified preserved prefix and the remaining
tasks, for the acknowledgement simulator only.
`execution.compile_job(..., preserved_placements=PREFIX)` excludes that prefix from the picks and
requires poses only for the pieces that are still available.

## Recovery of the Panda reference

`Journal.recover_reference_simulation` is a separate path from logical recovery. It requires the
concrete Panda adapter, a scene checkpoint, a persistent safe-position preparation, and a current
comparison of the scene and joints. The cell-reconciliation-0.1 evidence adds `robot_scene` and
`robot_scene_digest`. The child keeps `panda_moveit_kinematic` and is only ready once its scene is
activated. It does not enable hardware or `resume_simulation` for Panda.

## Task 1 input: relative color, schema 0.2

`integration.person1_intake.convert_inventory(value, min_score=...)` converts task 1's
`color_estimated` / `accepted` inventory into our snapshot. It keeps `uniform` / `color_group_N`, the
Lab centers, the heuristic score and the pixel geometry; it excludes unknown, partial, possible
merges, ineligible items and scores below the threshold. It does not take in `source_poses` or face
identity: `source=perception`, `face_aware=false`. The snapshot is enough to plan; executing requires
measured metric poses like any perception input. The IDs are local to the image; categories from
different captures are not automatically treated as equivalent. See `examples/person1/`.

## Task 1 inventory in the reference cell

`integration.person1_simulation.prepare_person1_simulation(inventory, cell, config=None)` consumes
classes and scores without reclassifying or filtering by any additional score. It returns
`observed_snapshot` (perception), `staged_snapshot` (synthetic), `plan`, `job` and `handoff`. Only the
selected IDs are placed on the staging grid. The job keeps `person1_handoff` with the Lab centers, the
inventory fingerprint, the recipe, the counts and the provenance of the geometry. The execution block
for a real snapshot without measured poses is preserved.

## Task 1 continuity during recovery

The reconciler keeps `job.person1_handoff` and the staging snapshot's `producer` in the child cycle.
For that batch, it rejects class or score changes for known IDs, and IDs that were not included in
the staging. The Panda adapter also verifies that the provenance does not change when the new job is
activated. The recipe, plan and prefix stay intact; the child contains only new actions for the
remainder. Jobs with `synthetic_staging_grid` geometry are not accepted with `mode=hardware`.

## Task 3 — independent process simulation

`plant_sim.model.Plant(config).run()` consumes the versioned configuration in
`config/plant_demo.json`; it returns run status, config/provenance, KPIs, material
ledger, pallet IDs, per-layer/pallet mixing metrics and a timestamped event log.
Time is seconds; rates are bricks/hour; dimensions are millimeters. One product
per run. Input geometry is 10x4x20 and output 10x4x14 in the organizer example.
The synthetic detector is separate from the existing task 1 adapter. No ROS or
hardware commands are emitted. `blocked` requires explicit reconciliation; no
automatic restart is implemented. Generated HTML is an offline event-log replay.

### Task 3 mechanical trace, revision 1.1

The process config/report is now 1.1 and includes `seconds.lane_transfer` and
brick/lane/slot/destination context on correction operation-start events.
`compile_mechanics(report)` emits meter-based, Y-up identity tracks, tool paths,
attachment intervals and inspection observations. `validate_mechanics` audits
continuity and exclusive tool booking, not contact or collision physics.
Default `index.html` is now an offline Three.js 3D view; the 2D view is preserved
as `process_2d.html`. `mechanics.json` records paths separately from `run.json`.
No robot or PLC control is introduced.

### Task 3 automation revision 1.2

`automation` contains positive speeds [m/s], grip/release/settle/exposure/inference
pauses [s], and carry clearance [m]. `initial_arrival_s` is nonnegative. The old
`seconds` table no longer drives motion. Every operation-start event embeds its
actual `motion_plan`: ordered substeps, material/tool/auxiliary tracks and duration.
SimPy executes that recipe; the renderer reads it without re-planning.
`automation.timing` reports travel/dwell, explicit resource waits and shared-clock
rate arithmetic. Join nests and physical infeed/lane/pairer/stacker berths have
exclusive reservations. Photoeyes in the viewer use material coordinates;
sequence limit confirmations remain virtual. 3D export checks swept brick bounds
against fixed solids and refuses known penetrations. Scope excludes full contact,
brick-brick, tools/cables and dynamics. Multi-robot process capacity requires a
separate audited geometric layout before exporting 3D.
