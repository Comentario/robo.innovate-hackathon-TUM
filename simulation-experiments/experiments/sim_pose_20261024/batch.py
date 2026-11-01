"""Truth-blind RGB stud-supported upright four-DOF pose experiment.

Inputs: original rendered RGB, public lattice design and nominal camera setup,
plus the frozen existing Evidence implementation. No depth, annotations, asset
states or actual camera records are opened. All full-image work uses Pueue.
"""

import argparse
import hashlib
import importlib.util
import json
import math
import os
from pathlib import Path
import time

import cv2
import numpy as np
import scipy
from scipy.optimize import least_squares

PITCH = .008
HEIGHT = .0096
PLATE = .0032
STUD_HEIGHT = .0017


def write_json(path, value):
    Path(path).write_text(json.dumps(value, indent=2, allow_nan=False)+"\n")


def sha256(path):
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def load_evidence(inputs):
    path = inputs/"upstream/evidence.py"
    spec = importlib.util.spec_from_file_location("frozen_pose_evidence", path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module.Evidence


def transform_local(points, pose):
    x, y, z, yaw = pose
    c, s = math.cos(yaw), math.sin(yaw)
    rotation = np.array([[c, -s, 0], [s, c, 0], [0, 0, 1]], np.float64)
    return np.asarray(points)@rotation.T+np.array([x, y, z])


def project_world(points, calibration):
    camera = np.asarray(points)@calibration["R"].T+calibration["t"]
    homogeneous = camera@calibration["K"].T
    return homogeneous[:, :2]/homogeneous[:, 2:3]


def project_local(points, pose, calibration):
    return project_world(transform_local(points, pose), calibration)


def brick_corners():
    return np.array([[-2*PITCH, -PITCH, HEIGHT], [2*PITCH, -PITCH, HEIGHT],
                     [2*PITCH, PITCH, HEIGHT], [-2*PITCH, PITCH, HEIGHT]])


def stud_model():
    return np.array([[(i-1.5)*PITCH, (j-.5)*PITCH, HEIGHT+STUD_HEIGHT]
                     for i in range(4) for j in range(2)], np.float64)


def pose_record(pose):
    return {"position_world_m": [float(v) for v in pose[:3]], "yaw_rad": float(pose[3]),
            "roll_rad": 0., "pitch_rad": 0.}


def candidate_priors(geometry, condition, config):
    source = np.asarray(geometry["source_xy_m"], np.float64)
    yaw_delta = math.radians(condition["yaw_deg"])
    c, s = math.cos(yaw_delta), math.sin(yaw_delta)
    rotation = np.array([[c, -s], [s, c]])
    for layer in config["candidate_layers"]:
        yaw_quarter = geometry["layer_yaws_quarter_turn"][layer]
        nx, ny = geometry["world_axis_counts_by_yaw_quarter_turn"][str(yaw_quarter)]
        footprint = (4, 2) if yaw_quarter == 0 else (2, 4)
        origin = geometry["layer_origins_studs_xy"][layer]
        for i in range(nx):
            for j in range(ny):
                xy_studs = np.array([geometry["border_studs"]+origin[0]+4*i+footprint[0]/2,
                                     geometry["border_studs"]+origin[1]+4*j+footprint[1]/2])
                xy = source+(xy_studs-geometry["baseplate_studs"]/2)*PITCH
                xy = source+rotation@(xy-source)+np.asarray(condition["translation_xy_m"])
                yield {"id": f"prior_l{layer:02d}_u{i:02d}_v{j:02d}", "layer": layer,
                    "pose": np.array([*xy, PLATE+layer*HEIGHT, yaw_quarter*np.pi/2+yaw_delta])}


def rectify(gray, layer, geometry, calibration, config, Evidence):
    pps = config["evidence"]["pixels_per_stud"]
    scale = pps/PITCH
    lower = np.asarray(geometry["source_xy_m"])-geometry["baseplate_studs"]*PITCH/2
    world_to_chart = np.array([[scale, 0, pps-lower[0]*scale],
                              [0, scale, pps-lower[1]*scale], [0, 0, 1]], np.float64)
    z = PLATE+(layer+1)*HEIGHT+STUD_HEIGHT
    R, t, K = calibration["R"], calibration["t"], calibration["K"]
    world_to_image = K@np.column_stack((R[:, 0], R[:, 1], R[:, 2]*z+t))
    image_to_chart = world_to_chart@np.linalg.inv(world_to_image)
    size = (geometry["baseplate_studs"]+2)*pps
    rectified = cv2.warpPerspective(gray, image_to_chart, (size, size))
    return Evidence(rectified, config["evidence"]), world_to_chart, np.linalg.inv(image_to_chart)


def fit_pose(local, observed, prior, calibration, geometry, config):
    yaw_bound = math.radians(config["yaw_correction_bound_deg"])
    xy_bound = config["xy_correction_bound_m"]
    z_bound = config["z_correction_bound_heights"]*HEIGHT
    lower = [prior[0]-xy_bound, prior[1]-xy_bound, max(0., prior[2]-z_bound), prior[3]-yaw_bound]
    upper = [prior[0]+xy_bound, prior[1]+xy_bound,
             min(PLATE+geometry["layers"]*HEIGHT, prior[2]+z_bound), prior[3]+yaw_bound]

    def residual(pose):
        return (project_local(local, pose, calibration)-observed).ravel()

    result = least_squares(residual, prior, bounds=(lower, upper), loss="soft_l1",
        f_scale=config["fit_loss_scale_px"], max_nfev=config["fit_max_evaluations"],
        x_scale=np.array([.001, .001, .01, .02]))
    errors = residual(result.x).reshape(-1, 2)
    rms = float(np.sqrt(np.mean(np.sum(errors**2, axis=1))))
    columns = []
    for axis, step in enumerate(config["jacobian_steps"]):
        shift = np.zeros(4); shift[axis] = step
        columns.append((residual(result.x+shift)-residual(result.x-shift))/(2*step))
    jacobian = np.column_stack(columns)
    rank = int(np.linalg.matrix_rank(jacobian))
    variance = max(config["pixel_noise_floor_px"]**2,
                   float(np.sum(errors**2)/max(1, 2*len(local)-4)))
    covariance = variance*np.linalg.pinv(jacobian.T@jacobian)
    std = np.sqrt(np.maximum(0., np.diag(covariance)))
    roots = PLATE+np.arange(geometry["layers"])*HEIGHT
    layer = int(np.argmin(np.abs(roots-result.x[2])))
    layer_error = float(abs(roots[layer]-result.x[2]))
    reasons = []
    if not result.success:
        reasons.append("optimizer_not_converged")
    if np.any(result.active_mask):
        reasons.append("optimizer_active_bound")
    if rms > config["fit_max_rms_px"]:
        reasons.append("excessive_image_reprojection_error")
    if rank < 4 or not np.isfinite(std).all():
        reasons.append("singular_pose_conditioning")
    if float(np.linalg.norm(std[:2])) > config["maximum_xy_std_m"]:
        reasons.append("xy_uncertainty_too_large")
    if std[2] > config["maximum_z_std_height_fraction"]*HEIGHT:
        reasons.append("height_uncertainty_too_large")
    if std[3] > math.radians(config["maximum_yaw_std_deg"]):
        reasons.append("yaw_uncertainty_too_large")
    if layer_error > config["maximum_layer_residual_height_fraction"]*HEIGHT:
        reasons.append("between_nominal_layers")
    return result.x, layer, reasons, {
        "rms_px": rms, "observed_studs": len(local), "evaluations": int(result.nfev),
        "optimizer_success": bool(result.success), "active_bounds": result.active_mask.tolist(),
        "correction_xyz_m": (result.x[:3]-prior[:3]).tolist(),
        "correction_yaw_rad": float(result.x[3]-prior[3]), "nearest_layer_residual_m": layer_error,
        "bounds": {"lower": lower, "upper": upper}}, {
        "std_xyz_m": std[:3].tolist(), "std_yaw_rad": float(std[3]), "jacobian_rank": rank,
        "pixel_noise_variance": variance, "covariance_xyzyaw": covariance.tolist(),
        "interpretation": "Local one-pixel-floor image-fit conditioning only; calibration/prior/model error excluded"}


def analyze(image, geometry, calibration, condition, config, Evidence, image_name):
    gray = cv2.cvtColor(image, cv2.COLOR_BGR2GRAY)
    planes = {layer: rectify(gray, layer, geometry, calibration, config, Evidence)
              for layer in config["candidate_layers"]}
    model, corners = stud_model(), brick_corners()
    candidates = []
    for candidate in candidate_priors(geometry, condition, config):
        prior, layer = candidate["pose"], candidate["layer"]
        evidence, world_to_chart, chart_to_image = planes[layer]
        world_studs = transform_local(model, prior)
        chart_homogeneous = np.column_stack((world_studs[:, :2], np.ones(8)))@world_to_chart.T
        chart_points = chart_homogeneous[:, :2]
        observations = [evidence.stud(point) for point in chart_points]
        confirmed = [i for i, observation in enumerate(observations) if observation["score"] >= config["stud_confirm_score"]]
        prior_polygon = project_local(corners, prior, calibration)
        # Transform the projected BODY face into the stud-plane chart; their Zs differ.
        image_to_chart = np.linalg.inv(chart_to_image)
        edge_polygon = cv2.perspectiveTransform(prior_polygon.astype(np.float32)[None], image_to_chart)[0]
        _, side_scores = evidence.edges(edge_polygon)
        edge_score = float(.4*side_scores[0]+.1*side_scores[1]+.4*side_scores[2]+.1*side_scores[3])
        mean_score = float(np.mean([o["score"] for o in observations]))
        observability = float(np.mean([o["observability"] for o in observations]))
        reasons = []
        if len(confirmed) < config["minimum_confirmed_studs"]:
            reasons.append("insufficient_confirmed_studs")
        if not (set(confirmed)&{0, 1} and set(confirmed)&{6, 7}):
            reasons.append("studs_not_distributed_across_both_long_ends")
        if mean_score < config["minimum_mean_stud_score"]:
            reasons.append("weak_mean_stud_evidence")
        if observability < config["minimum_observability"]:
            reasons.append("poor_observability")
        if edge_score < config["minimum_edge_score"]:
            reasons.append("weak_brick_edge_evidence")
        observed_chart = np.asarray([o["refined_xy"] for o in observations], np.float32)
        observed_pixels = cv2.perspectiveTransform(observed_chart[None], chart_to_image)[0]
        record = {"id": candidate["id"], "prior_layer": layer, "prior_pose": pose_record(prior),
            "prior_polygon": prior_polygon.tolist(), "polygon": prior_polygon.tolist(), "polygon_source": "prior",
            "pose_estimate": None, "estimated_layer": None, "decision": "uncertain", "selected_top": False,
            "reason_flags": reasons, "fit": None, "uncertainty": None,
            "evidence": {"confirmed_studs": len(confirmed), "mean_stud_score": mean_score,
                "observability": observability, "edge_score": edge_score, "edge_scores": side_scores},
            "stud_observations": [{"index": i, "local_xyz_m": model[i].tolist(),
                "expected_pixel": project_local(model[i:i+1], prior, calibration)[0].tolist(),
                "observed_pixel": observed_pixels[i].tolist(), "score": float(o["score"]),
                "observability": float(o["observability"]), "used_for_fit": i in confirmed and not reasons}
                for i, o in enumerate(observations)],
            "physical_exposure": "unverified", "gripper_accessibility": "unverified"}
        if not reasons:
            pose, fitted_layer, fit_reasons, fit, uncertainty = fit_pose(model[confirmed],
                observed_pixels[confirmed], prior, calibration, geometry, config)
            record.update(pose_estimate=pose_record(pose), estimated_layer=fitted_layer, fit=fit,
                          uncertainty=uncertainty, polygon=project_local(corners, pose, calibration).tolist(),
                          polygon_source="image_fitted", reason_flags=fit_reasons)
            if not fit_reasons:
                record["decision"] = "supported"
                record["selected_top"] = fitted_layer == geometry["layers"]-1
        candidates.append(record)
    return {"image": image_name, "condition": condition["id"], "width": image.shape[1], "height": image.shape[0],
        "pose_origin": "brick_body_bottom_center", "pose_frame": "world_robot_base",
        "estimated_dofs": ["x", "y", "z", "yaw"], "roll_pitch": "fixed upright prior",
        "candidates": candidates, "nms": False,
        "limitations": ["Known-layout and nominal-camera-assisted top/immediately-lower search, not arbitrary detection.",
            "Continuous Z is image fitted; estimated layer is a separate proximity test, never a pose snap.",
            "Physical exposure/reachability and calibrated placement accuracy are unverified.",
            "Nominal priors are nearly exact for the design scene; evaluate prior and fitted poses separately."]}


def overlay(image, result):
    canvas = image.copy()
    for candidate in result["candidates"]:
        if candidate["evidence"]["confirmed_studs"] < 3:
            continue
        color = (0, 220, 0) if candidate["selected_top"] else (220, 120, 0) if candidate["decision"] == "supported" else (0, 210, 240)
        polygon = np.rint(candidate["polygon"]).astype(np.int32)
        cv2.polylines(canvas, [polygon], True, color, 1)
        center = tuple(np.rint(polygon.mean(axis=0)).astype(int))
        cv2.putText(canvas, f"L{candidate['prior_layer']}->{candidate['estimated_layer']}", center,
                    cv2.FONT_HERSHEY_SIMPLEX, .3, color, 1)
        for observation in candidate["stud_observations"]:
            if observation["used_for_fit"]:
                cv2.circle(canvas, tuple(np.rint(observation["observed_pixel"]).astype(int)), 2, color, 1)
    return canvas


def self_test():
    # Numerical image-fit contract only, not another rendered experiment.
    config = json.loads(Path(__file__).with_name("config.json").read_text())
    calibration = {"K": np.array([[900., 0, 640], [0, 900., 360], [0, 0, 1]]),
        "R": np.diag([1., -1., -1.]), "t": np.array([0., 0., .45])}
    actual = np.array([.01, .02, PLATE+9*HEIGHT, .1])
    prior = actual+np.array([.0008, -.0006, 0, math.radians(.3)])
    observations = project_local(stud_model(), actual, calibration)
    fitted, _, reasons, _, uncertainty = fit_pose(stud_model(), observations, prior, calibration, {"layers": 10}, config)
    assert np.linalg.norm(fitted[:3]-actual[:3]) < 1e-6 and abs(fitted[3]-actual[3]) < 1e-5
    assert "height_uncertainty_too_large" in reasons and uncertainty["jacobian_rank"] == 4
    # A mathematically recovered pose can still be too weakly conditioned at a
    # one-pixel noise floor. A closer synthetic observation passes the same gate.
    calibration["t"][2] = .30
    observations = project_local(stud_model(), actual, calibration)
    fitted, _, reasons, _, _ = fit_pose(stud_model(), observations, prior, calibration, {"layers": 10}, config)
    assert np.linalg.norm(fitted[:3]-actual[:3]) < 1e-6 and not reasons
    print("upright image-fit tiny contract passed")


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--inputs", type=Path)
    parser.add_argument("--output", type=Path)
    parser.add_argument("--config", type=Path, default=Path(__file__).with_name("config.json"))
    parser.add_argument("--self-test", action="store_true")
    args = parser.parse_args()
    cv2.setNumThreads(2)
    if args.self_test:
        self_test(); return
    if os.environ.get("ROBO_PUEUE_JOB") != "1":
        parser.error("Full-image processing must use the frozen default Pueue queue")
    if args.inputs is None or args.output is None:
        parser.error("--inputs and --output required")
    started = time.monotonic()
    config = json.loads(args.config.read_text())
    geometry = json.loads((args.inputs/"geometry.json").read_text())
    package = json.loads((args.inputs/"calibration.json").read_text())
    Evidence = load_evidence(args.inputs)
    args.output.mkdir(parents=True, exist_ok=True)
    cases = []
    for condition in config["conditions"]:
        for view_id, nominal in package["views"].items():
            case_started = time.monotonic()
            path = args.inputs/"images"/f"{view_id}.png"
            image = cv2.imread(str(path))
            if image is None:
                raise ValueError(f"Could not decode RGB {path}")
            if condition["blank"]:
                mean_rgb = np.rint(image.mean(axis=(0, 1))).astype(np.uint8)
                image = np.broadcast_to(mean_rgb, image.shape).copy()
            calibration = {"K": np.asarray(package["K"], np.float64),
                "R": np.asarray(nominal["R_world_to_camera"], np.float64),
                "t": np.asarray(nominal["t_world_to_camera_m"], np.float64)}
            result = analyze(image, geometry, calibration, condition, config, Evidence, path.name)
            folder = args.output/condition["id"]/view_id
            folder.mkdir(parents=True, exist_ok=True)
            write_json(folder/"predictions.json", result)
            if not cv2.imwrite(str(folder/"overlay.png"), overlay(image, result)):
                raise OSError("Overlay write failed")
            counts = {"supported": sum(c["decision"] == "supported" for c in result["candidates"]),
                      "selected_top": sum(c["selected_top"] for c in result["candidates"]),
                      "fitted": sum(c["pose_estimate"] is not None for c in result["candidates"])}
            if condition["blank"] and (counts["supported"] or counts["fitted"]):
                raise RuntimeError("Flat control unexpectedly produced a pose fit")
            cases.append({"condition": condition["id"], "view": view_id, "counts": counts,
                          "seconds": time.monotonic()-case_started})
            print("POSE_CASE", json.dumps(cases[-1]), flush=True)
    write_json(args.output/"runtime.json", {"seconds": time.monotonic()-started, "cases": cases,
        "versions": {"opencv": cv2.__version__, "numpy": np.__version__, "scipy": scipy.__version__},
        "input_hashes": {"geometry": sha256(args.inputs/"geometry.json"), "calibration": sha256(args.inputs/"calibration.json"),
            "config": sha256(args.config), "evidence_source": sha256(args.inputs/"upstream/evidence.py")}})
    write_json(args.output/"run_complete.json", {"completed": True, "cases": len(cases), "conditions": len(config["conditions"])})


if __name__ == "__main__":
    main()
