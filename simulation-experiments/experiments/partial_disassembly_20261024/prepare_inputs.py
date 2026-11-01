"""Queued deterministic sensor-copy/corruption generation; no detector or truth labels."""
import argparse,hashlib,importlib.util,json,os,shutil
from pathlib import Path
import numpy as np


def main():
    p=argparse.ArgumentParser();p.add_argument('--manifest',type=Path,required=True);p.add_argument('--inputs',type=Path,required=True);p.add_argument('--depth-helper',type=Path,required=True);a=p.parse_args()
    if os.environ.get('ROBO_PUEUE_JOB')!='1':raise RuntimeError('Sensor preparation must use default Pueue')
    spec=importlib.util.spec_from_file_location('fixed_control_depth',a.depth_helper);module=importlib.util.module_from_spec(spec);spec.loader.exec_module(module)
    package=json.loads((a.inputs/'calibration.json').read_text());(a.inputs/'images').mkdir(exist_ok=True);(a.inputs/'depth').mkdir(exist_ok=True)
    rows=json.loads(a.manifest.read_text());hashes={}
    for row in rows:
        image=a.inputs/'images'/f"{row['id']}.png";depthfile=a.inputs/'depth'/f"{row['id']}.npy"
        shutil.copy2(row['rgb_source'],image)
        operation=row.get('operation')
        if not operation:shutil.copy2(row['depth_source'],depthfile)
        else:
            depth=np.load(row['depth_source'],allow_pickle=False)
            if operation=='all_depth_NaN':depth=np.full_like(depth,np.nan)
            elif operation=='depth_patch_NaN':
                depth=depth.copy();x0,y0,x1,y1=row['pixel_xyxy'];depth[y0:y1,x0:x1]=np.nan
            elif operation=='flat_world_plane':
                c=package['views'][row['camera']];cal={'K':np.asarray(package['K']),'R':np.asarray(c['R_world_to_camera']),'t':np.asarray(c['t_world_to_camera_m'])}
                depth=module.flat_plane_depth(depth.shape,cal,row['height_m'])
            else:raise ValueError('Unknown frozen corruption')
            np.save(depthfile,depth)
        for f in (image,depthfile):hashes[str(f.relative_to(a.inputs))]=hashlib.sha256(f.read_bytes()).hexdigest()
    (a.inputs/'sensor_hashes.json').write_text(json.dumps(hashes,indent=2)+'\n')
    print('SENSORS_FROZEN',len(rows),flush=True)


if __name__=='__main__':main()
