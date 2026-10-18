"""Synthetic workcell geometry; positions describe brick reference centers, not a robot TCP."""
from copy import deepcopy
import math


def vector(value, size, name):
    if not isinstance(value, list) or len(value) != size or any(type(x) not in (int,float) or not math.isfinite(x) for x in value):
        raise ValueError(f'{name} requires {size} finite numbers')
    return tuple(float(x) for x in value)


def pose(position, quaternion=(0.,0.,0.,1.)):
    return dict(position_m=list(position), orientation_xyzw=list(quaternion))


class CellLayout:
    def __init__(self, config):
        if not isinstance(config, dict) or config.get('schema_version') != 'cell-0.1' or config.get('units') != 'm':
            raise ValueError('cell requires schema cell-0.1 and units m')
        self.config = deepcopy(config)
        self.frame = config.get('frame')
        if not isinstance(self.frame, str) or not self.frame.strip():
            raise ValueError('cell frame must be nonempty')
        self.size = vector(config['brick_size_m'],3,'brick_size_m')
        self.low = vector(config['workspace']['min_m'],3,'workspace min')
        self.high = vector(config['workspace']['max_m'],3,'workspace max')
        if any(x <= 0 for x in self.size) or any(a >= b for a,b in zip(self.low,self.high)):
            raise ValueError('invalid size or workspace bounds')
        self.source = vector(config['source']['origin_m'],3,'source origin')
        self.target = vector(config['pallet']['origin_m'],3,'pallet origin')
        self.source_columns = config['source']['columns']
        if type(self.source_columns) is not int or self.source_columns <= 0:
            raise ValueError('source columns must be positive integer')
        self.source_pitch = vector(config['source']['pitch_m'],2,'source pitch')
        self.target_pitch = vector(config['pallet']['pitch_m'],3,'pallet pitch')
        if any(a < b for a,b in zip(self.source_pitch,self.size[:2])) or any(a < b for a,b in zip(self.target_pitch[:2],self.size[:2])):
            raise ValueError('grid pitch must prevent brick overlap')
        if not math.isclose(self.target_pitch[2], self.size[2], abs_tol=1e-9):
            raise ValueError('this cell model requires touching, aligned layers')
        self.clearance = config['approach_clearance_m']
        if type(self.clearance) not in (int,float) or not math.isfinite(self.clearance) or self.clearance <= 0:
            raise ValueError('approach clearance must be positive and finite')
        self.home = pose(vector(config['home_m'],3,'home'))
        self.capacity = config['pallet']['capacity']
        if not isinstance(self.capacity,dict) or set(self.capacity) != {'rows','columns','layers'} or any(type(v) is not int or v <= 0 for v in self.capacity.values()):
            raise ValueError('cell pallet capacity requires positive rows, columns and layers')
        self.orientations = config['orientation_quaternions']
        if not isinstance(self.orientations,dict) or not self.orientations:
            raise ValueError('cell requires explicit orientation mappings')
        for oid,q in self.orientations.items():
            q = vector(q,4,'orientation quaternion')
            if not isinstance(oid,str) or not oid or not math.isclose(sum(x*x for x in q),1,abs_tol=1e-6):
                raise ValueError('orientation mappings require normalized quaternions')
            # This first cell only supports upright bricks, including front/back yaw flips.
            if abs(q[0]) > 1e-8 or abs(q[1]) > 1e-8 or not (abs(q[2]) < 1e-8 or abs(q[3]) < 1e-8):
                raise ValueError('cell supports upright yaw 0 or 180 degrees only')
        self.check_pose(self.home, carrying=False)

    def check_pose(self, value, carrying=True):
        center = vector(value['position_m'],3,'object position')
        # Supported yaw rotations preserve the extents. No IK or trajectory collision test.
        for i,x in enumerate(center):
            half = self.size[i]/2 if carrying else 0
            if x-half < self.low[i]-1e-9 or x+half > self.high[i]+1e-9:
                raise ValueError('object waypoint is outside configured workspace bounds')

    def source_pose(self, index):
        return pose([self.source[0]+(index%self.source_columns)*self.source_pitch[0],
                     self.source[1]+(index//self.source_columns)*self.source_pitch[1], self.source[2]])

    def target_pose(self, placement):
        oid = placement.get('orientation_id','front_out')
        if oid not in self.orientations:
            raise ValueError(f'orientation is not mapped by this cell: {oid}')
        return pose([self.target[0]+placement['column']*self.target_pitch[0],
                     self.target[1]+placement['row']*self.target_pitch[1],
                     self.target[2]+placement['layer']*self.target_pitch[2]], self.orientations[oid])

    def above(self, value):
        result = deepcopy(value)
        result['position_m'][2] += self.clearance
        return result
