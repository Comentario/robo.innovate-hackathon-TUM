"""Run pinned teaching Python unchanged behind a local, network-free process seam."""
import hashlib
import importlib.util
import json
from pathlib import Path
import subprocess
import sys

MODULES=('kinematics','audit_kinematics','generate_stack','safe_motion','arc_motion','gripper_width','move_xyz')


def frame_parent_joint_compat(pin):
    """Expose the newer accessor on Pin2, without changing any joint value."""
    frame=pin.Frame
    applied=not hasattr(frame,'parentJoint')
    metadata={'applied':applied,'pinocchio_version':str(getattr(pin,'__version__','UNKNOWN')),
        'accessor':'Frame.parentJoint','source_attribute':'Frame.parent','scope':'process_local_SharedStack_context',
        'pinocchio3_runtime_equivalence_claim':False}
    alias=None
    if applied:
        if not hasattr(frame,'parent'):raise RuntimeError('Pinocchio Frame lacks both parent-joint accessors')
        alias=property(lambda value:value.parent)
        frame.parentJoint=alias
    def restore():
        if applied and frame.__dict__.get('parentJoint') is alias:delattr(frame,'parentJoint')
    return restore,metadata


class ProcessFacade:
    PIPE=subprocess.PIPE
    STDOUT=subprocess.STDOUT

    def __init__(self,directory,executor):self.directory=Path(directory).resolve();self.executor=executor

    def _command(self,command):
        args=list(map(str,command))
        prefix=['powerprofilesctl','launch','--profile','performance','--reason','Franka FCI real-time motion','--appid','franka-teaching']
        if args[:len(prefix)]==prefix:args=args[len(prefix):]
        if not args or Path(args[0]).resolve().parent!=self.directory:raise RuntimeError('Process not in frozen teaching directory')
        return Path(args[0]).name,args

    def run(self,command,**kwargs):
        name,args=self._command(command)
        if name=='read_pose' and len(args)==1:return self.executor.read_pose(args)
        if name=='joint_move' and len(args)==4 and args[3]=='--check':return self.executor.check(args)
        if name=='gripper_width' and len(args)==3 and args[2]=='--execute':return self.executor.gripper(args)
        raise RuntimeError('Unsupported simulation process request: '+str(args))

    def Popen(self,command,**kwargs):
        name,args=self._command(command)
        if name!='joint_move' or len(args)!=4 or args[3] not in ('--preview','--execute'):raise RuntimeError('Unsupported simulation execution request')
        return self.executor.process(args)


class SharedStack:
    """Explicit context restores imports and argv; never modifies subprocess itself.

    Vendor HERE remains its frozen directory. Its request/plan/log files are
    therefore written inside that job snapshot, exactly as the source expects.
    """
    def __init__(self,vendor_dir,executor,*,source_manifest):
        self.directory=Path(vendor_dir).resolve();self.executor=executor
        self.manifest=Path(source_manifest);self.modules={};self.active=False;self.compatibility={};self._frame_restore=None

    def __enter__(self):
        record=json.loads(self.manifest.read_text())
        if record['commit']!='13f37dad1980bcbc4491b7f27d8962602e49fea0' or record['executable_hardware_helpers_included'] is not False:raise RuntimeError('Unexpected teaching source contract')
        for relative,digest in record['sha256'].items():
            path=self.directory.parent/relative
            if hashlib.sha256(path.read_bytes()).hexdigest()!=digest:raise RuntimeError('Changed vendor source: '+relative)
        for name in ('read_pose','joint_move','gripper_width','arc_move','move_xyz'):
            if (self.directory/name).exists():raise RuntimeError('Hardware helper must not exist in simulation snapshot')
        self.old_path=sys.path[:];self.old_argv=sys.argv[:]
        self.old_modules={name:sys.modules.get(name) for name in MODULES}
        self.active=True;sys.path.insert(0,str(self.directory))
        try:
            import pinocchio
            self._frame_restore,self.compatibility['Frame.parentJoint']=frame_parent_joint_compat(pinocchio)
            for name in MODULES:
                spec=importlib.util.spec_from_file_location(name,self.directory/(name+'.py'))
                module=importlib.util.module_from_spec(spec);sys.modules[name]=module;spec.loader.exec_module(module);self.modules[name]=module
            facade=ProcessFacade(self.directory,self.executor)
            for name in ('move_xyz','arc_motion','gripper_width'):self.modules[name].subprocess=facade
            return self
        except BaseException:
            self.__exit__(None,None,None);raise

    def __exit__(self,*args):
        if self.active:
            if self._frame_restore is not None:self._frame_restore();self._frame_restore=None
            for name,previous in self.old_modules.items():
                if previous is None:sys.modules.pop(name,None)
                else:sys.modules[name]=previous
            sys.path[:]=self.old_path;sys.argv[:]=self.old_argv;self.active=False

    def move(self,identifier,*,grasp=False,relative_z_mm=None,execute=True,input_layers_removed=0):
        if not self.active:raise RuntimeError('SharedStack context is required')
        argv=[str(self.directory/'move_xyz.py'),str(identifier),'--input-layers-removed',str(input_layers_removed)]
        if grasp:argv.append('--grasp')
        if execute:argv.append('--execute')
        if relative_z_mm is not None:argv+=['--relative-z-mm',str(relative_z_mm)]
        previous=sys.argv;sys.argv=argv
        try:return self.modules['move_xyz'].main()
        finally:sys.argv=previous

    def command_width(self,action,*,execute=True):
        if not self.active or action not in ('approach','close','release'):raise ValueError('Active context and declared gripper action required')
        return self.modules['gripper_width'].command_width(action,execute)
