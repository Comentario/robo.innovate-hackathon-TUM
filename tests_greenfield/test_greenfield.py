"""Behavioral checks for the independent, synthetic greenfield concept."""
from copy import deepcopy
import json, unittest
from pathlib import Path
from collections import Counter
from greenfield.model import Plant, pattern
from greenfield.report import audit, equipment_checks
from greenfield.clearance import pose, sampled_material_clearance
ROOT=Path(__file__).resolve().parents[1]

class GreenfieldTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.config=json.loads((ROOT/'config/greenfield.json').read_text())
        cls.base=Plant(cls.config).run()

    def run_variant(self,**changes):
        c=deepcopy(self.config);c.update(changes);return Plant(c).run()

    def test_conservation_and_complete_pallet_release(self):
        r=self.base;k=r['kpis']
        self.assertEqual(r['status'],'completed_with_residual_stock')
        self.assertEqual(k['inspected'],1600)
        self.assertEqual(sum(k[x] for x in ('shipped_bricks','partial_pallet_bricks','reject_bricks','quarantine_bricks','residual_wip')),1600)
        self.assertTrue(audit(r)['continuous_tracks'])
        self.assertGreater(k['full_pallets'],0)
        for p in r['pallets']:self.assertEqual(len(set(p)),560)
        self.assertEqual(k['bad_placed'],0)
        self.assertTrue(all(x['within_envelope'] for x in equipment_checks(self.config)))

    def test_uncertainty_never_requires_manual_classification(self):
        r=self.run_variant(input_stacks=1,uncertain_rate=1,reinspection_resolution=0,quarantine_capacity=1000)
        self.assertEqual(r['kpis']['quarantine_bricks'],800)
        self.assertEqual(r['kpis']['reinspected'],800)
        self.assertEqual(r['kpis']['placed_bricks'],0)
        self.assertEqual(r['status'],'completed_with_residual_stock')
        self.assertTrue(all(b['observed']=='quarantine' for b in r['material']))

    def test_bounded_faults_confirm_recovery(self):
        r=self.base
        started=[e for e in r['events'] if e['kind']=='recovery_start']
        complete=[e for e in r['events'] if e['kind']=='recovery_complete']
        self.assertEqual(len(started),2);self.assertEqual(len(complete),2)
        self.assertEqual(r['kpis']['automatic_recoveries'],len(complete))
        self.assertTrue(all(a['t']<b['t'] for a,b in zip(started,complete)))

    def test_out_of_range_alignment_holds_material(self):
        f={**self.config['faults'],'alignment_error_m':.020}
        r=self.run_variant(faults=f)
        self.assertEqual(r['status'],'safe_hold')
        self.assertIn('Alignment outside',r['reason'])
        self.assertEqual(r['kpis']['full_pallets'],0)
        self.assertGreater(r['locations'].get('alignment_hold',0),0)

    def test_missing_confirmation_inhibits_transfer(self):
        r=self.run_variant(faults={**self.config['faults'],'critical_sensor_layer':2})
        self.assertEqual(r['status'],'safe_hold')
        layer=next(x for x in r['layers'] if x['index']==2)
        for identity in layer['ids']:
            self.assertFalse(any(s['station']=='stacker' for s in r['mechanics']['tracks'][identity]))
        self.assertEqual(r['kpis']['full_pallets'],0)

    def test_alternative_uses_same_material_and_decisions(self):
        r=self.run_variant(cells=2,accepted_overflow_capacity=100)
        self.assertEqual(r['status'],'completed_with_residual_stock')
        signature=lambda x:[(b['id'],b['shade'],b['good'],b['observed']) for b in x['material']]
        self.assertEqual(signature(r),signature(self.base))
        self.assertNotEqual(r['kpis']['released_good_bph'],self.base['kpis']['released_good_bph'])

    def test_truth_is_not_an_acceptance_oracle(self):
        r=self.run_variant(input_stacks=1,defect_rate=1,false_accept_rate=1,uncertain_rate=0)
        self.assertGreater(r['kpis']['bad_placed'],0)
        self.assertEqual(r['kpis']['formed_good'],0)
        self.assertEqual(r['kpis']['released_good_bph'],0)
        self.assertTrue(all(b['observed']=='accepted' for b in r['material']))

    def test_mix_and_lowering_geometry(self):
        r=self.base;m=r['mechanics'];byid={b['id']:b for b in r['material']}
        for p in r['pallets']:
            ys=Counter(round(pose(m,i,r['simulated_seconds'])[1],6) for i in p)
            self.assertEqual(len(ys),14);self.assertEqual(set(ys.values()),{40})
            levels=sorted(ys)
            for a,b in zip(levels,levels[1:]):self.assertAlmostEqual(b-a,.069,places=6)
            self.assertEqual(len({byid[i]['product_id'] for i in p}),1)
        self.assertTrue(all(p['monochrome_vertical_columns']==0 for p in r['pallet_mix']))
        for layer in r['layers']:
            self.assertEqual(sorted(layer['counts'].values()),[13,13,14])
            self.assertEqual(layer['monochrome_rows']+layer['monochrome_columns'],0)

    def test_initial_stack_and_transfers_preserve_pitch(self):
        m=self.base['mechanics'];t=30
        for k in range(1,10):
            a=pose(m,f'B{80+k-1:05}',t);b=pose(m,f'B{80+k:05}',t)
            self.assertAlmostEqual(b[2]-a[2],.067)
            self.assertAlmostEqual(b[0],a[0])
        self.assertTrue(sampled_material_clearance(self.base,96)['passed'])

    def test_release_rate_and_release_event_follow_motion(self):
        r=self.base
        self.assertAlmostEqual(r['kpis']['released_good_bph'],r['kpis']['shipped_good']*3600/r['simulated_seconds'],places=3)
        for event in (e for e in r['events'] if e['kind']=='pallet_released'):
            tracks=r['mechanics']['tracks'][f"P-OUT-{event['pallet']}"]
            release=next(s for s in tracks if s['station']=='pallet_out')
            self.assertAlmostEqual(event['t'],release['t1'],places=5)

    def test_configuration_rejects_unsupported_envelopes(self):
        for change in ({'brick_mass_kg':10},{'buffer_cells_per_shade':40},{'cells':3},
                       {'speeds':{**self.config['speeds'],'gantry_xy_m_s':3}},
                       {'recipe':[1,0,0]}):
            with self.subTest(change=change),self.assertRaises(ValueError):Plant({**self.config,**change})

    def test_output_guides_open_before_pallet_travel(self):
        r=self.base;m=r['mechanics']
        for identity,seq in m['tracks'].items():
            if not identity.startswith('P-OUT-'):continue
            for stroke in seq:
                if stroke['station'] not in ('pallet_out','pallet_in'):continue
                # Both full-pallet discharge and empty-pallet entry need an open path.
                if stroke['label']=='Index downstream pallet accumulation':continue
                for t in (stroke['t0'],(stroke['t0']+stroke['t1'])/2,stroke['t1']-1e-5):
                    self.assertGreater(pose(m,'GUIDE-GATE',t)[1]-.675,1.25)

    def test_layer_transfer_is_rigid(self):
        groups={}
        for identity,seq in self.base['mechanics']['tracks'].items():
            if not identity.startswith('B'):continue
            for s in seq:
                if s['label'] in ('Transfer mixed layer to guided well','Unload single layer'):
                    delta=tuple(round(b-a,7) for a,b in zip(s['from'],s['to']))
                    groups.setdefault((s['station'],s['t0']),[]).append(delta)
        self.assertTrue(groups)
        for deltas in groups.values():
            self.assertEqual(len(deltas),40);self.assertEqual(len(set(deltas)),1)

    def test_common_shuttle_activity_cannot_exceed_elapsed_time(self):
        for a in self.base['handling_activity']:
            self.assertGreater(a['busy_s'],0)
            self.assertLessEqual(a['active_fraction'],1)

    def test_pattern_has_constrained_counts_and_varies(self):
        for offset in range(3):
            p=pattern(4,10,[13,13,14],offset)
            self.assertEqual(Counter(p),{0:13,1:13,2:14})
            self.assertTrue(all(len(set(p[r*10:r*10+10]))>1 for r in range(4)))
            self.assertTrue(all(len({p[r*10+c] for r in range(4)})>1 for c in range(10)))

if __name__=='__main__':unittest.main()
