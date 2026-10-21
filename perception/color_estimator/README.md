# Color estimator

The estimator measures robust Lab statistics inside eligible detections and
selects between one, two, or three relative CIELAB groups. A compact single
group is labeled `uniform`; separated groups use `color_group_1` through
`color_group_3` and are ordered by their center lightness.

```powershell
.\.venv\Scripts\python.exe -m perception.color_estimator.measure_lab `
  <image_path> <partial_inventory_path> `
  --inventory-output data/inventories/inventory_with_color.json
```

Visualize the resulting Lab distribution with:

```powershell
.\.venv\Scripts\python.exe scripts\analyze_lab_distribution.py `
  <lab_measurements.json>
```

Each image uses its own partial inventory. Partial bricks and unresolved merged
boxes are excluded from color sampling.

The command writes:

- `lab_measurements.json`: median Lab values and lightness spread.
- `color_classification.json`: group centers, quality gates, and assignments.
- `sampling_preview.png`: sampled inner regions.
- `classification_preview.png`: provisional groups and confidence scores.
- `inventory_with_color.json`: a new schema `0.2` inventory containing the
  selected relative group and confidence for every eligible brick.

The detector's partial inventory is never overwritten. Excluded or inconclusive
detections remain `unknown`. The relative group centers are stored in the
enriched inventory because group names are scene-specific, not absolute color
names.
