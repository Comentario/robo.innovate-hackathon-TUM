"""Invoked inside a Pueue snapshot by submit.py. Never launch compute directly."""
import argparse
import json
from pathlib import Path
import sys
import os
import glob

ROOT = Path(__file__).resolve().parents[1]
if os.environ.get("ROBO_PUEUE_JOB") != "1":
    raise SystemExit("Submit hardware jobs with python3 scripts/submit.py (default Pueue queue).")
sys.path.insert(0, str(ROOT))
from challenge2.layout import load_config

parser = argparse.ArgumentParser()
parser.add_argument("--config", default=str(ROOT / "configs/workcell.json"))
parser.add_argument("--mode", choices=["smoke", "preview", "train", "evaluate"], default="smoke")
parser.add_argument("--steps", type=int, default=60)
parser.add_argument("--timesteps", type=int, default=100000)
parser.add_argument("--checkpoint")
parser.add_argument("--capture", action="store_true", help="Verify CUDA and save rendered overview/detail images")
from isaaclab.app import AppLauncher
AppLauncher.add_app_launcher_args(parser)
args = parser.parse_args()
if args.capture and not args.enable_cameras:
    parser.error("--capture requires --enable_cameras")
cfg = load_config(args.config)
print("DEVICE_FILES", glob.glob("/dev/nvidia*"), flush=True)
if cfg["tool"]["kind"] != "parallel":
    raise SystemExit("Paper tool is pending validated CAD and connection geometry; physical comparison is disabled.")
app = AppLauncher(args).app

import torch
from isaaclab.envs import ManagerBasedRLEnv
from challenge2.env_cfg import make_env_cfg
from challenge2.mdp import state

if args.capture:
    if not torch.cuda.is_available():
        raise RuntimeError("CUDA is unavailable for rendering verification")
    check = torch.arange(16, device="cuda").square().sum().item()
    if check != 1240:
        raise RuntimeError("CUDA arithmetic check failed")
    report = {"device": torch.cuda.get_device_name(0), "torch_cuda": torch.version.cuda, "arithmetic_check": check}
    (ROOT / "cuda_check.json").write_text(json.dumps(report, indent=2))
    print("CUDA_OK", json.dumps(report), flush=True)

env = ManagerBasedRLEnv(cfg=make_env_cfg(cfg, capture=args.capture))
# Isaac Lab's experiences disable USD transform updates by default. With Fabric
# disabled for native clutch physics, explicitly restore the USD rendering path.
env.sim.get_physics_context().set_physx_update_transformations_settings(update_to_usd=True)
obs, _ = env.reset(seed=cfg["seed"])
from bricksim.core import compute_connected_component
from challenge2.mdp import path
from isaaclab.sim import get_current_stage
connected, connections = compute_connected_component(path(env, "plate_source"))
expected = len(state(env).plan.remaining) + 1
if len(connected) != expected:
    raise RuntimeError(f"Source must be connected to the floor: expected {expected} parts, found {len(connected)}")
print("SOURCE_GRAPH", len(connected), "parts", len(connections), "connections", flush=True)
print("WORKCELL_READY", json.dumps({"robot": "FR3", "bricks": len(state(env).plan.remaining), "action_shape": list(env.action_space.shape), "observation_shape": list(obs["policy"].shape)}), flush=True)
if args.mode == "train":
    from stable_baselines3 import PPO
    from isaaclab_rl.sb3 import Sb3VecEnvWrapper
    wrapped = Sb3VecEnvWrapper(env)
    model = PPO("MlpPolicy", wrapped, n_steps=256, batch_size=64, verbose=1, device="cpu", seed=cfg["seed"])
    if args.checkpoint:
        model = PPO.load(args.checkpoint, env=wrapped, device="cpu")
    model.learn(total_timesteps=args.timesteps)
    model.save(str(ROOT / "policy"))
else:
    model = None
    if args.mode == "evaluate":
        if not args.checkpoint:
            raise ValueError("--mode evaluate requires --checkpoint")
        from stable_baselines3 import PPO
        model = PPO.load(args.checkpoint, device="cpu")
    completed, failed, timeouts = 0, 0, 0
    for i in range(args.steps):
        if not app.is_running():
            break
        if model:
            action, _ = model.predict(obs["policy"].cpu().numpy(), deterministic=True)
            action = torch.as_tensor(action, device=env.device)
        else:
            action = torch.zeros((1, env.action_manager.total_action_dim), device=env.device)
            action[:, -1] = 1.0  # Open gripper; hold the arm for stability checks.
        obs, rew, terminated, truncated, info = env.step(action)
        if terminated.item():
            # TerminationManager retains the per-term result across auto-reset.
            completed += int(env.termination_manager.get_term("success").item())
            failed += int(env.termination_manager.get_term("failure").item())
        timeouts += int(truncated.item())
        if not torch.isfinite(obs["policy"]).all():
            raise RuntimeError("Non-finite observation")
        if i % 30 == 0:
            print(f"STEP {i}: sorted={len(state(env).plan.completed)} failures={failed}", flush=True)
        if args.mode == "smoke" and i + 1 == args.steps // 2:
            obs, _ = env.reset(seed=cfg["seed"])
            parts, _ = compute_connected_component(path(env, "plate_source"))
            if len(parts) != expected:
                raise RuntimeError("Reset did not restore the source connection graph")
            print("RESET_GRAPH_OK", len(parts), flush=True)
    result = {"steps": i+1, "successful_episodes": completed, "failed_episodes": failed, "timeouts": timeouts,
              "transfers_in_current_episode": len(state(env).plan.completed)}
    (ROOT / "result.json").write_text(json.dumps(result, indent=2))
    print("RESULT", json.dumps(result), flush=True)
    if args.mode == "smoke" and (failed or completed or timeouts):
        raise RuntimeError("Idle scene did not remain stable for the smoke-test duration")
    if args.mode == "smoke":
        robot = env.scene["robot"]
        arm, _ = robot.find_joints("fr3_joint[1-7]")
        drift = (robot.data.joint_pos[:, arm]-robot.data.default_joint_pos[:, arm]).abs().max().item()
        print("IDLE_ARM_DRIFT_RAD", drift, flush=True)
        if drift > 0.02:
            raise RuntimeError("Idle arm drifted more than 0.02 rad from its configured pose")
if args.capture:
    from PIL import Image
    from pxr import UsdGeom
    robot = env.scene["robot"]
    hands, _ = robot.find_bodies("fr3_hand")
    physics_hand = robot.data.body_state_w[0, hands[0], :3].cpu().tolist()
    rendered_hand = list(UsdGeom.Xformable(get_current_stage().GetPrimAtPath(
        "/World/envs/env_0/Robot/fr3_hand")).ComputeLocalToWorldTransform(0).ExtractTranslation())
    poses = {"joint_positions": robot.data.joint_pos[0].cpu().tolist(),
             "default_joint_positions": robot.data.default_joint_pos[0].cpu().tolist(),
             "physics_hand_xyz": physics_hand, "usd_hand_xyz": rendered_hand}
    (ROOT / "render_poses.json").write_text(json.dumps(poses, indent=2))
    print("RENDER_POSES", json.dumps(poses), flush=True)
    if sum((a-b)**2 for a, b in zip(physics_hand, rendered_hand)) > 0.001**2:
        raise RuntimeError("Rendered FR3 hand is out of sync with physics by more than 1 mm")
    camera = env.scene["overview"]
    for name, eye, target in [
        ("overview", (1.35, -1.25, 1.05), (0.25, 0, 0.35)),
        ("bricks", (0.78, -0.55, 0.45), (0.43, 0, 0.03)),
    ]:
        camera.set_world_poses_from_view(
            torch.tensor([eye], device=env.device), torch.tensor([target], device=env.device))
        camera.reset()
        for _ in range(8):
            env.sim.render()
        camera.update(env.step_dt, force_recompute=True)
        rgb = camera.data.output["rgb"][0, :, :, :3].cpu().numpy()
        if rgb.max() == rgb.min():
            raise RuntimeError(f"Rendered {name} image is uniform")
        Image.fromarray(rgb).save(ROOT / f"{name}.png")
        print("RENDER_SAVED", name, list(rgb.shape), flush=True)
get_current_stage().GetRootLayer().Export(str(ROOT / "workcell.usda"))
env.close()
(ROOT / "run_complete.json").write_text(json.dumps({"mode": args.mode, "completed": True}))
app.close()
