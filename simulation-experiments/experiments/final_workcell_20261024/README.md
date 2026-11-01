# Final workcell from ten setup photographs

This is an approximate, editable reconstruction of the final workcell, using
the existing Franka Research 3 / BrickSim runtime. It does not establish a
calibrated robot or camera frame. Previous perception experiments and their
results are preserved.

The ten original images are archived unchanged under
`resources/setup_images/final_workcell_20261024`; `photo_inventory.json`
records their SHA256 hashes. All photos were inspected. Photo 9 provides the
clearest whole-layout reference; photos 8 and 3 corroborate the layout and stud
lattice, and the other views show the stack, ruler, bowl and robot mounting.
The user confirms an **iPhone 12**, with original photos **6 and 7 at 0.5×**
and the remainder at **1×**. The new reference attachments match photos 7 and
6 byte-for-byte; the primary layout reference, photo 9, is therefore 1×.
The supplied JPEGs contain no embedded focal-length or camera-model metadata;
some have been resized. Device/zoom provenance is recorded separately from
calibrated photo intrinsics and from the wrist D435i.

## Coordinate frame and evidence

The right-handed table frame has its origin at the white source plate centre,
X toward the gray destination plate, Y away from the robot toward the reject
bowl, and Z up. This frame is separate from the uncalibrated robot-base frame.

The source stack retains the confirmed 300-brick design: ten alternating
layers, six ridges of five 2×4 bricks per layer, two-stud gaps and the existing
native connection geometry. The user reports white **25×25 cm** and gray
**38×38 cm**, with black tape covering two stud rows at each taped edge.
The reused native assets have 32×32 and 48×48 studs at 8 mm pitch, giving
nominal 25.6/38.4 cm footprints. That reported/native difference is explicit;
bricks are not stretched. Hidden brick colors cannot be recovered from these
views; the existing synthetic inventory remains a placeholder.

`photo_measurements.json` records manual image anchors and their limitations.
The queued `measure_layout.py` run uses the reported white plate size to fit a
single-plane homography, then checks the separate ruler and reported gray size.
This is a layout estimate, not phone calibration, hand-eye calibration or
robot-frame registration.

The latest rendering preset improves directional lighting and surface finish
while preserving this layout. See [appearance comparison and commands](appearance/README.md)
for matched before/after images, unchanged-state checks and remaining limits.

The corrected audit distinguishes the visible white rectangle (25×21.8 cm)
from the hidden outer edges: two rows at 8 mm pitch imply an approximate
16 mm covered strip at each Y edge. Gray covered strips are likewise added
back before comparing outer dimensions. It measures the apparent 20 cm ruler
span as 18.68 cm and gray inferred outer spans as 40.75–40.85 cm along X and
38.42–38.99 cm along Y, versus reported 38 cm. These discrepancies remain;
the fit does not force all checks to agree. Hidden edges, manual picks, lens
distortion and raised surfaces can all matter. The two ±3-pixel
corner scenarios are sensitivity examples, not confidence intervals or bounds
on physical error. The partly occluded robot foot and elevated bowl rim have
additional projection uncertainty.

Rounded scene estimates in table coordinates are gray plate centre
(0.42, -0.06) m, robot base (-0.09, -0.40) m, and bowl centre (0.01, 0.27) m.
The robot yaw is photograph-estimated; table dimensions, bowl shape/height
and plate thickness remain explicit assumptions. Reachability and insertion clearances are not validated.

## Destinations and camera

The gray plate is one studded surface divided into three zones. The large
half away from the robot is the requested-stack zone; the two smaller zones
near the robot hold unrequested accepted colors. The bowl is the faulty-brick
destination on the far side of the input stack. At the black-taped Y edges,
two stud rows are visually covered and declared unavailable for placement;
yellow divider width is a separate estimate. Nominal zone rectangles do not
establish a collision-free, fully stud-supported output placement.

- One requested accepted color: requested color in the large zone, the other
  two accepted colors in separate small zones.
- Two requested accepted colors: both share the large zone, the third uses
  one small zone and the other small zone stays empty.
- Three requested accepted colors: all share the large zone; both small
  zones stay empty.

These are destination semantics, not a new task scheduler or classifier.
Challenge 1 still owns color/quality labels. A future mixed output can use a
simple repeating color sequence; the exact output lattice and usable stud
clearances await confirmation.

The existing physical wrist D435i is retained in the specification. Its
mount has not moved according to the user, but the repository did not contain
a calibrated wrist-camera transform. The earlier 6.3 cm and 2 cm measurements
describe housing offsets with unresolved axes, not an optical-frame transform.
Intrinsics and hand-to-optical transform therefore remain unset. Diagnostic
virtual inspection views are explicitly separate from physical cameras; the
two unspecified external cameras remain omitted. A second wrist housing, a
Logitech C920, is now represented by an approximate visual-only model on the
opposite gripper side; see [C920 mounting](c920_mount/README.md). No C920 optical
transform or image sensor is activated.

## Reproduction and scope

All photo processing and rendering uses `pueue add` in the default queue with
frozen code/configuration/input snapshots. The initial photo audit is preserved
as job **1696**. The tape-aware revision using the user's dimensions is job
**1697**, snapshot
`runs/20261024T203806.556370Z-final-workcell-photo-audit-tape`.

The scene reuses the existing runtime and native assembly/restoration checks.
No dependencies are installed, no shared environment or queue settings are
changed, and no training, manipulation, ROS or hardware control is started.
Native connections are checked at a static snapshot; connection dynamics are
not validated. Recreating native runtime links uses the scene launcher, rather
than assuming an exported USD restores all extension state by itself.

The private renderer explicitly initializes the configured nominal robot joints
with one simulation step **before** restoring the source bricks and creating
the native graph. It checks joint readback and PhysX/USD hand-pose agreement.
There are no physics steps after native preassembly. This fixes static visual
initialization; the robot joint pose is still nominal, not reconstructed from
the physical photographs.

For a new preview after committing configuration edits, run:

```bash
python3 experiments/final_workcell_20261024/submit_preview.py
```

This helper creates a fresh immutable snapshot, uses the existing environment,
submits its foreground launcher through default Pueue and prints the job ID.
It does not overwrite earlier captures.

The marker-board design is now known from the supplied specification:
**7×5 squares, DICT_4X4_50, 30 mm squares and 22 mm markers**. The nominal
pattern spans 210×150 mm, with 17 default markers and 24 inner corners. The
specified 100% print setting is an instruction, not a verified measurement
of the physical print. The A4 backing and estimated scene location remain.

Robot-base position remains estimated; yaw is now estimated from the fixed
housing features documented below. D435i intrinsics and a measured optical
mount transform remain necessary for calibrated wrist-view equivalence.
Identifying the phone lenses and ChArUco design does not supply those transforms.

## Completed preview

Latest capture: **Pueue1773**, frozen source`3cee3d7`: corrected tapered pad mounting and simple outside screw heads. Independent job1774 passes60/60 visual/invariance checks.

- [Overhead render](../../runs/20261025T072956.568941Z-final-workcell-preview/output/images/diagnostic_table_top.png)
- [Pad support and outside screw head](../../runs/20261025T072956.568941Z-final-workcell-preview/output/images/diagnostic_pad_support_side.png)
- [Opposing gripping faces](../../runs/20261025T072956.568941Z-final-workcell-preview/output/images/diagnostic_pad_inner_faces.png)
- [USD visual scene](../../runs/20261025T072956.568941Z-final-workcell-preview/output/final_workcell.usda)
- [Native graph, scene and camera manifest](../../runs/20261025T072956.568941Z-final-workcell-preview/output/manifest.json)
- [Jobs, snapshots, artifact hashes and validation](completion.json)
- [Editable layout and destination recipes](scene_config.json)

Validation passed for all 300 source bricks, 930 native connections and 301
connected parts including the source plate. Joint readback matches requested
nominal values exactly; hand PhysX/USD positions and orientations agree within
the configured tolerances. Source placement and state are unchanged across
the two captures. One explicit preassembly initialization step is recorded;
no physics step occurs after native assembly.

Job **1701** generated and checked the specified board. Both the generated
image and original photo 9 recover all 17 marker IDs and all 24 inner corners.
Ordered per-ID corners support a nominal 0° scene rotation (raw fitted angle
0.0603°) without changing any scene position or scale. The fit's diagnostic
scale factor 1.05666 mixes approximate layout, lens, picking and possible print
errors; it does not verify physical print scale.

The earlier job 1702 rendered top view decodes seven markers and agrees with the intended
ordered-corner mapping at 1.26 px RMS, versus 62.34 px for a mirrored mapping
and 107.94 px for a 180° mapping. No markers decode in the distant oblique
render, so that view remains unverified. These are asset/orientation checks,
not physical calibration or complete board-detection performance claims.

- [Printed-board detection in photo 9](../../runs/20261024T211152.477912Z-charuco-asset-audit/output/photo09_charuco_detection.png)
- [Generated board and real-photo audit](charuco_board.json)
- [Earlier job 1702 UV correspondence check](../../runs/20261024T211537.337776Z-final-workcell-preview/output/charuco_uv_check.json)

Jobs 1696–1706 all ran through default Pueue; earlier audits and previews are
preserved. Kit cleanup stalled after validated capture and was bounded by the
existing owned-process supervisor, independently of capture validation.
The exported USD references the frozen snapshot's assets; use the launcher
to recreate runtime native connections. No independent graph reload or
load-bearing dynamics claim is made.

## Photo-supported base orientation

The previously assumed `yaw_table_deg: 90.0` is now **45.0**, a rounded visual
estimate from the two new reference photographs. No additional physical
measurement was required for this update.

Photo 1 establishes that the fixed connector-bearing housing side faces the
table +X/−Y quadrant. Photo 2 is used only to identify the lower connector bank
and adjacent asymmetric mounting outline; its different brick layout is ignored.
Neither arm bend nor nominal joint angles are used to infer yaw.

Job **1703** inspected the existing composed FR3 asset with actual fixed-link0
axes. The large lower socket and neighboring smaller sockets belong to the
white housing flank on approximately **asset −Y**. The red upper fixtures are
not the connector cue. A 45° root rotation maps asset −Y into table +X/−Y.
The photo supports a coarse diagonal orientation, not angular metrology or a
numerical uncertainty bound.

Job **1704** rendered the updated orientation and comparable fixed-base views.
Only yaw and its status/evidence metadata changed in `scene_config.json`.
The base position, layout, plate dimensions, tower geometry and nominal joint
configuration remain identical. Queued evidence checks also confirm identical
300×13 source states and identical requested joint values versus the baseline.
Native counts remain 300 bricks, 930 connections and 301 connected parts, with
zero post-assembly physics steps. Diagnostic moving-link hiding is visual-only
and restored before USD export.

- [Annotated Photo 1](../../runs/20261024T214949.269584Z-base-orientation-evidence/output/photo1_annotated.png)
- [Comparable annotated top render](../../runs/20261024T214949.269584Z-base-orientation-evidence/output/base_top_annotated.png)
- [Connector-facing asset detail](../../runs/20261024T214949.269584Z-base-orientation-evidence/output/base_connector_face_annotated.png)
- [Side-by-side visual comparison](../../runs/20261024T214949.269584Z-base-orientation-evidence/output/comparison.jpg)
- [References, feature match and qualitative uncertainty](base_orientation/reference.json)
- [Unchanged-configuration guard](base_orientation/change_guard.json)

Jobs **1705/1706** create deterministic annotations; the second removes cropped
text fragments without changing the estimate or render. All use frozen inputs
and default Pueue. To recreate these diagnostic views in a new snapshot:

```bash
python3 experiments/final_workcell_20261024/submit_preview.py --cameras experiments/final_workcell_20261024/base_orientation/cameras_after.json
```

The annotated comparison is deliberately unregistered and uses different
perspectives. This is a visual-twin adjustment, not calibrated robot-frame
alignment, camera extrinsics or coordinates suitable for hardware commands.

## Wrist camera side correction

The camera and its bracket now occupy the opposite hand flank, as corrected by the user. See [mount correction and close-up](wrist_mount/README.md). The housing remains nominal; the optical transform is uncalibrated.

## Reference-based end-effector corrections

The C920 folded-holder interpretation and fingertip visuals now follow the user-supplied photograph and STL. See [registration, limits and reproduction](end_effector/README.md). The pad collision model is still stock and must be checked separately before new-tip contact claims.
