"""Record sensor/truth hashes and capture integrity only; no detector/held-out inspection."""
import argparse,hashlib,json
from pathlib import Path


def main():
    p=argparse.ArgumentParser();p.add_argument('--render-run',type=Path,required=True);a=p.parse_args();exp=Path(__file__).resolve().parent
    root=a.render_run/'render_output';benchmark=json.loads((exp/'benchmark.json').read_text());assert json.loads((root/'run_complete.json').read_text())['complete']
    hashes={};cases=[]
    for case in benchmark['cases']:
        folder=root/case['split']/case['id'];m=json.loads((folder/'manifest.json').read_text());expected=case['expected']
        actual=(m['brick_count'],m['native_connections'],m['native_connected_parts'])
        if actual!=(expected['active_bricks'],expected['native_connections'],expected['connected_parts']):raise ValueError(case['id'])
        if not m['all_capture_states_exactly_equal'] or m['post_connection_physics_steps']!=0:raise ValueError('Capture state changed')
        selected=['manifest.json','run_complete.json','supervisor.json','evaluation_truth/active_bricks.json','evaluation_truth/active_root_states.npy','evaluation_truth/annotations.json','evaluation_truth/cameras.json','evaluation_truth/native_graph.json','evaluation_truth/case_state.json']
        selected += [f'images/{v}.png' for v in benchmark['views']]+[f'evaluation_truth/{v}_depth.npy' for v in benchmark['views']]
        for relative in selected:
            f=folder/relative;hashes[str(f.relative_to(root))]=hashlib.sha256(f.read_bytes()).hexdigest()
        cases.append({'id':case['id'],'split':case['split'],'capture_validated':True,'actual_counts':list(actual)})
    record={'render_run':str(a.render_run.resolve()),'render_root':str(root.resolve()),'render_job_id':1686,'benchmark_sha256':hashlib.sha256((exp/'benchmark.json').read_bytes()).hexdigest(),'cases':cases,'sha256':hashes,'reserved_integrity_only':True}
    (exp/'dataset.json').write_text(json.dumps(record,indent=2)+'\n');print('Dataset frozen:10captures/20views; reserved bytes hashed without visual or detector feedback.')


if __name__=='__main__':main()
