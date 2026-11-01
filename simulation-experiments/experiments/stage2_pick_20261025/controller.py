"""Existing Isaac Lab DLS IK with explicit FR3 root and updated grip frames."""
import math
import numpy as np


class Controller:
    def __init__(self, robot, protocol):
        import torch
        from isaaclab.controllers import DifferentialIKController, DifferentialIKControllerCfg
        from isaaclab.utils import math as math_utils
        if not robot.is_fixed_base or robot.num_instances != 1:
            raise RuntimeError('This experiment uses one fixed-base FR3')
        self.robot, self.protocol = robot, protocol
        self.torch, self.math = torch, math_utils
        self.arm_ids = [robot.joint_names.index('fr3_joint'+str(i)) for i in range(1, 8)]
        self.finger_ids = [robot.joint_names.index('fr3_finger_joint'+str(i)) for i in (1, 2)]
        self.hand_id = robot.body_names.index('fr3_hand')
        self.finger_body_ids = {label: robot.body_names.index('fr3_'+label+'finger')
                                for label in ('left', 'right')}
        self.offset = torch.tensor([protocol['tool_frames']['T_hand_grip_translation_m']],
                                   dtype=torch.float32, device=robot.device)
        self.offset_quat = torch.tensor([protocol['tool_frames']['T_hand_grip_quaternion_wxyz']],
                                        dtype=torch.float32, device=robot.device)
        if not np.allclose(self.offset_quat.cpu().numpy(), [[1., 0., 0., 0.]], atol=0, rtol=0):
            raise RuntimeError('The frozen grip frame has no extra orientation offset')
        config = DifferentialIKControllerCfg(command_type='pose', use_relative_mode=False, ik_method='dls')
        self.ik = DifferentialIKController(config, num_envs=1, device=robot.device)
        self.previous_command = robot.data.joint_pos.clone()
        self.joint_limits = robot.data.joint_pos_limits.clone()

    def _frames(self):
        robot, m = self.robot, self.math
        hand_pos = robot.data.body_link_pos_w[:, self.hand_id]
        hand_quat = robot.data.body_link_quat_w[:, self.hand_id]
        tcp_pos, tcp_quat = m.combine_frame_transforms(hand_pos, hand_quat, self.offset, self.offset_quat)
        root_pos, root_quat = robot.data.root_link_pos_w, robot.data.root_link_quat_w
        return hand_pos, hand_quat, tcp_pos, tcp_quat, root_pos, root_quat

    def state(self):
        robot, t = self.robot, self.torch
        _, _, tcp_pos, tcp_quat, _, _ = self._frames()
        q, qdot = robot.data.joint_pos, robot.data.joint_vel
        if not all(t.isfinite(x).all().item() for x in (q, qdot, tcp_pos, tcp_quat)):
            raise RuntimeError('Nonfinite robot proprioception')
        if (q < self.joint_limits[..., 0]-2e-6).any() or (q > self.joint_limits[..., 1]+2e-6).any():
            raise RuntimeError('Actual robot joint position limit')
        if qdot[:, self.arm_ids].abs().max().item() > self.protocol['motion']['actual_joint_velocity_abort_rad_s']:
            raise RuntimeError('Actual arm joint velocity limit')
        pose = t.cat((tcp_pos, tcp_quat), dim=-1)[0].cpu().numpy().tolist()
        return {
            'tcp_pose_world_wxyz': pose,
            # The frozen scene's source-centered TABLE frame equals simulation
            # world, unlike the translated and yawed robot root frame.
            'tcp_pose_table_wxyz': list(pose),
            'finger_poses_world_wxyz': {
                label: robot.data.body_link_pose_w[0, index].cpu().numpy().tolist()
                for label, index in self.finger_body_ids.items()},
            'q': q[0].cpu().numpy().tolist(), 'qdot': qdot[0].cpu().numpy().tolist(),
        }

    def command(self, target_pose_table_wxyz, finger_command_scalar):
        t, m, robot = self.torch, self.math, self.robot
        target = np.asarray(target_pose_table_wxyz, dtype=float)
        if target.shape != (7,) or not np.isfinite(target).all():
            raise RuntimeError('Invalid sensor-derived TCP target')
        norm = np.linalg.norm(target[3:])
        if not math.isfinite(norm) or norm < 1e-9 or not math.isfinite(finger_command_scalar):
            raise RuntimeError('Invalid target quaternion or gripper command')
        target = target.copy()
        target[3:] /= norm
        self.state()  # Actual finite, joint position and arm speed guards.
        _, hand_quat, tcp_pos, tcp_quat, root_pos, root_quat = self._frames()
        desired = t.tensor(target[None], dtype=t.float32, device=robot.device)
        tcp_b, quat_b = m.subtract_frame_transforms(root_pos, root_quat, tcp_pos, tcp_quat)
        desired_b, desired_quat_b = m.subtract_frame_transforms(root_pos, root_quat,
                                                               desired[:, :3], desired[:, 3:])
        jacobian = robot.root_physx_view.get_jacobians()[:, self.hand_id-1, :, :][:, :, self.arm_ids].clone()
        # First move the hand-link Jacobian to the grip point in world axes.
        # The offset must be rotated by the measured hand orientation.
        offset_world = m.quat_apply(hand_quat, self.offset)
        jacobian[:, :3] -= t.bmm(m.skew_symmetric_matrix(offset_world), jacobian[:, 3:])
        world_to_root = m.matrix_from_quat(m.quat_inv(root_quat))
        jacobian[:, :3] = t.bmm(world_to_root, jacobian[:, :3])
        jacobian[:, 3:] = t.bmm(world_to_root, jacobian[:, 3:])
        self.ik.set_command(t.cat((desired_b, desired_quat_b), dim=-1))
        arm = self.ik.compute(tcp_b, quat_b, jacobian, robot.data.joint_pos[:, self.arm_ids])
        command = self.previous_command.clone()
        command[:, self.arm_ids] = arm
        command[:, self.finger_ids] = float(finger_command_scalar)
        if not t.isfinite(command).all():
            raise RuntimeError('Nonfinite DLS joint command')
        if ((command < self.joint_limits[..., 0]) | (command > self.joint_limits[..., 1])).any():
            raise RuntimeError('DLS command outside actual joint limits')
        increment = (command[:, self.arm_ids]-self.previous_command[:, self.arm_ids]).abs().max().item()
        if increment > self.protocol['motion']['maximum_joint_command_increment_rad']+1e-7:
            raise RuntimeError('DLS joint command increment limit')
        robot.set_joint_position_target(command)
        self.previous_command = command.clone()
        measured_quat = tcp_quat[0]/t.linalg.vector_norm(tcp_quat[0])
        desired_quat = desired[0, 3:]/t.linalg.vector_norm(desired[0, 3:])
        angle = 2*math.acos(min(1., abs(float(t.dot(measured_quat, desired_quat)))))
        return {'joint_commands': command[0].cpu().numpy().tolist(),
                'tcp_position_error_m': float(t.linalg.vector_norm(tcp_pos-desired[:, :3]).item()),
                'tcp_angle_error_rad': angle,
                'maximum_arm_command_increment_rad': increment}
