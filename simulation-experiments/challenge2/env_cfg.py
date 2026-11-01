"""One CPU PhysX workcell with native clutch physics and FR3 differential IK."""

from isaaclab.actuators import ImplicitActuatorCfg
from isaaclab.assets import ArticulationCfg, AssetBaseCfg, RigidObjectCfg
from isaaclab.controllers import DifferentialIKControllerCfg
from isaaclab.envs import ManagerBasedRLEnvCfg, mdp
from isaaclab.managers import EventTermCfg, ObservationGroupCfg, ObservationTermCfg, RewardTermCfg, TerminationTermCfg
from isaaclab.scene import InteractiveSceneCfg
from isaaclab.sensors import CameraCfg
from isaaclab.sim import CuboidCfg, CollisionPropertiesCfg, DomeLightCfg, PinholeCameraCfg, PreviewSurfaceCfg, RigidBodyPropertiesCfg, UsdFileCfg
from isaaclab.utils import configclass
from bricksim.assets.robots.fr3 import FR3_ROBOT_USD_PATH
from bricksim.mdp.brick_part import BrickPartCfg
from bricksim.mdp.connection_thresholds import configure_assembly_thresholds, configure_breakage_thresholds
from bricksim.mdp.events import reset_scene_to_default_no_kinematic_vel

from .layout import SortPlan
from . import mdp as task


@configclass
class Actions:
    arm = mdp.DifferentialInverseKinematicsActionCfg(
        asset_name="robot", joint_names=["fr3_joint[1-7]"], body_name="fr3_hand",
        controller=DifferentialIKControllerCfg(command_type="pose", use_relative_mode=True, ik_method="dls"),
        scale=(0.01, 0.01, 0.01, 0.08, 0.08, 0.08),
        body_offset=mdp.DifferentialInverseKinematicsActionCfg.OffsetCfg(pos=(0, 0, 0.1034)),
    )
    gripper = mdp.BinaryJointPositionActionCfg(
        asset_name="robot", joint_names=["fr3_finger_joint.*"],
        open_command_expr={".*": 0.04}, close_command_expr={".*": 0.0},
    )


@configclass
class Policy(ObservationGroupCfg):
    state = ObservationTermCfg(func=task.observation)


@configclass
class Observations:
    policy = Policy()


@configclass
class Events:
    clear_connections = EventTermCfg(func=task.clear_connections, mode="reset")
    reset_scene = EventTermCfg(func=reset_scene_to_default_no_kinematic_vel, mode="reset", params={"reset_joint_targets": True})
    initialize_task = EventTermCfg(func=task.reset_task, mode="reset")


@configclass
class Rewards:
    task = RewardTermCfg(func=task.reward, weight=1.0)
    action_rate = RewardTermCfg(func=mdp.action_rate_l2, weight=-0.005)
    joint_speed = RewardTermCfg(func=mdp.joint_vel_l2, weight=-0.0001)


@configclass
class Terminations:
    success = TerminationTermCfg(func=task.success)
    failure = TerminationTermCfg(func=task.failure)
    timeout = TerminationTermCfg(func=mdp.time_out, time_out=True)


def output_centers(cfg):
    if cfg["recipe"] == "mixed":
        return {"mixed": cfg["output_xy"]}
    good = [c for c in cfg["colors"] if c not in cfg["reject_colors"]]
    # Independent plates, with clearance between their edges.
    return {c: (cfg["output_xy"][0] - 0.08 + (i % 2) * 0.22,
                cfg["output_xy"][1] + (i // 2) * 0.22) for i, c in enumerate(good)}


def make_env_cfg(cfg, capture=False):
    if cfg["tool"]["kind"] != "parallel":
        raise ValueError("Paper EOAT comparison requires validated tool CAD, flange transform, mass/inertia and stud interface. No substitute grasp is enabled.")
    configure_assembly_thresholds(enabled=True, required_force=cfg["physics"]["assembly_force_n"])
    configure_breakage_thresholds(enabled=True, preloaded_force=cfg["physics"]["clutch_preload_n"], friction_coefficient=cfg["physics"]["clutch_friction"])
    scene = InteractiveSceneCfg(num_envs=1, env_spacing=3, replicate_physics=False)
    scene.robot = ArticulationCfg(
        prim_path="{ENV_REGEX_NS}/Robot", spawn=UsdFileCfg(
            usd_path=str(FR3_ROBOT_USD_PATH),
            # Ideal gravity compensation for the relative-IK arm controller.
            # Bricks retain gravity and all contact/clutch loads remain active.
            rigid_props=RigidBodyPropertiesCfg(disable_gravity=True)),
        init_state=ArticulationCfg.InitialStateCfg(joint_pos={
            "fr3_joint1": 0.0, "fr3_joint2": -0.4, "fr3_joint3": 0.0,
            "fr3_joint4": -2.5, "fr3_joint5": 0.0, "fr3_joint6": 2.1,
            "fr3_joint7": 0.7854, "fr3_finger_joint.*": 0.04}),
        actuators={
            "arm": ImplicitActuatorCfg(joint_names_expr=["fr3_joint[1-7]"], stiffness=400.0, damping=80.0),
            "hand": ImplicitActuatorCfg(joint_names_expr=["fr3_finger_joint.*"], effort_limit_sim=15.0, stiffness=2000.0, damping=100.0),
        })
    scene.light = AssetBaseCfg(prim_path="/World/Light", spawn=DomeLightCfg(intensity=800.0))
    if capture:
        scene.overview = CameraCfg(
            prim_path="/World/Overview", width=960, height=720, data_types=["rgb"],
            spawn=PinholeCameraCfg(focal_length=24.0, horizontal_aperture=24.0,
                                   clipping_range=(0.01, 10.0)))
    scene.table = AssetBaseCfg(prim_path="/World/Table", spawn=CuboidCfg(
        size=(1.2, 1.2, 0.05), collision_props=CollisionPropertiesCfg(),
        visual_material=PreviewSurfaceCfg(diffuse_color=(0.65, 0.65, 0.65))),
        init_state=AssetBaseCfg.InitialStateCfg(pos=(0.35, 0, -0.025)))
    studs = cfg["baseplate_studs"]
    for key, xy in {"source": cfg["source_xy"], **output_centers(cfg)}.items():
        setattr(scene, f"plate_{key}", RigidObjectCfg(
            prim_path=f"{{ENV_REGEX_NS}}/plate_{key}",
            spawn=BrickPartCfg(dimensions=(studs, studs, 1), color=(120, 125, 130),
                rigid_props=RigidBodyPropertiesCfg(kinematic_enabled=True, disable_gravity=True)),
            init_state=RigidObjectCfg.InitialStateCfg(pos=(*xy, 0.0))))
    for b in SortPlan(cfg).remaining:
        pos, rot = b.pose(cfg["source_xy"], studs)
        setattr(scene, b.name, RigidObjectCfg(prim_path=f"{{ENV_REGEX_NS}}/{b.name}",
            spawn=BrickPartCfg(dimensions=(4, 2, 3), color=tuple(cfg["colors"][b.color]),
                rigid_props=RigidBodyPropertiesCfg(solver_position_iteration_count=32, solver_velocity_iteration_count=4, max_depenetration_velocity=0.2)),
            init_state=RigidObjectCfg.InitialStateCfg(pos=pos, rot=rot)))
    # Scrap tray floor and walls. Scrap remains loose rather than snapping to studs.
    sx, sy = cfg["scrap_xy"]
    w, d = cfg["scrap_size"]
    for name, size, pos in [
        ("floor", (w, d, 0.004), (sx, sy, 0.002)),
        ("left", (0.004, d, 0.025), (sx-w/2, sy, 0.0125)),
        ("right", (0.004, d, 0.025), (sx+w/2, sy, 0.0125)),
        ("front", (w, 0.004, 0.025), (sx, sy-d/2, 0.0125)),
        ("back", (w, 0.004, 0.025), (sx, sy+d/2, 0.0125)),
    ]:
        setattr(scene, f"scrap_{name}", AssetBaseCfg(prim_path=f"/World/Scrap/{name}",
            spawn=CuboidCfg(size=size, collision_props=CollisionPropertiesCfg(), visual_material=PreviewSurfaceCfg(diffuse_color=(0.15, 0.15, 0.15))),
            init_state=AssetBaseCfg.InitialStateCfg(pos=pos)))
    env = ManagerBasedRLEnvCfg()
    env.scene, env.actions, env.observations = scene, Actions(), Observations()
    env.events, env.rewards, env.terminations = Events(), Rewards(), Terminations()
    env.commands = None
    env.decimation = cfg["physics"]["decimation"]
    env.episode_length_s = cfg["episode_seconds"]
    env.sim.dt = cfg["physics"]["dt"]
    env.sim.device, env.sim.use_fabric = "cpu", False
    env.sim.render_interval = env.decimation
    env.viewer.eye, env.viewer.lookat = (1.1, -1.0, 0.9), (0.4, 0, 0.05)
    env.workcell = cfg
    env.seed = cfg["seed"]
    env.actions.arm.body_offset.pos = tuple(cfg["tool"]["tcp_offset_m"])
    return env
