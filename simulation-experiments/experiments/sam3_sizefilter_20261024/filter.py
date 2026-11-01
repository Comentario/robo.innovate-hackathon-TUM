"""One-shot apparent-size filtering and evidence-supported seam splitting.

Inputs are a saved SAM 3 LEGO-brick raw output and its original RGB image.
There are no annotation, registration, layer, grid or model inference inputs.
All full-image processing belongs in a frozen default Pueue queue job.
"""

import argparse
import hashlib
import json
import math
import os
from pathlib import Path
import shutil

import cv2
import numpy as np


def write_json(path, value):
    Path(path).write_text(json.dumps(value, indent=2, allow_nan=False) + "\n")


def file_hash(path):
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def mask_geometry(mask):
    """Return image-plane rectangle sides; retain every original foreground pixel."""
    y, x = np.nonzero(mask)
    if len(x) < 3:
        return None
    points = np.column_stack((x, y)).astype(np.float32)
    rectangle = cv2.minAreaRect(points)
    box = cv2.boxPoints(rectangle)
    edges = [box[1] - box[0], box[2] - box[1]]
    lengths = [float(np.linalg.norm(edge)) for edge in edges]
    longest = int(np.argmax(lengths))
    long_side, short_side = lengths[longest], lengths[1-longest]
    if short_side <= 0:
        return None
    long_axis = edges[longest] / long_side
    # Deterministic sign, independent of minAreaRect's corner convention.
    if long_axis[0] < 0 or (long_axis[0] == 0 and long_axis[1] < 0):
        long_axis = -long_axis
    short_axis = np.array([-long_axis[1], long_axis[0]], dtype=np.float32)
    components, _, stats, _ = cv2.connectedComponentsWithStats(mask.astype(np.uint8), connectivity=8)
    largest = int(stats[1:, cv2.CC_STAT_AREA].max()) if components > 1 else 0
    return {"short": short_side, "long": long_side,
            "aspect": long_side/short_side,
            "extent": min(1.0, len(x)/((short_side+1)*(long_side+1))),
            "area": int(len(x)), "largest_component_fraction": largest/len(x),
            "center": [float(v) for v in rectangle[0]],
            "long_axis": [float(v) for v in long_axis],
            "short_axis": [float(v) for v in short_axis],
            "rectangle_corners": box.tolist()}


def strongest_mode(seeds, config):
    """Largest deterministic joint log-size neighborhood; no fitted grid."""
    if not seeds:
        return None
    radius = math.log(config["cluster_side_ratio"])
    proposals = []
    for seed in seeds:
        members = []
        residual = 0.0
        for other in seeds:
            delta = [abs(math.log(other[side]/seed[side])) for side in ("short", "long")]
            if max(delta) <= radius:
                members.append(other)
                residual += sum(delta)/radius
        proposals.append((-len(members), residual, seed["id"], members))
    _, residual, anchor_id, members = min(proposals, key=lambda p: p[:3])
    return {"anchor_id": anchor_id, "member_ids": sorted(p["id"] for p in members),
            "support": len(members), "summed_normalized_log_residual": residual,
            "short": float(np.median([p["short"] for p in members])),
            "long": float(np.median([p["long"] for p in members]))}


def estimate_scale(entries, config):
    seeds = []
    for entry in entries:
        geometry = entry["geometry"]
        if geometry is not None and (config["seed_aspect_min"] <= geometry["aspect"] <= config["seed_aspect_max"]
                and geometry["extent"] >= config["seed_extent_min"]
                and geometry["largest_component_fraction"] >= config["seed_largest_component_fraction_min"]):
            seeds.append({"id": entry["id"], **geometry})
    winner = strongest_mode(seeds, config)
    members = set(winner["member_ids"]) if winner else set()
    runner_up = strongest_mode([s for s in seeds if s["id"] not in members], config)
    ratio = winner["support"]/runner_up["support"] if winner and runner_up else None
    reasons = []
    if winner is None or winner["support"] < config["minimum_mode_support"]:
        reasons.append("insufficient_scale_support")
    if ratio is not None and ratio < config["minimum_mode_ratio"]:
        reasons.append("ambiguous_scale_modes")
    return {"status": "abstain" if reasons else "estimated", "reasons": reasons,
            "eligible_seeds": seeds, "winning_mode": winner, "runner_up_mode": runner_up,
            "support_ratio": ratio,
            "method": "Largest joint log-side neighborhood; runner-up excludes winning members; pixel geometry only",
            "limitation": "Full-brick identity and physical layer are not established by apparent size"}


def side_errors(geometry, nominal):
    return {side: geometry[side]/nominal[side]-1 for side in ("short", "long")}


def seam_evidence(gray, geometry, nominal, split_count, config):
    """Find shared cut columns; each row uses that SAME column, never its own maximum."""
    center = np.asarray(geometry["center"])
    long_axis = np.asarray(geometry["long_axis"])
    short_axis = np.asarray(geometry["short_axis"])
    # Approximately one source pixel per sample; coordinates recorded for audit.
    columns = max(3, int(math.ceil(geometry["long"]))+1)
    rows = max(3, int(math.ceil(geometry["short"]*config["seam_width_fraction"]))+1)
    u = np.linspace(-geometry["long"]/2, geometry["long"]/2, columns)
    v = np.linspace(-geometry["short"]*config["seam_width_fraction"]/2,
                     geometry["short"]*config["seam_width_fraction"]/2, rows)
    points = center + u[None, :, None]*long_axis + v[:, None, None]*short_axis
    patch = cv2.remap(gray, points[:, :, 0].astype(np.float32),
                      points[:, :, 1].astype(np.float32), cv2.INTER_LINEAR,
                      borderMode=cv2.BORDER_REPLICATE).astype(np.float32)
    # Signed central difference, absolute contrast in gray levels per pixel.
    gradient = np.abs((patch[:, 2:]-patch[:, :-2])/2)
    positions = u[1:-1]
    background = float(np.median(gradient))
    mad = float(np.median(np.abs(gradient-background)))
    threshold = max(config["seam_derivative_floor"],
                    background+config["seam_noise_mad_multiplier"]*mad)
    seams = []
    for index in range(1, split_count):
        expected = -geometry["long"]/2 + index*geometry["long"]/split_count
        window = config["seam_search_half_length"]*nominal["long"]
        possible = np.flatnonzero(np.abs(positions-expected) <= window)
        candidates = []
        for column in possible:
            strengths = gradient[:, column]
            support = float(np.mean(strengths >= threshold))
            median = float(np.median(strengths))
            ratio = median/max(background, .5)
            candidates.append({"u": float(positions[column]), "column": int(column+1),
                "support_fraction": support, "median_derivative": median,
                "background_ratio": ratio})
        if not candidates:
            seams.append({"index": index, "expected_u": expected, "supported": False,
                          "reason": "empty_seam_search_window"})
            continue
        # A common line, chosen by cross-width support; not independently selected per row.
        best = min(candidates, key=lambda c: (-c["support_fraction"], -c["median_derivative"],
                                              abs(c["u"]-expected), c["u"]))
        supported = (best["support_fraction"] >= config["seam_support_fraction_min"]
                     and best["background_ratio"] >= config["seam_background_ratio_min"])
        point = center+best["u"]*long_axis
        seams.append({"index": index, "expected_u": expected, "supported": supported,
                      "search_half_window_pixels": window, "line_center_xy": point.tolist(),
                      "line_direction_xy": short_axis.tolist(), **best})
    return {"seams": seams, "background_median_derivative": background,
            "background_mad_derivative": mad, "derivative_threshold": threshold,
            "fixed_width_domain_rows": rows, "fixed_width_fraction": config["seam_width_fraction"],
            "all_supported": bool(seams) and all(s["supported"] for s in seams)}


def split_mask(mask, geometry, cuts):
    y, x = np.nonzero(mask)
    offsets = ((x-geometry["center"][0])*geometry["long_axis"][0]
               + (y-geometry["center"][1])*geometry["long_axis"][1])
    assignments = np.searchsorted(np.asarray(cuts), offsets, side="right")
    children = []
    for index in range(len(cuts)+1):
        child = np.zeros_like(mask)
        chosen = assignments == index
        child[y[chosen], x[chosen]] = True
        children.append(child)
    residual = mask & ~np.logical_or.reduce(children)
    return children, residual


def tight_box(mask):
    y, x = np.nonzero(mask)
    return [int(x.min()), int(y.min()), int(x.max()+1), int(y.max()+1)]


def duplicate_pairs(detections, masks, threshold):
    pairs = []
    for i, first in enumerate(detections):
        for j in range(i):
            second = detections[j]
            a, b = first["box_xyxy"], second["box_xyxy"]
            if min(a[2], b[2]) <= max(a[0], b[0]) or min(a[3], b[3]) <= max(a[1], b[1]):
                continue
            intersection = int(np.count_nonzero(masks[first["id"]] & masks[second["id"]]))
            union = int(np.count_nonzero(masks[first["id"]] | masks[second["id"]]))
            overlap = intersection/union if union else 0.0
            if overlap >= threshold:
                pairs.append({"ids": [second["id"], first["id"]], "mask_iou": overlap,
                              "involves_split_child": first["operation"] == "split_child" or second["operation"] == "split_child"})
    return pairs


def stage_overlay(image, detections, masks):
    canvas = image.copy()
    for index, detection in enumerate(detections):
        color = tuple(int(v) for v in cv2.cvtColor(np.uint8([[[index*47 % 180, 220, 255]]]), cv2.COLOR_HSV2BGR)[0, 0])
        contours, _ = cv2.findContours(masks[detection["id"]].astype(np.uint8), cv2.RETR_LIST, cv2.CHAIN_APPROX_SIMPLE)
        cv2.drawContours(canvas, contours, -1, color, 1)
        x, y = [round(v) for v in detection["box_xyxy"][:2]]
        cv2.putText(canvas, detection["id"], (max(0, x), max(12, y)), cv2.FONT_HERSHEY_SIMPLEX, .35, color, 1)
    return canvas


def process_image(image, raw, raw_directory, output, config):
    output = Path(output)
    output.mkdir(parents=True, exist_ok=True)
    height, width = image.shape[:2]
    if raw["prompt_id"] != config["source_prompt_id"] or raw["prompt"] != config["source_prompt"]:
        raise ValueError("Only the frozen saved LEGO brick prompt is authorized")
    if (raw["width"], raw["height"]) != (width, height):
        raise ValueError("Original image and saved prediction dimensions differ")
    entries, source_masks = [], {}
    for record in raw["detections"]:
        path = Path(raw_directory)/record["mask"]
        if file_hash(path) != record["mask_sha256"]:
            raise ValueError("Saved source mask SHA differs from its unchanged SAM manifest")
        encoded = cv2.imread(str(path), cv2.IMREAD_GRAYSCALE)
        if encoded is None or encoded.shape != (height, width) or not np.all((encoded == 0) | (encoded == 255)):
            raise ValueError("Source mask is not unchanged original-resolution binary data")
        mask = encoded != 0
        source_masks[record["id"]] = mask
        entries.append({"id": record["id"], "geometry": mask_geometry(mask)})
    scale = estimate_scale(entries, config)
    geometry_by_id = {e["id"]: e["geometry"] for e in entries}
    gray = cv2.cvtColor(image, cv2.COLOR_BGR2GRAY)
    retained, final, decisions, masks = [], [], [], {}
    for stage in ("retained_only", "final"):
        (output/stage).mkdir(exist_ok=True)
    for record in raw["detections"]:
        identity = record["id"]
        geometry = geometry_by_id[identity]
        decision = {"id": identity, "geometry": geometry, "decision": "rejected", "reasons": [],
                    "children": [], "seam_evidence": None, "residual_area": None}
        decisions.append(decision)
        if scale["status"] != "estimated":
            decision.update(decision="uncertain", reasons=scale["reasons"])
            continue
        if geometry is None:
            decision["reasons"] = ["degenerate_mask_geometry"]
            continue
        nominal = scale["winning_mode"]
        errors = side_errors(geometry, nominal)
        decision["relative_side_errors"] = errors
        tolerance = config["dimension_relative_tolerance"]
        if abs(errors["short"]) > tolerance:
            decision["reasons"] = ["short_dimension_mismatch"]
            continue
        if abs(errors["long"]) <= tolerance:
            kept = {**record, "parent_id": identity, "operation": "retained", "box_origin": "unchanged_model"}
            for stage in ("retained_only", "final"):
                shutil.copy2(Path(raw_directory)/record["mask"], output/stage/record["mask"])
            retained.append(kept)
            final.append(kept)
            masks[identity] = source_masks[identity]
            decision.update(decision="retained", reasons=["both_dimensions_match"])
            continue
        length_ratio = geometry["long"]/nominal["long"]
        count = round(length_ratio)
        decision.update(length_ratio=length_ratio, proposed_split_count=count,
                        integer_length_residual=abs(length_ratio-count))
        if not 2 <= count <= config["maximum_split_count"] or abs(length_ratio-count) > config["integer_length_residual_max"]:
            decision["reasons"] = ["long_dimension_not_supported_integer_multiple"]
            continue
        evidence = seam_evidence(gray, geometry, nominal, count, config)
        decision["seam_evidence"] = evidence
        if not evidence["all_supported"]:
            decision.update(decision="uncertain", reasons=["unsupported_image_seam"])
            continue
        cuts = [seam["u"] for seam in evidence["seams"]]
        children, residual = split_mask(source_masks[identity], geometry, cuts)
        child_geometry = [mask_geometry(child) for child in children]
        decision["proposed_child_geometry"] = child_geometry
        decision["residual_area"] = int(np.count_nonzero(residual))
        if any(g is None or any(abs(value) > tolerance for value in side_errors(g, nominal).values()) for g in child_geometry):
            decision.update(decision="uncertain", reasons=["split_child_dimension_mismatch"])
            continue
        if decision["residual_area"] != 0:
            raise RuntimeError("Partition unexpectedly lost source mask pixels")
        for index, child in enumerate(children, 1):
            child_id = f"{identity}_s{index:02d}"
            filename = f"{child_id}.png"
            if not cv2.imwrite(str(output/"final"/filename), child.astype(np.uint8)*255):
                raise OSError("Child mask write failed")
            final.append({"id": child_id, "parent_id": identity, "operation": "split_child",
                          "box_origin": "derived_tight_mask_half_open", "box_xyxy": tight_box(child),
                          "score": record["score"], "score_origin": "inherited_parent_not_recalibrated",
                          "mask": filename, "mask_sha256": file_hash(output/"final"/filename)})
            masks[child_id] = child
            decision["children"].append(child_id)
        residual_file = f"{identity}_residual.png"
        if not cv2.imwrite(str(output/residual_file), residual.astype(np.uint8)*255):
            raise OSError("Residual mask write failed")
        decision.update(decision="split", reasons=["integer_size_and_all_image_seams_supported"],
                        residual_mask=residual_file, parent_area=geometry["area"],
                        children_area=sum(int(np.count_nonzero(child)) for child in children))
    for stage, detections in (("retained_only", retained), ("final", final)):
        write_json(output/stage/"raw.json", {"image": raw["image"], "prompt_id": raw["prompt_id"],
            "prompt": raw["prompt"], "width": width, "height": height, "detections": detections,
            "stage": stage, "notes": "Apparent pixel-size filtering; physical identity/layer unknown; no deduplication"})
        if not cv2.imwrite(str(output/stage/"overlay.png"), stage_overlay(image, detections, masks)):
            raise OSError("Overlay write failed")
    diagnostics = {"image": raw["image"], "source_prompt_id": raw["prompt_id"],
        "source_count": len(raw["detections"]), "config": config, "scale": scale,
        "decisions": decisions, "retained_count": len(retained), "final_count": len(final),
        "duplicate_pairs": duplicate_pairs(final, masks, config["duplicate_mask_iou_threshold"]),
        "deduplication": False, "limitations": [
            "Apparent minAreaRect side lengths are not metric dimensions or calibrated pose.",
            "Perspective, side faces, fragments and layer visibility can violate the scale hypothesis.",
            "A compatible-size mask is not verified to be an exposed accessible full brick.",
            "Original rejected/uncertain masks remain unchanged in the frozen source directory."]}
    write_json(output/"diagnostics.json", diagnostics)
    return diagnostics


def self_test(config):
    # Tiny contracts only, no uploaded images or model inference.
    entries = [{"id": f"a{i}", "geometry": {"short": 10., "long": 20., "aspect": 2.,
                "extent": .9, "largest_component_fraction": 1.}} for i in range(6)]
    assert estimate_scale(entries, config)["status"] == "estimated"
    alternate = [{"id": f"b{i}", "geometry": {"short": 20., "long": 40., "aspect": 2.,
                  "extent": .9, "largest_component_fraction": 1.}} for i in range(6)]
    assert estimate_scale(entries+alternate, config)["status"] == "abstain"
    mask = np.zeros((32, 64), dtype=bool)
    mask[8:19, 8:49] = True
    geometry = mask_geometry(mask)
    children, residual = split_mask(mask, geometry, [0.])
    assert np.array_equal(np.logical_or.reduce(children), mask) and not residual.any()
    assert not np.any(children[0] & children[1])
    flat = np.zeros(mask.shape, dtype=np.uint8)
    assert not seam_evidence(flat, geometry, {"long": 20.}, 2, config)["all_supported"]
    seam = np.full(mask.shape, 100, dtype=np.uint8)
    seam[8:19, 27:30] = 0
    assert seam_evidence(seam, geometry, {"long": 20.}, 2, config)["all_supported"]
    staggered = np.full(mask.shape, 100, dtype=np.uint8)
    for row in range(8, 19):
        staggered[row, 25+(row % 7)] = 0
    assert not seam_evidence(staggered, geometry, {"long": 20.}, 2, config)["all_supported"]
    print("size/seam tiny contracts passed")


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--config", type=Path, default=Path(__file__).with_name("config.json"))
    parser.add_argument("--image", type=Path)
    parser.add_argument("--raw", type=Path)
    parser.add_argument("--output", type=Path)
    parser.add_argument("--self-test", action="store_true")
    args = parser.parse_args()
    config = json.loads(args.config.read_text())
    cv2.setNumThreads(2)
    if args.self_test:
        self_test(config)
        return
    if os.environ.get("ROBO_PUEUE_JOB") != "1":
        parser.error("Image processing must use the frozen default Pueue queue job")
    if args.image is None or args.raw is None or args.output is None:
        parser.error("--image, --raw and --output are required")
    image = cv2.imread(str(args.image), cv2.IMREAD_COLOR)
    if image is None:
        raise ValueError("Could not decode the original RGB image")
    raw = json.loads(args.raw.read_text())
    diagnostics = process_image(image, raw, args.raw.parent, args.output, config)
    print(json.dumps({"image": raw["image"], "scale_status": diagnostics["scale"]["status"],
                      "source_count": diagnostics["source_count"], "retained": diagnostics["retained_count"],
                      "final": diagnostics["final_count"]}), flush=True)


if __name__ == "__main__":
    main()
