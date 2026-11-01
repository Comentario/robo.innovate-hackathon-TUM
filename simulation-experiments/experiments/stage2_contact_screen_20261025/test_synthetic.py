"""Small pure-function negatives and input immutability; no saved scene data."""
import copy
import inspect
import json
import sys
from pathlib import Path
sys.path.insert(0,str(Path(__file__).resolve().parents[2]))
from screen import screen_contact


def surface(y):
    return {'vertices_finger_m':[[-.01,y,-.01],[.01,y,-.01],[0.,y,.01]],'triangle_indices':[[0,1,2]]}


def main():
    cad={'inner_plane_y_m':0.,'expected_grip_normal_finger':[0.,1.,0.],
         'white_surfaces':[surface(.01)],'head_surfaces':[surface(-.01)]}
    args=([0.,0.,0.],0.,[0.,1.,0.],[0.,0.,0.,1.,0.,0.,0.],cad,True)
    original=copy.deepcopy(args);result=screen_contact(*args)
    assert result['decision']=='UNVERIFIED_GRIP_PLANE_COMPATIBLE' and result['compatible']
    assert not result['body_ownership_established'] and not result['pick_permission']
    assert args==original;json.dumps(result,allow_nan=False)
    wrong_plane=screen_contact([0.,.0001,0.],*args[1:])
    assert 'outside_grip_plane_tolerance' in wrong_plane['reasons']
    wrong_normal=screen_contact(args[0],args[1],[0.,-1.,0.],*args[3:])
    assert 'normal_not_lateral_qualified' in wrong_normal['reasons']
    for category in ('white','head'):
        blocked=copy.deepcopy(cad);blocked[category+'_surfaces']=[surface(.0001)]
        assert category+'_not_excluded' in screen_contact(*args[:4],blocked,True)['reasons']
        blocked[category+'_surfaces']=[]
        assert screen_contact(*args[:4],blocked,True)['decision']=='UNKNOWN'
    assert screen_contact(*args[:5],False)['decision']=='INCOMPATIBLE'
    for association in (None,1,'true'):
        assert screen_contact(*args[:5],association)['decision']=='UNKNOWN'
    with_id={**cad,'native_id':123}
    assert screen_contact(*args[:4],with_id,True)['decision']=='UNKNOWN'
    assert list(inspect.signature(screen_contact).parameters)==['point_world_m','separation_m','outward_normal_world','finger_pose_world_wxyz','cad','rendered_association']
    assert screen_contact([float('nan'),0,0],*args[1:])['decision']=='UNKNOWN'
    print('PASS: plane/normal/WHITE/HEAD/association negatives, no identity inputs, JSON and immutability')


if __name__=='__main__':main()
