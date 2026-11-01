"""Supervise the single reviewed guard correction; no cooking or retries."""
import json
from pathlib import Path
import subprocess
import sys
import time

ROOT = Path(__file__).resolve().parent.parent
PRIOR_WALL = 0.49498790899815504
LIMIT = 180.0
started = time.monotonic()
records = []
completed = False
capture = None
try:
    before = time.monotonic()
    command = [sys.executable, str(ROOT/'compound/construct.py'), '--stl', str(ROOT/'inputs/tip.stl'), '--features', str(ROOT/'inputs/features.json'), '--output', str(ROOT/'output')]
    try:
        code = subprocess.run(command, timeout=min(60.0, LIMIT-PRIOR_WALL)).returncode
    finally:
        capture = time.monotonic()-before
        artifact = ROOT/'output/compound.json'
        completed = artifact.exists() and json.loads(artifact.read_text()).get('status') == 'candidate_constructed_requires_independent_audit'
        (ROOT/'construction_supervisor.json').write_text(json.dumps({'capture_wall_seconds':capture, 'construction_completed':completed, 'prior_supervised_seconds':PRIOR_WALL, 'remaining_independent_audit_seconds':max(0.,LIMIT-PRIOR_WALL-capture)})+'\n')
    records.append({'phase':'construction','returncode':code,'wall_seconds':capture})
    if code or not completed:
        raise RuntimeError('Single corrected resource guard construction stopped; no retry')
    baseline = json.loads((ROOT/'inputs/baseline_compound.json').read_text())
    candidate = json.loads(artifact.read_text())
    prefix_exact = candidate['cells'][:len(baseline['cells'])] == baseline['cells']
    (ROOT/'prefix_check.json').write_text(json.dumps({'exact27':prefix_exact, 'baseline_cells':len(baseline['cells']), 'candidate_cells':len(candidate['cells'])})+'\n')
    if len(baseline['cells']) != 27 or not prefix_exact:
        raise RuntimeError('Retained27 cell records changed; no audit promotion')
    before = time.monotonic()
    command = [sys.executable, str(ROOT/'compound/evaluation/evaluate.py'), '--stl', str(ROOT/'inputs/tip.stl'), '--features', str(ROOT/'inputs/features.json'), '--candidate', str(artifact), '--probe-config', str(ROOT/'inputs/probe_config.json'), '--supervisor', str(ROOT/'construction_supervisor.json'), '--output', str(ROOT/'audit')]
    try:
        code = subprocess.run(command, timeout=max(.001,LIMIT-PRIOR_WALL-(before-started))).returncode
    finally:
        records.append({'phase':'audit','wall_seconds':time.monotonic()-before})
    records[-1]['returncode'] = code
    if code:
        raise RuntimeError('Independent audit process stopped; no retry')
finally:
    elapsed = time.monotonic()-started
    (ROOT/'supervisor.json').write_text(json.dumps({'phases':records, 'prior_supervised_seconds':PRIOR_WALL, 'current_supervised_seconds':elapsed, 'cumulative_supervised_seconds':PRIOR_WALL+elapsed, 'cumulative_limit_seconds':LIMIT, 'within_budget':PRIOR_WALL+elapsed<=LIMIT, 'cooking_authorized':False, 'physical_collision_validated':False})+'\n')
if PRIOR_WALL+elapsed>LIMIT:
    raise SystemExit(1)
