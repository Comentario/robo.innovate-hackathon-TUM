#!/usr/bin/env bash
set -euo pipefail
task_root="${1:-$HOME/workspace/brickflow-cinematic}"
cd "$task_root"
ffmpeg -hide_banner -loglevel error -y -i renders/inspection-replay.mp4 \
  -vf "drawtext=fontfile=/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf:text='KINEMATIC SIMULATION | SYNTHETIC INPUT | 1x REPLAY':fontsize=20:fontcolor=white:box=1:boxcolor=black@0.55:boxborderw=12:x=36:y=h-64" \
  -c:v libx264 -crf 18 -pix_fmt yuv420p -movflags +faststart \
  renders/inspection-replay-captioned.mp4
ffprobe -v error -count_frames -select_streams v:0 \
  -show_entries stream=width,height,r_frame_rate,nb_read_frames,duration \
  -of json renders/inspection-replay-captioned.mp4 > renders/video-verification.json
