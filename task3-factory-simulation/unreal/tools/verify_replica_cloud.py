#!/usr/bin/env python3
"""Verify the complete restored workspace before retiring its source VM."""
import hashlib
import csv
import json
import os
from pathlib import Path
import subprocess


def digest(path):
    result = hashlib.sha256()
    with path.open('rb') as source:
        for block in iter(lambda: source.read(8 * 1024 * 1024), b''):
            result.update(block)
    return result.hexdigest()


def main():
    root = Path.home() / 'workspace'
    project = root / 'brickflow-native'
    state = project / 'Saved/Migration'
    archive = root / '.migration/brickflow-saved.tar'
    expected = (state / 'saved-archive.sha256').read_text().split()[0]
    actual = digest(archive)
    assert actual == expected, 'Historical archive differs from source'
    members = json.loads((state / 'saved-members.json').read_text())
    for member in members:
        relative = Path(member['name'])
        assert not relative.is_absolute() and '..' not in relative.parts
        path = project / relative
        if member['symlink']:
            assert path.is_symlink() and os.readlink(path) == member['linkname'], str(path)
        elif member['file']:
            assert path.is_file() and path.stat().st_size == member['size'], str(path)
        else:
            assert path.exists(), str(path)
    subprocess.run(['sha256sum', '-c', str(state / 'project-expected.sha256')], cwd=project, check=True)
    gpus = subprocess.check_output(['nvidia-smi', '--query-gpu=index', '--format=csv,noheader'], text=True).splitlines()
    assert len(gpus) == 4
    for adapter in range(4):
        part = project / f'Saved/Films/four-gpu-smoke-v1-part{adapter}'
        assert (part / 'render.status').read_text().strip() == '0'
        assert (part / 'encoder.status').read_text().strip() == '0'
        assert f'Using device at index {adapter} of 4' in (part / 'engine.log').read_text()
        codec_part = project / f'Saved/Films/four-gpu-codec-smoke-v2-part{adapter}'
        assert (codec_part / 'render.status').read_text().strip() == '0'
        assert (codec_part / 'encoder.status').read_text().strip() == '0'
        assert int(json.loads((codec_part / 'video-probe.json').read_text())['streams'][0]['nb_frames']) == 12
    codec_rows = csv.reader((state / 'gpu-codec-processes.csv').read_text().splitlines())
    assert len({row[1].strip() for row in codec_rows}) == 4
    delivery = project / 'Saved/Films/continuous-4k-v4-delivery'
    subprocess.run(['sha256sum', '-c', str(delivery / 'review.sha256')], check=True)
    repo = root / 'robo.innovate-hackathon-TUM'
    subprocess.run(['python3', str(repo / 'tests_native/verify_film.py'), str(delivery),
                    '--reference', str(repo / 'artifacts/unreal_film/selected-reference.json'), '--complete'],
                   cwd=repo, check=True)
    subprocess.run(['python3', str(repo / 'tests_native/verify_film_packets.py'),
                    str(delivery / 'brickflow-tracking-4k.mp4'),
                    '--output', str(delivery / 'packet-verification.json')], check=True)
    result = {'verified': True, 'historyCopyComplete': True, 'archiveSha256': actual,
              'restoredArchiveEntries': len(members), 'gpuCount': 4,
              'projectChecksumsVerified': True, 'renderedTraceVerified': True,
              'videoChecksumVerified': True, 'videoTimestampsVerified': True,
              'distributedEncodingVerified': True,
              'limitation': 'Synthetic simulation checks; not physical validation.'}
    (state / 'final-verification.json').write_text(json.dumps(result, indent=2))
    print(json.dumps(result, indent=2))


if __name__ == '__main__':
    main()
