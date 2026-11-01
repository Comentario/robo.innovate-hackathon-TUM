# Reference-corrected C920 and supplied fingertip visuals

The user's folded-holder photograph supersedes the earlier C920 proxy. The
contact side is the holder UNDERSIDE. Its rear tail points armward to the
nominal circular wrist-face plane (hand Z=0). A compact folded clip, front
fold/lip and tape are represented against hand −X, centered laterally at Y=0.
The housing overlaps the foot instead of hanging below a long exposed strap.
D435i and its bracket remain on hand +X, with their existing joint frames.

In the reference the fascia faces the front of the folded foot. That forward
direction maps to hand +Z/fingers. Housing-only pitch toward hand +X therefore
points the decorative fascia toward the nominal grasp region, rather than
outward away from it. The illustrative 50° pitch and 94×29×24 mm housing remain
artist estimates. Neither the true mechanical stop nor optical-center position,
viewing direction, camera intrinsics or FOV was measured. No physical C920
image sensor is activated. The folded-contact placement is visual, not a fit or
clearance measurement. The C920 has no added collision, rigid-body or mass API.

The user corrected the fingertip orientation: the tapered **low CAD Z** end
points distally toward the bricks, the bosses point into the supporting metal
fingers, and the broad CAD X=0 gripping faces oppose each other across the
opening. A proper rotation, CAD Ry(180°) followed by finger Rz(±90°), reverses
CAD X/Z without reflecting the mesh.

The supplied STL remains unchanged, with nominal CAD bounds X[−11,0],
Y[−23,−8], Z[2.050005,27.600006]. STL has no units; millimeters remain assumed.
The body mounting plane at CAD X=−9.5 is placed at the old stock-pad backplane;
the boss front at X=−11 therefore extends nominally 1.5 mm into the support.
The user confirmed that the new pads share the stock pads’ **proximal/top
edge**, at finger Z=36.09037 mm. The 25.550001 mm custom body therefore extends
distally to Z=61.640371 mm, approximately 7.74049 mm beyond the old stock tip.
The boss axis and screw head move together to Z≈45.09037 mm. The prior fixed
53.89988 mm distal endpoint was an incorrect height anchor and is superseded.
Width centering and backing-plane placement remain nominal; the boss enters
the supporting finger’s screw hole as a simple rigid attachment, without
form-fit or clearance certification. The per-render `updated_fingertips.json`
records transforms, probes, boss depth and both proximal/distal extents.

A simple round screw head is a rigid visual child of each finger, on the
nominal boss axis. Head diameter 6 mm and outward protrusion
2 mm are configurable estimates. The head uses a nearby outer-metal visual
bound at the boss height; its full envelope is reported for later clearance
work. The through-metal connection is implicit; there are no shaft, threads,
form-fit, fastener collision or added mass.

Only the 262 old dark-pad faces are hidden; all 362 white-finger faces remain.
**Stock collision geometry and friction remain unchanged.** This visual
correction does not validate supplied-tip contact, grasping or insertion.
Closed perception/contact experiments retain their original transforms and
results; their old mounting is not silently updated by this correction.

Earlier orientation/screw-head preview: **Pueue1773**, source`3cee3d7`,
verification **1774:60/60 passed**. Its distal-fixed **height is superseded**
by the user’s proximal-edge alignment above; these results remain archived.

- [Superseded-height pads and outside screw head](../../../runs/20261025T072956.568941Z-final-workcell-preview/output/images/diagnostic_pad_support_side.png)
- [Superseded-height opposed gripping faces](../../../runs/20261025T072956.568941Z-final-workcell-preview/output/images/diagnostic_pad_inner_faces.png)
- [Superseded-height visual USD](../../../runs/20261025T072956.568941Z-final-workcell-preview/output/final_workcell.usda)
- [Independent checks](../../../runs/20261025T073123.815357Z-pad-mount-verification/output/verification.json)
- [Dimensions, envelopes, jobs and hashes](mount_correction/results.json)

The earlier1771 mounting had the right orientation but the wrong height: it
matched the old distal endpoint. It is superseded by1773, which aligns the
upper/proximal edges and leaves the extra length below the metal.

Historical artifacts below show the **superseded fingertip mounting**. They
remain useful for the earlier camera-holder and invariance work:

- [Historical C920 fascia and fingertips](../../../runs/20261025T000918.719244Z-final-workcell-preview/output/images/diagnostic_c920_grasp_side.png)
- [Historical camera-housing profile](../../../runs/20261025T000918.719244Z-final-workcell-preview/output/images/diagnostic_c920_profile.png)
- [Historical USD](../../../runs/20261025T000918.719244Z-final-workcell-preview/output/final_workcell.usda)
- [Historical invariance checks](../../../runs/20261025T001003.870890Z-end-effector-verification/output/verification.json)
- [Superseded STL registration report](../../../runs/20261025T000918.719244Z-final-workcell-preview/output/updated_fingertips.json)

Historical default-queue jobs were 1718 (C920/native-finger audit), 1719
(native pad separation), 1720 (earlier STL visuals) and 1721 (verification).
The current visual change preserves the source's 300 bricks, 930 native
connections and 301 connected parts, robot configuration, table layout and
both camera housings. New close-up views are diagnostic virtual cameras.

Reproduce the corrected visual preview from a stable queued snapshot:

```bash
python3 experiments/final_workcell_20261024/submit_preview.py --cameras experiments/final_workcell_20261024/end_effector/mount_correction/cameras.json --appearance experiments/final_workcell_20261024/appearance_config.json
```
