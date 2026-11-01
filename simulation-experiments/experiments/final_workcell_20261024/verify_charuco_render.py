"""Queued rendered-texture correspondence check; no camera calibration."""
import argparse
import hashlib
import json
import os
from pathlib import Path

import cv2
import numpy as np


def rotation(quaternion):
    w, x, y, z = np.asarray(quaternion)/np.linalg.norm(quaternion)
    return np.array([[1-2*(y*y+z*z), 2*(x*y-z*w), 2*(x*z+y*w)],
                     [2*(x*y+z*w), 1-2*(x*x+z*z), 2*(y*z-x*w)],
                     [2*(x*z-y*w), 2*(y*z+x*w), 1-2*(x*x+y*y)]])


def project(world, camera):
    # Actual camera quaternion is OpenGL: right, up, backward.
    optical = (world-np.asarray(camera["actual_eye_world_m"]))@rotation(camera["actual_quaternion_wxyz_opengl"])
    optical *= [1, -1, -1]
    pixels = optical@np.asarray(camera["intrinsics"]).T
    return pixels[:, :2]/pixels[:, 2:3]


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    for name in ("asset-audit", "cameras", "images", "output"):
        parser.add_argument("--"+name, type=Path, required=True)
    parser.add_argument("--center", type=float, nargs=3, default=[.4, -.42, .00045])
    parser.add_argument("--yaw-deg", type=float, default=0.)
    args = parser.parse_args()
    if os.environ.get("ROBO_PUEUE_JOB") != "1":
        raise RuntimeError("Rendered image detection must use default Pueue")
    audit = json.loads(args.asset_audit.read_text()); spec = audit["spec"]
    objects = dict(zip(audit["ideal"]["board_marker_ids"], audit["ideal"]["marker_corners_opencv_board_m"]))
    detector = cv2.aruco.ArucoDetector(cv2.aruco.getPredefinedDictionary(getattr(cv2.aruco, spec["dictionary"])))
    yaw = np.radians(args.yaw_deg)
    turn = np.array([[np.cos(yaw), -np.sin(yaw)], [np.sin(yaw), np.cos(yaw)]])
    rows = []
    for camera in json.loads(args.cameras.read_text()):
        path = args.images/(camera["id"]+".png")
        image = cv2.imread(str(path))
        if image is None:
            raise ValueError(f"Missing saved diagnostic image: {path}")
        corners, ids, _ = detector.detectMarkers(image)
        detected = [] if ids is None else ids.ravel().tolist()
        errors = {name: [] for name in ("normal", "Y_mirrored", "rotated_180")}
        markers = []
        for identity, observed in zip(detected, corners):
            if identity not in objects:
                continue
            xy = np.asarray(objects[identity])[:, :2].copy()
            xy[:, 1] = spec["pattern_size_m"][1]-xy[:, 1]
            xy -= np.asarray(spec["pattern_size_m"])/2
            record = {"id": identity, "observed_ordered_corners_xy": observed.reshape(4, 2).tolist(), "hypotheses": {}}
            for name, sign in (("normal", [1, 1]), ("Y_mirrored", [1, -1]), ("rotated_180", [-1, -1])):
                world = np.column_stack(((xy*sign)@turn.T, np.zeros(4)))+args.center
                expected = project(world, camera)
                squared = np.sum((observed.reshape(4, 2)-expected)**2, axis=1)
                errors[name].extend(squared.tolist())
                record["hypotheses"][name] = {"expected_ordered_corners_xy": expected.tolist(), "rms_px": float(np.sqrt(np.mean(squared)))}
            markers.append(record)
        rms = {name: float(np.sqrt(np.mean(values))) if values else None for name, values in errors.items()}
        enough = len({record["id"] for record in markers}) >= 2
        rows.append({"view": camera["id"], "image_sha256": hashlib.sha256(path.read_bytes()).hexdigest(),
                     "detected_ids": detected, "matched_markers": len(markers), "ordered_corner_checks": markers,
                     "rms_px": rms, "minimum_error_hypothesis": min(rms, key=rms.get) if enough else None,
                     "status": "conditional_correspondence_check_available" if enough else "unverified_insufficient_decoded_ids"})
    result = {"schema": "rendered-charuco-uv-check-v1", "configured_center_table_m": args.center,
              "configured_yaw_deg": args.yaw_deg, "views": rows,
              "asset_png_sha256": audit["provenance"]["generated_png_sha256"],
              "source_sha256": hashlib.sha256(Path(__file__).read_bytes()).hexdigest(),
              "asset_audit_sha256": hashlib.sha256(args.asset_audit.read_bytes()).hexdigest(),
              "cameras_sha256": hashlib.sha256(args.cameras.read_bytes()).hexdigest(),
              "interpretation": "Conditional decoded-ID ordered-corner check of saved render against configured asset geometry. No detector tuning, layout fitting, scale change or physical camera calibration; low-resolution non-decoding remains unverified."}
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(result, indent=2, allow_nan=False)+"\n")
    print(json.dumps([{key: row[key] for key in ("view", "matched_markers", "rms_px", "minimum_error_hypothesis", "status")} for row in rows]))


if __name__ == "__main__":
    main()
