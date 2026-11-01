#!/bin/sh
# Seed the persistent volume with the bundled weights, crops and calibrations (existing
# files are never overwritten), then point outputs2 at it, so calibrations, retrained
# networks, the detection area and the camera settings survive restarts and redeploys.
mkdir -p /data/outputs2
cp -r --update=none /app/seed/outputs2/. /data/outputs2/
rm -rf /app/outputs2
ln -s /data/outputs2 /app/outputs2

# Full-screen page on a monitor attached to the Jetson (KIOSK=0 turns it off).
if [ "${KIOSK:-1}" = "1" ]; then
    sh /app/kiosk.sh &
fi

exec python3 /app/scripts/web_demo.py --classifier "${CLASSIFIER:-nn}" --reference "${REFERENCE:-latest}" \
    --host :: --port "${PORT:-8000}" --half --camera-max-height "${CAMERA_MAX_HEIGHT:-720}" \
    --detect-imgsz "${DETECT_IMGSZ:-640}" ${DEMO_ARGS:-}
# --tensorrt is left out: the base image's TensorRT (JetPack 6) does not load on this
# JetPack 7.2 device (libnvdla_compiler.so missing); add it to DEMO_ARGS to try again.
