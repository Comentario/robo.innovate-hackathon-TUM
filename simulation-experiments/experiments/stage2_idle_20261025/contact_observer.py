"""Raw public tensor contact observation; no reporter, actor or solver authoring."""
import json
from pathlib import Path

NAMES = ('brick_9_0_3', 'brick_8_0_3', 'brick_8_0_4',
         'brick_9_0_2', 'brick_9_0_4', 'brick_9_5_1')
CAPACITY = 1024


def active_indices(counts, starts, capacity):
    """Keep only initialized buffer entries; preserve per-pair ranges separately."""
    import numpy as np
    result = []
    for count, start in zip(counts.ravel(), starts.ravel()):
        count, start = int(count), int(start)
        if count < 0 or (count and (start < 0 or start+count > capacity)):
            raise RuntimeError('Contact buffer count/start outside the fixed capacity')
        if count:
            result.extend(range(start, start+count))
    return np.asarray(sorted(set(result)), dtype=np.int64)


class ContactObserver:
    def __init__(self, sim, scene, output):
        import carb
        import hashlib
        import inspect
        from pxr import UsdGeom, UsdPhysics, PhysxSchema
        from isaaclab.sim import get_current_stage
        self.sim, self.scene, self.output = sim, scene, Path(output)
        self.directory = self.output/'contact_observations'
        self.directory.mkdir()
        stage = get_current_stage()
        meters_per_unit = UsdGeom.GetStageMetersPerUnit(stage)
        if meters_per_unit != 1.:
            raise RuntimeError('This contact diagnostic requires the existing SI-meter stage')
        actors = {str(p.GetPath()) for p in stage.Traverse() if p.HasAPI(UsdPhysics.RigidBodyAPI)}
        static = set()
        for prim in stage.Traverse():
            if prim.HasAPI(UsdPhysics.CollisionAPI):
                ancestor = prim
                while ancestor and str(ancestor.GetPath()) not in actors:
                    ancestor = ancestor.GetParent()
                if not ancestor:
                    static.add(str(prim.GetPath()))
        filters = sorted(actors|static)
        settings = carb.settings.get_settings()
        before = settings.get('/physics/disableContactProcessing')
        settings.set_bool('/physics/disableContactProcessing', False)
        self.views, resolved = {}, {}
        for name in NAMES:
            path = '/World/envs/env_0/'+name
            prim = stage.GetPrimAtPath(path)
            reporter = PhysxSchema.PhysxContactReportAPI.Get(stage, path)
            if not prim.HasAPI(PhysxSchema.PhysxContactReportAPI) or reporter.GetThresholdAttr().Get() != 0.:
                raise RuntimeError('Existing native zero-threshold reporter required: '+path)
            view = sim.physics_sim_view.create_rigid_contact_view(path,
                filter_patterns=filters, max_contact_data_count=CAPACITY)
            if (view.sensor_count != 1 or list(view.sensor_paths) != [path]
                or view.max_contact_data_count != CAPACITY or view.filter_count < 1 or not view.check()):
                raise RuntimeError('Contact observer sensor path/capacity/handle differs from the fixed protocol')
            # Interface preflight only: step0 values are stale and never evidence.
            normal = view.get_contact_data(dt=1.)
            friction = view.get_friction_data(dt=1.)
            if len(normal) != 6 or len(friction) != 4:
                raise RuntimeError('Unexpected public tensor contact return schema')
            if any(tuple(value.shape) != (1, view.filter_count) for value in (normal[4], normal[5], friction[2], friction[3])):
                raise RuntimeError('Contact count/start shapes do not match the resolved sensor/filter dimensions')
            for value in (*normal, *friction, view.get_net_contact_forces(dt=1.), view.get_contact_force_matrix(dt=1.)):
                value.cpu().numpy()
            self.views[name] = view
            paths = view.filter_paths
            if len(paths) == 1 and isinstance(paths[0], (list, tuple)):
                paths = paths[0]
            resolved_paths = set(paths) if all(isinstance(path, str) for path in paths) else set()
            resolved[name] = {'sensor_paths': view.sensor_paths, 'filter_paths': view.filter_paths,
                'sensor_count': view.sensor_count, 'filter_count': view.filter_count,
                'max_contact_data_count': view.max_contact_data_count,
                'missing_requested_filter_paths': sorted(set(filters)-resolved_paths),
                'extra_resolved_filter_paths': sorted(resolved_paths-set(filters)),
                'filter_coverage_status': 'Path lists require audit; mismatches are unknown, never zero-contact evidence'}
        api_file = Path(inspect.getfile(type(view))).resolve()
        self.metadata = {'schema': 'raw-tensor-contact-observer-v1', 'sensors': list(NAMES),
            'stage_meters_per_unit': meters_per_unit,
            'units': 'World points/COM/separations in meters; dt=1 queries underlying impulses Ns, actual physics dt queries forces N; normal matrices exclude friction',
            'tensor_api_source_file': str(api_file), 'tensor_api_sha256': hashlib.sha256(api_file.read_bytes()).hexdigest(),
            'tensor_extension_version_directory': next((part for part in api_file.parts if part.startswith('omni.physics.tensors-')), None),
            'preflight': 'Return schemas and CPU tensor access checked before step1; no step0 values interpreted',
            'requested_all_scene_actor_filters': sorted(actors), 'requested_standalone_static_filters': sorted(static),
            'resolved_views': resolved, 'normal_and_friction_capacity_per_view': CAPACITY,
            'observation_setting': {'path': '/physics/disableContactProcessing', 'before': before,
                'after': settings.get('/physics/disableContactProcessing'), 'scope': 'process-local; potentially perturbing, requires baseline-equivalence evaluation'},
            'reporter_authoring': False, 'stabilization_sleep_solver_changes': False,
            'internal_same_component_contacts': 'Native eKILL suppression; zero reports can be structural',
            'normal_sign': 'Raw scalar times reported normal is an unverified candidate convention; compare pair matrix/reciprocal nonzero pairs before interpreting',
            'friction': 'Raw backend friction-anchor vectors at their own points; not indexed with normal-contact points; full tangential completeness unverified',
            'coverage': 'Requested all live scene actors including robot plus standalone static colliders; resolved paths and net-normal comparison must be audited. Missing pairs are unknown.',
            'positive_reporting_control': 'Not established; no actor is added/moved. All-zero observations do not prove no load.',
            'time_alignment': 'After completed sim.step and scene.update, before next step; COM pre/post interval saved; substep contact timing is not exposed'}
        (self.directory/'metadata.json').write_text(json.dumps(self.metadata, indent=2)+'\n')
        self.pre_com = {}

    def before_step(self):
        self.time_before = float(self.sim.current_time)
        self.pre_com = {name: self.scene[name].data.root_com_pos_w[0].cpu().numpy().copy()
                        for name in NAMES}

    def sample(self, step):
        import numpy as np
        if step == 0:
            return {'status': 'not_fresh_step0_ignored'}
        clock = float(self.sim.current_time)
        dt = self.sim.get_physics_dt()
        folder = self.directory/f'step_{step:02d}'
        folder.mkdir()
        summaries = {}
        for name, view in self.views.items():
            copy = lambda value: value.cpu().numpy().copy()
            # These methods share count/start storage: clone EACH tuple before the next query.
            normal = [copy(value) for value in view.get_contact_data(dt=1.)]
            friction = [copy(value) for value in view.get_friction_data(dt=1.)]
            normal_force = [copy(value) for value in view.get_contact_data(dt=dt)]
            friction_force = [copy(value) for value in view.get_friction_data(dt=dt)]
            ni = active_indices(normal[4], normal[5], CAPACITY)
            fi = active_indices(friction[2], friction[3], CAPACITY)
            same_ranges = (np.array_equal(normal[4], normal_force[4]) and np.array_equal(normal[5], normal_force[5])
                and np.array_equal(friction[2], friction_force[2]) and np.array_equal(friction[3], friction_force[3]))
            if not same_ranges:
                raise RuntimeError('Contact ranges changed during no-step dt-scaling observation')
            net = copy(view.get_net_contact_forces(dt=1.))
            matrix = copy(view.get_contact_force_matrix(dt=1.))
            post_com = self.scene[name].data.root_com_pos_w[0].cpu().numpy().copy()
            arrays = {'normal_indices': ni, 'normal_impulses_Ns': normal[0][ni],
                'normal_points_world_m': normal[1][ni], 'normal_vectors_world': normal[2][ni],
                'normal_separations_m': normal[3][ni], 'normal_counts': normal[4], 'normal_starts': normal[5],
                'normal_forces_N': normal_force[0][ni], 'friction_indices': fi,
                'friction_impulses_world_Ns': friction[0][fi], 'friction_points_world_m': friction[1][fi],
                'friction_counts': friction[2], 'friction_starts': friction[3],
                'friction_forces_world_N': friction_force[0][fi], 'all_body_net_normal_impulse_world_Ns': net,
                'filtered_normal_impulse_matrix_world_Ns': matrix,
                'com_before_step_world_m': self.pre_com[name], 'com_after_step_world_m': post_com}
            np.savez_compressed(folder/(name+'.npz'), **arrays)
            saturated = len(ni) >= CAPACITY or len(fi) >= CAPACITY
            finite = all(np.isfinite(value).all() for value in arrays.values())
            summaries[name] = {'file': str((folder/(name+'.npz')).relative_to(self.output)),
                'normal_entries': len(ni), 'friction_entries': len(fi), 'finite': finite,
                'status': 'invalid_data_unknown' if not finite else 'capacity_saturated_or_truncated_unknown' if saturated else 'recorded_coverage_and_sign_unverified',
                'normal_dt_scaling_max_error_Ns': float(np.max(np.abs(normal[0][ni]-normal_force[0][ni]*dt))) if len(ni) and finite else None,
                'friction_dt_scaling_max_error_Ns': float(np.max(np.abs(friction[0][fi]-friction_force[0][fi]*dt))) if len(fi) and finite else None}
        if float(self.sim.current_time) != clock:
            raise RuntimeError('Physics time changed during contact queries')
        if abs(clock-self.time_before-dt) > 1e-7:
            raise RuntimeError('Contact observation interval does not match the frozen physics dt')
        record = {'step': step, 'physics_time_s': clock, 'physics_dt_s': dt,
            'physics_time_before_s': self.time_before, 'physics_time_after_s': clock, 'bodies': summaries,
            'no_fresh_or_nonzero_data_is_not_absence': True}
        with (self.directory/'trace.jsonl').open('a') as trace:
            trace.write(json.dumps(record, allow_nan=False)+'\n')
        return {'status': 'recorded', 'trace': str((self.directory/'trace.jsonl').relative_to(self.output))}
