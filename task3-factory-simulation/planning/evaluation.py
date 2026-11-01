"""Explain local distribution separately from global recipe availability."""
from collections import Counter


def evaluate_distribution(placements, shape, target_ratios, blend):
    total = sum(blend.values())
    selected_ratios = {g: n / total for g,n in blend.items()}

    def describe(region):
        counts = Counter(p['color_group'] for p in region)
        size = len(region)
        return dict(counts={g: counts[g] for g in target_ratios},
                    target_counts={g: size * target_ratios[g] for g in target_ratios},
                    selected_mix_counts={g: size * selected_ratios[g] for g in target_ratios},
                    recipe_l1_error=sum(abs(counts[g] / size - target_ratios[g]) for g in target_ratios),
                    distribution_l1_error=sum(abs(counts[g] / size - selected_ratios[g]) for g in target_ratios))

    layers, rows = [], []
    for layer in range(shape['layers']):
        layers.append(dict(layer=layer, **describe([p for p in placements if p['layer'] == layer])))
        for row in range(shape['rows']):
            rows.append(dict(layer=layer, row=row,
                             **describe([p for p in placements if p['layer'] == layer and p['row'] == row])))
    return dict(layers=layers, rows=rows,
                max_layer_distribution_l1=max(r['distribution_l1_error'] for r in layers),
                max_row_distribution_l1=max(r['distribution_l1_error'] for r in rows))
