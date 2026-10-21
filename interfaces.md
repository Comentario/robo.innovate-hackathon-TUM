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

## ROS 2 transport

The `marmon_perception` package runs a single `/perception` node. It receives
`sensor_msgs/msg/Image` on `/camera/image_raw` and publishes the existing schema
`0.2` inventory as JSON in `std_msgs/msg/String.data` on `/perception/inventory`.
Consumers parse the JSON before accessing inventory fields; no existing fields
are renamed. A generated `image_id` combines the input timestamp and a counter
local to the node run. Brick IDs remain scoped to each image.

Input QoS is best effort, volatile, keep last 1; output QoS is reliable,
volatile, keep last 1. New subscribers receive future results. A failed frame
produces a log entry and no inventory. Recognized empty pallets produce an
empty inventory, and insufficient color measurements produce
`color_inconclusive` with unknown colors.

See [perception/README.md](perception/README.md) for configuration, build,
transport setup, and a dataset publisher example. The camera adapter and
planning/integration consumers are separate work.
