# Motion-free active fingertip queries

The final corrected observation passes **34/34 data-integrity checks**, but the
unchanged automatic-decomposition proxy is not accepted as a faithful updated
tip model. Actual pad queries report overlaps in CAD-free bore regions and
millimetre-scale first-hit discrepancies. No contact trial follows.

| Attempt | Capture / independent audit | Outcome |
|---|---|---|
| Original setup, `e75efa2` | 1759 / 1760 | Both positive controls report no hits; four control records, zero pad probes |
| Query manager enabled, `8380bec` | 1761 / 1762 | All250 probes and34 integrity checks complete; geometry discrepancies observed |

Isaac Lab disables scene-query support by default in headless runs. The one
reviewed correction sets `env.sim.enable_scene_query_support=True` before
initialization, asserts the entire simulation configuration differs only by that
flag and the already tested PGS selection, and saves SDK/USD readbacks before
controls. The source geometry, registration, cooking settings, all fixed probes,
materials and nominal joints are unchanged. These two observational attempts
are closed; there is no third setup or automatic-decomposition sweep.

Each tip receives90 fixed contact-region rays,6 fixed bounds-axis rays and27
50µm bore-overlap probes, plus4 common Cube controls:250 queries. Every hit is
saved, including white-finger/other paths. Independent evaluation parses the
original STL, reconstructs probe frames and separates closest-pad from
closest-any hits. Simulator geometry is evaluation/fixture truth, not online
perception input.

| Per tip | Left | Right |
|---|---:|---:|
| Rays with expected CAD and actual pad hit | 42/96 | 42/96 |
| CAD-hit rays missing a pad hit | 0 | 0 |
| Pad-hit rays with no CAD hit | 0 | 0 |
| Largest absolute first-hit distance difference | 6.500mm | 1.346mm |
| Pad overlaps in27 CAD-free spheres | 2 | 9 |

The worst ray cases are neither edge-sensitive nor grazing under the frozen
reference flags. The left overlaps occur at CAD X=-10.5mm with approximately
0.598mm reference clearance; all nine right overlaps occur at X=-5mm with
0.500mm clearance. Probe radius is0.050mm. All positive overlap hits identify
only the corresponding `collisions/mesh_3` pad. These are conditional local
intrusion observations, not a claim of demonstrated grasp failure. Empty probes
do not prove absence, and ray distance is not a global mesh-error metric.

The full300-brick/301-part/930-link source, PGS/source32/4, nominal q/qdot,
source poses and graph are unchanged during the probes. The shared initializer
performs one nominal preassembly physics step; measured postassembly steps are
zero. Corrected capture plus the supervised audit command takes15.047s within180s
(the evaluator reports14.964s excluding its interpreter/import overhead). Full robot property
comparison, force/contact behavior, grasping and extraction remain untested.

## Reproduction and evidence

The existing `unitree_sim_env` is reused unchanged: Python3.11.15,
Isaac Sim5.1.0.0, torch2.7.0+cu128, NumPy1.26.0 and SciPy1.15.3. External
Isaac Lab commit is `80094be3245aa5c8376a7464d29cb4412ea518f5`.
All jobs use default Pueue; no global concurrency or environment changes occur.

- [Frozen capture command and snapshot](../../runs/20261025T044456.732801Z-active-tip-query-enabled/launch.sh)
- [Capture manifest and input hashes](../../runs/20261025T044456.732801Z-active-tip-query-enabled/manifest.json)
- [Runtime/USD query-support readback](../../runs/20261025T044456.732801Z-active-tip-query-enabled/output/prequery_setup.json)
- [All raw query observations](../../runs/20261025T044456.732801Z-active-tip-query-enabled/output/queries.json)
- [Independent audit command](../../runs/20261025T044722.913725Z-active-tip-query-enabled-audit/launch.sh)
- [Per-ray and per-sphere evaluation](../../runs/20261025T044722.913725Z-active-tip-query-enabled-audit/output/evaluation.json)
- [Machine-readable outcomes and hashes](results.json)

The earlier three-round [contact benchmark](../stage2_contact_20261025/README.md)
remains failed for the supplied tip; its stock-pad positive control remains
valid within its fixture scope. A reviewed reassessment may examine one explicit
CAD-derived convex compound. Its actual parts must preserve the bore and
contact surfaces before any cooking is authorized. This is not another
three-round allowance, a stock-pad substitution or an implemented repair.
