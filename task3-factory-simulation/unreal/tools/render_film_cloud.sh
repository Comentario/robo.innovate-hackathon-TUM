#!/usr/bin/env bash
set -euo pipefail
engine="$HOME/workspace/brickflow-cinematic/tools/unreal-5.8.4"
project="$HOME/workspace/brickflow-native"
label="${1:?Supply a new render label}"
width="${2:-1920}"
stride="${3:-300}"
mode="${4:-png}"
port="${5:-7891}"
first="${6:-0}"
last="${7:-0}"
adapter=()
encoding_gpu="${8:-0}"
if [[ -n "${8:-}" ]]; then
  [[ "$8" =~ ^[0-9]+$ ]] || { echo 'GPU adapter must be a nonnegative integer.'; exit 2; }
  adapter=("-graphicsadapter=$8")
fi
height=$((width*9/16))
output="$project/Saved/Films/$label"
mkdir -p "$output"
if [[ -e "$output/edit-plan.json" ]]; then echo 'Use a new render label; existing film is preserved.'; exit 1; fi
extra=()
encoder_pid=''
if [[ "$mode" == stream ]]; then
  ffmpeg -nostdin -hide_banner -loglevel warning -filter_threads 2 -y \
    -f rawvideo -pixel_format bgra -video_size "${width}x${height}" -framerate 30 \
    -i "tcp://127.0.0.1:$port?listen=1" \
    -map 0:v -c:v h264_nvenc -gpu "$encoding_gpu" -preset p7 -tune lossless -profile:v high444p \
    -rc constqp -qp 0 -vf 'scale=in_range=pc:out_range=pc:out_color_matrix=bt709,format=yuv444p' -pix_fmt yuv444p -color_range pc -colorspace bt709 -color_primaries bt709 -color_trc iec61966-2-1 "$output/brickflow-master-444.mkv" \
    -map 0:v -vf 'scale=in_range=pc:out_range=tv:out_color_matrix=bt709,format=yuv420p' \
    -c:v h264_nvenc -gpu "$encoding_gpu" -preset p7 -tune hq -profile:v high -rc vbr -cq 16 -b:v 0 \
    -spatial-aq 1 -temporal-aq 1 -pix_fmt yuv420p -color_range tv -colorspace bt709 \
    -color_primaries bt709 -color_trc iec61966-2-1 -movflags +faststart "$output/brickflow-review-4k.mp4" \
    > "$output/encoder.log" 2>&1 &
  encoder_pid=$!
  extra=("-BrickflowFilmPort=$port")
  sleep 1
fi
export XDG_RUNTIME_DIR="$HOME/.cache/brickflow-film"
mkdir -p "$XDG_RUNTIME_DIR"
chmod 700 "$XDG_RUNTIME_DIR"
status=0
xvfb-run -n "$((120+(port-7891)*5))" -a -s "-screen 0 ${width}x${height}x24" \
 "$engine/Engine/Binaries/Linux/UnrealEditor" "$project/Brickflow.uproject" /Engine/Maps/Entry \
 -game -RenderOffscreen -vulkan -preferNvidia -nosound -nosplash -unattended -nop4 \
 "${adapter[@]}" \
 -Windowed -ForceRes "-ResX=$width" "-ResY=$height" \
 "-BrickflowFilm=$output" "-BrickflowFilmStride=$stride" "-BrickflowFilmFirst=$first" "-BrickflowFilmLast=$last" -BrickflowFilmSettle=8 \
 "${extra[@]}" '-ExecCmds=r.ScreenPercentage 100,r.AntiAliasingMethod 4,sg.ViewDistanceQuality 4,sg.ShadowQuality 4,sg.ReflectionQuality 4,r.MotionBlurQuality 0' \
 "-abslog=$output/engine.log" > "$output/stdout.log" 2>&1 || status=$?
printf '%s\n' "$status" > "$output/render.status"
if [[ -n "$encoder_pid" ]]; then
  encoder_status=0
  wait "$encoder_pid" || encoder_status=$?
  printf '%s\n' "$encoder_status" > "$output/encoder.status"
  ffprobe -v error -show_entries stream=codec_name,profile,width,height,pix_fmt,r_frame_rate,nb_frames \
    -show_entries format=duration,size -of json "$output/brickflow-review-4k.mp4" > "$output/video-probe.json"
fi
printf 'FILM_RENDER_EXIT_CODE=%s\n' "$status"
