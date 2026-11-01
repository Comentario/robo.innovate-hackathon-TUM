"""Frozen partial-state/color adapter for the existing static native renderer.

Case/layout metadata is renderer/evaluator input only, never perception input.
No simulator is imported for the pure manifest/geometry self-test.
"""

import argparse
from dataclasses import replace
import json
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))
from challenge2.layout import PLATE, HEIGHT, overlaps
from experiments.sim_views_20261024 import render_views as renderer


def ridge_brick_indices(brick, spec):
    origin = spec["layer_origins_studs_xy"][brick.layer]
    i = (brick.x-spec["border_studs"]-origin[0])//4
    j = (brick.y-spec["border_studs"]-origin[1])//4
    return (j, i) if brick.yaw == 0 else (i, j)


def prepare_case(spec, full_bricks, benchmark_path, case_id):
    benchmark = json.loads(Path(benchmark_path).read_text())
    if benchmark["status"] != "frozen_before_implementation":
        raise ValueError("Benchmark must be frozen before renderer adaptation")
    matches = [case for case in benchmark["cases"] if case["id"] == case_id]
    if len(matches) != 1:
        raise ValueError(f"Unknown or duplicate benchmark case: {case_id}")
    case = matches[0]
    if len(full_bricks) != spec["required_bricks"]:
        raise ValueError("Cases must start from the complete original colored design")
    top = benchmark["top_layer_removed_only"]
    keep = case["keep_only_top_ridge_brick"]
    remove = case["remove_top_ridge_brick"]
    if keep is not None and remove is not None:
        raise ValueError("Choose remove or keep-only semantics, never both")
    keep = {tuple(index) for index in keep} if keep is not None else None
    remove = {tuple(index) for index in remove} if remove is not None else set()
    valid_indices = {(r, b) for r in range(spec["ridges_per_layer"]) for b in range(spec["bricks_per_ridge"])}
    if not remove <= valid_indices or (keep is not None and not keep <= valid_indices):
        raise ValueError("Case contains invalid ridge/long-axis indices")
    colored = []
    for brick in full_bricks:
        r, b = ridge_brick_indices(brick, spec)
        if case["palette"] == "mixed":
            color = brick.color  # Original full300 RNG assignment, before filtering.
        elif case["palette"] == "single_tan":
            color = "tan"
        elif case["palette"] == "repeated":
            colors = benchmark["palettes"]["repeated"]["colors"]
            color = colors[(r+b) % 2]
        else:
            raise ValueError("Unsupported frozen benchmark palette")
        colored.append(replace(brick, color=color))
    active = [brick for brick in colored if brick.layer != top or (
        ridge_brick_indices(brick, spec) in keep if keep is not None else ridge_brick_indices(brick, spec) not in remove)]
    active_ids = {brick.name for brick in active}
    removed_ids = [brick.name for brick in colored if brick.name not in active_ids]
    if not active or any(brick.layer and not any(lower.layer == brick.layer-1 and overlaps(lower, brick) for lower in active) for brick in active):
        raise ValueError("Case leaves an unsupported brick")
    actual = {"active_bricks": len(active), "native_connections": renderer.geometry_audit(active)["expected_native_connection_count"],
              "connected_parts": len(active)+1}
    if actual != case["expected"]:
        raise ValueError(f"Case counts disagree with frozen manifest: {actual}")
    result_spec = dict(spec)
    result_spec["design_expected_native_connections"] = spec["expected_native_connections"]
    result_spec["expected_native_connections"] = actual["native_connections"]
    result_spec["expected_active_bricks"] = len(active)
    metadata = {"case": case, "views": benchmark["views"], "removed_ids": removed_ids,
        "active_ids": [brick.name for brick in active], "original_design_bricks": len(full_bricks),
        "highest_remaining_layer": max(brick.layer for brick in active),
        "fixed_reference_center_world_m": [*spec["source_xy_m"], PLATE+spec["layers"]*HEIGHT+.0017],
        "palette_assignment": "Full original design colored before filtering removals",
        "temporal_history": "none; fresh static scene",
        "active_design_records": [{"id": brick.name, "layer": brick.layer, "color": brick.color,
            "grid_studs_xy": [brick.x, brick.y], "yaw_quarter_turn": brick.yaw} for brick in active]}
    return result_spec, active, metadata


def self_test(geometry_path, benchmark_path):
    spec, original = renderer.load_geometry(geometry_path)
    benchmark = json.loads(Path(benchmark_path).read_text())
    fixed_centers = []
    for case in benchmark["cases"]:
        _, active, metadata = prepare_case(spec, original, benchmark_path, case["id"])
        assert len(active) == case["expected"]["active_bricks"]
        assert len(metadata["removed_ids"])+len(active) == len(original)
        fixed_centers.append(metadata["fixed_reference_center_world_m"])
        if case["palette"] == "mixed":
            source = {brick.name: brick.color for brick in original}
            assert all(brick.color == source[brick.name] for brick in active)
        if case["id"] == "T_mix":
            assert max(brick.layer for brick in active) == 8
            assert renderer.geometry_audit(active)["layers"][9]["bounds_studs_xyxy"] is None
    assert all(center == fixed_centers[0] for center in fixed_centers)
    print("All frozen case counts, colors, active membership, empty top and fixed reference contracts passed")


if __name__ == "__main__":
    if "--self-test" in sys.argv:
        parser = argparse.ArgumentParser(description=__doc__)
        parser.add_argument("--self-test", action="store_true")
        parser.add_argument("--geometry", type=Path, default=ROOT/"experiments/sim_views_20261024/geometry.json")
        parser.add_argument("--benchmark", type=Path, default=Path(__file__).with_name("benchmark.json"))
        args = parser.parse_args()
        self_test(args.geometry, args.benchmark)
    else:
        renderer.main(case_adapter=prepare_case)
