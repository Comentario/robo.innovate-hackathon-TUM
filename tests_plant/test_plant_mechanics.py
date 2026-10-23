"""Mechanical trace contracts independent of the rendering engine."""
import json
from pathlib import Path
import unittest

from plant_sim.model import Plant
from plant_sim.mechanics import compile_mechanics, validate_mechanics, position_at

ROOT=Path(__file__).resolve().parents[1]


class MechanicalContracts(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        config_path=ROOT/'config/plant_demo.json'
        if not config_path.exists():config_path=ROOT/'plant_demo.json'
        cls.config=json.loads(config_path.read_text())
        cls.report=Plant(cls.config).run()
        cls.mechanics=compile_mechanics(cls.report)

    def test_every_brick_has_one_identity_and_continuous_nonoverlapping_tracks(self):
        m=self.mechanics
        self.assertEqual(set(m['initial_positions']),{b['id'] for b in self.report['material']})
        audit=validate_mechanics(m)
        self.assertTrue(audit['exclusive_tool_ownership'])
        self.assertGreater(audit['motion_segments'],1600)
        for seq in m['tracks'].values():
            for segment in seq:
                self.assertGreaterEqual(min(p[2] for p in segment['points']),self.config['geometry']['brick_mm'][2]/2000)

    def test_held_material_remains_attached_to_its_tool(self):
        m=self.mechanics;half_height=m['brick_dimensions_m'][1]/2
        for tool,seq in m['tools'].items():
            for segment in seq:
                for fraction in (.15,.25,.5,.75,.85):
                    t=segment['t0']+(segment['t1']-segment['t0'])*fraction
                    head=position_at([segment],segment['points'][0][1:],t)
                    bricks=[position_at(m['tracks'][i],m['initial_positions'][i],t) for i in segment['brick_ids']]
                    reference=[sum(p[0] for p in bricks)/len(bricks),max(p[1] for p in bricks)+half_height,sum(p[2] for p in bricks)/len(bricks)]
                    for a,b in zip(head,reference):self.assertAlmostEqual(a,b,places=5,msg=tool)

    def test_restacking_has_fourteen_physical_layers_per_complete_pallet(self):
        m=self.mechanics;t=self.report['simulated_seconds']
        for index,ids in enumerate(self.report['pallets']):
            positions=[position_at(m['tracks'][i],m['initial_positions'][i],t) for i in ids]
            self.assertEqual(len({round(p[1],6) for p in positions}),14)
            meanx=sum(p[0] for p in positions)/len(positions)
            self.assertAlmostEqual(meanx,22+index*.65,places=5)

    def test_corrected_layer_transfer_is_timed_and_precedes_pairing(self):
        ends={}
        for e in self.report['events']:
            if e['kind']=='operation_start' and e.get('phase')=='Transfer corrected layer':
                self.assertGreater(e['duration'],0)
                ends[e['pair'],e['lane']]=e['t']+e['duration']
            if e['kind']=='operation_start' and e['station']=='pairer':
                self.assertGreaterEqual(e['t'],max(ends[e['pair'],i] for i in (0,1)))

    def test_handoff_has_no_zero_time_geometry_jump(self):
        m=self.mechanics
        for identity,seq in m['tracks'].items():
            for a,b in zip(seq,seq[1:]):
                self.assertEqual(a['points'][-1][1:],b['points'][0][1:])
        pairer=self.mechanics['tools']['pairer']
        self.assertTrue(all(a['t1']<=b['t0'] for a,b in zip(pairer,pairer[1:])))

    def test_timeout_run_preserves_trace_and_original_material(self):
        c=json.loads(json.dumps(self.config));c['fault']={'station':'separator','pair':3}
        r=Plant(c).run();m=compile_mechanics(r)
        self.assertEqual(r['status'],'blocked')
        self.assertEqual(m['stop_time'],r['simulated_seconds'])
        self.assertTrue(validate_mechanics(m)['continuous_brick_tracks'])
        self.assertEqual(len(m['initial_positions']),r['kpis']['input_bricks']+r['kpis']['initial_reserve'])


if __name__=='__main__':unittest.main()
