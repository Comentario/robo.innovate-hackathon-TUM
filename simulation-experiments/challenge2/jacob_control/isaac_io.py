"""Isaac-only state/actuation boundary. No robot network or world-target API."""
import math
import numpy as np
from scipy.spatial.transform import Rotation


def transform(position,quaternion):
    t=np.eye(4);t[:3,3]=position;t[:3,:3]=Rotation.from_quat(np.asarray(quaternion)[[1,2,3,0]]).as_matrix();return t


class IsaacIO:
    def __init__(self,sim,scene,robot,F_T_EE,T_flange_hand,model,*,watchdog=None):
        import torch
        self.torch=torch;self.sim,self.scene,self.robot=sim,scene,robot;self.model=model;self.watchdog=watchdog
        self.arm=[robot.joint_names.index(f'fr3_joint{i}') for i in range(1,8)]
        self.fingers=[robot.joint_names.index(f'fr3_finger_joint{i}') for i in (1,2)]
        self.hand=robot.body_names.index('fr3_hand');self.F_T_EE=np.asarray(F_T_EE).reshape(4,4,order='F')
        self.T_hand_EE=np.linalg.inv(np.asarray(T_flange_hand))@self.F_T_EE
        self.dt=float(sim.get_physics_dt())
        if abs(self.dt-.001)>1e-12:raise RuntimeError('This backend requires healthy 1 kHz simulation ticks')
        self.last_target=self._targets()[self.arm].copy();self.desired_velocity=np.zeros(7);self.desired_acceleration=np.zeros(7)
        self.command_count=0;self.width_commands=0;self.last_requested=self.last_target.copy()
        self.tool_mass=float(robot.root_physx_view.get_masses()[0,[robot.body_names.index(n) for n in ('fr3_hand','fr3_leftfinger','fr3_rightfinger')]].sum().item())
        self.provenance={'q':'PhysX actual DOF positions','dq':'PhysX actual DOF velocities',
            'q_d':'public get_dof_position_targets, float32 accepted target readback',
            'dq_d_ddq_d':'derived from successive public target readbacks at 1 ms; not measured hardware derivatives',
            'm_ee':'runtime sum of actual hand and both finger masses; not measured physical tool payload',
            'O_dP_EE_c':'real-model Jacobian at accepted q_d times derived desired velocity',
            'current_errors':'simulation guard state only; hardware errors unavailable',
            'robot_mode':'simulation task idle/move marker only',
            'control_command_success_rate':'unavailable hardware network diagnostic',
            'is_grasped':'unavailable; never inferred from finger width'}
        self.mode='Idle'

    def _targets(self):return self.robot.root_physx_view.get_dof_position_targets()[0].cpu().numpy().astype(float)

    def read_state(self):
        robot=self.robot
        q=robot.root_physx_view.get_dof_positions()[0].cpu().numpy().astype(float)
        dq=robot.root_physx_view.get_dof_velocities()[0].cpu().numpy().astype(float);target=self._targets()
        root=transform(robot.data.root_link_pos_w[0].cpu().numpy(),robot.data.root_link_quat_w[0].cpu().numpy())
        hand=transform(robot.data.body_link_pos_w[0,self.hand].cpu().numpy(),robot.data.body_link_quat_w[0,self.hand].cpu().numpy())
        tcp=np.linalg.inv(root)@hand@self.T_hand_EE
        if not all(np.isfinite(a).all() for a in (q,dq,target,tcp)):raise RuntimeError('Nonfinite public simulation state')
        desired=target[self.arm];twist=self.model.jacobian(desired)@self.desired_velocity
        return {'q':q[self.arm].tolist(),'dq':dq[self.arm].tolist(),'q_d':desired.tolist(),
            'dq_d':self.desired_velocity.tolist(),'ddq_d':self.desired_acceleration.tolist(),
            'O_T_EE':tcp.reshape(-1,order='F').tolist(),'F_T_EE':self.F_T_EE.reshape(-1,order='F').tolist(),
            'O_dP_EE_c':twist.tolist(),'m_ee':self.tool_mass,'robot_mode':self.mode,'current_errors':[],
            'time':float(self.sim.current_time),'control_command_success_rate':None,
            'joint_target_readback':desired.tolist(),'raw_requested_q':self.last_requested.tolist(),
            'T_world_root':root.tolist(),'model_grip_frame_used':False}

    def _step(self,target):
        t=self.torch;self.robot.set_joint_position_target(t.tensor([target],dtype=t.float32,device=self.robot.device))
        self.scene.write_data_to_sim();self.sim.step(render=False);self.scene.update(self.dt)
        actual_target=self._targets()[self.arm];velocity=(actual_target-self.last_target)/self.dt
        self.desired_acceleration=(velocity-self.desired_velocity)/self.dt;self.desired_velocity=velocity;self.last_target=actual_target.copy()
        if self.watchdog is not None:self.watchdog()

    def advance(self,command_q,period_s=.001):
        command=np.asarray(command_q,dtype=float)
        if command.shape!=(7,) or not np.isfinite(command).all() or abs(period_s-self.dt)>1e-12:raise ValueError('Finite seven-joint command / exact simulation tick required')
        bounds=self.robot.data.joint_pos_limits[0,self.arm].cpu().numpy()
        if np.any(command<bounds[:,0]) or np.any(command>bounds[:,1]):raise RuntimeError('Command exceeds actual Isaac articulation limit')
        self.last_requested=command.copy();target=self._targets();target[self.arm]=command
        self._step(target);self.command_count+=1;return self.read_state()

    def read_gripper(self):
        q=self.robot.root_physx_view.get_dof_positions()[0,self.fingers].cpu().numpy()
        maximum=float(self.robot.data.joint_pos_limits[0,self.fingers,1].sum().item())
        return {'width':float(np.sum(q)),'max_width':maximum,'is_grasped':None,
            'width_semantics':'SDK-compatible joint sum, not modified-pad inner gap'}

    def move_gripper(self,width,speed):
        # Blocking simulated position servo. Loaded-contact completion is unvalidated.
        start=self.read_gripper()['width']
        if not 0<=width<=self.read_gripper()['max_width'] or not 0<speed<=.1:raise ValueError('Invalid simulated width request')
        steps=max(1,math.ceil(abs(width-start)/(speed*self.dt)));self.width_commands+=1
        for step in range(1,steps+1):
            wanted=start+(width-start)*min(step/steps,1.);target=self._targets();target[self.fingers]=wanted/2
            self._step(target)
        for _ in range(500):
            if abs(self.read_gripper()['width']-width)<=.001:return True
            self._step(self._targets())
        return False
