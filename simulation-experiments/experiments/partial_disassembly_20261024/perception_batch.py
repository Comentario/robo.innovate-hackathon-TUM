"""Run a frozen detector on opaque sensor frames, without scenario/GT inputs."""
import argparse,hashlib,importlib.util,json,os,time
from pathlib import Path
import cv2,numpy as np


def load(name,path):
    spec=importlib.util.spec_from_file_location(name,path);module=importlib.util.module_from_spec(spec);spec.loader.exec_module(module);return module


def scalar(value):
    if isinstance(value,np.generic):return value.item()
    raise TypeError(type(value).__name__)


def main():
    p=argparse.ArgumentParser();p.add_argument('--inputs',type=Path,required=True);p.add_argument('--method',type=Path,required=True);p.add_argument('--config',type=Path,required=True);p.add_argument('--output',type=Path,required=True);a=p.parse_args()
    if os.environ.get('ROBO_PUEUE_JOB')!='1':raise RuntimeError('Perception must use default Pueue')
    cv2.setNumThreads(2)
    method=load('frozen_method',a.method);depth_module=load('frozen_depth',a.inputs/'upstream/depth_module.py');Evidence=load('frozen_evidence',a.inputs/'upstream/evidence.py').Evidence
    cfg=json.loads(a.config.read_text());dcfg=json.loads((a.inputs/'upstream/depth_config.json').read_text());calibration=json.loads((a.inputs/'calibration.json').read_text());frames=json.loads((a.inputs/'frames.json').read_text());started=time.monotonic();records=[]
    for frame in frames:
        cv2.setRNGSeed(26)
        depth=np.load(a.inputs/frame['depth'],allow_pickle=False);rgb=cv2.imread(str(a.inputs/frame['rgb']))
        if rgb is None or depth.shape!=rgb.shape[:2]:raise ValueError('Sensor shape mismatch')
        c=calibration['views'][frame['camera']];cal={'K':np.asarray(calibration['K'],np.float64),'R':np.asarray(c['R_world_to_camera'],np.float64),'t':np.asarray(c['t_world_to_camera_m'],np.float64)}
        result,mask,ridges=method.analyze(depth,rgb,cal,depth_module,dcfg,cfg,Evidence,frame['camera'],'observed')
        result['frame_id']=frame['id'];folder=a.output/frame['id'];folder.mkdir(parents=True,exist_ok=True)
        (folder/'detections.json').write_text(json.dumps(result,indent=2,allow_nan=False,default=scalar)+'\n')
        for name,image in [('overlay.png',method.overlay(rgb,result)),('top_band_world_xy.png',mask.astype(np.uint8)*255),('ridge_mask_world_xy.png',ridges.astype(np.uint8)*255)]:
            if not cv2.imwrite(str(folder/name),image):raise OSError(name)
        decisions={key:sum(c['decision']==key for c in result['candidates']) for key in ['present','missing','uncertain']}
        row={'id':frame['id'],'camera':frame['camera'],'raw':len(result['candidates']),'decisions':decisions,'direction_status':result['depth_direction']['status'],'height_band_world_m':result['depth_direction']['height_band_world_m']}
        records.append(row);print('PERCEPTION_FRAME',json.dumps(row),flush=True)
    (a.output/'runtime.json').write_text(json.dumps({'seconds':time.monotonic()-started,'frames':records,'versions':{'opencv':cv2.__version__,'numpy':np.__version__},'per_frame_rng_seed':26,'method_sha256':hashlib.sha256(a.method.read_bytes()).hexdigest(),'sensor_hashes_sha256':hashlib.sha256((a.inputs/'sensor_hashes.json').read_bytes()).hexdigest()},indent=2)+'\n')
    (a.output/'run_complete.json').write_text(json.dumps({'complete':True,'frames':len(records)})+'\n')


if __name__=='__main__':main()
