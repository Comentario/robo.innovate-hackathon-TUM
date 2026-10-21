# Robo Innovate Hackathon TUM — Marmon

Prototype organized around perception, planning, and integration responsibilities.

The pallet geometry detector is version `0.2` and has been validated from small
stacks through a full 70-brick pallet. The relative CIELAB color estimator
exports enriched inventory schema `0.2`.

## Generate the perception inventories

From the repository root, run:

```powershell
.\.venv\Scripts\python.exe -m perception.brick_detector.background_difference
```

The detector writes the 70-brick example to
`data/inventories/partial_inventory.json`. To add relative color groups, run:

```powershell
.\.venv\Scripts\python.exe -m perception.color_estimator.measure_lab `
  data/images/zenodo_detection/bricks_70.png `
  data/inventories/partial_inventory.json `
  --inventory-output data/inventories/inventory_with_color.json
```

Additional enriched test inventories are available in
`data/inventories/color_estimation/`. Diagnostic images are written to
`outputs/` and are not versioned.

The current data contract is documented in `interfaces.md`.

## ROS 2 perception node

The `marmon_perception` package in `ros2/marmon_perception/` wraps the existing
Python pipeline in one ROS 2 Humble node. It subscribes to images and publishes
the shared inventory as JSON. Build, transport configuration, and dataset test
instructions are in [perception/README.md](perception/README.md).

The selected Zenodo images required to reproduce the current detector results are included in `data/images/zenodo_detection/` with their attribution and license.
