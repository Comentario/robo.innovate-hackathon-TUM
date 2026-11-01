#!/usr/bin/env python3
"""Check encoded presentation timestamps across all concatenation boundaries."""
import argparse
import json
import subprocess
from pathlib import Path


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('video', type=Path)
    parser.add_argument('--frames', type=int, default=11867)
    parser.add_argument('--fps', type=float, default=30)
    parser.add_argument('--output', type=Path, required=True)
    args = parser.parse_args()
    probe = json.loads(subprocess.check_output([
        'ffprobe', '-v', 'error', '-select_streams', 'v:0', '-show_packets',
        '-show_entries', 'packet=pts_time,dts_time,duration_time', '-of', 'json', str(args.video)
    ]))
    packets = probe['packets']
    assert len(packets) == args.frames, len(packets)
    pts = sorted(float(packet['pts_time']) for packet in packets)
    error = max(abs(t-i/args.fps) for i, t in enumerate(pts))
    assert error < .00002, f'Presentation timestamp discontinuity: {error}s'
    dts = [float(packet['dts_time']) for packet in packets if 'dts_time' in packet]
    assert all(b > a for a, b in zip(dts, dts[1:])), 'Nonmonotonic decode timestamps'
    result = {'verified': True, 'packets': len(packets), 'fps': args.fps,
              'maximumPresentationTimestampErrorSeconds': error,
              'limitation': 'Timestamp continuity only; visual review and native trace checks are separate.'}
    args.output.write_text(json.dumps(result, indent=2))
    print(json.dumps(result, indent=2))


if __name__ == '__main__':
    main()
