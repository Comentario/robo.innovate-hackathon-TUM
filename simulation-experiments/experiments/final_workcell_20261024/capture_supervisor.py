"""One queued static capture, reusing the established bounded Kit cleanup."""
import argparse
import json
import os
from pathlib import Path
import signal
import subprocess
import sys
import time

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))
from experiments.partial_disassembly_20261024.render_supervisor import finish_child


def main():
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument('--output', type=Path, required=True)
    p.add_argument('--python', required=True)
    p.add_argument('--cameras', type=Path)
    p.add_argument('--appearance', type=Path)
    a = p.parse_args()
    if os.environ.get('ROBO_PUEUE_JOB') != '1':
        raise RuntimeError('Rendering requires default Pueue')
    a.output.mkdir(parents=True, exist_ok=True)
    directory = Path(__file__).resolve().parent
    command = [a.python, str(directory/'render_final.py'), '--geometry', str(directory/'geometry.json'),
               '--cameras', str(a.cameras or directory/'cameras.json'), '--output', str(a.output),
               '--views', 'all', '--headless', '--enable_cameras', '--device', 'cpu']
    if a.appearance is not None:
        command += ['--appearance', str(a.appearance)]
    with (a.output/'process.log').open('w') as log:
        process = subprocess.Popen(command, stdout=log, stderr=subprocess.STDOUT, start_new_session=True)
        def cancelled(signum, _frame):
            try:
                os.killpg(process.pid, signal.SIGKILL)
            except ProcessLookupError:
                pass
            raise SystemExit(128+signum)
        signal.signal(signal.SIGTERM, cancelled)
        signal.signal(signal.SIGINT, cancelled)
        start, marker_time, reason = time.monotonic(), None, None
        try:
            while process.poll() is None:
                if (a.output/'failure.json').exists():
                    reason = 'capture_failure'
                    break
                if (a.output/'run_complete.json').exists():
                    if marker_time is None:
                        marker_time = time.monotonic()
                    if time.monotonic()-marker_time > 5:
                        reason = 'cleanup_stall_after_validated_capture'
                        break
                if time.monotonic()-start > 180:
                    reason = 'capture_timeout'
                    break
                time.sleep(.2)
        finally:
            code = finish_child(process)
    if reason in ('capture_failure', 'capture_timeout') or not (a.output/'run_complete.json').exists():
        raise RuntimeError(f'Capture failed: {reason}, exit={code}; see process.log')
    marker = json.loads((a.output/'run_complete.json').read_text())
    m = json.loads((a.output/'manifest.json').read_text())
    assert marker['capture_validated'] and m['all_capture_states_exactly_equal']
    assert (m['brick_count'], m['native_connections'], m['native_connected_parts']) == (300, 930, 301)
    assert m['post_connection_physics_steps'] == 0
    assert m['final_layout']['target_studs'] == 48 and len(m['final_layout']['target_zones']) == 3
    assert m['final_layout']['wrist_optical_transform_available'] is False
    if m['final_layout'].get('additional_wrist_visual') is not None:
        assert m['final_layout']['wrist_camera_config_count'] == 2
        assert m['final_layout']['additional_wrist_visual']['optical_camera_activated'] is False
    assert m['final_layout']['external_physical_cameras_modeled'] == 0
    assert (a.output/'final_workcell.usda').is_file()
    record = {'capture_validated': True, 'child_returncode': code,
              'cleanup_result': reason or 'returned', 'seconds': time.monotonic()-start,
              'native_source_parts': 301, 'native_source_connections': 930,
              'diagnostic_views': m['selected_views'], 'physical_camera_calibration': 'unavailable'}
    (a.output/'supervisor.json').write_text(json.dumps(record, indent=2)+'\n')
    print(json.dumps(record), flush=True)


if __name__ == '__main__':
    main()
