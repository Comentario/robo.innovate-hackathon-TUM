"""Mechanical sequence checks using one freshly generated nominal report."""
from copy import deepcopy
from pathlib import Path
import json,os,unittest
from greenfield.twin import TwinPlant
from greenfield.clearance import pose

class TransferMechanicsTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.config=json.loads((Path(__file__).parents[1]/'config/greenfield_dual.json').read_text())
        cached=os.environ.get('GREENFIELD_MECHANICS_REPORT')
        cls.r=json.loads(Path(cached).read_text()) if cached else TwinPlant(cls.config).run()
        if cls.r['config']!=cls.config:raise AssertionError('Report/configuration mismatch')

    def test_index_moves_every_remaining_brick_by_the_same_amount(self):
        r=self.r;m=r['mechanics'];events=[e for e in r['events'] if e['kind']=='pack_index_start']
        self.assertEqual(len(events),320)
        for e in events:
            self.assertIn(len(e['ids']),(40,30,20,10));dx=[]
            for identity in e['ids']:
                s=next(s for s in m['tracks'][identity] if abs(s['t0']-e['t'])<1e-6 and s['label']=='Synchronously index complete remaining pack and receiving rollers')
                dx.append(s['to'][0]-s['from'][0]);self.assertEqual(s['to'][1:],s['from'][1:])
            self.assertLess(max(dx)-min(dx),1e-6)

    def test_pull_off_never_moves_the_held_rows(self):
        r=self.r;m=r['mechanics'];checks=0
        for e in r['events']:
            if e['kind']!='hold_down_confirmed':continue
            held=e['held_ids'];sample=next(s for s in m['tracks'][held[-1]] if s['label']=='Synchronously index complete remaining pack and receiving rollers' and s['t1']<=e['t']+1e-6)
            # Find the following gap confirmation for this nest.
            gap=next(q for q in r['events'] if q['kind']=='row_gap_verified' and q['bay']==e['bay'] and q['nest']==e['nest'] and q['t']>=e['t'])
            for identity in held:
                self.assertFalse(any(s['t0']<gap['t']-1e-7 and s['t1']>e['t']+1e-7 for s in m['tracks'][identity]))
            rear=min(pose(m,i,gap['t'])[0]-.245/2 for i in gap['row'])
            front=max(pose(m,i,gap['t'])[0]+.245/2 for i in held)
            self.assertGreaterEqual(rear-front,.10-1e-6);checks+=1
        self.assertEqual(checks,240)

    def test_every_paddle_stroke_has_one_axis_only(self):
        m=self.r['mechanics'];count=0
        for identity,seq in m['tracks'].items():
            if not identity.startswith(('INFEED-','ROW-PUSHER-')):continue
            for s in seq:
                axes=sum(abs(a-b)>1e-8 for a,b in zip(s['from'],s['to']))
                self.assertLessEqual(axes,1,(identity,s));count+=1
        self.assertGreater(count,1000)

    def test_incoming_row_bricks_clear_the_raised_former(self):
        r=self.r;m=r['mechanics'];count=0
        for b in r['material']:
            for s in m['tracks'][b['id']]:
                if s['label']!='Feed row inlet':continue
                for u in [0,.25,.5,.75,1]:
                    t=s['t0']+u*(s['t1']-s['t0']);brick=pose(m,b['id'],t);paddle=pose(m,f"ROW-PUSHER-{b['cell']}",t)
                    hit=abs(brick[0]-paddle[0])<.245/2+.012-1e-6 and abs(brick[1]-paddle[1])<.069/2+.045-1e-6 and abs(brick[2]-paddle[2])<.067/2+.345-1e-6
                    self.assertFalse(hit,(b['id'],t,brick,paddle))
                count+=1
        self.assertGreater(count,2000)

    def test_pose_is_centered_before_narrow_lane_entry(self):
        r=self.r;starts=[e for e in r['events'] if e['kind']=='piece_centering_start'];self.assertEqual(len(starts),1)
        e=starts[0];self.assertEqual(e['brick'],'B00000');self.assertEqual(e['yaw_deg'],8)
        done=next(q for q in r['events'] if q['kind']=='piece_centering_complete' and q['brick']==e['brick'])
        entry=next(s for s in r['mechanics']['tracks'][e['brick']] if s['label']=='Meter across connected roller bridge')
        self.assertGreaterEqual(entry['t0'],done['t']-1e-6)

    def test_unsafe_yaw_is_inhibited_before_inspection(self):
        c=deepcopy(self.config);c['faults']['piece_yaw_deg']=90
        r=TwinPlant(c).run();self.assertEqual(r['status'],'safe_hold');self.assertIn('orientation outside',r['reason'])
        self.assertFalse(any(s['label']=='Meter across connected roller bridge' for s in r['mechanics']['tracks']['B00000']))

    def test_missing_hold_down_confirmation_inhibits_extraction(self):
        c=deepcopy(self.config);c['faults']['hold_down_fault_bay']=0
        r=TwinPlant(c).run();self.assertEqual(r['status'],'safe_hold');self.assertIn('hold-down confirmation',r['reason'])
        self.assertFalse(any(s['label']=='Independent pull-off rollers create measured row separation' for seq in r['mechanics']['tracks'].values() for s in seq if s['station']=='feeder_0'))

    def test_completed_batch_keeps_material_and_finite_bins(self):
        r=self.r;self.assertEqual(r['status'],'completed_with_residual_stock');self.assertTrue(r['kpis']['material_balance_ok'])
        self.assertEqual(r['kpis']['bad_placed'],0);self.assertEqual(r['kpis']['discard_cart_exchanges'],0)
        self.assertTrue(all(len(cart['ids'])<=240 for cart in r['discard_cart_state']))

if __name__=='__main__':unittest.main()
