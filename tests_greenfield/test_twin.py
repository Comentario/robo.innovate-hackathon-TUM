"""Logistics invariants for the two-line layout, independent of graphics."""
from copy import deepcopy
from pathlib import Path
import json, unittest
from greenfield.twin import TwinPlant
from greenfield.report import audit
from greenfield.clearance import pose,sampled_material_clearance

class TwinTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.config=json.loads((Path(__file__).parents[1]/'config/greenfield_dual.json').read_text())
        cls.base=TwinPlant(cls.config).run()

    def test_inventory_arrives_on_one_cart_before_fork_delivery(self):
        r=self.base;m=r['mechanics'];arrived=next(e['t'] for e in r['events'] if e['kind']=='inventory_arrived')
        delivered=[e for e in r['events'] if e['kind']=='stack_delivered']
        self.assertEqual(len(delivered),4);self.assertEqual({e['line'] for e in delivered},{0,1})
        self.assertTrue(all(e['t']>arrived for e in delivered))
        for b in r['material']:
            seq=m['tracks'][b['id']];self.assertEqual(seq[0]['station'],'inventory_cart')
            self.assertAlmostEqual(seq[0]['to'][0]-seq[0]['from'][0],4)

    def test_local_dehackers_actually_overlap_with_shorter_envelope(self):
        r=self.base;m=r['mechanics'];ranges=[]
        for line,z in enumerate(m['line_z']):
            seq=[s for s in m['tracks'][f'TOOL-dehack_{line}'] if s['label']=='Unload single layer']
            self.assertEqual(len(seq),40)
            self.assertTrue(all(abs(s['from'][2]-z)<5.4 and abs(s['to'][2]-z)<5.4 for s in seq))
            ranges.append(seq)
        self.assertTrue(any(max(a['t0'],b['t0'])<min(a['t1'],b['t1']) for a in ranges[0] for b in ranges[1]))

    def test_both_first_pallets_are_raised_before_the_first_layer(self):
        r=self.base;m=r['mechanics'];byid={b['id']:b for b in r['material']}
        for line in range(2):
            events=[e for e in r['events'] if e['kind']=='layer_stacked' and e['line']==line]
            self.assertTrue(events)
            for event in events[:14]:
                layer=next(x for x in r['layers'] if x['index']==event['layer'])
                wood=pose(m,f"P-OUT-{event['pallet']}",event['t'])
                # At the end of every descent, bottom layer lies on the wood deck.
                pallet_layers=[x for x in r['layers'] if x['index'] in {e['layer'] for e in events if e['t']<=event['t'] and e['pallet']==event['pallet']}]
                lowest=min(pose(m,i,event['t'])[1] for x in pallet_layers for i in x['ids'])
                self.assertAlmostEqual(lowest-.069/2,wood[1]+.07,places=5)
        self.assertEqual({p['line'] for p in r['delivered_pallets']},{0,1})

    def test_merge_is_exclusive_and_every_delivered_pallet_is_on_dispatch_cart(self):
        r=self.base;m=r['mechanics'];inside=False
        for e in r['events']:
            if e['kind']=='merge_enter':self.assertFalse(inside);inside=True
            if e['kind']=='merge_exit':self.assertTrue(inside);inside=False
        self.assertFalse(inside);self.assertEqual(r['kpis']['full_pallets'],4)
        t=r['simulated_seconds'];cart=pose(m,'OUTPUT-CART',t)
        self.assertTrue(r['kpis']['output_cart_dispatched'])
        for p in r['delivered_pallets']:
            wood=pose(m,p['wood'],t)
            self.assertAlmostEqual(wood[0],cart[0])
            self.assertLessEqual(abs(wood[2]-cart[2]),2.02501)
            self.assertEqual(len(set(p['ids'])),560)

    def test_one_discard_stream_keeps_both_reasons_and_exchanges_carts(self):
        r=self.base;seen=[]
        for cart in r['discard_cart_state']:
            self.assertLessEqual(len(cart['ids']),cart['capacity']);seen+=cart['ids']
        seen += [i for ids in r['disposal_ids'] for i in ids]
        self.assertEqual(len(set(seen)),len(seen));self.assertEqual(len(seen),r['kpis']['discard_bricks'])
        self.assertGreater(r['kpis']['quarantine_bricks'],0);self.assertGreater(r['kpis']['reject_bricks'],0)
        self.assertEqual(r['kpis']['discard_cart_exchanges'],2)
        self.assertEqual(len([e for e in r['events'] if e['kind']=='discard_cart_removed']),2)
        self.assertEqual(len([e for e in r['events'] if e['kind']=='discard_cart_emptied']),2)
        self.assertEqual(len([e for e in r['events'] if e['kind']=='discard_cart_returned']),2)
        self.assertTrue(all(b.get('discard_reason') in ('reject','quarantine') for b in r['material'] if b['id'] in set(seen)))

    def test_unavailable_collection_blocks_without_reclassifying_or_losing_material(self):
        c=deepcopy(self.config);c['logistics'].update(discard_cart_capacity=20,discard_carts_per_line=1,discard_collection_available=False)
        r=TwinPlant(c).run();self.assertEqual(r['status'],'safe_hold');self.assertIn('collection unavailable',r['reason'])
        self.assertEqual(len({b['id'] for b in r['material']}),3200)
        self.assertLess(r['kpis']['discard_bricks'],3200)

    def test_empty_and_loaded_carts_keep_clearance_through_exchange_and_return(self):
        r=self.base;m=r['mechanics'];ids=[i for i,a in m['auxiliaries'].items() if a['kind']=='discard_cart']
        times=[e['t'] for e in r['events'] if e['kind'] in ('discard_swap_start','discard_swap_complete','discard_cart_emptied','discard_cart_returned')]
        times += [r['simulated_seconds']*k/200 for k in range(201)]
        for t in times:
            ps={i:pose(m,i,t) for i in ids}
            for n,a in enumerate(ids):
                for b in ids[n+1:]:
                    self.assertFalse(abs(ps[a][0]-ps[b][0])<1.1-1e-4 and abs(ps[a][2]-ps[b][2])<1.0-1e-4,(t,a,b))

    def test_payload_and_external_paths_are_audited(self):
        r=self.base;self.assertEqual(r['status'],'completed_with_residual_stock')
        self.assertTrue(audit(r)['continuous_tracks']);self.assertTrue(sampled_material_clearance(r,96)['passed'])
        c=deepcopy(self.config);c['logistics']['bridge_capacity_kg']=1000
        with self.assertRaises(ValueError):TwinPlant(c)

    def test_missing_confirmation_stops_both_lines_before_transfer(self):
        c=deepcopy(self.config);c['faults']['critical_sensor_layer']=2
        r=TwinPlant(c).run();self.assertEqual(r['status'],'safe_hold')
        layer=next(x for x in r['layers'] if x['index']==2)
        for identity in layer['ids']:
            self.assertFalse(any(s['station'].startswith('stacker_') for s in r['mechanics']['tracks'][identity]))

if __name__=='__main__':unittest.main()
