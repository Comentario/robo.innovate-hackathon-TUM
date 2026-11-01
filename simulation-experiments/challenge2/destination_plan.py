"""Nominal destination EE targets and color routing; never motion authorization.

These base-frame data targets do not establish physical held-brick offsets,
clearance, registration, grasp success, quality, or placement confirmation.
Legacy simulator-truth SortPlan is deliberately independent of this module.
"""
import copy
import math
import numbers
import numpy as np
from challenge2.layout import PITCH,HEIGHT

PALETTE=('dark_red','brown','tan')
REJECT_LABELS=('reject_4211201','reject_6135191')
DESTINATIONS=('B','C','D')
RIDGES=4
PER_RIDGE=3
PITCH_M=4*PITCH
PER_LAYER=RIDGES*PER_RIDGE


def _count(value,maximum=None):
    if isinstance(value,bool) or not isinstance(value,numbers.Integral) or value<0 or (maximum is not None and value>maximum):
        raise ValueError('Nonnegative bounded integer count required')
    return int(value)


def _colors(requested,palette,reject_labels=()):
    if isinstance(requested,str) or isinstance(palette,str) or isinstance(reject_labels,str):raise ValueError('Color sequences required')
    requested=tuple(requested);palette=tuple(palette);rejects=tuple(reject_labels)
    for values in (requested,palette,rejects):
        if any(not isinstance(v,str) or not v or v=='UNKNOWN' for v in values) or len(set(values))!=len(values):raise ValueError('Unique named colors required')
    if palette!=PALETTE or not 1<=len(requested)<=3 or not set(requested)<=set(palette) or not set(rejects)<=set(REJECT_LABELS):raise ValueError('Requested/rejected palette is inconsistent')
    return requested,palette,rejects


def route(label,requested,palette=PALETTE,reject_labels=REJECT_LABELS):
    """Route an observed label only; UNKNOWN is never a placement or quality fact."""
    requested,palette,rejects=_colors(requested,palette,reject_labels)
    if label is None or label=='UNKNOWN':return {'decision':'abstain','destination':None,'reason':'unknown_color'}
    if not isinstance(label,str):raise ValueError('Color must be a label or None')
    if label in rejects:return {'decision':'reject','destination':'REJECT','reason':'configured_reject_color'}
    if label not in palette:return {'decision':'abstain','destination':None,'reason':'unrecognized_color'}
    other=[color for color in palette if color not in requested]
    destination='B' if label in requested else ('C','D')[other.index(label)]
    return {'decision':'route','destination':destination,'reason':'configured_color_route'}


def preferred_B_color(count,requested,palette=PALETTE):
    """Preference only: availability/abstention may prevent balanced placement."""
    requested,_,_=_colors(requested,palette)
    return requested[_count(count)%len(requested)]


class DestinationPlan:
    def __init__(self,reference,requested,*,counts=None,reject_labels=REJECT_LABELS,max_layers=25,assumptions=None):
        self.requested,_,self.reject_labels=_colors(requested,PALETTE,reject_labels)
        self.max_layers=_count(max_layers,25)
        if not self.max_layers:raise ValueError('At least one configured layer required')
        self.capacity=PER_LAYER*self.max_layers
        counts={} if counts is None else counts
        if not isinstance(counts,dict) or set(counts)-set(DESTINATIONS):raise ValueError('Only B/C/D confirmed counts accepted')
        self.counts={d:_count(counts.get(d,0),self.capacity) for d in DESTINATIONS}
        self.assumptions={'alternating_layers_share_center':'USER_CONFIRMED',
            'cross_ridge_gap_two_studs':'USER_CONFIRMED','anchors_are_first_brick_EE_centers':'ASSUMED_UNCONFIRMED',
            'physical_held_brick_T_EE':'UNVERIFIED','physical_mount_registration':'UNVERIFIED'}
        if assumptions is not None:
            if not isinstance(assumptions,dict) or set(assumptions)-set(self.assumptions) or any(v not in ('ASSUMED_UNCONFIRMED','USER_CONFIRMED','UNVERIFIED') for v in assumptions.values()):raise ValueError('Explicit assumption statuses required')
            self.assumptions.update(assumptions)
        rows=reference['poses'];poses={p['id']:p for p in rows}
        if len(poses)!=len(rows):raise ValueError('Duplicate reference pose IDs')
        def xyz(name):
            p=np.asarray(poses[name]['xyz_m'],float)
            if p.shape!=(3,) or not np.isfinite(p).all():raise ValueError('Finite reference XYZ required')
            return p
        origin=xyz('a_0_0_9');u=xyz('a_0_1_9')-origin;v=xyz('a_1_0_9')-origin
        if abs(u[2])>1e-9 or abs(v[2])>1e-9 or min(np.linalg.norm(u),np.linalg.norm(v))<=0:raise ValueError('Nonzero horizontal source-grid axes required')
        self.u=u/np.linalg.norm(u);self.v=v/np.linalg.norm(v)
        if abs(self.u@self.v)>1e-8:raise ValueError('Orthogonal source-grid axes required')
        self.first_z=float(xyz('point_03')[2]-9*HEIGHT)
        self.anchors={d:xyz(name)[:2].copy() for d,name in zip(DESTINATIONS,('point_11','point_14','point_15'))}
        self.centers={d:a+PITCH_M*(self.v[:2]+1.5*self.u[:2]) for d,a in self.anchors.items()}
        self.rotations=[]
        for long,name in ((self.v,'a_0_0_8'),(self.u,'a_0_0_9')):
            raw=np.asarray(poses[name]['O_T_EE'],float)
            if raw.shape!=(16,) or not np.isfinite(raw).all():raise ValueError('Finite reference orientation required')
            raw=raw.reshape(4,4,order='F')[:3,:3]
            if not np.allclose(raw.T@raw,np.eye(3),atol=1e-5,rtol=0) or abs(np.linalg.det(raw)-1)>1e-5:raise ValueError('Proper source rotation required')
            candidates=[]
            for sign in (1,-1):
                x=sign*long;y=np.cross([0.,0.,-1.],x);rotation=np.column_stack((x,y,[0.,0.,-1.]))
                candidates.append((float(np.trace(raw.T@rotation)),rotation))
            self.rotations.append(max(candidates,key=lambda item:item[0])[1])

    def route(self,label):return route(label,self.requested,PALETTE,self.reject_labels)

    def preferred_B_color(self):return preferred_B_color(self.counts['B'],self.requested)

    def slot(self,destination,count=None):
        if destination not in DESTINATIONS:raise ValueError('Unknown destination')
        count=_count(self.counts[destination] if count is None else count,self.capacity)
        if count==self.capacity:raise OverflowError('Destination capacity exhausted')
        k,remainder=divmod(count,PER_LAYER);n,m=divmod(remainder,PER_RIDGE)
        long,across=(self.v,self.u) if k%2==0 else (self.u,self.v)
        position=np.r_[self.centers[destination]+PITCH_M*((m-1)*long[:2]+(n-1.5)*across[:2]),self.first_z+k*HEIGHT]
        rotation=self.rotations[k%2];theta=math.atan2(rotation[1,0],rotation[0,0])
        quaternion=[0.,math.cos(theta/2),math.sin(theta/2),0.]
        matrix=np.eye(4);matrix[:3,:3]=rotation;matrix[:3,3]=position
        corners=[(position+dl*long+da*across).tolist() for dl,da in
            ((-2*PITCH,-PITCH),(2*PITCH,-PITCH),(2*PITCH,PITCH),(-2*PITCH,PITCH))]
        return {'id':f'{destination.lower()}_{n}_{m}_{k}','destination':destination,'count':count,'n':n,'m':m,'k':k,
            'reference_frame':'robot_base_O','pose_frame':'configured_end_effector_EE','position_m':position.tolist(),
            'quaternion_wxyz':quaternion,'T_base_EE':matrix.tolist(),'O_T_EE':matrix.reshape(-1,order='F').tolist(),
            'long_axis_base':long.tolist(),'across_axis_base':across.tolist(),'footprint_corners_base_m':corners,
            'footprint_center_base_m':[*self.centers[destination].tolist(),float(position[2])],
            'footprint_center_scope':'Common whole-layer center; individual nominal brick center is position_m',
            'footprint_scope':'Nominal32x16mm stud envelope at EE target XY; not measured held-brick geometry',
            'pitch_m':PITCH_M,'body_height_m':HEIGHT,'assumptions':copy.deepcopy(self.assumptions),
            'target_scope':'Nominal configured EE target only','hardware_authorized':False}

    def confirm(self,destination,expected_count):
        """Caller supplies actual placement confirmation; this function verifies none."""
        if destination not in DESTINATIONS:raise ValueError('Unknown destination')
        expected_count=_count(expected_count,self.capacity)
        if expected_count!=self.counts[destination]:raise ValueError('Stale placement count')
        self.slot(destination,expected_count)  # Refuse overflow before mutation.
        self.counts[destination]+=1
        return self.counts[destination]
