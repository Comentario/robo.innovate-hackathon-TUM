# Interfaces

## Partial inventory v0.1

Persona 1 exports `data/inventories/partial_inventory.json` for detector-only
tests and `data/inventories/inventory_with_color.json` after color estimation.
Additional scene inventories for integration tests are stored under
`data/inventories/color_estimation/` with filenames matching their image IDs.

Each item in `bricks` contains:

- `id`: unique brick identifier within the processed image.
- `bbox_px`: detection rectangle using the image top-left as origin.
- `center_px`: detected brick center in image pixels.
- `color_group`: `unknown`, `uniform`, or a relative `color_group_N` label.
- `color_score`: currently `0.0`; later the color classification confidence.

Optional detector metadata includes:

- `source_detector`: detector and version that generated the inventory.
- `eligible_for_color`: whether a detection is reliable for color sampling.
- `is_partial`: whether the brick touches an image boundary.
- `possible_merge`: whether one box may still contain multiple bricks.

Each processed image has its own inventory file. The color estimator must receive
the matching image and inventory paths explicitly and verifies `image_id` and
`image_size_px` before sampling.

`processing_status` is `partial` while color estimation is pending. After color
estimation, a separate `inventory_with_color.json` uses schema `0.2` and status
`color_estimated` or `color_inconclusive`.

The enriched inventory includes top-level `color_estimation` metadata:

- `method`: estimator and version.
- `selected_k`: number of relative Lab groups selected for that image.
- `group_centers_lab`: CIELAB center of each relative group.

Relative labels only have meaning together with their scene's Lab centers; they
are not absolute material names such as white or red.
