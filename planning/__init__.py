"""Hardware-independent planning for visual brick blending."""
from collections import Counter
import math


def blend_planner(inventory, capacity, target_ratios=None):
    """Select category counts using largest deficits and available stock."""
    if not isinstance(inventory, list):
        raise ValueError('inventory must be a list')
    seen = set()
    stock = Counter()
    for brick in inventory:
        if not isinstance(brick, dict):
            raise ValueError('each brick must be an object')
        for key in ('id', 'color_group'):
            if not isinstance(brick.get(key), str) or not brick[key].strip():
                raise ValueError(f'{key} must be a nonempty string')
        if brick['id'] in seen:
            raise ValueError('duplicate brick id')
        seen.add(brick['id'])
        stock[brick['color_group']] += 1
    if type(capacity) is not int or capacity <= 0:
        raise ValueError('capacity must be a positive integer')
    weights = dict(stock) if target_ratios is None else target_ratios
    if not isinstance(weights, dict) or not weights:
        raise ValueError('target_ratios must be a nonempty object')
    for group, weight in weights.items():
        if not isinstance(group, str) or not group.strip():
            raise ValueError('ratio categories must be nonempty strings')
        if type(weight) not in (int, float) or not math.isfinite(weight) or weight < 0:
            raise ValueError('ratio weights must be finite nonnegative numbers')
    total = sum(weights.values())
    if not math.isfinite(total) or total <= 0:
        raise ValueError('ratio weights must have a finite positive sum')
    ratios = {g: w / total for g, w in sorted(weights.items())}
    eligible = [g for g in ratios if ratios[g] > 0 and stock[g] > 0]
    if sum(stock[g] for g in eligible) < capacity:
        raise ValueError('insufficient eligible inventory for a complete pallet')
    counts = {g: 0 for g in ratios}
    for _ in range(capacity):
        available = [g for g in eligible if counts[g] < stock[g]]
        group = min(available, key=lambda g: (-(capacity * ratios[g] - counts[g]), g))
        counts[group] += 1
    return counts, ratios


def pallet_pattern_planner(counts, rows, columns, layers, *, mode="mixed", tone_values=None):
    """Greedy logical grid; penalize equal neighbors, then row/layer deficit."""
    remaining = dict(counts)
    capacity = rows * columns * layers
    grid = {}
    row_counts = Counter()
    layer_counts = Counter()
    for layer in range(layers):
        for row in range(rows):
            for column in range(columns):
                previous = [(layer, row, column - 1), (layer, row - 1, column),
                            (layer - 1, row, column)]
                def cost(group):
                    neighbors = sum(grid.get(p) == group for p in previous)
                    if mode == "smooth":
                        neighbors = sum(abs(tone_values[group] - tone_values[grid[p]])
                                        for p in previous if p in grid)
                    fraction = counts[group] / capacity
                    deficit = (fraction * columns - row_counts[layer, row, group]
                               + fraction * rows * columns - layer_counts[layer, group])
                    return neighbors, -deficit, group
                group = min((g for g in remaining if remaining[g] > 0), key=cost)
                grid[layer, row, column] = group
                remaining[group] -= 1
                row_counts[layer, row, group] += 1
                layer_counts[layer, group] += 1
    return grid


def placement_sequence_planner(inventory, grid):
    """Assign stable IDs in layer/row/column order."""
    pools = {}
    for brick in sorted(inventory, key=lambda b: b['id'], reverse=True):
        pools.setdefault(brick['color_group'], []).append(brick['id'])
    return [dict(step=step, brick_id=pools[group].pop(), color_group=group,
                 layer=position[0], row=position[1], column=position[2])
            for step, (position, group) in enumerate(sorted(grid.items()), 1)]


def make_plan(inventory, *, rows, columns, layers=1, target_ratios=None,
              mode="mixed", tone_values=None, shortage_policy="redistribute"):
    """Validate an inventory and return a complete logical pallet plan."""
    if any(type(n) is not int or n <= 0 for n in (rows, columns, layers)):
        raise ValueError('rows, columns and layers must be positive integers')
    if mode not in ('mixed', 'smooth'):
        raise ValueError('mode must be mixed or smooth')
    if shortage_policy not in ('redistribute', 'reject'):
        raise ValueError('shortage_policy must be redistribute or reject')
    capacity = rows * columns * layers
    counts, ratios = blend_planner(inventory, capacity, target_ratios)
    if shortage_policy == 'reject':
        # Compare with the same integer allocation under unlimited stock.
        ideal = dict.fromkeys(ratios, 0)
        for _ in range(capacity):
            group = min((g for g in ratios if ratios[g] > 0),
                        key=lambda g: (-(capacity * ratios[g] - ideal[g]), g))
            ideal[group] += 1
        if counts != ideal:
            raise ValueError('inventory cannot satisfy the rounded target recipe')
    if mode == 'smooth':
        if not isinstance(tone_values, dict):
            raise ValueError('smooth mode requires tone_values')
        for group, count in counts.items():
            value = tone_values.get(group)
            if count and (type(value) not in (int, float) or not math.isfinite(value)
                          or not 0 <= value <= 1):
                raise ValueError('selected categories require tone_values in [0, 1]')
    grid = pallet_pattern_planner(counts, rows, columns, layers,
                                 mode=mode, tone_values=tone_values)
    placements = placement_sequence_planner(inventory, grid)
    same = 0
    edges = 0
    tone_distance = 0.0
    for (layer, row, column), group in grid.items():
        for previous in ((layer - 1, row, column), (layer, row - 1, column),
                         (layer, row, column - 1)):
            if previous in grid:
                edges += 1
                same += grid[previous] == group
                if mode == 'smooth':
                    tone_distance += abs(tone_values[group] - tone_values[grid[previous]])
    actual = {g: counts[g] / capacity for g in ratios}
    return dict(schema_version='0.2', policy=dict(mode=mode, shortage_policy=shortage_policy,
                                                 tone_values=tone_values if mode == 'smooth' else None),
                shape=dict(rows=rows, columns=columns, layers=layers),
                blend=counts, placements=placements,
                metrics=dict(target_ratios=ratios, actual_ratios=actual,
                             ratio_l1_error=sum(abs(actual[g] - ratios[g]) for g in ratios),
                             same_tone_neighbors=same, neighbor_pairs=edges,
                             mean_neighbor_tone_distance=(tone_distance / edges if edges else 0.0)
                             if mode == "smooth" else None))
