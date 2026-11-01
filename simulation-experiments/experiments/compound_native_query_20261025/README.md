# Native fingertip compound validation

The offline 48-cell CAD approximation passed its sampled audit, but native
first-surface query quality **failed**. No custom-tip contact, grasp or extraction
is validated. The shared visual workcell and earlier stock-pad control are intact.

| Default Pueue job | Frozen source | Outcome |
|---|---|---|
|1766|`9d789ab`|Offline geometry audit passes; separate [offline evidence](../tip_partition_20261025/compound/README.md)|
|1767|`0fbc0bf`|Stops before cook/query: collider-dependent finger mass/inertia/COM differ from frozen1754 model|
|1768|`cd7aca3`|Stops before explicit initialization/cook/query: full-articulation setters restore fingers but alter nonfinger inertia readback|
|1769|`c6b141b`|Finger-only setters preserve all properties;42/42 observation-integrity checks pass, native tested-feature quality fails|

The original two full-articulation setups remain failed and closed. One reviewed
finger-only API change avoids collateral writes to arm links. This is an explicit
aggregate **three native executions**, not a fresh improvement pool. Cumulative
supervised process time is45.996s/180s. This gate is closed with no automatic
recook, threshold, geometry, setter-order or contact trial.

| Job1769 measurement | Left | Right |
|---|---:|---:|
|Target rays / all rays|42/96|42/96|
|CAD-hit misses / unexpected target hits|0/0|0/0|
|Clear, non-grazing reference hits|42|42|
|Clear first-hit errors greater than100µm|7|5|
|Largest absolute first-hit error|5.000mm|5.000mm|
|Positive target overlaps in27 CAD-free50µm spheres|0|0|
|Actual valid single-hull cell descriptors|48|48|

All192 binary parities pass, but some rays reach a rear-body cell instead of the
expected front surface. Both worst rays are`grid_4_1`: CAD first distance21.5mm,
actual26.5mm. They are not flagged as original-STL edge/grazing cases. No reference
hit is excluded. The overall quality result remains **FAIL**.

The SDK returns6–9 vertices and5–9 polygons per cell, versus up to133 offline
input vertices; saved descriptor bounds differ by up to0.593mm. These are
observations, not proof of descriptor/active-shape identity or a causal diagnosis.
Compared with the older automatic decomposition's same probes, observed bore
intrusions decrease from2left/9right to0/0. Negative sparse overlaps do not certify
the whole bore, and ray depths are not global Hausdorff or contact-failure metrics.

A later source/contract reassessment must distinguish cooking/active geometry
changes from compound-query reporting or partition-boundary behavior. One known
unresolved setting is the installed convex-hull schema's1mm `minThickness`
fallback; its effective runtime value was not recorded. This is a hypothesis,
not an established cause or permission to tune it in this closed benchmark.

Job1769 retains the full300-brick/301-part/930-native-link source, PGS32/4,
dt1/120, epsilon1e-4 and nominal joints. It has zero measured postassembly steps;
the shared initializer still performs one explicit preassembly step and internal
reset initialization. Only two exact-path finger views receive property writes.
The declared frozen1754 mass/COM/inertia model, actuator arrays, white geometry,
materials, q/qdot, source properties and native graph pass their strict guards.
This preserves a controlled simulation model; it does not measure real tool mass.
Physical fingertip mounting remains provisional.

Reproduce from a fresh stable snapshot through the **default Pueue queue**:

```bash
pueue add 'bash /absolute/path/to/frozen-snapshot/launch.sh'
```

- [Exact1769 command](../../runs/20261025T064519.962873Z-explicit-tip-native-query-targeted-mass/launch.sh)
- [Source/dependency/input hashes](../../runs/20261025T064519.962873Z-explicit-tip-native-query-targeted-mass/manifest.json)
- [Independent per-probe audit](../../runs/20261025T064519.962873Z-explicit-tip-native-query-targeted-mass/audit/evaluation.json)
- [Actual raw cooked descriptors](../../runs/20261025T064519.962873Z-explicit-tip-native-query-targeted-mass/output/cook_results.json)
- [Targeted property restoration](../../runs/20261025T064519.962873Z-explicit-tip-native-query-targeted-mass/output/property_restoration.json)
- [Aggregate supervised budget](../../runs/20261025T064519.962873Z-explicit-tip-native-query-targeted-mass/pipeline_supervisor.json)
- [All attempts, measurements and hashes](results.json)

The unchanged`unitree_sim_env` supplies Python3.11.15, Isaac Sim5.1.0.0,
NumPy1.26.0, SciPy1.15.3 and torch2.7.0+cu128. External Isaac Lab commit is
`80094be3245aa5c8376a7464d29cb4412ea518f5`. No shared dependencies or queue
concurrency were changed. No remote compute, training, ROS or hardware control.
