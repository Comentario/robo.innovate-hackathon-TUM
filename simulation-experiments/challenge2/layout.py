"""Simulator-independent task geometry. Meters, Z-up, WXYZ quaternions.

Grid coordinates describe the lower left corner of a brick footprint in studs.
Each lattice layer alternates orientation, leaving the ventilation gaps in the
reference photos. RGB values are visual placeholders, not a shade classifier.
"""

import json
import math
import random
from dataclasses import dataclass
from pathlib import Path

PITCH = 0.008
PLATE = 0.0032
HEIGHT = 3 * PLATE


@dataclass(frozen=True)
class Brick:
    name: str
    x: int
    y: int
    layer: int
    yaw: int
    color: str

    @property
    def footprint(self):
        return (4, 2) if self.yaw % 2 == 0 else (2, 4)

    def pose(self, center, studs):
        """Return brick bottom-center XYZ and WXYZ in the robot base frame."""
        w, d = self.footprint
        return (
            (center[0] + (self.x + w / 2 - studs / 2) * PITCH,
             center[1] + (self.y + d / 2 - studs / 2) * PITCH,
             PLATE + self.layer * HEIGHT),
            (math.cos(self.yaw * math.pi / 4), 0, 0,
             math.sin(self.yaw * math.pi / 4)),
        )


def load_config(path):
    cfg = json.loads(Path(path).read_text())
    assert cfg["robot"] == "fr3", "This workcell uses the confirmed FR3 robot"
    assert cfg["recipe"] in ("mixed", "single_shade")
    assert 1 <= cfg["source_cells"] <= cfg["baseplate_studs"] // 4
    assert 1 <= cfg["output_cells"] <= cfg["baseplate_studs"] // 4
    assert cfg["source_layers"] >= 1
    assert set(cfg["reject_colors"]) < set(cfg["colors"])
    return cfg


def lattice(cells, layers, colors, seed=26, prefix="brick"):
    rng = random.Random(seed)
    return [Brick(f"{prefix}_{k}_{i}_{j}", i * 4, j * 4, k, k % 2,
                  rng.choice(list(colors)))
            for k in range(layers) for i in range(cells) for j in range(cells)]


def overlaps(a, b):
    aw, ad = a.footprint
    bw, bd = b.footprint
    return max(a.x, b.x) < min(a.x + aw, b.x + bw) and max(a.y, b.y) < min(a.y + ad, b.y + bd)


def supports(bricks, brick):
    return [b for b in bricks if b.layer == brick.layer - 1 and overlaps(b, brick)]


def exposed(bricks):
    return [b for b in bricks if not any(t.layer == b.layer + 1 and overlaps(b, t) for t in bricks)]


def connection_offset(lower, upper, studs):
    """Native interface offset: upper local grid origin in lower local grid.

    Brick interface origins rotate with the brick. For a quarter turn the
    local (0,0) corner lies at the world footprint's lower right corner.
    """
    lx, ly = (0, 0) if lower is None else (lower.x, lower.y)
    lw = studs if lower is None else lower.footprint[0]
    lq = 0 if lower is None else lower.yaw
    ux, uy = upper.x, upper.y
    if upper.yaw == 1:
        ux += upper.footprint[0]
    if lq == 1:
        lx += lw
    dx, dy = ux - lx, uy - ly
    return ((dx, dy) if lq == 0 else (dy, -dx)), (upper.yaw - lq) % 4


class SortPlan:
    """Top-down removal and bottom-up output slots, independent of perception."""

    def __init__(self, cfg):
        self.cfg = cfg
        pad = (cfg["baseplate_studs"] - 4 * cfg["source_cells"]) // 2
        self.remaining = [Brick(b.name, b.x + pad, b.y + pad, b.layer, b.yaw, b.color)
                          for b in lattice(cfg["source_cells"], cfg["source_layers"], cfg["colors"], cfg["seed"])]
        self.placed = {}
        self.completed = []

    @property
    def target(self):
        return max(exposed(self.remaining), key=lambda b: (b.layer, -b.x, -b.y)) if self.remaining else None

    def destination(self, brick):
        if brick.color in self.cfg["reject_colors"]:
            return "scrap", None
        key = "mixed" if self.cfg["recipe"] == "mixed" else brick.color
        count = len(self.placed.get(key, []))
        cells = self.cfg["output_cells"]
        k, n = divmod(count, cells * cells)
        i, j = divmod(n, cells)
        pad = (self.cfg["baseplate_studs"] - 4 * cells) // 2
        return key, Brick(brick.name, pad + i * 4, pad + j * 4, k, k % 2, brick.color)

    def complete(self, brick):
        key, slot = self.destination(brick)
        self.remaining.remove(brick)
        self.completed.append(brick)
        if slot is not None:
            self.placed.setdefault(key, []).append(slot)
