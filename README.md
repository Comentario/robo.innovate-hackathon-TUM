# Robo Innovate Hackathon TUM — Marmon

Prototype organized around perception, planning, and integration responsibilities.

## Generate the partial inventory

From the repository root, run:

```powershell
.\.venv\Scripts\python.exe -m perception.brick_detector.background_difference
```

The shareable inventory is written to `data/inventories/partial_inventory.json`. Diagnostic images are written to `outputs/` and are not versioned.

The current data contract is documented in `interfaces.md`.

The selected Zenodo images required to reproduce the current detector results are included in `data/images/zenodo_detection/` with their attribution and license.
