"""One scheduled offline shared-stack replay; ideal IO is not simulation evidence."""
import argparse
import copy
import hashlib
import json
import os
from pathlib import Path
import sys
import numpy as np
from scipy.spatial.transform import Rotation
ROOT=Path(__file__).resolve().parents[2];sys.path.insert(0,str(ROOT))
from challenge2.jacob_control.bridge import SharedStack,ProcessFacade
from challenge2.jacob_control.executor import JointExecutor,JointPlan
from challenge2.jacob_control.native import NativeLimiter


def write(path,data):path.write_text(json.dumps(data,indent=2,allow_nan=False)+'\n')


class IdealIO:
    def __init__(self,q,tool):
        self.q=np.array(q,float);self.target=self.q.copy();self.velocity=np.zeros(7);self.acceleration=np.zeros(7)
        self.tool=tool;self.model=None;self.t=0.;self.mode='Idle';self.overrides={};self.steps=0
    def read_state(self):
        t=self.model.fk(self.q).homogeneous
        state={'q':self.q.tolist(),'dq':self.velocity.tolist(),'q_d':self.target.tolist(),'dq_d':self.velocity.tolist(),'ddq_d':self.acceleration.tolist(),
            'O_T_EE':t.reshape(-1,order='F').tolist(),'F_T_EE':self.tool,'m_ee':.8,'robot_mode':self.mode,'current_errors':[],
            'O_dP_EE_c':(self.model.jacobian(self.target)@self.velocity).tolist(),'time':self.t,'control_command_success_rate':None,
            'joint_target_readback':self.target.tolist()}
        state.update(copy.deepcopy(self.overrides));return state
    def advance(self,q,period_s=.001):
        target=np.asarray(q);v=(target-self.target)/period_s;self.acceleration=(v-self.velocity)/period_s;self.velocity=v
        self.q=target.copy();self.target=target.copy();self.t+=period_s;self.steps+=1;return self.read_state()
    def read_gripper(self):return {'width':.02,'max_width':.08,'is_grasped':None}
    def move_gripper(self,*args):raise RuntimeError('Only NOOP width check belongs to phase A')


def common_metadata(root,output,executor,io,phase,extra):
    teaching=root/'vendor/jacob_teaching/teaching';moves=sorted((teaching/'moves').glob('*/outcome.json'))
    if len(moves)!=1:raise RuntimeError('Exactly one canonical shared move required')
    run=moves[0].parent
    relative=lambda p:os.path.relpath(p,output)
    final=json.loads(moves[0].read_text())
    metadata={'phase':phase,'upstream_commit':'13f37dad1980bcbc4491b7f27d8962602e49fea0',
        'source_manifest_file':relative(teaching.parent/'SOURCE.json'),'plan_file':relative(run/'joint_plan.json'),
        'joint_input_file':relative(run/'joint_input.txt'),'cpp_check_csv':relative(run/'model_check.csv'),
        'outcome_file':relative(moves[0]),'trace_file':relative(executor.output/'joint_callback_trace.jsonl'),
        'native_build_file':relative(root/'native/build.json'),'limiter_library':relative(root/'native/libjoint_limiter.so'),
        'tool_F_T_EE':io.tool if hasattr(io,'tool') else io.F_T_EE.reshape(-1,order='F').tolist(),
        'physics_dt_s':.001,'command_scope':'same pinned vendor CLI/planner, shared policy and healthy 1 kHz backend protocol; not identical hardware dynamics',
        'grasp_or_placement_claim':False,'hardware_commands':0,**extra}
    write(output/'metadata.json',metadata);return metadata


def main():
    p=argparse.ArgumentParser();p.add_argument('--output',type=Path,required=True);args=p.parse_args()
    if os.environ.get('ROBO_PUEUE_JOB')!='1':raise RuntimeError('Offline planning/replay requires default Pueue')
    out=args.output;out.mkdir(parents=True,exist_ok=True);teaching=ROOT/'vendor/jacob_teaching/teaching'
    catalog=json.loads((teaching/'positions.json').read_text());point=catalog['points']['point_03'];config=json.loads((teaching/'motion_config.json').read_text())
    io=IdealIO(point['q_rad'],point['tool_frames']['F_T_EE']);limiter=NativeLimiter(ROOT/'native/libjoint_limiter.so',teaching/'robot_model.urdf')
    executor=JointExecutor(io,limiter,ROOT/'native/joint_check',out)
    with SharedStack(teaching,executor,source_manifest=teaching.parent/'SOURCE.json') as shared:
        io.model=shared.modules['kinematics'].Kinematics(io.tool,config['singularity_avoidance'])
        predicted=io.model.fk(io.q).homogeneous;measured=np.array(point['measured_O_T_EE']).reshape(4,4,order='F')
        fidelity={'position_error_m':float(np.linalg.norm(predicted[:3,3]-measured[:3,3])),
            'orientation_error_rad':float(Rotation.from_matrix(predicted[:3,:3].T@measured[:3,:3]).magnitude()),
            'scope':'Imported measured pose versus exported robot model, not Isaac state'}
        width=shared.command_width('release');move=shared.move('3',relative_z_mm=1)
        plans=sorted((teaching/'moves').glob('*/joint_input.txt'))
        if move or width or len(plans)!=1:raise RuntimeError('Shared baseline failed; no alternative route or retry')
        guards=[];frozen=JointPlan(plans[0]);before=io.steps
        original=io.overrides
        for name,override in [('stale_start',{'q':(frozen.q0+np.array([.003,0,0,0,0,0,0])).tolist()}),
                              ('changed_tool',{'F_T_EE':(np.asarray(io.tool)+np.array([0]*12+[.001,0,0,0])).tolist()})]:
            io.overrides=override;start_steps=io.steps;blocked=False
            try:next(executor._joint(['joint_move',str(plans[0]),str(out/'unused.csv'),'--execute']))
            except RuntimeError:blocked=True
            guards.append({'case':name,'blocked':blocked,'advance_count':io.steps-start_steps})
        io.overrides=original
        facade=shared.modules['move_xyz'].subprocess;blocked=False
        try:facade.run(['ssh','172.16.0.2'])
        except RuntimeError:blocked=True
        guards.append({'case':'unknown_process','blocked':blocked,'advance_count':io.steps-before})
        write(out/'guard_cases.json',guards)
        cases=[]
        for i in range(12):
            q=frozen.q0.copy();command=q.copy();command[i%7]+=(1 if i%2 else -1)*(.05 if i>=4 else .0000001)
            v=np.zeros(7);acc=np.zeros(7)
            if i>=8:
                j=i%7;upper=i%2==0;q[j]=limiter.parameters[j,3 if upper else 4]+(-.05 if upper else .05)
                command=q.copy();command[j]+=.05 if upper else -.05;v[j]=.05 if upper else -.05;acc[j]=.5 if upper else -.5
            limited=limiter.limit(command,q,v,acc)
            cases.append({'parameters':limiter.parameters.tolist(),'command':command.tolist(),'q_d':q.tolist(),'dq_d':v.tolist(),'ddq_d':acc.tolist(),'limited':limited.tolist()})
        write(out/'limiter_cases.json',cases)
        common_metadata(ROOT,out,executor,io,'A',{'move_returncode':move,'width_returncode':width,'model_fidelity':fidelity,
            'api_compatibility':shared.compatibility,'joint_names':[f'joint{i}' for i in range(1,8)],'root_world_transform':np.eye(4).tolist(),
            'io_provenance':{'plant':'IDEAL OFFLINE REPLAY ONLY','q_d':'explicit ideal target, not measured hardware/Isaac'},
            'limiter_cases_file':'limiter_cases.json','guard_cases_file':'guard_cases.json'})
    write(out/'run_complete.json',{'completed':True,'phase':'A','physics_steps':0,'hardware_commands':0})


if __name__=='__main__':main()
