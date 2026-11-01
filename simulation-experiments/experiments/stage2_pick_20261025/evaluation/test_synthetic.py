"""Tiny no-capture geometry/frame/serialization regressions; no simulation."""
import json
import math
import numpy as np
from evaluate import polygon_iou,relative_pose,initial_matches,expected_names,legacy_budget_only
from contact_helpers import rotation,angle_between,classify_point
from safety_views import project_free

def main():
    square=[[0,0],[10,0],[10,10],[0,10]]
    cal={'K':[[1,0,0],[0,1,0],[0,0,1]],'R':np.eye(3).tolist(),'t':[0,0,0]}
    points=np.array([[0.,0.,1.],[0.,0.,3.],[100.,0.,1.],[0.,0.,-1.]])
    a=project_free(points,np.array([[2.]]),cal);b=project_free(points,np.array([[4.]]),cal)
    assert a.tolist()==[True,False,False,False] and b.tolist()==[True,True,False,False]
    assert not project_free(points,np.array([[np.nan]]),cal).any() and (a|b).tolist()==[True,True,False,False]
    spec={'layers':2,'layer_yaws_quarter_turn':[0,1],'world_axis_counts_by_yaw_quarter_turn':{'0':[5,6],'1':[6,5]}}
    names=expected_names(spec,[])
    assert len(names)==61 and 'brick_0_4_5' in names and 'brick_0_5_4' not in names and 'brick_1_5_4' in names and 'brick_1_4_5' not in names
    assert 'brick_1_5_4' not in expected_names(spec,['brick_1_5_4'])
    legacy={'budget':{'capture_plus_independent_audit_seconds_per_case':600},'physics':{'solver':'PGS'}}
    current={'budget':{'capture_plus_independent_audit_seconds_per_case':1200},'physics':{'solver':'PGS'}}
    assert legacy_budget_only(legacy,current)
    changed={'budget':{'capture_plus_independent_audit_seconds_per_case':1200},'physics':{'solver':'TGS'}}
    assert not legacy_budget_only(legacy,changed)
    assert polygon_iou(square,square)==1
    assert initial_matches(square,[{'id':'hidden','layer':7,'image_polygon':square},{'id':'top','layer':9,'image_polygon':square}])==[{'id':'top','iou':1.,'layer':9}]
    assert polygon_iou(square,[[20,0],[30,0],[30,10],[20,10]])==0
    tcp=[1,2,3,1,0,0,0];body=[1.001,2.002,3.003,1,0,0,0]
    p,r=relative_pose(tcp,body)
    assert np.allclose(p,[.001,.002,.003]) and np.array_equal(r,np.eye(3))
    assert angle_between([1,0,0,0],[-1,0,0,0])==0
    q=[math.sqrt(.5),0,0,math.sqrt(.5)]
    assert np.allclose(rotation(q)@[1,0,0],[0,1,0],atol=1e-15)
    protocol={'geometry':{'pad_distance_allowance_m':50e-6,'white_extra_clearance_m':.0001,'side_contact':{'minimum_outward_dot_grip_normal':.9}}}
    vertices=[[-1,0,-1],[1,0,-1],[1,0,1],[-1,0,1]]
    colliders=[{'enabled':True,'role':role,'points_finger_m':(np.asarray(vertices)+[0,y,0]).tolist(),'triangle_indices':[[0,1,2],[0,2,3]]} for role,y in [('body',0),('white',1),('head',2)]]
    result=classify_point([0,0,0],0,[0,0,0,1,0,0,0],colliders,protocol,outward_world=[0,-1,0],flat_face_y_m=0,expected_grip_normal_finger=[0,-1,0])
    assert result['uniquely_pad_compatible']
    wrong=classify_point([0,0,0],0,[0,0,0,1,0,0,0],colliders,protocol,outward_world=[0,0,1],flat_face_y_m=0,expected_grip_normal_finger=[0,-1,0])
    assert not wrong['uniquely_pad_compatible']
    json.dumps({'pass':np.bool_(True)},default=lambda x:x.item(),allow_nan=False)
    print('Synthetic polygon/frame/all-point normal-domain/serialization checks PASS')
if __name__=='__main__':main()
