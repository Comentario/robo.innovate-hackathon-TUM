"""Small synthetic backend/math tests; no vendor planning, USD or hardware."""
import hashlib
import json
from pathlib import Path
import subprocess
import sys
import tempfile
from types import SimpleNamespace
import unittest
import numpy as np
from challenge2.jacob_control.bridge import SharedStack,ProcessFacade,MODULES,frame_parent_joint_compat
from challenge2.jacob_control.executor import JointExecutor,JointPlan,blend,sample_command


def frozen(path):
    identity=np.eye(4).reshape(-1,order='F').tolist();coeff=np.tile([.01,.02,.03,.1],(7,1))
    values=[2,2]+identity*3+[.1]*7+[0.]*18+[-1.]*3+[1.]*3
    values+=[1.,.02,.4,.3,1.,.001,.017453292519943295,.5,2.,6.,.3,.1,.08,50.,0.,.15,0.,1.]
    values+=[-2.]*7+[2.]*7+identity*8+[0.]+coeff.reshape(-1).tolist()+[1.]
    path.write_text('\n'.join(map(str,values)))


class FakeIO:
    def __init__(self,width=.02):self.time=0.;self.width=width;self.moves=0;self.steps=0;self.mode='Idle';self.grasped=None
    def read_state(self):
        return {'q':[0.]*7,'dq':[0.]*7,'q_d':[0.]*7,'dq_d':[0.]*7,'ddq_d':[0.]*7,
            'O_T_EE':np.eye(4).reshape(-1,order='F').tolist(),'F_T_EE':np.eye(4).reshape(-1,order='F').tolist(),
            'm_ee':.73,'robot_mode':self.mode,'current_errors':[],'O_dP_EE_c':[0.]*6,'time':self.time}
    def advance(self,q,period_s=.001):self.time+=period_s;self.steps+=1;return self.read_state()
    def read_gripper(self):return {'width':self.width,'max_width':.08,'is_grasped':self.grasped}
    def move_gripper(self,width,speed):self.moves+=1;self.time+=.25;self.width=width;return True


class ControlTests(unittest.TestCase):
    def test_frame_accessor_compatibility_is_scoped(self):
        class Frame:
            parent=1
            previousFrame=2
        restore,record=frame_parent_joint_compat(SimpleNamespace(Frame=Frame,__version__='synthetic2.7'))
        self.assertTrue(record['applied']);self.assertFalse(record['pinocchio3_runtime_equivalence_claim'])
        try:
            self.assertEqual(Frame().parentJoint,1);self.assertNotEqual(Frame().parentJoint,Frame().previousFrame)
            nested,nested_record=frame_parent_joint_compat(SimpleNamespace(Frame=Frame))
            self.assertFalse(nested_record['applied']);nested();self.assertEqual(Frame().parentJoint,1)
        finally:restore()
        self.assertFalse(hasattr(Frame,'parentJoint'));restore()
        class NewFrame:
            parentJoint=7
        original=NewFrame.parentJoint
        restore,record=frame_parent_joint_compat(SimpleNamespace(Frame=NewFrame))
        self.assertFalse(record['applied']);restore();self.assertIs(NewFrame.parentJoint,original)

    def test_spline_nested_time_and_initial_reference(self):
        with tempfile.TemporaryDirectory() as directory:
            path=Path(directory)/'joint_input';frozen(path);p=JointPlan(path)
            for u in (0.,.25,1.):np.testing.assert_allclose(p.q(u),[.01*u**3+.02*u*u+.03*u+.1]*7,atol=1e-15)
            np.testing.assert_allclose(p.expected(.3),np.eye(4).reshape(-1,order='F'),atol=1e-15)
            reference=np.full(7,.1004);u,raw,command=sample_command(p,0,reference)
            np.testing.assert_array_equal(command,reference)
            u,raw,command=sample_command(p,.25,reference)
            self.assertAlmostEqual(u,blend(.25));np.testing.assert_allclose(command,raw+.0004*(1-blend(blend(.25))),atol=1e-15)
            with self.assertRaises(RuntimeError):p.guard([3.]*7)
            with self.assertRaises(RuntimeError):p.guard([.1]*7)  # Synthetic coincident axes are singular.

    def test_stationary_and_gripper_completion_boundaries(self):
        with tempfile.TemporaryDirectory() as directory:
            root=Path(directory);io=FakeIO();executor=JointExecutor(io,None,root/'offline_checker',root)
            result=executor.read_pose(['read_pose']);self.assertEqual(result.returncode,0)
            self.assertEqual(json.loads(result.stdout)['stationary_check']['duration_ms'],500);self.assertEqual(io.steps,500)
            command=root/'gripper_input';command.write_text('.02\n.02\n.001\n0\n')
            before=io.steps;result=executor.gripper(['gripper_width',str(command),'--execute'])
            self.assertEqual(result.returncode,0);self.assertEqual(io.moves,0);self.assertEqual(io.steps-before,100)
            command.write_text('.02\n.02\n.001\n1\n');before=io.steps
            self.assertEqual(executor.gripper(['gripper_width',str(command),'--execute']).returncode,1)
            self.assertEqual(io.steps,before)  # Unknown SDK held flag is not fabricated.
            io.width=.0152;command.write_text('.014\n.02\n.001\n2\n.0168\n')
            io.move_gripper=lambda width,speed:False
            self.assertEqual(executor.gripper(['gripper_width',str(command),'--execute']).returncode,1)
            before=io.steps;io.move_gripper=lambda width,speed:True
            result=executor.gripper(['gripper_width',str(command),'--execute'])
            self.assertEqual(result.returncode,0);self.assertEqual(io.steps-before,100)
            self.assertIsNone(json.loads(result.stdout.splitlines()[1].split(' ',1)[1])['is_grasped'])

    def test_process_allowlist_and_import_restoration(self):
        class Backend:
            def read_pose(self,args):return subprocess.CompletedProcess(args,0,'synthetic','')
            def check(self,args):return subprocess.CompletedProcess(args,0,'checked','')
            def gripper(self,args):return subprocess.CompletedProcess(args,0,'width','')
            def process(self,args):return ('simulated',args)
        with tempfile.TemporaryDirectory() as directory:
            root=Path(directory);teaching=root/'teaching';teaching.mkdir();pins={}
            for name in MODULES:
                code="from pathlib import Path\nimport subprocess\nHERE=Path(__file__).parent\ndef main():\n    return subprocess.run([str(HERE/'read_pose')],capture_output=True,text=True).returncode\n"
                path=teaching/(name+'.py');path.write_text(code);pins['teaching/'+path.name]=hashlib.sha256(path.read_bytes()).hexdigest()
            manifest=root/'SOURCE.json';manifest.write_text(json.dumps({'commit':'13f37dad1980bcbc4491b7f27d8962602e49fea0','executable_hardware_helpers_included':False,'sha256':pins}))
            saved_path=sys.path[:];saved_modules={name:sys.modules.get(name) for name in MODULES};saved_run=subprocess.run
            try:
                with SharedStack(teaching,Backend(),source_manifest=manifest) as shared:
                    self.assertEqual(shared.move('3',relative_z_mm=1),0)
                    facade=shared.modules['move_xyz'].subprocess
                    self.assertEqual(facade.run([str(teaching/'read_pose')]).stdout,'synthetic')
                    for command in (['ssh','172.16.0.2'],[str(teaching/'record.py')],[str(teaching/'joint_move'),'a','b','--execute']):
                        with self.assertRaises(RuntimeError):facade.run(command)
                    with self.assertRaises(RuntimeError):facade.Popen([str(teaching/'arc_move'),'a','b','--execute'])
                    self.assertIs(subprocess.run,saved_run)
                    raise RuntimeError('synthetic exit')
            except RuntimeError as error:self.assertEqual(str(error),'synthetic exit')
            self.assertEqual(sys.path,saved_path)
            for name in MODULES:self.assertIs(sys.modules.get(name),saved_modules[name])
            self.assertIs(subprocess.run,saved_run)


if __name__=='__main__':unittest.main()
