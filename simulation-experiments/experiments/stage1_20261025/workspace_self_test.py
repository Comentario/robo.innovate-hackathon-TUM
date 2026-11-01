"""Tiny sensor/world-frame fixture, not an actual image batch."""
import json
from pathlib import Path
import numpy as np
from online import filter_workspace_depth

workspace = json.loads(Path(__file__).with_name('workspace_v1.json').read_text())
depth = np.array([[.1, .583, np.nan, np.inf], [0., -.1, .199, .201]], np.float32)
original = depth.copy()
calibration = {'K': np.eye(3), 'R': np.eye(3), 't': np.zeros(3)}
filtered, counts = filter_workspace_depth(depth, calibration, workspace)
assert np.array_equal(depth, original, equal_nan=True)
assert filtered[0, 0] == depth[0, 0] and filtered[1, 2] == depth[1, 2]
assert np.isnan(filtered[0, 1:]).all() and np.isnan(filtered[1, :2]).all() and np.isnan(filtered[1, 3])
assert counts['above_volume'] == 2 and counts['invalid_input'] == 4
# A camera one meter above the table looking down: optical depth .9 means tableZ .1.
calibration.update(R=np.diag([1., -1., -1.]), t=np.array([0., 0., 1.]))
filtered, _ = filter_workspace_depth(np.array([[.9, .417]], np.float32), calibration, workspace)
assert np.isfinite(filtered[0, 0]) and np.isnan(filtered[0, 1])
print('Workspace world-Z, raw preservation, invalid and out-of-volume fixtures: PASS')
