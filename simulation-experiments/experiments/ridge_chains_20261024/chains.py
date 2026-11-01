"""RGB-only projected ridge and fixed-phase brick-chain hypotheses.

This bounded experiment uses image lines, stud periodicity and local cap/edge
evidence. Its projected strips do not establish physical height or metric pose.
No annotation, registration, SAM, robot or simulation inputs are read.
"""

import argparse
import json
import math
import os
from pathlib import Path

import cv2
import numpy as np


def save_json(path, data):
    Path(path).write_text(json.dumps(data, indent=2, allow_nan=False)+"\n")


def unit(vector):
    vector = np.asarray(vector, np.float64)
    return vector/max(float(np.linalg.norm(vector)), 1e-9)


def canonical_direction(vector):
    direction = unit(vector)
    return -direction if direction[0] < 0 or (direction[0] == 0 and direction[1] < 0) else direction


def fit_group(segments):
    points = np.asarray([point for s in segments for point in s["points"]], np.float64)
    center = points.mean(axis=0)
    _, _, axes = np.linalg.svd(points-center, full_matrices=False)
    direction = canonical_direction(axes[0])
    offsets = (points-center)@direction
    return {"center": center, "direction": direction,
            "points": np.array([center+offsets.min()*direction, center+offsets.max()*direction]),
            "segments": segments, "length": float(np.ptp(offsets))}


def extract_lines(gray, config):
    height, width = gray.shape
    diagonal = math.hypot(width, height)
    result = cv2.createLineSegmentDetector(cv2.LSD_REFINE_STD).detect(gray)[0]
    segments = []
    for index, coordinates in enumerate(result if result is not None else []):
        points = np.asarray(coordinates).reshape(2, 2).astype(np.float64)
        length = float(np.linalg.norm(points[1]-points[0]))
        if length >= config["minimum_segment_diagonal_fraction"]*diagonal:
            segments.append({"id": f"e{index:04d}", "points": points.tolist(), "length": length})
    groups = []
    for segment in sorted(segments, key=lambda s: (-s["length"], s["id"])):
        points = np.asarray(segment["points"])
        direction = canonical_direction(points[1]-points[0])
        eligible = []
        for index, group in enumerate(groups):
            if abs(direction@group["direction"]) < math.cos(math.radians(config["merge_angle_degrees"])):
                continue
            normal = np.array([-group["direction"][1], group["direction"][0]])
            distance = float(np.max(np.abs((points-group["center"])@normal)))
            if distance > config["merge_distance_side_fraction"]*min(width, height):
                continue
            a = (points-group["center"])@group["direction"]
            b = (group["points"]-group["center"])@group["direction"]
            gap = max(float(a.min()-b.max()), float(b.min()-a.max()), 0.)
            if gap <= config["merge_gap_diagonal_fraction"]*diagonal:
                eligible.append((distance+gap*.01, index, distance, gap))
        if eligible:
            _, index, distance, gap = min(eligible)
            prior = groups[index]
            groups[index] = fit_group(prior["segments"]+[segment])
            groups[index]["joins"] = prior.get("joins", [])+[{"segment_id": segment["id"],
                "reason": "angle_distance_and_gap_within_frozen_collinear_limits",
                "perpendicular_distance_px": distance, "longitudinal_gap_px": gap}]
        else:
            groups.append({**fit_group([segment]), "joins": []})
    for index, group in enumerate(groups):
        group["id"] = f"line{index:04d}"
    return segments, groups


def side_at(group, coordinate, axis):
    return group["center"] + ((coordinate-group["center"]@axis)/(group["direction"]@axis))*group["direction"]


def ridge_proposals(groups, image_shape, config):
    height, width = image_shape
    proposals = []
    for i, first in enumerate(groups):
        for second in groups[:i]:
            if abs(first["direction"]@second["direction"]) < math.cos(math.radians(config["pair_angle_degrees"])):
                continue
            # Lines are undirected: align signs before averaging near-vertical lines.
            sign = 1 if first["direction"]@second["direction"] >= 0 else -1
            axis = unit(first["direction"]+sign*second["direction"])
            normal = np.array([-axis[1], axis[0]])
            a, b = first, second
            if a["center"]@normal > b["center"]@normal:
                a, b = b, a
            intervals = [group["points"]@axis for group in (a, b)]
            start = min(float(v.min()) for v in intervals)
            end = max(float(v.max()) for v in intervals)
            overlap = max(0., min(float(v.max()) for v in intervals)-max(float(v.min()) for v in intervals))
            if end <= start or overlap/(end-start) < config["minimum_side_overlap_fraction"]:
                continue
            quad = np.asarray([side_at(a, start, axis), side_at(a, end, axis),
                               side_at(b, end, axis), side_at(b, start, axis)])
            widths = [float(np.linalg.norm(quad[3]-quad[0])), float(np.linalg.norm(quad[2]-quad[1]))]
            mean_width = float(np.mean(widths))
            if not config["ridge_width_side_fraction"][0]*min(width, height) <= mean_width <= config["ridge_width_side_fraction"][1]*min(width, height):
                continue
            if end-start < config["minimum_ridge_length_width_ratio"]*mean_width:
                continue
            if any((quad[3-j]-quad[j])@normal <= 0 for j in (0, 1)):
                continue
            residuals = []
            source_ids = []
            for group in (a, b):
                n = np.array([-group["direction"][1], group["direction"][0]])
                for segment in group["segments"]:
                    residuals.extend(np.abs((np.asarray(segment["points"])-group["center"])@n).tolist())
                    source_ids.append(segment["id"])
            endpoint_fit = float(np.clip(1-np.mean(residuals)/max(mean_width*.1, 1.), 0, 1))
            proposals.append({"id": f"ridge_{a['id']}_{b['id']}", "quad": quad,
                "axis": axis, "length": end-start, "width": mean_width,
                "segment_ids": sorted(set(source_ids)), "endpoint_fit": endpoint_fit,
                "side_segment_endpoints": [segment["points"] for group in (a, b) for segment in group["segments"]],
                "support": a["length"]+b["length"]})
    return sorted(proposals, key=lambda p: (-p["support"], p["id"]))[:config["maximum_geometric_proposals"]]


def autocorrelation(profile, lag):
    lag = int(round(lag))
    if lag < 1 or lag >= len(profile)-2:
        return 0.
    a, b = profile[:-lag], profile[lag:]
    return float(a@b/max(float(np.linalg.norm(a)*np.linalg.norm(b)), 1e-9))


def infer_pitch(gray, config):
    width, length = gray.shape
    lower, upper = int(width*.15), max(int(width*.85), int(width*.15)+1)
    profile = gray[lower:upper].mean(axis=0).astype(np.float32)
    smooth = cv2.GaussianBlur(profile[None], (0, 0), sigmaX=max(width/2, 1), sigmaY=1)[0]
    profile = profile-smooth
    tolerance = config["pitch_width_relative_tolerance"]
    candidates = list(range(max(2, math.ceil(width*.5*(1-tolerance))),
                            min(length-2, math.floor(width*.5*(1+tolerance)))+1))
    values = [{"pitch": p, "correlation": autocorrelation(profile, p)} for p in candidates]
    if not values:
        return {"status": "ambiguous", "reasons": ["no_pitch_search_window"], "candidates": values}
    best = min(values, key=lambda item: (-item["correlation"], abs(item["pitch"]-width/2), item["pitch"]))
    prominence = best["correlation"]-float(np.median([v["correlation"] for v in values]))
    # This half-pitch probe deliberately lies OUTSIDE the nominal width-derived window.
    half = autocorrelation(profile, best["pitch"]/2)
    alias = half >= config["pitch_autocorrelation_min"] and half >= config["half_pitch_alias_ratio"]*best["correlation"]
    reasons = []
    if best["correlation"] < config["pitch_autocorrelation_min"]:
        reasons.append("weak_periodicity")
    if prominence < config["pitch_prominence_min"]:
        reasons.append("ambiguous_period_peak")
    if alias:
        reasons.append("half_pitch_alias")
    return {"status": "ambiguous" if reasons else "supported", "reasons": reasons,
            "pitch_px": best["pitch"], "correlation": best["correlation"], "prominence": prominence,
            "half_pitch_correlation_outside_search": half, "alias": alias, "candidates": values,
            "limitation": "Width/period agreement is an image hypothesis, not physical calibration"}


class Strip:
    def __init__(self, gray, proposal, config):
        self.config = config
        self.length = max(8, round(proposal["length"]))
        self.width = max(4, round(proposal["width"]))
        destination = np.float32([[0, 0], [self.length-1, 0], [self.length-1, self.width-1], [0, self.width-1]])
        self.homography = cv2.getPerspectiveTransform(proposal["quad"].astype(np.float32), destination)
        self.inverse = np.linalg.inv(self.homography)
        self.pad = self.width
        shift = np.array([[1, 0, self.pad], [0, 1, self.width/2], [0, 0, 1]], np.float64)
        self.extended = cv2.warpPerspective(gray, shift@self.homography,
            (self.length+2*self.pad, self.width*2), flags=cv2.INTER_LINEAR).astype(np.float32)
        self.valid = cv2.warpPerspective(np.ones_like(gray, np.uint8), shift@self.homography,
            (self.length+2*self.pad, self.width*2), flags=cv2.INTER_NEAREST).astype(bool)
        self.gx = cv2.Sobel(self.extended, cv2.CV_32F, 1, 0, ksize=3)/8
        self.gy = cv2.Sobel(self.extended, cv2.CV_32F, 0, 1, ksize=3)/8
        self.mag = np.hypot(self.gx, self.gy)
        self.gray = self.extended[self.width//2:self.width//2+self.width, self.pad:self.pad+self.length]
        noise = float(np.median(self.mag))
        mad = float(np.median(np.abs(self.mag-noise)))
        self.threshold = max(config["edge_derivative_floor"], noise+config["edge_noise_mad_multiplier"]*mad)

    def to_image(self, points):
        return cv2.perspectiveTransform(np.asarray(points, np.float32)[None], self.inverse)[0].tolist()

    def sample(self, data, points):
        points = np.asarray(points, np.float32)
        return cv2.remap(data, (points[:, 0]+self.pad)[:, None],
                         (points[:, 1]+self.width/2)[:, None], cv2.INTER_LINEAR).ravel()

    def cross_support(self):
        a = round(self.width*(.5+(1-self.config["cross_width_fraction"])/2))
        b = round(self.width*(1.5-(1-self.config["cross_width_fraction"])/2))
        return (np.abs(self.gx[a:b]) >= self.threshold).mean(axis=0)

    def cap(self, point, pitch):
        point = np.asarray(point, np.float32)
        radius = max(1, round(pitch*self.config["stud_search_pitch_fraction"]))
        shifts = np.asarray([(x, y) for y in range(-radius, radius+1) for x in range(-radius, radius+1)], np.float32)
        centers = point+shifts
        margin = max(2, round(pitch*.6))
        x, y = np.round(point+[self.pad, self.width/2]).astype(int)
        patch = self.extended[max(0, y-margin):y+margin+1, max(0, x-margin):x+margin+1]
        gradients = self.mag[max(0, y-margin):y+margin+1, max(0, x-margin):x+margin+1]
        if patch.size == 0:
            return 0.
        contrast = float(np.percentile(patch, 90)-np.percentile(patch, 10))
        observation = min(1., contrast/self.config["contrast_full_observability"])
        noise = max(float(np.median(gradients)), .5)
        theta = np.linspace(0, 2*np.pi, 32, endpoint=False)
        rays = np.column_stack((np.cos(theta), np.sin(theta)))
        best = 0.
        for fraction in self.config["stud_radius_pitch_fractions"]:
            samples = centers[:, None]+pitch*fraction*rays[None]
            gx = self.sample(self.gx, samples.reshape(-1, 2)).reshape(len(centers), -1)
            gy = self.sample(self.gy, samples.reshape(-1, 2)).reshape(len(centers), -1)
            radial = np.abs(gx*rays[None, :, 0]+gy*rays[None, :, 1])
            coherence = radial.sum(axis=1)/(np.hypot(gx, gy).sum(axis=1)+1e-6)
            signal = np.clip((coherence-2/np.pi)/(1-2/np.pi), 0, 1)
            score = signal*(radial > noise).mean(axis=1)*math.sqrt(observation)
            best = max(best, float(score.max()))
        return best

    def footprint(self, start, end, pitch):
        along = np.linspace(start+(end-start)*.1, end-(end-start)*.1, 40)
        sides = []
        for v in (0., self.width-1.):
            strengths = [np.abs(self.sample(self.gy, np.column_stack((along, np.full_like(along, v+offset)))))
                         for offset in (-1.5, 0, 1.5)]
            sides.append(float((np.max(strengths, axis=0) >= self.threshold).mean()))
        caps = [self.cap([start+(column+.5)*pitch, self.width*(row+.5)/2], pitch)
                for column in range(4) for row in range(2)]
        x0, x1 = max(0, round(start+self.pad)), min(self.extended.shape[1], round(end+self.pad)+1)
        region = self.extended[self.width//2:self.width//2+self.width, x0:x1]
        contrast = float(np.percentile(region, 90)-np.percentile(region, 10)) if region.size else 0.
        # A SAME common column must continue over the full fixed 2W cross-strip span.
        cx0 = max(0, round(start+(end-start)*.15+self.pad))
        cx1 = min(self.extended.shape[1], round(end-(end-start)*.15+self.pad)+1)
        continuation = float((np.abs(self.gx[:, cx0:cx1]) >= self.threshold).mean(axis=0).max()) if cx1 > cx0 else 0.
        valid = self.valid[self.width//2:self.width//2+self.width, x0:x1]
        return {"cap_scores": caps, "cap_count": sum(s >= self.config["stud_score_min"] for s in caps),
                "end_columns_supported": any(s >= self.config["stud_score_min"] for s in caps[:2]) and any(s >= self.config["stud_score_min"] for s in caps[-2:]),
                "side_support": sides, "contrast": contrast,
                "perpendicular_continuation": continuation,
                "valid_fraction": float(valid.mean()) if valid.size else 0.}


def phase_distance(a, b, period):
    return abs((a-b+period/2) % period-period/2)


def classify_slots(slots, selected, config):
    """Missing runs retain the chain's phase and use nearest bilateral anchors."""
    for slot in slots:
        evidence = slot["scores"]
        slot["decision"] = "uncertain"
        reasons = []
        if not selected:
            reasons.append("ambiguous_chain_phase")
        if slot["observed_fraction"] < config["minimum_slot_observed_fraction"]:
            reasons.append("partial_observed_window")
        if evidence["valid_fraction"] < config["minimum_slot_observed_fraction"]:
            reasons.append("image_crop_or_invalid_projection")
        lower = evidence["perpendicular_continuation"] >= config["perpendicular_continuation_min"]
        if lower:
            reasons.append("lower_perpendicular_compatible")
        same_ridge = (evidence["cap_count"] >= config["present_stud_count_min"]
            and evidence["end_columns_supported"] and min(evidence["side_support"]) >= config["present_side_support_min"])
        if selected and slot["observed_fraction"] >= config["minimum_slot_observed_fraction"] and evidence["valid_fraction"] >= config["minimum_slot_observed_fraction"] and same_ridge and not lower:
            slot["decision"] = "present"
            reasons.append("distributed_caps_and_same_ridge_sides")
        slot["reason_flags"] = reasons or ["insufficient_same_ridge_footprint_evidence"]
    present = [i for i, slot in enumerate(slots) if slot["decision"] == "present"]
    for index, slot in enumerate(slots):
        if slot["decision"] == "present":
            continue
        evidence = slot["scores"]
        left = [i for i in present if i < index]
        right = [i for i in present if i > index]
        absent = (evidence["cap_count"] <= config["missing_stud_count_max"]
            and max(evidence["side_support"]) <= config["missing_side_support_max"]
            and evidence["contrast"] >= config["missing_contrast_min"])
        if selected and left and right and absent and slot["observed_fraction"] >= config["minimum_slot_observed_fraction"] and evidence["valid_fraction"] >= config["minimum_slot_observed_fraction"]:
            slot["decision"] = "missing"
            slot["reason_flags"].append("observable_parallel_footprint_break_between_present_anchors")
            slot["missing_anchor_ids"] = [slots[max(left)]["id"], slots[min(right)]["id"]]
        elif not left or not right:
            slot["reason_flags"].append("no_bilateral_present_anchors_for_missing")


def solve_chain(proposal, strip, scale, config):
    pitch, period = float(scale["pitch_px"]), float(scale["pitch_px"])*4
    support = strip.cross_support()
    threshold = config["cross_line_support_min"]
    peaks = []
    active = np.flatnonzero(support >= threshold)
    for run in np.split(active, np.flatnonzero(np.diff(active) > 1)+1):
        if len(run):
            index = min(run.tolist(), key=lambda x: (-support[x], x))
            u = float(index-strip.pad)
            if -pitch*.25 <= u <= strip.length+pitch*.25:
                peaks.append({"u": u, "support": float(support[index]), "kind": "cross_line"})
    ends = []
    for name, target in (("start", 0.), ("end", float(strip.length-1))):
        possible = [p for p in peaks if abs(p["u"]-target) <= config["end_search_pitch_fraction"]*pitch]
        best = min(possible, key=lambda p: (-p["support"], abs(p["u"]-target))) if possible else None
        ends.append({"name": name, "status": "observed" if best else "unknown",
                     "u": best["u"] if best else target, "support": best["support"] if best else 0.})
        if best:
            best["kind"] = f"observed_{name}"
    span_start, span_end = ends[0]["u"], ends[1]["u"]
    span = span_end-span_start
    seed_phases = sorted(peaks, key=lambda p: (-p["support"], p["u"]))
    clusters = []
    for anchor in seed_phases:
        existing = [c for c in clusters if phase_distance(anchor["u"], c["phase"], period) <= config["phase_cluster_pitch_fraction"]*pitch]
        if existing:
            existing[0]["anchors"].append(anchor)
        else:
            clusters.append({"phase": anchor["u"] % period, "anchors": [anchor]})
    if not clusters:
        clusters = [{"phase": span_start % period, "anchors": []}]
    both_ends = all(end["status"] == "observed" for end in ends)
    nearest = round(span/period)
    counts = [n for n in (nearest-1, nearest, nearest+1) if 1 <= n <= config["maximum_observed_window_count"]]
    alternatives = []
    weights = config["objective_weights"]
    for cluster in clusters:
        phase = cluster["phase"]
        indices = range(math.floor((span_start-phase)/period), math.ceil((span_end-phase)/period))
        slots = []
        for index in indices:
            start, end = phase+index*period, phase+(index+1)*period
            fraction = max(0., min(end, span_end)-max(start, span_start))/period
            if fraction < .5:
                continue
            slots.append({"index": index, "start": start, "end": end,
                          "observed_fraction": fraction, "scores": strip.footprint(start, end, pitch)})
        cap_score = float(np.mean([s["scores"]["cap_count"]/8 for s in slots])) if slots else 0.
        side_score = float(np.mean([np.mean(s["scores"]["side_support"]) for s in slots])) if slots else 0.
        agreement = float(np.mean([max(0., 1-phase_distance(a["u"], phase, period)/(period*.2)) for a in peaks])) if peaks else 0.
        usable_anchor = any(a["kind"].startswith("observed_") for a in cluster["anchors"]) or len(cluster["anchors"]) >= 2
        score = weights["caps"]*cap_score+weights["sides"]*side_score+weights["anchors"]*agreement+weights["segment_endpoints"]*proposal["endpoint_fit"]
        for count in counts if both_ends else [len(slots)]:
            residual = abs(span/period-count) if both_ends else None
            end_residual = max(phase_distance(e["u"], phase, period)/period for e in ends if e["status"] == "observed") if any(e["status"] == "observed" for e in ends) else None
            valid_count = not both_ends or (residual <= config["integer_length_residual_max"] and end_residual <= config["integer_length_residual_max"])
            alternatives.append({"phase": phase, "count": count, "score": score,
                "cap_term": cap_score, "side_term": side_score, "anchor_term": agreement,
                "segment_endpoint_term": proposal["endpoint_fit"], "integer_length_residual": residual,
                "observed_end_phase_residual": end_residual, "usable_anchor": usable_anchor,
                "valid_count": valid_count, "anchor_ids": [p["u"] for p in cluster["anchors"]], "slots": slots})
    alternatives.sort(key=lambda a: (not (a["usable_anchor"] and a["valid_count"]), -a["score"], a["phase"], a["count"]))
    best = alternatives[0] if alternatives else None
    eligible = [a for a in alternatives if a["usable_anchor"] and a["valid_count"]]
    margin = eligible[0]["score"]-eligible[1]["score"] if len(eligible) > 1 else None
    selected = bool(eligible) and (margin is None or margin >= config["phase_margin_min"])
    identity = proposal["id"]
    boundaries, slots = [], []
    boundary_cache = {}
    if best:
        for offset, slot in enumerate(best["slots"]):
            boundary_ids = []
            for index, coordinate in ((slot["index"], slot["start"]), (slot["index"]+1, slot["end"])):
                if index not in boundary_cache:
                    nearby = [p for p in peaks if abs(p["u"]-coordinate) <= config["phase_cluster_pitch_fraction"]*pitch]
                    observed = min(nearby, key=lambda p: (-p["support"], abs(p["u"]-coordinate))) if nearby else None
                    evidence = observed["support"] if observed else 0.
                    observed_u = observed["u"] if observed else coordinate
                    boundary = {"id": f"{identity}_b{index}", "index": index, "coordinate_u": coordinate,
                                "line_xy": strip.to_image([[observed_u, 0], [observed_u, strip.width-1]]),
                                "model_line_xy": strip.to_image([[coordinate, 0], [coordinate, strip.width-1]]),
                                "observed_coordinate_u": observed_u if observed else None,
                                "provenance": "observed" if evidence >= threshold else "inferred",
                                "support": evidence}
                    boundary_cache[index] = boundary
                    boundaries.append(boundary)
                boundary_ids.append(boundary_cache[index]["id"])
            polygon = strip.to_image([[slot["start"], 0], [slot["end"], 0],
                                      [slot["end"], strip.width-1], [slot["start"], strip.width-1]])
            points = np.asarray(polygon)
            slots.append({"id": f"{identity}_s{offset:02d}", "parent_chain_id": identity,
                "index": slot["index"], "coordinate_u": [slot["start"], slot["end"]],
                "polygon": polygon, "box_xyxy": [*points.min(axis=0).tolist(), *points.max(axis=0).tolist()],
                "boundary_ids": boundary_ids, "scores": slot["scores"],
                "observed_fraction": slot["observed_fraction"], "layer": "unknown"})
    classify_slots(slots, selected, config)
    return {"id": identity, "polygon": proposal["quad"].tolist(), "axis_xy": proposal["axis"].tolist(),
        "proposal_segment_ids": proposal["segment_ids"], "surviving_segment_endpoints": proposal["side_segment_endpoints"],
        "all_segment_endpoint_fit": proposal["endpoint_fit"], "rectification_homography": strip.homography.tolist(),
        "endpoint_fit_semantics": "Perpendicular residual of ALL source side-segment endpoints to fitted sides; longitudinal count consistency is the separate integer/end residual",
        "scale": scale, "extent": {"start": ends[0], "end": ends[1], "observed_span_u": [span_start, span_end],
            "window_status": "bounded_current_window" if both_ends else "partial_open_window",
            "full_chain_count": None, "outside_current_span": "unknown; observed end is not proof of original extent"},
        "phase": {"status": "selected" if selected else "ambiguous", "unit_length_px": period,
                  "selected": best["phase"] if selected else None, "margin": margin,
                  "alternatives": [{k: v for k, v in a.items() if k != "slots"} for a in alternatives],
                  "reasons": [] if selected else ["insufficient_or_ambiguous_joint_phase_count_evidence"]},
        "boundaries": boundaries, "slots": slots}


def polygon_iou(a, b):
    area_a, area_b = abs(cv2.contourArea(a.astype(np.float32))), abs(cv2.contourArea(b.astype(np.float32)))
    intersection, _ = cv2.intersectConvexConvex(a.astype(np.float32), b.astype(np.float32))
    return float(intersection/max(area_a+area_b-intersection, 1e-9))


def mark_unlinked_windows(chains, image_shape, config):
    """Do not independently establish phase across an unbridged collinear gap."""
    distance_limit = config["merge_distance_side_fraction"]*min(image_shape)
    for i, first in enumerate(chains):
        for second in chains[:i]:
            a, b = np.asarray(first["axis_xy"]), np.asarray(second["axis_xy"])
            if abs(a@b) < math.cos(math.radians(config["pair_angle_degrees"])):
                continue
            normal = np.array([-a[1], a[0]])
            qa, qb = np.asarray(first["polygon"]), np.asarray(second["polygon"])
            if abs((qa.mean(axis=0)-qb.mean(axis=0))@normal) > distance_limit:
                continue
            ia, ib = qa@a, qb@a
            if min(ia.max(), ib.max()) >= max(ia.min(), ib.min()):
                continue
            for chain, other in ((first, second), (second, first)):
                chain.setdefault("unlinked_collinear_windows", []).append(other["id"])
                chain["phase"]["status"] = "ambiguous"
                chain["phase"]["selected"] = None
                chain["phase"]["reasons"].append("unbridged_collinear_window_global_phase_unknown")
                classify_slots(chain["slots"], False, config)


def analyze(image, config, image_name):
    gray = cv2.cvtColor(image, cv2.COLOR_BGR2GRAY)
    source_segments, groups = extract_lines(gray, config)
    proposals = ridge_proposals(groups, gray.shape, config)
    accepted, rejected, chains = [], [], []
    for proposal in proposals:
        strip = Strip(gray, proposal, config)
        scale = infer_pitch(strip.gray, config)
        if scale["status"] != "supported":
            rejected.append({"id": proposal["id"], "polygon": proposal["quad"].tolist(), "reasons": scale["reasons"], "scale": scale})
            continue
        duplicates = [p for p in accepted if polygon_iou(proposal["quad"], p["quad"]) >= config["proposal_duplicate_polygon_iou"]]
        if duplicates:
            rejected.append({"id": proposal["id"], "polygon": proposal["quad"].tolist(),
                             "reasons": ["duplicate_geometric_ridge_proposal"], "duplicate_of": duplicates[0]["id"], "scale": scale})
            continue
        accepted.append(proposal)
        chains.append(solve_chain(proposal, strip, scale, config))
    mark_unlinked_windows(chains, gray.shape, config)
    return {"image": image_name, "width": image.shape[1], "height": image.shape[0],
        "method": config["experiment"], "config": config, "source_segments": source_segments,
        "merged_lines": [{"id": group["id"], "points": group["points"].tolist(),
            "segment_ids": [s["id"] for s in group["segments"]], "joins": group["joins"],
            "status": "collinear_join" if group["joins"] else "single_surviving_segment_no_join"} for group in groups],
        "merged_line_count": len(groups), "geometric_proposal_count": len(proposals),
        "chains": chains, "rejected_proposals": rejected,
        "limitations": ["RGB projected ridge hypotheses; no calibrated pose, physical layer or accessibility claim.",
            "Stud/width aliases, perpendicular lower patterns and shadows can remain indistinguishable.",
            "Full original extent/count is unknown even when both current visible ends have edge support.",
            "Weak same-color seams are optional support; inferred boundaries are explicitly labeled."]}


def overlay(image, result):
    canvas = image.copy()
    colors = {"present": (40, 210, 40), "missing": (40, 40, 230), "uncertain": (0, 210, 240)}
    for chain in result["chains"]:
        for slot in chain["slots"]:
            points = np.rint(slot["polygon"]).astype(np.int32)
            color = colors[slot["decision"]]
            cv2.polylines(canvas, [points], True, color, 1)
            center = tuple(np.rint(points.mean(axis=0)).astype(int))
            cv2.putText(canvas, f"{slot['index']}:{slot['decision'][0]}", center, cv2.FONT_HERSHEY_SIMPLEX, .35, color, 1)
        for boundary in chain["boundaries"]:
            a, b = np.asarray(boundary["line_xy"])
            if boundary["provenance"] == "observed":
                cv2.line(canvas, tuple(np.rint(a).astype(int)), tuple(np.rint(b).astype(int)), (255, 180, 0), 1)
            else:
                for alpha in np.linspace(0, 1, 12):
                    cv2.circle(canvas, tuple(np.rint(a+alpha*(b-a)).astype(int)), 1, (220, 0, 220), -1)
    return canvas


def self_test(config):
    # Pure tiny contracts, including a two-slot gap and fixed coordinates/phase.
    good = {"cap_count": 8, "end_columns_supported": True, "side_support": [.9, .9],
            "contrast": 30., "perpendicular_continuation": .1, "valid_fraction": 1.}
    gap = {**good, "cap_count": 0, "end_columns_supported": False,
           "side_support": [.05, .05], "perpendicular_continuation": .9}
    slots = [{"id": f"s{i}", "index": i, "coordinate_u": [i*40, (i+1)*40],
              "scores": dict(good if i in (0, 3) else gap), "observed_fraction": 1.} for i in range(4)]
    before = [s["coordinate_u"][:] for s in slots]
    classify_slots(slots, True, config)
    assert [s["decision"] for s in slots] == ["present", "missing", "missing", "present"]
    assert [s["coordinate_u"] for s in slots] == before
    assert slots[1]["missing_anchor_ids"] == ["s0", "s3"]
    classify_slots(slots, False, config)
    assert all(s["decision"] == "uncertain" for s in slots)
    lower = [{"id": "l", "scores": {**good, "perpendicular_continuation": .9}, "observed_fraction": 1.}]
    classify_slots(lower, True, config)
    assert lower[0]["decision"] == "uncertain"
    assert infer_pitch(np.zeros((20, 80), np.uint8), config)["status"] == "ambiguous"
    harmonic = np.tile((100+40*np.cos(np.arange(160)*2*np.pi/10)).astype(np.uint8), (40, 1))
    assert "half_pitch_alias" in infer_pitch(harmonic, config)["reasons"]
    assert phase_distance(2, 82, 40) == 0
    # Near-vertical undirected sides must not average into a horizontal axis.
    groups = []
    for index, points in enumerate(([[39.9, 0], [40.1, 100]], [[19.9, 100], [20.1, 0]])):
        group = fit_group([{"id": str(index), "points": points, "length": 100.}])
        group["id"] = str(index)
        groups.append(group)
    proposals = ridge_proposals(groups, (200, 200), config)
    assert proposals and abs(proposals[0]["axis"][1]) > .99
    assert np.isfinite(proposals[0]["quad"]).all()
    # Two disconnected collinear windows do not become independent certain phases.
    windows = []
    for index, start in enumerate((0, 100)):
        windows.append({"id": str(index), "axis_xy": [1., 0.],
            "polygon": [[start, 0], [start+40, 0], [start+40, 10], [start, 10]],
            "phase": {"status": "selected", "selected": 0., "reasons": []}, "slots": []})
    mark_unlinked_windows(windows, (200, 200), config)
    assert all(w["phase"]["status"] == "ambiguous" for w in windows)
    assert not analyze(np.zeros((64, 64, 3), np.uint8), config, "tiny.png")["chains"]
    print("ridge tiny contracts passed")


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--config", type=Path, default=Path(__file__).with_name("config.json"))
    parser.add_argument("--image", type=Path)
    parser.add_argument("--output", type=Path)
    parser.add_argument("--self-test", action="store_true")
    args = parser.parse_args()
    config = json.loads(args.config.read_text())
    cv2.setNumThreads(2)
    if args.self_test:
        self_test(config)
        return
    if os.environ.get("ROBO_PUEUE_JOB") != "1":
        parser.error("Image processing must run in the frozen default Pueue queue job")
    if args.image is None or args.output is None:
        parser.error("--image and --output required")
    image = cv2.imread(str(args.image))
    if image is None:
        raise ValueError("Could not decode input RGB image")
    result = analyze(image, config, args.image.name)
    args.output.mkdir(parents=True, exist_ok=True)
    save_json(args.output/"chains.json", result)
    if not cv2.imwrite(str(args.output/"overlay.png"), overlay(image, result)):
        raise OSError("Overlay write failed")
    counts = {decision: sum(s["decision"] == decision for c in result["chains"] for s in c["slots"])
              for decision in ("present", "missing", "uncertain")}
    print(json.dumps({"image": args.image.name, "chains": len(result["chains"]), "slots": counts}), flush=True)


if __name__ == "__main__":
    main()
