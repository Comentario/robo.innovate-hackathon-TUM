"""Round2: source-only velocity iterations16; unchanged full-stack idle gate."""
import hashlib
import json
import os
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))


def main():
    if os.environ.get('ROBO_PUEUE_JOB') != '1' or os.environ.get('OSQP_EPSILON') != '1e-4':
        raise RuntimeError('Round2 requires default Pueue and explicit baseline numerical epsilon1e-4')
    directory = Path(__file__).resolve().parent
    protocol = json.loads((directory/'round2_velocity16_protocol.json').read_text())
    if hashlib.sha256((directory/'protocol.json').read_bytes()).hexdigest() != protocol['baseline_protocol_sha256']:
        raise RuntimeError('Baseline idle protocol changed')
    for path, digest in protocol['frozen_inputs'].items():
        if hashlib.sha256((ROOT/path).read_bytes()).hexdigest() != digest:
            raise RuntimeError('Frozen round2 input changed: '+path)
    from experiments.final_workcell_20261024 import scene as final_scene
    from experiments.final_workcell_20261024 import render_core
    from run_idle import run_idle
    original_factory = final_scene.make_env_cfg
    factory_audit = {}

    def factory(cfg, capture=False):
        import omni.kit.app
        from isaacsim.core.utils.extensions import enable_extension
        manager = omni.kit.app.get_app().get_extension_manager()
        enabled_before = manager.is_extension_enabled('omni.isaac.dynamic_control')
        if not enabled_before and not enable_extension('omni.isaac.dynamic_control'):
            raise RuntimeError('Installed dynamic_control extension could not be activated')
        env = original_factory(cfg, capture=capture)
        changed = []
        for name, asset in vars(env.scene).items():
            if name.startswith('brick_'):
                props = asset.spawn.rigid_props
                before = props.to_dict()
                if before['solver_position_iteration_count'] != 32 or before['solver_velocity_iteration_count'] != 4:
                    raise RuntimeError('Expected pinned authored source counts32/4 before variant')
                props.solver_velocity_iteration_count = 16
                after = props.to_dict()
                if after != {**before, 'solver_velocity_iteration_count': 16}:
                    raise RuntimeError('Factory modified more than source velocity iterations')
                changed.append(name)
        factory_audit.update(configured_before={'position': 32, 'velocity': 4},
            configured_after={'position': 32, 'velocity': 16}, configured_candidates=changed,
            note='Factory square-grid candidates are pruned to the confirmed300 by unchanged renderer guards',
            extension_enabled_before=enabled_before, extension_activation='Process-local installed extension only')
        return env

    def callback(**context):
        from pxr import PhysxSchema, UsdPhysics
        from isaaclab.sim import get_current_stage
        from omni.isaac.dynamic_control import _dynamic_control
        from bricksim.core import get_breakage_thresholds, get_assembly_thresholds
        from diagnose_breakage import threshold_snapshot
        output, sim = Path(context['output']), context['sim']
        dc = _dynamic_control.acquire_dynamic_control_interface()
        source = ['/World/envs/env_0/'+brick.name for brick in context['bricks']]
        controls = ['/World/envs/env_0/plate_source', '/World/envs/env_0/plate_mixed',
                    '/World/envs/env_0/Robot/fr3_link0']
        stage = get_current_stage()
        scene_properties = []
        for prim in stage.Traverse():
            if prim.IsA(UsdPhysics.Scene):
                values = {name: prim.GetAttribute('physxScene:'+name).Get() for name in (
                    'solverType', 'minVelocityIterationCount', 'maxVelocityIterationCount',
                    'minPositionIterationCount', 'maxPositionIterationCount')}
                if (str(values['solverType']).upper() != 'TGS'
                    or values['minVelocityIterationCount'] is None or values['maxVelocityIterationCount'] is None
                    or not values['minVelocityIterationCount'] <= 16 <= values['maxVelocityIterationCount']):
                    raise RuntimeError('USD PhysicsScene solver/clamps do not support the declared16-iteration variant')
                scene_properties.append({'path': str(prim.GetPath()), **values})
        if not scene_properties:
            raise RuntimeError('No USD PhysicsScene available for solver/clamp verification')

        def readback():
            rows = {}
            for path in source+controls:
                handle = dc.get_rigid_body(path)
                props = dc.get_rigid_body_properties(handle) if handle != _dynamic_control.INVALID_HANDLE else None
                usd = PhysxSchema.PhysxRigidBodyAPI.Get(stage, path)
                available = props is not None and hasattr(props, 'solver_velocity_iteration_count')
                row = {'status': 'available' if available else 'unavailable',
                    'authored_position': usd.GetSolverPositionIterationCountAttr().Get(),
                    'authored_velocity': usd.GetSolverVelocityIterationCountAttr().Get()}
                if available:
                    row.update(runtime_position=int(props.solver_position_iteration_count),
                               runtime_velocity=int(props.solver_velocity_iteration_count))
                rows[path] = row
            return rows

        def verify_source(rows):
            if len(source) != 300 or any(rows[path].get('runtime_position') != 32
                or rows[path].get('runtime_velocity') != 16 for path in source):
                raise RuntimeError('Actual source actor iteration readback is not32/16 for all300')

        initial = readback()
        breakage_initial = threshold_snapshot(get_breakage_thresholds())
        assembly = get_assembly_thresholds()
        assembly_initial = {'enabled': assembly.enabled, 'required_force': assembly.required_force}
        report = {'schema': 'round2-source-iteration-readback-v1', 'protocol': protocol,
            'factory': factory_audit, 'source_paths': source, 'control_paths': controls, 'initial': initial,
            'getter_module': _dynamic_control.__file__,
            'getter_module_sha256': hashlib.sha256(Path(_dynamic_control.__file__).read_bytes()).hexdigest(),
            'scene_velocity_clamps': [sim.cfg.physx.min_velocity_iteration_count, sim.cfg.physx.max_velocity_iteration_count],
            'usd_physics_scenes': scene_properties,
            'native_breakage_initial': breakage_initial, 'native_assembly_initial': assembly_initial,
            'runtime_before4_measured': False, 'executed_island_iteration_counter_available': False}
        (output/'solver_iterations.json').write_text(json.dumps(report, indent=2)+'\n')
        verify_source(initial)
        try:
            run_idle(**context)
        finally:
            # Only republish success after terminal property verification.
            (output/'idle_complete.json').unlink(missing_ok=True)
            terminal = readback()
            report['terminal'] = terminal
            report['native_breakage_terminal'] = threshold_snapshot(get_breakage_thresholds())
            assembly = get_assembly_thresholds()
            report['native_assembly_terminal'] = {'enabled': assembly.enabled, 'required_force': assembly.required_force}
            (output/'solver_iterations.json').write_text(json.dumps(report, indent=2)+'\n')
            verify_source(terminal)
            if report['native_breakage_terminal'] != breakage_initial or report['native_assembly_terminal'] != assembly_initial:
                raise RuntimeError('Native breakage/assembly thresholds changed during round2')
            for path in controls:
                if initial[path]['status'] == terminal[path]['status'] == 'available' and initial[path] != terminal[path]:
                    raise RuntimeError('Plate/robot property control changed during round2')
        idle = json.loads((output/'idle_report.json').read_text())
        idle.update(round2_velocity16=True, idle_candidate_only=True, solver_iterations='solver_iterations.json')
        (output/'idle_report.json').write_text(json.dumps(idle, indent=2)+'\n')
        (output/'velocity16_complete.json').write_text(json.dumps({'idle_validated': True, 'capture_validated': False,
            'idle_candidate_only': True, 'postassembly_physics_steps': 120,
            'terminal_runtime_readback_verified': True,
            'report_sha256': hashlib.sha256((output/'idle_report.json').read_bytes()).hexdigest()})+'\n')

    # This wrapper exists only in this queued process; shared factory files stay unchanged.
    final_scene.make_env_cfg = factory
    render_core.main(postassembly_hook=callback)


if __name__ == '__main__':
    main()
