# Full-stack geometry gate

The user's corrected full input is **10 layers × 6 × 6 = 360 2×4 bricks**.
Successive layers alternate by 90°. The uploaded images were taken after layer
removal, and no D435i calibration metadata accompanies the 1280×720 JPEGs.

The existing workcell cannot simply be scaled with `--cells 6 --layers 10`:
its lattice generator has no layer-origin staggering. Brick count alone does
not establish the required lower-layer openings or native connection graph.

A fixed-center interpretation is geometrically plausible: a horizontal 6×6
layer occupies 24×22 studs and its 90° rotation occupies 22×24 studs. Origins
`A=(0,1), B=(1,0)` in a 24×24 stud bounding square create reciprocal one-stud
edge protrusions without moving the layer center. The images show this kind of
edge protrusion, but the photographs alone do not establish every hidden
layer's origin. The rightmost visible strip in `img_13` has five 2×4 bricks,
consistent with a partly disassembled photographed state rather than a complete
six-brick-long original layer.

Other offsets also satisfy a verbal one-stud stagger and 90° alternation but
produce different overlap graphs. For 36 bricks per layer at 4-stud pitch:

| A/B footprint origins in studs | Connections between the two layers |
| --- | ---: |
| `(0,0)` / `(1,1)` | 66 |
| `(1,0)` / `(0,1)` | 121 |
| `(0,0)` / `(1,0)` | 36 |
| Common-center horizontal `(0,1)` / vertical `(1,0)` | 36 |

These are geometric overlap counts, not simulated measurements or evidence that
any candidate is the physical arrangement. Orientation order matters: horizontal
`(0,1)` and vertical `(1,0)` share a center, while swapping those origins gives
different centers. The common-center candidate has 2×2-stud overlap patches;
some other candidates have smaller patches. Any native connection limitation
must remain explicit if it affects a later run.

`geometry_spec.json` therefore leaves all ten layer origins unset. The renderer
rejects that file before starting Isaac Sim. It requires an explicit confirmed
origin for each layer; it never substitutes the smaller 48-brick scene or an
invented hidden arrangement. A common-center confirmation plus the existing
90° alternation and brick dimensions would determine the simplest repeating
layout. If that is not the intended build, a top-down stud-grid sketch of the
two repeating layer footprints is the remaining input.

When geometry is confirmed, `scripts/submit_render.py` freezes the existing
FR3/BrickSim code, dependencies and explicit geometry, submits to the default
Pueue queue, and prints its job ID. The planned renderer preserves all 360
bricks and checks a 361-part connected component including the anchored plate.
It writes six RGB images as the detector inputs. Depth, identities, poses and
projected polygons are isolated under `evaluation_truth/` and are never detector
inputs. Camera framing/intrinsics remain approximate, rather than a calibrated
digital-twin claim.
