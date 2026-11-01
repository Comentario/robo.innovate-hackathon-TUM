"""Final round: one PGS full-stack/reserved idle setting, no physical tuning."""
import argparse
import hashlib
import json
import os
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[2]
HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT/'experiments/stage2_idle_20261025'))


def main():
    parser = argparse.ArgumentParser(add_help=False)
    parser.add_argument('--phase', choices=('B','C'), required=True)
    args, remaining = parser.parse_known_args()
    sys.argv = [sys.argv[0], *remaining]
    if os.environ.get('ROBO_PUEUE_JOB') != '1' or os.environ.get('OSQP_EPSILON') != '1e-4':
        raise RuntimeError('Final round requires default Pueue and baseline epsilon1e-4')
    protocol = json.loads((HERE/'protocol.json').read_text())
    idle_protocol = json.loads((HERE/protocol['phases'][args.phase]['config']).read_text())
    for path, digest in protocol['frozen_inputs'].items():
        if hashlib.sha256((ROOT/path).read_bytes()).hexdigest() != digest:
            raise RuntimeError('Frozen round3 input changed: '+path)
    from experiments.final_workcell_20261024 import scene as final_scene, render_core
    from experiments.partial_disassembly_20261024.render_adapter import prepare_case
    from run_idle import run_idle
    from diagnose_breakage import threshold_snapshot
    original_factory = final_scene.make_env_cfg
    factory_audit = {}

    def factory(cfg, capture=False):
        import omni.kit.app
        from isaacsim.core.utils.extensions import enable_extension
        manager = omni.kit.app.get_app().get_extension_manager()
        enabled_before = manager.is_extension_enabled('omni.isaac.dynamic_control')
        if not enabled_before and not enable_extension('omni.isaac.dynamic_control'):
            raise RuntimeError('Installed dynamic_control getter extension unavailable')
        env = original_factory(cfg, capture=capture)
        before = env.sim.physx.to_dict()
        if before['solver_type'] != 1:
            raise RuntimeError('Pinned factory baseline must be TGS1')
        env.sim.physx.solver_type = 0
        after = env.sim.physx.to_dict()
        if after != {**before, 'solver_type':0}:
            raise RuntimeError('More than the scene solver type changed')
        # The shared renderer prunes factory candidates to the active design.
        for name, asset in vars(env.scene).items():
            if name.startswith('brick_'):
                props = asset.spawn.rigid_props
                if props.solver_position_iteration_count != 32 or props.solver_velocity_iteration_count != 4:
                    raise RuntimeError('Source actor configuration must remain32/4, not round2 variant16')
        factory_audit.update(before=before, after=after, extension_enabled_before=enabled_before,
            extension_activation='Process-local installed getter only; no runtime setter')
        return env

    def callback(**context):
        from pxr import PhysxSchema, UsdPhysics
        from isaaclab.sim import get_current_stage
        from omni.isaac.dynamic_control import _dynamic_control
        import bricksim.core as core
        output, sim, robot = Path(context['output']), context['sim'], context['robot']
        if hashlib.sha256(Path(core.__file__).read_bytes()).hexdigest() != protocol['native_core_sha256']:
            raise RuntimeError('Installed native binary differs from baseline')
        dc = _dynamic_control.acquire_dynamic_control_interface()
        source = ['/World/envs/env_0/'+brick.name for brick in context['bricks']]
        controls = ['/World/envs/env_0/plate_source','/World/envs/env_0/plate_mixed','/World/envs/env_0/Robot/fr3_link0']
        stage = get_current_stage()

        def settings():
            scenes = []
            for prim in stage.Traverse():
                if prim.IsA(UsdPhysics.Scene):
                    values = {name:prim.GetAttribute('physxScene:'+name).Get() for name in (
                        'solverType','minVelocityIterationCount','maxVelocityIterationCount',
                        'minPositionIterationCount','maxPositionIterationCount')}
                    if (str(values['solverType']).upper() != 'PGS'
                        or not values['minVelocityIterationCount'] <= 4 <= values['maxVelocityIterationCount']
                        or not values['minPositionIterationCount'] <= 32 <= values['maxPositionIterationCount']):
                        raise RuntimeError('USD PhysicsScene is not the declared PGS32/4-capable scene')
                    scenes.append({'path':str(prim.GetPath()), **values})
            if not scenes: raise RuntimeError('No USD PhysicsScene available')
            actors = {}
            for path in source+controls:
                handle = dc.get_rigid_body(path)
                props = dc.get_rigid_body_properties(handle) if handle != _dynamic_control.INVALID_HANDLE else None
                usd = PhysxSchema.PhysxRigidBodyAPI.Get(stage,path)
                row = {'authored_position':usd.GetSolverPositionIterationCountAttr().Get(),
                    'authored_velocity':usd.GetSolverVelocityIterationCountAttr().Get(),
                    'runtime_status':'available' if props is not None else 'unavailable'}
                if props is not None:
                    row.update(runtime_position=int(props.solver_position_iteration_count),
                        runtime_velocity=int(props.solver_velocity_iteration_count))
                actors[path] = row
            if len(source) != idle_protocol['expected_source_bricks'] or any(
                actors[path].get('runtime_position') != 32 or actors[path].get('runtime_velocity') != 4
                or actors[path]['authored_position'] != 32 or actors[path]['authored_velocity'] != 4 for path in source):
                raise RuntimeError('All active source actors must read back authored/runtime32/4')
            assembly = core.get_assembly_thresholds()
            return {'physics_scenes':scenes,'actor_settings':actors,
                'native_breakage':threshold_snapshot(core.get_breakage_thresholds()),
                'native_assembly':{'enabled':assembly.enabled,'required_force':assembly.required_force},
                'robot_joint_positions':robot.root_physx_view.get_dof_positions()[0].cpu().numpy().tolist(),
                'robot_joint_velocities':robot.root_physx_view.get_dof_velocities()[0].cpu().numpy().tolist()}

        initial = settings()
        expected_breakage = json.loads((HERE/'A_fixture.json').read_text())['breakage_thresholds']
        expected_breakage['debug_dump'] = False
        if initial['native_breakage'] != expected_breakage or initial['native_assembly'] != {'enabled':False,'required_force':1.0}:
            raise RuntimeError('Native physical thresholds/switches differ from baseline')
        report = {'phase':args.phase,'solver_type_configured':'PGS','factory':factory_audit,
            'changed_fields':['solver_type:TGS->PGS'],'source_paths':source,'control_paths':controls,
            'native_core_sha256':protocol['native_core_sha256'],'OSQP_EPSILON':os.environ['OSQP_EPSILON'],
            'dt_s':sim.get_physics_dt(),'initial':initial,'terminal':None,
            'runtime_getter_module':_dynamic_control.__file__,
            'runtime_getter_sha256':hashlib.sha256(Path(_dynamic_control.__file__).read_bytes()).hexdigest(),
            'executed_island_iteration_counter_available':False,
            'settings_scope':'Actor property readback and USD scene solver, not a measured island iteration counter'}
        (output/'pgs_settings.json').write_text(json.dumps(report,indent=2)+'\n')
        try:
            run_idle(**context, protocol_override=idle_protocol)
        finally:
            # The inherited marker is provisional until terminal settings pass.
            (output/'idle_complete.json').unlink(missing_ok=True)
            terminal = settings(); report['terminal'] = terminal
            (output/'pgs_settings.json').write_text(json.dumps(report,indent=2)+'\n')
            if (terminal['physics_scenes'] != initial['physics_scenes']
                or terminal['native_breakage'] != initial['native_breakage']
                or terminal['native_assembly'] != initial['native_assembly']
                or any(terminal['actor_settings'][p] != initial['actor_settings'][p] for p in source+controls)):
                raise RuntimeError('Solver/physical actor/native settings changed during PGS test')
        idle = json.loads((output/'idle_report.json').read_text())
        (output/'pgs_idle_complete.json').write_text(json.dumps({'phase':args.phase,'idle_candidate_only':True,
            'idle_validated':True,'capture_validated':False,'postassembly_physics_steps':120,
            'terminal_settings_verified':True,
            'report_sha256':hashlib.sha256((output/'idle_report.json').read_bytes()).hexdigest(),
            'settings_sha256':hashlib.sha256((output/'pgs_settings.json').read_bytes()).hexdigest()})+'\n')

    final_scene.make_env_cfg = factory
    render_core.main(case_adapter=prepare_case if args.phase == 'C' else None, postassembly_hook=callback)


if __name__ == '__main__': main()
