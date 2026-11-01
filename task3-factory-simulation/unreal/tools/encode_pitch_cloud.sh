#!/usr/bin/env bash
set -euo pipefail
project="$HOME/workspace/brickflow-native"
frames="${1:-$project/Saved/PitchTourFinal}"
count=$(find "$frames" -maxdepth 1 -name 'frame-*.png' | wc -l)
test "$count" -eq 576
ffmpeg -hide_banner -loglevel warning -y -framerate 24 \
  -i "$frames/frame-%05d.png" -frames:v 576 -c:v libx264 -preset slow \
  -crf 17 -pix_fmt yuv420p -movflags +faststart \
  "$project/Saved/NativePresentation/brickflow-native-pitch.mp4"
ffprobe -v error -show_entries stream=width,height,nb_frames,r_frame_rate \
  -show_entries format=duration,size -of json \
  "$project/Saved/NativePresentation/brickflow-native-pitch.mp4"
