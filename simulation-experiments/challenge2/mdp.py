"""Task state and scoring. Only observed physics can complete a transfer.

The planner never deletes a clutch to simulate a successful pick and never
teleports a brick during a step. Initial connections are authored on reset.
"""

import math
import torch
from bricksim.core import compute_connected_component, create_connection, deallocate_connection, get_disassembled_connections
from isaaclab.sim import get_current_stage
from isaaclab.utils.math import combine_frame_transforms

from .layout import SortPlan, connection_offset, supports


def path(env, name):
    # Scene config paths become regexes even for a single environment.
    return env.scene[name].cfg.prim_path.replace("{ENV_REGEX_NS}", "/World/envs/env_0").replace("env_.*", "env_0")


def clear_connections(env, env_ids):
    """Remove connections in this one-workcell process before resetting poses."""
    del env_ids
    connections = [str(p.GetPath()) for p in get_current_stage().Traverse() if p.GetTypeName() == "LegoConnection"]
    for p in connections:
        deallocate_connection(p)
    get_disassembled_connections(clear=True)


def reset_task(env, env_ids):
    del env_ids
    env.sort_state = State(env)
    cfg, plan = env.cfg.workcell, env.sort_state.plan
    for brick in plan.remaining:
        lower_bricks = supports(plan.remaining, brick) if brick.layer else [None]
        for lower in lower_bricks:
            offset, yaw = connection_offset(lower, brick, cfg["baseplate_studs"])
            create_connection(path(env, "plate_source" if lower is None else lower.name), 1,
                              path(env, brick.name), 0, offset, yaw)
    env.sort_state.initialized = True


def state(env):
    if not hasattr(env, "sort_state"):
        env.sort_state = State(env)
    return env.sort_state


class State:
    def __init__(self, env):
        self.plan = SortPlan(env.cfg.workcell)
        self.initialized = False
        self.last_tick = -1
        self.detached = False
        self.failed = False
        self.stable_steps = 0
        self.transfer_bonus = 0.0
        self.detach_bonus = 0.0
        self.initial = {b.name: env.scene[b.name].data.root_pos_w[0].clone() for b in self.plan.remaining}

    def update(self, env):
        tick = env.common_step_counter
        if not self.initialized or self.last_tick == tick:
            return
        self.last_tick = tick
        self.transfer_bonus = self.detach_bonus = 0.0
        b = self.plan.target
        if b is None:
            return
        parts, _ = compute_connected_component(path(env, b.name))
        remaining_paths = {path(env, other.name) for other in self.plan.remaining if other != b}
        separated = path(env, "plate_source") not in parts and not remaining_paths.intersection(parts)
        if separated and not self.detached:
            self.detached = True
            self.detach_bonus = 10.0
        # Losing any non-target clutch is a one-piece disassembly failure.
        for event in get_disassembled_connections(clear=True):
            if event.stud_path != path(env, b.name) and event.hole_path != path(env, b.name):
                self.failed = True
        for other in self.plan.remaining:
            if other != b and torch.linalg.vector_norm(env.scene[other.name].data.root_pos_w[0] - self.initial[other.name]) > 0.015:
                self.failed = True
        obj = env.scene[b.name].data
        if obj.root_pos_w[0, 2] < -0.005 or not torch.isfinite(obj.root_state_w).all():
            self.failed = True
        destination, slot = self.plan.destination(b)
        robot = env.scene["robot"]
        fingers, _ = robot.find_joints("fr3_finger_joint.*")
        opened = robot.data.joint_pos[0, fingers].sum().item() > 0.07
        slow = torch.linalg.vector_norm(obj.root_lin_vel_w[0]).item() < 0.02 and torch.linalg.vector_norm(obj.root_ang_vel_w[0]).item() < 0.2
        if slot is None:
            cfg = env.cfg.workcell
            x, y, z = obj.root_pos_w[0].tolist()
            w, d = cfg["scrap_size"]
            # Entire 2x4 brick must fit inside the walls, independent of yaw.
            arrived = abs(x-cfg["scrap_xy"][0]) < w/2-0.020 and abs(y-cfg["scrap_xy"][1]) < d/2-0.020 and 0.003 < z < 0.05
        else:
            pos, quat = target_pose(env)
            close = torch.linalg.vector_norm(obj.root_pos_w[0]-pos).item() < 0.002
            aligned = abs(torch.dot(obj.root_quat_w[0], quat).item()) > math.cos(math.radians(5)/2)
            arrived = path(env, f"plate_{destination}") in parts and close and aligned
        self.stable_steps = self.stable_steps + 1 if self.detached and arrived and opened and slow else 0
        if self.stable_steps >= 10:
            self.plan.complete(b)
            self.transfer_bonus = 100.0
            self.stable_steps = 0
            self.detached = False


def tcp_pose(env):
    robot = env.scene["robot"]
    hands, _ = robot.find_bodies("fr3_hand")
    pose = robot.data.body_state_w[:, hands[0], :7]
    offset = torch.tensor(env.cfg.workcell["tool"]["tcp_offset_m"], device=env.device).reshape(1, 3)
    return combine_frame_transforms(pose[:, :3], pose[:, 3:7], offset)


def target_pose(env):
    from .env_cfg import output_centers
    b = state(env).plan.target
    if b is None:
        return torch.zeros(3, device=env.device), torch.tensor([1., 0, 0, 0], device=env.device)
    cfg = env.cfg.workcell
    key, slot = state(env).plan.destination(b)
    if slot is None:
        pos, quat = (*cfg["scrap_xy"], 0.012), (1., 0, 0, 0)
    else:
        pos, quat = slot.pose(output_centers(cfg)[key], cfg["baseplate_studs"])
    return torch.tensor(pos, device=env.device), torch.tensor(quat, device=env.device)


def observation(env):
    s = state(env)
    r = env.scene["robot"].data
    tcp, rot = tcp_pose(env)
    b = s.plan.target
    brick = env.scene[b.name].data.root_state_w[:, :7] if b else torch.zeros((1, 7), device=env.device)
    goal, quat = target_pose(env)
    colors = list(env.cfg.workcell["colors"])
    label = torch.zeros((1, len(colors)), device=env.device)
    if b:
        label[0, colors.index(b.color)] = 1
    flags = torch.tensor([[float(s.detached), len(s.plan.completed)/(len(s.plan.remaining)+len(s.plan.completed))]], device=env.device)
    return torch.cat((r.joint_pos, r.joint_vel, tcp, rot, brick, goal[None], quat[None], label, flags), dim=-1)


def reward(env):
    s = state(env)
    b = s.plan.target
    if b is None:
        return torch.tensor([s.transfer_bonus], device=env.device)
    pos = env.scene[b.name].data.root_pos_w[0]
    tcp, _ = tcp_pose(env)
    goal, _ = target_pose(env)
    distance = torch.linalg.vector_norm(pos-goal) if s.detached else torch.linalg.vector_norm(tcp[0]-pos-torch.tensor([0, 0, 0.015], device=env.device))
    return (1.0-torch.tanh(distance/0.05)+s.transfer_bonus+s.detach_bonus-0.05-20.0*float(s.failed)).reshape(1)


def success(env):
    s = state(env)
    s.update(env)
    return torch.tensor([s.initialized and not s.plan.remaining and not s.failed], device=env.device)


def failure(env):
    return torch.tensor([state(env).failed], device=env.device)
