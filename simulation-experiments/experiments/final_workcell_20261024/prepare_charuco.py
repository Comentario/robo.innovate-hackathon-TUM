"""Queued ChArUco asset generation and bounded photo09 correspondence audit."""
import argparse
import hashlib
import json
import os
from pathlib import Path

import cv2
import numpy as np


def sha(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def fit_xy(source, target):
    source, target = np.asarray(source), np.asarray(target)
    pc, qc = source-source.mean(axis=0), target-target.mean(axis=0)
    u, _, vt = np.linalg.svd(pc.T@qc)
    rotation = vt.T@u.T
    if np.linalg.det(rotation) < 0:
        vt[-1] *= -1
        rotation = vt.T@u.T
    rigid = pc@rotation.T
    scale = float(np.sum(qc*rigid)/np.sum(pc*pc))
    return {"yaw_deg": float(np.degrees(np.arctan2(rotation[1, 0], rotation[0, 0])) % 360),
            "rotation_board_to_table_xy": rotation.tolist(),
            "translation_board_center_table_xy_m": (target.mean(axis=0)-source.mean(axis=0)@rotation.T).tolist(),
            "rigid_rms_m": float(np.sqrt(np.mean(np.sum((rigid-qc)**2, axis=1)))),
            "diagnostic_similarity_scale": scale,
            "diagnostic_similarity_rms_m": float(np.sqrt(np.mean(np.sum((scale*rigid-qc)**2, axis=1))))}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--spec", type=Path, required=True)
    parser.add_argument("--photo", type=Path, required=True)
    parser.add_argument("--layout", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    if os.environ.get("ROBO_PUEUE_JOB") != "1":
        raise RuntimeError("Board generation and image detection must use default Pueue")
    spec = json.loads(args.spec.read_text())
    dictionary = cv2.aruco.getPredefinedDictionary(getattr(cv2.aruco, spec["dictionary"]))
    board = cv2.aruco.CharucoBoard(tuple(spec["squares_xy"]), spec["square_length_m"], spec["marker_length_m"], dictionary)
    ids = board.getIds().ravel().tolist()
    if ids != spec["marker_ids"] or len(board.getChessboardCorners()) != spec["expected_charuco_corners"]:
        raise ValueError("OpenCV board does not match the user-specified IDs/corner count")
    args.output.mkdir(parents=True, exist_ok=True)
    ideal = board.generateImage(tuple(spec["image_size_wh"]), marginSize=spec["margin_pixels"], borderBits=spec["border_bits"])
    detector = cv2.aruco.CharucoDetector(board)
    ideal_corners, ideal_ids, _, ideal_markers = detector.detectBoard(ideal)
    if ideal_ids is None or len(ideal_ids) != spec["expected_charuco_corners"] or ideal_markers is None or sorted(ideal_markers.ravel().tolist()) != sorted(ids):
        raise RuntimeError("Ideal board self-detection failed the exact24corner/17marker contract")
    asset = args.output/"charuco_7x5_4x4_50.png"
    if not cv2.imwrite(str(asset), ideal):
        raise RuntimeError("Could not write generated board asset")
    photo = cv2.imread(str(args.photo))
    if photo is None:
        raise ValueError("Missing frozen original photo")
    charuco, charuco_ids, corners, marker_ids = detector.detectBoard(photo)
    detected = [] if marker_ids is None else marker_ids.ravel().tolist()
    by_id = dict(zip(ids, board.getObjPoints()))
    h = np.asarray(json.loads(args.layout.read_text())["nominal_image_to_table_homography"], np.float64)
    records, object_points, table_points = [], [], []
    for identity, pixel in zip(detected, corners):
        if identity not in by_id:
            continue
        # OpenCV board points: +Y down. Desired printed frame: +Y up, centered.
        metric = np.asarray(by_id[identity])[:, :2].astype(np.float64)
        metric[:, 1] = spec["pattern_size_m"][1]-metric[:, 1]
        metric -= np.asarray(spec["pattern_size_m"])/2
        pixel = np.asarray(pixel).reshape(4, 2)
        table = cv2.perspectiveTransform(pixel.astype(np.float64)[None], h)[0]
        record = {"id": identity, "ordered_pixel_corners_xy": pixel.tolist(),
                  "metric_board_corners_xy_m": metric.tolist(), "approximate_table_corners_xy_m": table.tolist(),
                  "per_marker_fit": fit_xy(metric, table)}
        records.append(record)
        object_points.extend(metric)
        table_points.extend(table)
    global_fit = fit_xy(object_points, table_points) if len(records) >= 2 else None
    resolved, disagreements = False, []
    if global_fit is not None:
        yaw = global_fit["yaw_deg"]
        disagreements = [abs((record["per_marker_fit"]["yaw_deg"]-yaw+180) % 360-180) for record in records]
        resolved = len({record["id"] for record in records}) >= spec["minimum_matched_markers_for_orientation"] and max(disagreements) <= spec["maximum_per_marker_rotation_disagreement_deg"]
        global_fit.update(nearest_quarter_turn_deg=int(np.floor(yaw/90+.5)) % 4*90,
                          per_marker_disagreement_deg=disagreements,
                          orientation_status="resolved" if resolved else "unresolved")
    annotated = photo.copy()
    if marker_ids is not None:
        cv2.aruco.drawDetectedMarkers(annotated, corners, marker_ids)
    if charuco_ids is not None:
        cv2.aruco.drawDetectedCornersCharuco(annotated, charuco, charuco_ids)
    if not cv2.imwrite(str(args.output/"photo09_charuco_detection.png"), annotated):
        raise RuntimeError("Could not write photo detection overlay")
    result = {"schema": "bounded-charuco-asset-check-v1", "spec": spec,
              "ideal": {"board_marker_ids": ids, "detected_marker_ids": ideal_markers.ravel().tolist(), "charuco_ids": ideal_ids.ravel().tolist(),
                        "charuco_corners_pixel_xy": ideal_corners.reshape(-1, 2).tolist(),
                        "charuco_board_corner_ids": list(range(spec["expected_charuco_corners"])),
                        "charuco_corners_opencv_board_m": board.getChessboardCorners().tolist(),
                        "marker_corners_opencv_board_m": [point.tolist() for point in board.getObjPoints()]},
              "photo": {"processed_once": True, "original_image_wh": list(photo.shape[1::-1]),
                        "detected_ids": detected, "unexpected_ids": sorted(set(detected)-set(ids)),
                        "charuco_count": 0 if charuco_ids is None else len(charuco_ids),
                        "matched_markers": len(records), "ordered_correspondences": records,
                        "orientation_status": "resolved" if resolved else "unresolved", "fit": global_fit},
              "provenance": {"opencv": cv2.__version__, "numpy": np.__version__, "source_sha256": sha(Path(__file__)),
                             "spec_sha256": sha(args.spec), "photo_sha256": sha(args.photo), "layout_sha256": sha(args.layout),
                             "generated_png_sha256": sha(asset)}, "limitations": spec["limitations"]}
    (args.output/"board_audit.json").write_text(json.dumps(result, indent=2, allow_nan=False)+"\n")
    print(json.dumps({"ideal_markers": len(ideal_markers), "ideal_corners": len(ideal_ids),
                      "photo_markers": len(records), "orientation_status": result["photo"]["orientation_status"], "fit": global_fit}))


if __name__ == "__main__":
    main()
