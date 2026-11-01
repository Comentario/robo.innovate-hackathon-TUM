#!/usr/bin/env bash
set -euo pipefail
output="$HOME/workspace/brickflow-native/Saved/Films/${1:?Supply delivery directory name}"
test -f "$output/delivery.status"
ffmpeg -nostdin -hide_banner -loglevel warning -y \
  -hwaccel cuda -hwaccel_output_format cuda -i "$output/brickflow-tracking-4k.mp4" \
  -vf scale_cuda=1920:1080 -c:v h264_nvenc -preset p7 -tune hq \
  -rc vbr -cq 18 -b:v 0 -profile:v high -spatial-aq 1 -temporal-aq 1 \
  -color_range tv -colorspace bt709 -color_primaries bt709 -color_trc iec61966-2-1 \
  -movflags +faststart "$output/brickflow-tracking-1080p.mp4"
ffprobe -v error -show_entries stream=width,height,r_frame_rate,nb_frames \
  -show_entries format=duration,size -of json "$output/brickflow-tracking-1080p.mp4" \
  > "$output/preview-probe.json"
