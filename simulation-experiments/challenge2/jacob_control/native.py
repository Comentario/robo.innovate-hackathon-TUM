"""Small ctypes boundary to pinned, network-free libfranka joint-limit math."""
import ctypes
from pathlib import Path
import xml.etree.ElementTree as ET
import numpy as np


class NativeLimiter:
    def __init__(self,library_path,urdf_path):
        self.library_path=Path(library_path)
        self.lib=ctypes.CDLL(str(self.library_path.resolve()))
        pointer=ctypes.POINTER(ctypes.c_double)
        self.lib.robo_limit.argtypes=[pointer]*6;self.lib.robo_limit.restype=ctypes.c_int
        tree=ET.parse(urdf_path).getroot();parameters=[]
        for i in range(1,8):
            rows=[j for j in tree.findall('joint') if j.attrib['name']==f'joint{i}']
            if len(rows)!=1:raise ValueError('Unique real-model joint required')
            limit=rows[0].find('limit');dynamic=rows[0].find('position_based_velocity_limits')
            parameters.append([float(limit.attrib['velocity']),float(dynamic.attrib['velocity_offset']),float(dynamic.attrib['deceleration_limit']),float(limit.attrib['upper']),float(limit.attrib['lower'])])
        self.parameters=np.asarray(parameters,dtype=np.float64)
        if not np.isfinite(self.parameters).all():raise ValueError('Invalid real-model velocity parameters')

    def limit(self,command,q_d,dq_d,ddq_d):
        arrays=[self.parameters.reshape(-1)]
        for values in (command,q_d,dq_d,ddq_d):
            a=np.ascontiguousarray(values,dtype=np.float64)
            if a.shape!=(7,) or not np.isfinite(a).all():raise ValueError('Finite seven-joint SDK state required')
            arrays.append(a)
        output=np.empty(7,dtype=np.float64);arrays.append(output)
        result=self.lib.robo_limit(*(a.ctypes.data_as(ctypes.POINTER(ctypes.c_double)) for a in arrays))
        if result or not np.isfinite(output).all():raise RuntimeError('Pinned libfranka limiter failed')
        return output

    def __call__(self,command,q_d,dq_d,ddq_d,first=False):
        # SDK uses the first callback command as the initial filter reference.
        reference=np.asarray(command if first else q_d,dtype=float)
        limited=self.limit(command,reference,dq_d,ddq_d)
        velocity=(limited-reference)/.001
        return limited,velocity,(velocity-np.asarray(dq_d))/.001
