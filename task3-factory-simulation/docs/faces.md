# Per-face shade — proposal v0.3

A brick can have a different shade on each face. The shade of a hidden face must not be inferred from
another one. The v0.2 per-brick category API is kept, and `planning.faces.make_face_plan` is added as
an independent extension.

## Input

Each brick carries `id`, `faces` and `allowed_orientations`:

```json
{
  "id": "brick_01",
  "faces": {
    "front": {"color_group": "dark"},
    "back": {"color_group": "light"},
    "top": null
  },
  "allowed_orientations": [
    {"id": "front_out", "visible_face": "front"},
    {"id": "back_out", "visible_face": "back"}
  ]
}
```

`null` or a missing face means not observed. Only faces that were observed and are referenced by an
allowed orientation can be chosen. Observed faces may carry extra metadata, but the MVP consumes
their `color_group`. Face identifiers are bound to the physical brick; perception has to keep them
stable, even if the brick moves.

Orientations are declared by integration according to the permitted grasp. In the fixtures they are
synthetic hypotheses, not verified robot capabilities. An `orientation_id` is not yet an angle, a pose
or an executable rotation instruction.

## Selection and output

An explicit recipe is required. Integer quotas are computed first, with the same rule as v0.2. A
matching assignment then looks for distinct bricks whose allowed faces cover those quotas; it may
reassign a flexible brick to preserve another scarce shade. With `reject`, the plan is refused if no
such assignment exists. With `redistribute`, the quotas that can be met are met and the rest is
filled by shade shortfall among the remaining candidates; that substitution is heuristic.

The mixed or smooth pattern and the sequence are then computed with the chosen face. The output uses
`schema_version="0.3"`; every placement adds `visible_face` and `orientation_id`. `face_policy`
identifies allowed faces that were not observed, bricks with no observed candidates, and the declared
origin of the orientations.

This version optimizes a single exposed face per position. It does not evaluate front, side and top at
the same time, and it does not predict the appearance of a wall once the package is unpacked. The
shade values used by smooth mode are still representative of the category, not per-face calibrated
measurements, and they do not describe texture.

## Reproduce

```bash
python3 -m demo --face-aware --inventory examples/faces/inventory.json --config examples/faces/config.json --output artifacts/faces_run.json
```

In this example every front face is dark. To meet 4/4/4, the planner has to choose some back faces.
Tops that were not observed are never used.

## Open agreements

Which faces count in the package and in the wall, the exposure orientation per position, the
rotations that are physically permitted, texture and variation within one face, and how to acquire
and calibrate multiple observations without losing identity.
