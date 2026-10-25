import json
from itertools import combinations
from pathlib import Path

import cv2
import numpy as np

from scripts.validate_wall_lab_clusters import (
    CLUSTER_COUNT,
    build_mask_panel,
    cluster_lab_image,
    reconstruct_cluster_map,
)


PROJECT_ROOT = Path(__file__).resolve().parents[1]
IMAGE_DIRECTORY = PROJECT_ROOT / "Initial_Dataset_Bricks_LEGO"
OUTPUT_DIRECTORY = PROJECT_ROOT / "outputs" / "hackathon_isolated_bricks_experiment"


def find_table_boundary(image: np.ndarray) -> int:
    """Estimate the wall-to-table boundary from the unobstructed right side."""
    height, width = image.shape[:2]
    lab = cv2.cvtColor(image, cv2.COLOR_BGR2LAB).astype(np.float32)
    x1, x2 = round(width * 0.78), round(width * 0.98)
    y1, y2 = round(height * 0.50), round(height * 0.92)
    strip = lab[y1:y2, x1:x2]
    row_change = np.mean(np.linalg.norm(np.diff(strip, axis=0), axis=2), axis=1)
    row_change = cv2.GaussianBlur(row_change.reshape(-1, 1), (1, 15), 0).ravel()
    return y1 + int(np.argmax(row_change))


def cluster_options() -> list[tuple[int, ...]]:
    """Return every one- and two-cluster foreground hypothesis."""
    return [
        option
        for size in (1, 2)
        for option in combinations(range(CLUSTER_COUNT), size)
    ]


def clean_candidate_mask(
    labels: np.ndarray,
    selected: tuple[int, ...],
    table_y: int,
) -> tuple[np.ndarray, np.ndarray]:
    """Build a foreground mask and limit it to the physical work area."""
    height, width = labels.shape
    raw = np.where(np.isin(labels, selected), 255, 0).astype(np.uint8)
    limited = raw.copy()
    limited[: round(height * 0.10), :] = 0
    limited[min(height, table_y + round(height * 0.10)) :, :] = 0
    limited[:, : round(width * 0.055)] = 0
    limited[:, round(width * 0.985) :] = 0

    open_kernel = cv2.getStructuringElement(cv2.MORPH_RECT, (5, 5))
    close_kernel = cv2.getStructuringElement(cv2.MORPH_RECT, (9, 13))
    cleaned = cv2.morphologyEx(limited, cv2.MORPH_OPEN, open_kernel)
    cleaned = cv2.morphologyEx(cleaned, cv2.MORPH_CLOSE, close_kernel)
    return raw, cleaned


def clean_existing_mask(mask: np.ndarray, table_y: int) -> np.ndarray:
    """Apply the same spatial limits and morphology to an existing mask."""
    height, width = mask.shape
    limited = mask.copy()
    limited[: round(height * 0.10), :] = 0
    limited[min(height, table_y + round(height * 0.10)) :, :] = 0
    limited[:, : round(width * 0.055)] = 0
    limited[:, round(width * 0.985) :] = 0
    open_kernel = cv2.getStructuringElement(cv2.MORPH_RECT, (5, 5))
    close_kernel = cv2.getStructuringElement(cv2.MORPH_RECT, (9, 13))
    cleaned = cv2.morphologyEx(limited, cv2.MORPH_OPEN, open_kernel)
    return cv2.morphologyEx(cleaned, cv2.MORPH_CLOSE, close_kernel)


def component_candidates(mask: np.ndarray, table_y: int) -> tuple[list[dict], list[dict]]:
    """Separate plausible upright bricks from rejected foreground regions."""
    height, width = mask.shape
    count, _, stats, _ = cv2.connectedComponentsWithStats(mask, connectivity=8)
    accepted = []
    rejected = []
    image_area = height * width

    for label in range(1, count):
        x, y, box_width, box_height, area = (int(value) for value in stats[label])
        fill_ratio = area / max(1, box_width * box_height)
        bottom = y + box_height
        reasons = []
        if area < image_area * 0.002:
            reasons.append("area")
        if box_width < width * 0.025:
            reasons.append("width")
        if box_height < height * 0.18:
            reasons.append("height")
        if bottom < table_y - height * 0.18:
            reasons.append("unsupported")
        if fill_ratio < 0.16:
            reasons.append("fill")
        if x <= width * 0.06 or x + box_width >= width * 0.98:
            reasons.append("border")
        if y <= height * 0.12:
            reasons.append("top_border")

        item = {
            "bbox_px": {
                "x": x,
                "y": y,
                "width": box_width,
                "height": box_height,
            },
            "area_px": area,
            "fill_ratio": round(fill_ratio, 4),
            "reasons": reasons,
        }
        (accepted if not reasons else rejected).append(item)
    return accepted, rejected


def evaluate_option(
    labels: np.ndarray,
    selected: tuple[int, ...],
    table_y: int,
) -> dict:
    """Measure how well one cluster union behaves as isolated bricks."""
    height, width = labels.shape
    raw, cleaned = clean_candidate_mask(labels, selected, table_y)
    accepted, rejected = component_candidates(cleaned, table_y)

    wall_seed = raw[
        round(height * 0.10) : round(height * 0.23),
        round(width * 0.12) : round(width * 0.96),
    ]
    table_seed = raw[
        max(round(height * 0.93), table_y + round(height * 0.10)) : round(
            height * 0.99
        ),
        round(width * 0.25) : round(width * 0.96),
    ]
    wall_occupancy = float(np.mean(wall_seed > 0)) if wall_seed.size else 1.0
    table_occupancy = float(np.mean(table_seed > 0)) if table_seed.size else 1.0
    accepted_area = sum(item["area_px"] for item in accepted)
    rejected_area = sum(item["area_px"] for item in rejected)
    work_area = max(1, (table_y - round(height * 0.10)) * width)
    object_coverage = accepted_area / work_area
    accepted_share = accepted_area / max(1, accepted_area + rejected_area)
    mean_fill = (
        float(np.mean([item["fill_ratio"] for item in accepted]))
        if accepted
        else 0.0
    )
    useful_count = min(len(accepted), 8) / 8.0
    oversized = any(
        item["bbox_px"]["width"] > width * 0.65
        or item["bbox_px"]["height"] > height * 0.85
        for item in accepted
    )

    score = (
        1.6 * min(object_coverage / 0.30, 1.0)
        + 1.2 * accepted_share
        + 0.8 * mean_fill
        + 0.5 * useful_count
        - 2.6 * wall_occupancy
        - 0.7 * table_occupancy
        - (1.0 if oversized else 0.0)
        - (2.0 if not accepted else 0.0)
    )
    return {
        "selected_clusters": list(selected),
        "score": round(score, 4),
        "wall_occupancy": round(wall_occupancy, 4),
        "table_occupancy": round(table_occupancy, 4),
        "object_coverage": round(object_coverage, 4),
        "accepted_share": round(accepted_share, 4),
        "mean_fill": round(mean_fill, 4),
        "accepted_count": len(accepted),
        "rejected_count": len(rejected),
        "oversized": oversized,
        "raw_mask": raw,
        "cleaned_mask": cleaned,
        "accepted": accepted,
        "rejected": rejected,
    }


def normalized_profile(profile: np.ndarray) -> np.ndarray:
    """Normalize a one-dimensional signal without amplifying flat profiles."""
    lower, upper = np.percentile(profile, (10, 90))
    if upper <= lower:
        return np.zeros_like(profile, dtype=np.float32)
    return np.clip((profile - lower) / (upper - lower), 0.0, 1.0)


def build_local_search_region(
    image: np.ndarray,
    table_y: int,
) -> tuple[np.ndarray, np.ndarray, dict]:
    """Find broad object columns using their Lab distance from the upper wall."""
    height, width = image.shape[:2]
    lab = cv2.cvtColor(image, cv2.COLOR_BGR2LAB).astype(np.float32)
    wall_seed = lab[
        round(height * 0.10) : round(height * 0.23),
        round(width * 0.12) : round(width * 0.96),
    ]
    wall_center = np.median(wall_seed.reshape(-1, 3), axis=0)
    difference = lab - wall_center
    distance = np.sqrt(
        0.05 * difference[:, :, 0] ** 2
        + difference[:, :, 1] ** 2
        + difference[:, :, 2] ** 2
    )
    seed_difference = wall_seed - wall_center
    seed_distance = np.sqrt(
        0.05 * seed_difference[:, :, 0] ** 2
        + seed_difference[:, :, 1] ** 2
        + seed_difference[:, :, 2] ** 2
    )
    threshold = max(10.0, float(np.percentile(seed_distance, 99.0)) + 3.0)
    coarse = np.where(distance >= threshold, 255, 0).astype(np.uint8)
    coarse[: round(height * 0.10), :] = 0
    coarse[table_y:, :] = 0
    coarse[:, : round(width * 0.055)] = 0
    coarse[:, round(width * 0.985) :] = 0
    coarse = cv2.morphologyEx(
        coarse,
        cv2.MORPH_OPEN,
        cv2.getStructuringElement(cv2.MORPH_RECT, (5, 5)),
    )

    y1 = round(height * 0.18)
    y2 = table_y
    column_occupancy = np.mean(coarse[y1:y2] > 0, axis=0)
    active = np.where(column_occupancy >= 0.16, 255, 0).astype(np.uint8)
    active = cv2.morphologyEx(
        active.reshape(1, -1),
        cv2.MORPH_CLOSE,
        cv2.getStructuringElement(cv2.MORPH_RECT, (61, 1)),
    ).ravel()

    region = np.zeros_like(coarse)
    count, _, stats, _ = cv2.connectedComponentsWithStats(
        active.reshape(1, -1), connectivity=8
    )
    spans = []
    margin = round(width * 0.02)
    for label in range(1, count):
        x, _, span_width, _, _ = (int(value) for value in stats[label])
        if span_width < width * 0.045:
            continue
        start = max(round(width * 0.055), x - margin)
        stop = min(round(width * 0.985), x + span_width + margin)
        region[round(height * 0.10) : table_y + round(height * 0.10), start:stop] = 255
        spans.append({"x": start, "width": stop - start})
    return coarse, region, {
        "wall_center_lab_opencv": [round(float(value), 2) for value in wall_center],
        "distance_threshold": round(threshold, 3),
        "horizontal_spans": spans,
    }


def local_mask_quality(mask: np.ndarray, table_y: int) -> tuple[float, list[dict], list[dict]]:
    """Score a locally completed mask using only foreground geometry."""
    height, width = mask.shape
    accepted, rejected = component_candidates(mask, table_y)
    accepted_area = sum(item["area_px"] for item in accepted)
    rejected_area = sum(item["area_px"] for item in rejected)
    work_area = max(1, (table_y - round(height * 0.10)) * width)
    coverage = accepted_area / work_area
    accepted_share = accepted_area / max(1, accepted_area + rejected_area)
    mean_fill = (
        float(np.mean([item["fill_ratio"] for item in accepted]))
        if accepted
        else 0.0
    )
    useful_count = min(len(accepted), 8) / 8.0
    score = (
        1.6 * min(coverage / 0.30, 1.0)
        + 1.2 * accepted_share
        + 0.8 * mean_fill
        + 0.5 * useful_count
        - (2.0 if not accepted else 0.0)
    )
    return score, accepted, rejected


def build_silhouette_mask(
    coarse_foreground: np.ndarray,
    search_region: np.ndarray,
    table_y: int,
) -> np.ndarray:
    """Build a support-line-limited fallback from the wall-distance silhouette."""
    silhouette = cv2.bitwise_and(coarse_foreground, search_region)
    silhouette[table_y:, :] = 0
    close_kernel = cv2.getStructuringElement(cv2.MORPH_RECT, (11, 17))
    open_kernel = cv2.getStructuringElement(cv2.MORPH_RECT, (5, 5))
    silhouette = cv2.morphologyEx(silhouette, cv2.MORPH_CLOSE, close_kernel)
    return cv2.morphologyEx(silhouette, cv2.MORPH_OPEN, open_kernel)


def extend_components_to_support(
    components: list[dict],
    table_y: int,
    image_height: int,
) -> list[dict]:
    """Restore the portion hidden below the rear wall-to-table boundary."""
    support_bottom = min(image_height, table_y + round(image_height * 0.10))
    extended = []
    for component in components:
        item = {**component, "bbox_px": dict(component["bbox_px"])}
        box = item["bbox_px"]
        current_bottom = box["y"] + box["height"]
        if current_bottom >= table_y - round(image_height * 0.18):
            box["height"] = max(box["height"], support_bottom - box["y"])
        extended.append(item)
    return extended


def recover_local_complement(
    image: np.ndarray,
    labels: np.ndarray,
    selection: dict,
    table_y: int,
) -> dict:
    """Add one unselected cluster only inside a wall-distance object region."""
    coarse, region, region_diagnostics = build_local_search_region(image, table_y)
    base_mask = selection["cleaned_mask"]
    base_score, base_accepted, base_rejected = local_mask_quality(base_mask, table_y)
    candidates = [
        {
            "recovery_source": "none",
            "complementary_cluster": None,
            "score": base_score,
            "mask": base_mask,
            "local_mask": np.zeros_like(base_mask),
            "accepted": base_accepted,
            "rejected": base_rejected,
        }
    ]

    selected_clusters = set(selection["selected_clusters"])
    for cluster in range(CLUSTER_COUNT):
        if cluster in selected_clusters:
            continue
        local_mask = np.where(
            (labels == cluster) & (region > 0) & (coarse > 0),
            255,
            0,
        ).astype(np.uint8)
        combined = clean_existing_mask(cv2.bitwise_or(base_mask, local_mask), table_y)
        score, accepted, rejected = local_mask_quality(combined, table_y)
        candidates.append(
            {
                "recovery_source": "local_cluster",
                "complementary_cluster": cluster,
                "score": score,
                "mask": combined,
                "local_mask": local_mask,
                "accepted": accepted,
                "rejected": rejected,
            }
        )

    silhouette = build_silhouette_mask(coarse, region, table_y)
    silhouette_score, silhouette_accepted, silhouette_rejected = local_mask_quality(
        silhouette,
        table_y,
    )
    candidates.append(
        {
            "recovery_source": "silhouette",
            "complementary_cluster": None,
            "score": silhouette_score,
            "mask": silhouette,
            "local_mask": silhouette,
            "accepted": silhouette_accepted,
            "rejected": silhouette_rejected,
        }
    )

    candidates.sort(
        key=lambda item: (
            -item["score"],
            item["recovery_source"] != "none",
        )
    )
    best = candidates[0]
    if best["recovery_source"] != "none" and best["score"] < base_score + 0.04:
        best = next(item for item in candidates if item["recovery_source"] == "none")
    return {
        **best,
        "coarse_foreground": coarse,
        "search_region": region,
        "silhouette_mask": silhouette,
        "region_diagnostics": region_diagnostics,
        "candidate_scores": [
            {
                "recovery_source": item["recovery_source"],
                "complementary_cluster": item["complementary_cluster"],
                "score": round(float(item["score"]), 4),
                "accepted_count": len(item["accepted"]),
                "rejected_count": len(item["rejected"]),
            }
            for item in candidates
        ],
    }


def split_wide_components(image: np.ndarray, components: list[dict]) -> list[dict]:
    """Split wide brick groups at nearby vertical image-edge evidence."""
    lab = cv2.cvtColor(image, cv2.COLOR_BGR2LAB)
    lightness = lab[:, :, 0].astype(np.float32)
    gradient_x = np.abs(cv2.Sobel(lightness, cv2.CV_32F, 1, 0, ksize=3))
    detections = []

    for component in components:
        box = component["bbox_px"]
        x, y = box["x"], box["y"]
        width, height = box["width"], box["height"]
        nominal_width = max(1.0, height * 0.32)
        estimated_count = max(1, min(12, round(width / nominal_width)))
        if estimated_count == 1 or width < nominal_width * 1.55:
            detections.append(component)
            continue

        inner_y1 = y + round(height * 0.08)
        inner_y2 = y + round(height * 0.90)
        local_lightness = lightness[inner_y1:inner_y2, x : x + width]
        local_gradient = gradient_x[inner_y1:inner_y2, x : x + width]
        edge_profile = np.mean(local_gradient, axis=0)
        darkness_profile = 255.0 - np.mean(local_lightness, axis=0)
        edge_profile = cv2.GaussianBlur(edge_profile.reshape(1, -1), (11, 1), 0).ravel()
        darkness_profile = cv2.GaussianBlur(
            darkness_profile.reshape(1, -1), (11, 1), 0
        ).ravel()
        evidence = 0.7 * normalized_profile(edge_profile) + 0.3 * normalized_profile(
            darkness_profile
        )

        cuts = []
        spacing = width / estimated_count
        search_radius = max(8, round(spacing * 0.28))
        for index in range(1, estimated_count):
            predicted = round(index * spacing)
            start = max(1, predicted - search_radius)
            stop = min(width - 1, predicted + search_radius + 1)
            cut = start + int(np.argmax(evidence[start:stop]))
            if not cuts or cut - cuts[-1] >= spacing * 0.45:
                cuts.append(cut)

        boundaries = [0, *cuts, width]
        for start, stop in zip(boundaries, boundaries[1:]):
            if stop - start < nominal_width * 0.45:
                continue
            detections.append(
                {
                    **component,
                    "bbox_px": {
                        "x": x + int(start),
                        "y": y,
                        "width": int(stop - start),
                        "height": height,
                    },
                    "parent_bbox_px": box,
                    "split_from_group": True,
                }
            )
    return sorted(detections, key=lambda item: item["bbox_px"]["x"])


def draw_preview(
    image: np.ndarray,
    detections: list[dict],
    table_y: int,
) -> np.ndarray:
    """Draw the estimated support line and accepted component boxes."""
    preview = image.copy()
    cv2.line(preview, (0, table_y), (image.shape[1] - 1, table_y), (255, 0, 0), 2)
    for index, item in enumerate(detections, start=1):
        box = item["bbox_px"]
        start = (box["x"], box["y"])
        end = (box["x"] + box["width"], box["y"] + box["height"])
        cv2.rectangle(preview, start, end, (0, 255, 0), 3)
        cv2.putText(
            preview,
            f"{index:03d}",
            (box["x"] + 4, box["y"] + 24),
            cv2.FONT_HERSHEY_SIMPLEX,
            0.7,
            (255, 0, 0),
            2,
            cv2.LINE_AA,
        )
    return preview


def serializable_result(result: dict) -> dict:
    """Remove image arrays before writing candidate diagnostics as JSON."""
    return {
        key: value
        for key, value in result.items()
        if key not in {"raw_mask", "cleaned_mask", "accepted", "rejected"}
    }


def process_image(image_path: Path) -> dict:
    """Run cluster selection for one NS brick scene and save diagnostics."""
    image = cv2.imread(str(image_path))
    if image is None:
        raise FileNotFoundError(f"Could not read image: {image_path}")
    labels, centers = cluster_lab_image(image, CLUSTER_COUNT)
    table_y = find_table_boundary(image)
    results = [evaluate_option(labels, option, table_y) for option in cluster_options()]
    results.sort(key=lambda item: (-item["score"], len(item["selected_clusters"])))
    selected = results[0]
    local_recovery = recover_local_complement(image, labels, selected, table_y)
    extended_components = extend_components_to_support(
        local_recovery["accepted"],
        table_y,
        image.shape[0],
    )
    detections = split_wide_components(image, extended_components)

    scene_directory = OUTPUT_DIRECTORY / image_path.stem
    scene_directory.mkdir(parents=True, exist_ok=True)
    cluster_map = reconstruct_cluster_map(labels, centers)
    cluster_panel, cluster_summary = build_mask_panel(labels, centers)
    preview = draw_preview(image, detections, table_y)

    primary = np.where(labels == selected["selected_clusters"][0], 255, 0).astype(np.uint8)
    secondary = np.zeros_like(primary)
    if len(selected["selected_clusters"]) == 2:
        secondary = np.where(
            labels == selected["selected_clusters"][1], 255, 0
        ).astype(np.uint8)

    cv2.imwrite(str(scene_directory / "cluster_map.png"), cluster_map)
    cv2.imwrite(str(scene_directory / "cluster_masks.png"), cluster_panel)
    cv2.imwrite(str(scene_directory / "selected_primary.png"), primary)
    cv2.imwrite(str(scene_directory / "selected_secondary.png"), secondary)
    cv2.imwrite(str(scene_directory / "selected_union_raw.png"), selected["raw_mask"])
    cv2.imwrite(str(scene_directory / "selected_union_cleaned.png"), selected["cleaned_mask"])
    cv2.imwrite(
        str(scene_directory / "local_coarse_foreground.png"),
        local_recovery["coarse_foreground"],
    )
    cv2.imwrite(
        str(scene_directory / "local_search_region.png"),
        local_recovery["search_region"],
    )
    cv2.imwrite(
        str(scene_directory / "local_complement.png"),
        local_recovery["local_mask"],
    )
    cv2.imwrite(
        str(scene_directory / "local_silhouette.png"),
        local_recovery["silhouette_mask"],
    )
    cv2.imwrite(
        str(scene_directory / "final_mask.png"),
        local_recovery["mask"],
    )
    cv2.imwrite(str(scene_directory / "detections_preview.png"), preview)

    report = {
        "image": image_path.name,
        "table_y": table_y,
        "selected_clusters": selected["selected_clusters"],
        "selection_score": selected["score"],
        "recovery_source": local_recovery["recovery_source"],
        "complementary_cluster": local_recovery["complementary_cluster"],
        "local_recovery_score": round(float(local_recovery["score"]), 4),
        "local_region": local_recovery["region_diagnostics"],
        "local_candidate_scores": local_recovery["candidate_scores"],
        "component_count_before_split": len(local_recovery["accepted"]),
        "detection_count": len(detections),
        "detections": detections,
        "cluster_summary": cluster_summary,
        "candidate_ranking": [serializable_result(item) for item in results],
    }
    (scene_directory / "diagnostics.json").write_text(
        json.dumps(report, indent=2) + "\n",
        encoding="utf-8",
    )
    return report


def main() -> None:
    image_paths = sorted(IMAGE_DIRECTORY.glob("*B_*_NS.jpg"))
    if not image_paths:
        raise FileNotFoundError(f"No NS brick images found in: {IMAGE_DIRECTORY}")

    OUTPUT_DIRECTORY.mkdir(parents=True, exist_ok=True)
    reports = []
    print("Image             clusters  expected  detected  table_y  score")
    for image_path in image_paths:
        report = process_image(image_path)
        expected = int(image_path.name.split("B", 1)[0])
        reports.append({**report, "expected_count": expected})
        clusters = "+".join(f"C{i}" for i in report["selected_clusters"])
        print(
            f"{image_path.name:<17} {clusters:<8} {expected:>8} "
            f"{report['detection_count']:>9} {report['table_y']:>8} "
            f"{report['selection_score']:>6.3f}"
        )

    summary = [
        {
            "image": item["image"],
            "expected_count": item["expected_count"],
            "detected_count": item["detection_count"],
            "selected_clusters": item["selected_clusters"],
            "selection_score": item["selection_score"],
            "table_y": item["table_y"],
        }
        for item in reports
    ]
    (OUTPUT_DIRECTORY / "summary.json").write_text(
        json.dumps(summary, indent=2) + "\n",
        encoding="utf-8",
    )
    exact = sum(item["expected_count"] == item["detection_count"] for item in reports)
    print(f"\nExact-count scenes: {exact}/{len(reports)}")
    print(f"Outputs: {OUTPUT_DIRECTORY}")


if __name__ == "__main__":
    main()
