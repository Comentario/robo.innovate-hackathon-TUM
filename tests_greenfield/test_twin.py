"""Logistics invariants for the two-line layout, independent of graphics."""
from copy import deepcopy
from pathlib import Path
import json, unittest, os
from greenfield.twin import TwinPlant
from greenfield.report import audit
from greenfield.clearance import pose,sampled_material_clearance

class TwinTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.config=json.loads((Path(__file__).parents[1]/'config/greenfield_dual.json').read_text())
        cls.config['logistics'].update(discard_mode='mobile',discard_carts_per_line=4,discard_cart_capacity=120)
        cached=os.environ.get('GREENFIELD_TEST_REPORT')
        cls.base=json.loads(Path(cached).read_text()) if cached else TwinPlant(cls.config).run()
        if cached and cls.base['config']!=cls.config:raise AssertionError('Cached run configuration differs from tested configuration')

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

    def test_pusher_is_raised_during_every_new_row_arrival(self):
        r=self.base;m=r['mechanics'];L,H,D=m['brick_m']
        for b in r['material']:
            cell=b.get('cell')
            if cell is None:continue
            for stroke in m['tracks'][b['id']]:
                if stroke['label']!='Powered row discharge to infeed':continue
                for u in [0,.25,.5,.75,1]:
                    t=stroke['t0']+(stroke['t1']-stroke['t0'])*u
                    tool=pose(m,f'INFEED-{cell}',t);brick=pose(m,b['id'],t)
                    collision=abs(tool[0]-brick[0])<L/2+.012-1e-6 and abs(tool[1]-brick[1])<H/2+.045-1e-6 and abs(tool[2]-brick[2])<D/2+.025-1e-6
                    self.assertFalse(collision,(b['id'],t,tool,brick))

    def test_every_push_is_at_brick_height_and_rear_face_contact(self):
        r=self.base;m=r['mechanics'];count=0
        for b in r['material']:
            for stroke in m['tracks'][b['id']]:
                if stroke['label']!='Pusher singulates one brick':continue
                cell=b['cell'];count+=1
                for u in [0,.25,.5,.75,1]:
                    t=stroke['t0']+(stroke['t1']-stroke['t0'])*u
                    paddle=pose(m,f'INFEED-{cell}',t);brick=pose(m,b['id'],t)
                    self.assertAlmostEqual(paddle[0]+.012,brick[0]-m['brick_m'][0]/2,places=5)
                    self.assertAlmostEqual(paddle[1]-.045,1.25,places=5)
                    self.assertAlmostEqual(paddle[2],brick[2],places=5)
        self.assertEqual(count,len(r['material']))

    def test_discard_chute_finishes_at_supported_collector_entry(self):
        r=self.base;m=r['mechanics'];count=0
        for b in r['material']:
            seq=m['tracks'][b['id']]
            for k,s in enumerate(seq):
                if s['label']!='Travel down supported full-length discard chute':continue
                count+=1;next_s=seq[k+1]
                self.assertEqual(s['to'],next_s['from']);self.assertAlmostEqual(s['to'][0],7.06)
                self.assertEqual(next_s['label'],'Enter flush collector receiving rollers')
                self.assertEqual(next_s['to'],[6.8,.65,s['to'][2]])
                # 30 mm bridge to the collector edge: less than a brick's support length.
                self.assertLess(7.06-(6.8+.46/2),m['brick_m'][0])
        self.assertEqual(count,r['kpis']['discard_bricks'])

    def test_retention_and_automatic_cart_cycle_are_recorded(self):
        r=self.base;events=r['events']
        cmds=[e for e in events if e['kind']=='retention_command']
        self.assertEqual([e['closed'] for e in cmds],[False,True,False,True]*4)
        for stroke in r['mechanics']['tracks']['INVENTORY-FORK']:
            if stroke['label'] not in ('Lift complete 800-brick stack above local gantries','Lower stack onto receiving dock') and not stroke['label'].startswith('Transfer retained stack'):continue
            last=max((e for e in cmds if e['t']<=stroke['t0']),key=lambda e:e['t'])
            self.assertTrue(last['closed']);self.assertGreaterEqual(stroke['t0']+1e-6,last['t']+last['duration'])
        for e in events:
            if e['kind']!='discard_cart_returned':continue
            states=[x['state'] for x in events if x['kind']=='cart_route_state' and x['cart']==e['cart'] and x['t']<=e['t']]
            self.assertEqual(states[-4:],['Loaded departure','Automatic unloading','Empty return','Available spare'])


class FixedDiscardTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.config=json.loads((Path(__file__).parents[1]/'config/greenfield_dual.json').read_text())
        cached=os.environ.get('GREENFIELD_FIXED_REPORT')
        cls.base=json.loads(Path(cached).read_text()) if cached else TwinPlant(cls.config).run()
        if cls.base['config']!=cls.config:raise AssertionError('Fixed-bin report/configuration mismatch')

    def test_only_two_stationary_bins_exist_at_outer_ends(self):
        r=self.base;m=r['mechanics'];ids=[i for i,a in m['auxiliaries'].items() if a['kind']=='discard_cart']
        self.assertEqual(len(ids),2)
        for line,z in enumerate([-16.5,16.5]):
            key=f'DISCARD-CART-{line}-0';self.assertEqual(m['initial'][key],[6.8,0,z]);self.assertFalse(m['tracks'].get(key,[]))
        self.assertFalse(any(e['kind'] in ('cart_route_state','discard_swap_start','discard_cart_returned') for e in r['events']))
        self.assertEqual(r['kpis']['discard_cart_exchanges'],0);self.assertEqual(r['kpis']['discard_carts_emptied'],0)

    def test_collection_moves_outward_without_hidden_disposal(self):
        r=self.base
        for line in range(2):
            direction=-1 if line==0 else 1
            for seq in r['mechanics']['tracks'].values():
                for s in seq:
                    if s['station']!=f'discard_conveyor_{line}':continue
                    self.assertGreaterEqual(direction*(s['to'][2]-s['from'][2]),0)
                    self.assertEqual(s['to'][0],6.8)
        self.assertEqual(r['disposal_ids'],[[],[]])

    def test_all_discarded_bricks_remain_inside_the_two_bins(self):
        r=self.base;m=r['mechanics'];count=0
        for cart in r['discard_cart_state']:
            center=m['initial'][cart['id']];self.assertLessEqual(len(cart['ids']),240)
            for identity in cart['ids']:
                p=pose(m,identity,r['simulated_seconds']);count+=1
                self.assertLess(abs(p[0]-center[0])+.245/2,.55)
                self.assertLess(abs(p[2]-center[2])+.067/2,.48)
                self.assertGreaterEqual(p[1]-.069/2,.15-1e-6)
                self.assertLessEqual(p[1]+.069/2,.65)
        self.assertEqual(count,r['kpis']['discard_bricks']);self.assertEqual(r['status'],'completed_with_residual_stock')

    def test_discard_crosses_full_flat_deck_before_descending(self):
        r=self.base;count=0
        for identity,seq in r['mechanics']['tracks'].items():
            for k,stroke in enumerate(seq):
                if stroke['label']!='Cross flat receiving deck at inspection height':continue
                count+=1
                self.assertAlmostEqual(stroke['from'][0],9.0)
                self.assertAlmostEqual(stroke['to'][0],8.5)
                self.assertAlmostEqual(stroke['from'][1],1.2845)
                self.assertEqual(stroke['from'][1:],stroke['to'][1:])
                self.assertEqual(seq[k+1]['from'],stroke['to'])
                self.assertEqual(seq[k+1]['label'],'Travel down supported full-length discard chute')
        self.assertEqual(count,r['kpis']['discard_bricks'])

    def test_full_stationary_bin_stops_without_synthetic_emptying(self):
        c=deepcopy(self.config);c['logistics']['discard_cart_capacity']=1;c['defect_rate']=1;c['uncertain_rate']=0
        r=TwinPlant(c).run();self.assertEqual(r['status'],'safe_hold')
        self.assertIn('Stationary discard bin full',r['reason'])
        self.assertTrue(any(e['kind']=='fixed_bin_full' for e in r['events']))
        self.assertEqual(r['kpis']['discard_cart_exchanges'],0)
        self.assertTrue(all(len(cart['ids'])<=1 for cart in r['discard_cart_state']))

if __name__=='__main__':unittest.main()
