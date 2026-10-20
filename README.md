# Robo Innovate Hackathon TUM — Marmon

Prototype organized around perception, planning, and integration responsibilities.

The current geometry detector is version `0.2` and has been validated from small stacks through a full 70-brick pallet. The shared inventory contract remains schema version `0.1` while color estimation is pending.

## Generate the partial inventory

From the repository root, run:

```powershell
.\.venv\Scripts\python.exe -m perception.brick_detector.background_difference
```

The default 70-brick example writes its shareable inventory to `data/inventories/partial_inventory.json`. Diagnostic images are written to `outputs/` and are not versioned.

The current data contract is documented in `interfaces.md`.

The selected Zenodo images required to reproduce the current detector results are included in `data/images/zenodo_detection/` with their attribution and license.
