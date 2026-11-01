"""Synthetic data/interface evidence only; no actual placement or hardware claim."""
import copy
import unittest
import numpy as np
from challenge2.destination_plan import DestinationPlan,route,preferred_B_color,PALETTE,PITCH_M


def reference(theta=0.):
    u=np.array([-np.cos(theta),-np.sin(theta),0.]);v=np.array([np.sin(theta),-np.cos(theta),0.])
    origin=np.array([.4,.1,.1]);r16=np.diag([1.,-1.,-1.]);r17=np.array([[0.,1.,0.],[1.,0.,0.],[0.,0.,-1.]])
    points={'a_0_0_9':origin,'a_0_1_9':origin+.0318*u,'a_1_0_9':origin+.0318*v,
        'a_0_0_8':origin+[0,0,-.0096],'point_03':origin,
        'point_11':[.5,-.3,12.],'point_14':[.3,-.3,13.],'point_15':[.3,-.5,14.]}
    rows=[]
    for name,xyz in points.items():
        a=np.eye(4);a[:3,3]=xyz;a[:3,:3]=r17 if name=='a_0_0_8' else r16
        rows.append({'id':name,'xyz_m':list(xyz),'O_T_EE':a.reshape(-1,order='F').tolist()})
    return {'poses':rows}


class DestinationTests(unittest.TestCase):
    def test_indices_shared_height_and_anchor(self):
        p=DestinationPlan(reference(),['dark_red'])
        a=p.slot('B',0);self.assertEqual((a['n'],a['m'],a['k']),(0,0,0))
        np.testing.assert_allclose(a['position_m'],[.5,-.3,.1-9*.0096],atol=1e-15)
        self.assertEqual(p.slot('B',11)['id'],'b_3_2_0')
        self.assertEqual(p.slot('B',12)['id'],'b_0_0_1')
        np.testing.assert_allclose(np.array(p.slot('B',1)['position_m'])-a['position_m'],[0,-.032,0],atol=1e-15)
        np.testing.assert_allclose(np.array(p.slot('B',3)['position_m'])-a['position_m'],[-.032,0,0],atol=1e-15)
        expected=np.array(a['position_m'])+.5*.032*(p.u-p.v)+[0,0,.0096]
        np.testing.assert_allclose(p.slot('B',12)['position_m'],expected,atol=1e-15)
        for d in ('B','C','D'):
            self.assertAlmostEqual(p.slot(d,0)['position_m'][2],a['position_m'][2])
            for k in (0,1,24):
                layer=[p.slot(d,k*12+i) for i in range(12)]
                mean=np.mean([r['position_m'] for r in layer],axis=0)
                np.testing.assert_allclose(mean,layer[0]['footprint_center_base_m'],atol=1e-15)
                np.testing.assert_allclose(mean[:2],p.centers[d],atol=1e-15)

    def test_native_stud_envelopes_and_proper_parallel_rotation(self):
        p=DestinationPlan(reference(.017),['brown'])
        for k in (0,1):
            layer=[p.slot('B',k*12+i) for i in range(12)]
            for row in layer:
                a=np.asarray(row['T_base_EE']);r=a[:3,:3]
                np.testing.assert_allclose(r.T@r,np.eye(3),atol=1e-12);self.assertAlmostEqual(np.linalg.det(r),1.)
                np.testing.assert_allclose(r[:,2],[0,0,-1],atol=1e-15)
                self.assertAlmostEqual(abs(r[:,0]@row['long_axis_base']),1.)
                np.testing.assert_allclose(np.asarray(row['O_T_EE']).reshape(4,4,order='F'),a,atol=0)
                w,x,y,z=row['quaternion_wxyz'];qr=np.array([[1-2*(y*y+z*z),2*(x*y-z*w),2*(x*z+y*w)],
                    [2*(x*y+z*w),1-2*(x*x+z*z),2*(y*z-x*w)],[2*(x*z-y*w),2*(y*z+x*w),1-2*(x*x+y*y)]])
                np.testing.assert_allclose(qr,r,atol=1e-12)
                self.assertFalse(row['hardware_authorized'])
            long=np.asarray(layer[0]['long_axis_base']);across=np.asarray(layer[0]['across_axis_base'])
            for i,a in enumerate(layer):
                ca=np.asarray(a['footprint_corners_base_m'])
                self.assertAlmostEqual(np.ptp(ca@long),.032);self.assertAlmostEqual(np.ptp(ca@across),.016)
                for b in layer[i+1:]:
                    cb=np.asarray(b['footprint_corners_base_m'])
                    overlap=[min(max(ca@axis),max(cb@axis))-max(min(ca@axis),min(cb@axis)) for axis in (long,across)]
                    self.assertLessEqual(min(overlap),1e-12)
            gap=np.min(np.asarray(layer[3]['footprint_corners_base_m'])@across)-np.max(np.asarray(layer[0]['footprint_corners_base_m'])@across)
            self.assertAlmostEqual(gap,.016)
        self.assertEqual(PITCH_M,.032)  # Deliberately not imported-reference31.8mm.

    def test_routing_preferences_and_confirmation_only(self):
        self.assertEqual(PALETTE,('dark_red','brown','tan'))
        self.assertEqual([route(c,['dark_red'])['destination'] for c in PALETTE],['B','C','D'])
        self.assertEqual([route(c,['tan'])['destination'] for c in PALETTE],['C','D','B'])
        self.assertEqual(route('brown',['tan','brown'])['destination'],'B')
        self.assertEqual(route('reject_4211201',['tan'])['decision'],'reject')
        for label in (None,'UNKNOWN','bright_red'):
            self.assertEqual(route(label,['tan'])['decision'],'abstain')
        self.assertEqual([preferred_B_color(i,['tan','dark_red']) for i in range(4)],['tan','dark_red','tan','dark_red'])
        source=reference();before=copy.deepcopy(source);counts={'B':11};p=DestinationPlan(source,['tan'],counts=counts)
        p.slot('B');p.route('tan');p.preferred_B_color()
        self.assertEqual(p.counts,{'B':11,'C':0,'D':0});self.assertEqual(counts,{'B':11});self.assertEqual(source,before)
        self.assertEqual(p.confirm('B',11),12)
        with self.assertRaises(ValueError):p.confirm('B',11)
        self.assertEqual(p.counts['B'],12)
        full=DestinationPlan(source,['tan'],counts={'B':299})
        self.assertEqual(full.slot('B')['id'],'b_3_2_24');self.assertEqual(full.confirm('B',299),300)
        with self.assertRaises(OverflowError):full.slot('B')
        with self.assertRaises(OverflowError):full.confirm('B',300)
        self.assertEqual(full.counts['B'],300)

    def test_invalid_inputs_and_assumption_readback(self):
        for kwargs in ({'counts':{'B':True}},{'counts':{'B':301}},{'counts':{'A':0}},{'max_layers':0},{'max_layers':26}):
            with self.assertRaises(ValueError):DestinationPlan(reference(),['tan'],**kwargs)
        for requested in ([],['tan','tan'],['blue'],['tan','brown','dark_red','extra']):
            with self.assertRaises(ValueError):DestinationPlan(reference(),requested)
        for action in (lambda:route('tan',['tan'],reject_labels=['tan']),lambda:route(7,['tan']),lambda:preferred_B_color(-1,['tan'])):
            with self.assertRaises(ValueError):action()
        p=DestinationPlan(reference(),['tan']);packet=p.slot('B');packet['assumptions'].clear()
        self.assertTrue(p.slot('B')['assumptions']);self.assertFalse(p.slot('B')['hardware_authorized'])
        self.assertEqual(p.assumptions['alternating_layers_share_center'],'USER_CONFIRMED')
        self.assertEqual(p.assumptions['cross_ridge_gap_two_studs'],'USER_CONFIRMED')
        self.assertEqual(p.assumptions['anchors_are_first_brick_EE_centers'],'ASSUMED_UNCONFIRMED')
        for destination,count in (('A',0),('B',-1),('B',True),('B',300)):
            with self.assertRaises((ValueError,OverflowError)):p.slot(destination,count)
        bad=reference();bad['poses'][1]['xyz_m']=[float('nan'),0,0]
        with self.assertRaises(ValueError):DestinationPlan(bad,['tan'])


if __name__=='__main__':unittest.main()
