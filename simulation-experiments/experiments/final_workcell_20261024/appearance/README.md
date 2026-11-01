# Appearance-only refinement

The corrected preset adds directional lighting and surface finish to the
existing 45°-base visual twin. It is visual polish, not measured sim-to-real
validation or improved detection evidence. All previous results are retained.

The setup photos show an LED panel on negative table X. The old scene used a
small spherical key on positive X and strong uniform ambient fill. The new
preset uses a neutral 26×18 cm rectangular emitter at (-0.55, 0.05, 0.40) m,
aimed at (0.03, 0, 0.06) m, with authored intensity 20000, normalization off,
and dome intensity 120. These are heuristic rendering settings, not measured
panel power, BRDF or camera calibration.

Native brick colors and ABS shaders were preserved. BrickSim already converts
uint8 sRGB to linear shader values and uses roughness 0.15 and IOR 1.53.
The new finishes change roughness only for the plates (0.35), table (0.55),
black duct tape (0.45), yellow tape (0.30), paper/printed board (0.85), and bowl
(0.35). Render-time binding checks prove that edited plate shaders are disjoint
from all 300 tower material paths. No physics material or visual geometry was
changed. No procedural textures, sensor noise or domain randomization were added.

Job **1707** used intensity 2000, which produced a darker, weakly lit image.
One reviewed correction changed only the key intensity to 20000. Job **1708**
captures that corrected preset; job **1709** compares both passes against the
same two original views from job **1704**. Camera poses/intrinsics, exposure,
tone mapping and auto-exposure settings are identical. No histograms were fitted
to the differently framed phone photographs.

All comparison guards pass: scene configuration, nominal/actual joint values,
source identities/poses/velocities, camera matrices, exposure/tone mapping,
300 bricks, 930 connections, 301 connected parts and zero post-assembly physics
steps. Source pose differences and camera differences are zero. There is no
white clipping (gray or any channel >=254) in the two checked frames or fixed
projected-source regions. The regions can include occluding robot pixels and
are evaluation diagnostics only.

Visual review finds clearer bowl/table contact shadows, curved robot highlights
and directional falloff. The gray plate and surroundings are darker than before.
The scene still has ideal geometry and smooth surfaces; physical camera
calibration and fine surface detail remain unresolved. Brightness statistics
do not establish perception or transfer improvements.

- [Overhead before/after](../../../runs/20261024T223147.006998Z-appearance-comparison/output/corrected/diagnostic_table_top_before_after.png)
- [Oblique before/after](../../../runs/20261024T223147.006998Z-appearance-comparison/output/corrected/diagnostic_oblique_before_after.png)
- [Checks and exposure diagnostics](../../../runs/20261024T223147.006998Z-appearance-comparison/output/corrected/comparison.json)
- [Updated USD](../../../runs/20261024T223031.192426Z-final-workcell-preview/output/final_workcell.usda)

To enable the appearance preset in a new immutable queued preview:

```bash
python3 experiments/final_workcell_20261024/submit_preview.py --cameras experiments/final_workcell_20261024/cameras_realism.json --appearance experiments/final_workcell_20261024/appearance_config.json
```

The legacy default remains available without these flags. Exact snapshots,
source commits, input hashes and launchers are in the run manifests and the
parent `completion.json`. No dependencies or shared environment settings were
changed. Both simulation and comparison used default Pueue.
