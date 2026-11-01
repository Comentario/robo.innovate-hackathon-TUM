"""Person 2 + person 3 orchestration; detector and robot SDK stay behind contracts."""
from planning import make_plan
from planning.faces import make_face_plan
from execution import compile_job
from .intake import normalize_snapshot, execution_source_poses


def prepare(snapshot,config,cell=None):
    snapshot=normalize_snapshot(snapshot)
    planner=make_face_plan if snapshot['face_aware'] else make_plan
    plan=planner(snapshot['items'],**config)
    if cell is None:return snapshot,plan,None
    poses=execution_source_poses(snapshot,cell)
    job=compile_job(plan,snapshot['items'],cell,source_poses=poses)
    return snapshot,plan,job
