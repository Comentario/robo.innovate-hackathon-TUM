"""Protect original render directories from competing helper publication."""
import sys,tempfile
from pathlib import Path
sys.path.insert(0,str(Path(__file__).resolve().parents[1]/'unreal/tools'))
from render_pending_tail import publish_no_replace
with tempfile.TemporaryDirectory() as tmp:
    root=Path(tmp)
    for state in ('missing','empty','busy'):
        source=root/('source-'+state);source.mkdir();(source/'raw.mp4').write_bytes(b'verified helper movie')
        target=root/('target-'+state)
        if state!='missing':target.mkdir()
        if state=='busy':(target/'trace.csv').write_text('original capture in progress')
        published=publish_no_replace(source,target)
        if state=='missing':
            assert published and not source.exists() and (target/'raw.mp4').read_bytes()==b'verified helper movie'
        else:
            assert not published and source.exists() and not (target/'raw.mp4').exists()
            if state=='busy':assert (target/'trace.csv').read_text()=='original capture in progress'
print('Atomic publication verified: existing empty or active render directories are never replaced.')
