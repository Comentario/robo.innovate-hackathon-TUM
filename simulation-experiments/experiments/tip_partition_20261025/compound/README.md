# Source-derived fingertip compound

One fixed 48-cell CAD approximation passes its frozen **offline sampled** audit.
Native cooking, mounting accuracy and contact remain unvalidated.

| Default Pueue job | Frozen source | Result |
|---|---|---|
|1764|`8e1c4cd`|Original 128-vertex guard stops after 27 cells; incomplete|
|1765|`0ab784e`|Logging-only replay reproduces those cells exactly; first failed cell has 133 extreme vertices|
|1766|`9d789ab`|One reviewed 255-vertex guard correction completes the same 48-cell geometry; 16/16 offline checks pass|

The one resource correction changes no geometry, margins, sampling or fidelity
threshold. The source supports 16 sectors in each of the annular boss, bored
body and rear solid body regions. All 27 original cells remain exactly equal.
No point clustering, jitter, adaptive splitting or new three-round pool is used.

| Offline measurement, job1766 | Result |
|---|---:|
|Candidate sampled exterior distance to STL, including 1µm bracket|60.667µm maximum|
|Source outside exact distance to candidate union|59.735µm maximum|
|Source inside samples whose fixed 100µm normal endpoint remains inside|0 / 83,185|
|Relative volume difference|0.0530%|
|Reference-free 50µm bore spheres preserved|27 / 27|
|Actual cumulative supervised time, including1764/1765|6.547s / 180s|

There are 102,418 candidate samples (31,100 confirmed exterior, 71,296 internal
interfaces, 22 unresolved exterior brackets) and 101,886 source samples. These
are sampled bounds, not a global Hausdorff certificate. The inside-source rule
is a fixed outward-normal upper-bound check, not a nearest-distance measurement.
All 48 cells are convex under the frozen checks; maximum vertex count is133.
Input vertex, triangle and plane-row counts do not establish cooked polygon
counts. The matching-family PhysX contract limits both vertices and polygons;
this offline run does not establish installed-binary cooking fidelity.

The existing CAD-to-finger registration is unchanged and physically unverified.
The original automatic-decomposition failures remain failed and preserved.

Reproduce only as a new stable snapshot through the **default Pueue queue**:

```bash
pueue add 'bash /absolute/path/to/frozen-snapshot/launch.sh'
```

Job1766's exact [launch command](../../../runs/20261025T061618.814542Z-explicit-tip-compound-255/launch.sh),
[source/input hashes](../../../runs/20261025T061618.814542Z-explicit-tip-compound-255/manifest.json),
[independent audit](../../../runs/20261025T061618.814542Z-explicit-tip-compound-255/audit/evaluation.json),
and [supervised budget](../../../runs/20261025T061618.814542Z-explicit-tip-compound-255/supervisor.json)
are retained. The unchanged `unitree_sim_env` supplies Python3.11.15,
NumPy1.26.0 and SciPy1.15.3. No new dependencies or shared-environment changes.
[Machine-readable outcomes](results.json) include previous attempts and hashes.
