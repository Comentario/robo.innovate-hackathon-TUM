# Brick sorter on the Jetson (WendyOS)

The Jetson Orin Nano runs the whole pipeline (`scripts/web_demo.py`: Orbbec Gemini 2
color camera at its largest resolution -> YOLO11n-seg + ByteTrack -> neural network ->
vote). The laptop only shows the page: `web_demo.py --remote` serves the same GUI and
passes every request and the video stream through to the Jetson.

```
Gemini 2 --USB--> Jetson: web_demo.py (FastAPI, port 8000) --LAN / USB--> laptop: web_demo.py --remote (port 8000) --> browser
```

## 1. Build the bundle (laptop)

```powershell
.\.venv\Scripts\python.exe scripts\stage_jetson_app.py
```

This copies `scripts/*.py`, the detector, the reference network, the base crops and the
calibrations (json + crops) into `jetson/bundle/` (~35 MB, git-ignored). Run it again
after changing code or weights.

## 2. Deploy

The Jetson is reached over the USB-C cable (adapter "Ethernet 3", UsbNcm). Its
`.local` name resolves to a 169.254.x.x address that Windows routes through Tailscale
(timeout), and the venue Wi-Fi blocks device-to-device traffic, so use its IPv6
link-local address with the adapter index (`%56`; check with
`Get-NetAdapter "Ethernet 3"` -> ifIndex if the cable was replugged):

```powershell
cd jetson
wendy run --device "fe80::5741:1%56"
```

- The image is ARM64. Either start Docker Desktop on the laptop (it emulates ARM64; the
  first build is slow and uploads the 5-9 GB base image, use the USB-C cable), or, if
  the Jetson has internet, build on the Jetson itself: `wendy run --build-host=wendyos-brick-hackathon-1.local --device wendyos-brick-hackathon-1.local`.
- Later deploys only upload the changed layers (code: seconds).
- Check the camera is visible: `wendy device camera list`. Logs: `wendy device logs`.

The container keeps `outputs2/` on a persistent volume (`/data`): calibrations,
retrained networks, the detection area and the fixed camera settings survive restarts
and redeploys. The bundled files only fill it the first time (never overwrite).

## 3. Open the GUI on the laptop

```powershell
.\.venv\Scripts\python.exe scripts\web_demo.py --remote "http://[fe80::5741:1%56]:8000"
```

Open http://localhost:8000. Browsers cannot open IPv6 link-local addresses, which is
one more reason the laptop serves the page and forwards to the Jetson.

## Standalone with a monitor (no laptop)

`kiosk.sh` opens the page full screen (presentation mode) on a monitor plugged into the
Jetson: Firefox ESR in kiosk mode, drawn through the WendyOS compositor (`display`
entitlement). Deploy once with a restart policy, then the laptop can be unplugged:

```powershell
cd jetson
wendy run --device "fe80::5741:1%56" --chunking off --detach --restart-unless-stopped
```

- Plug the monitor (HDMI / DisplayPort) in before deploying; a keyboard and mouse on the
  Jetson work in the page (`p` leaves presentation mode, `o` shows the operator panel).
- Logs: `wendy device logs --device ...`; lines starting with `kiosk:` tell whether a
  display was found. Without a Wayland display (headless WendyOS image) the page is
  still served on port 8000 and the kiosk keeps checking every 30 s.
- `KIOSK=0` (`wendy run --env KIOSK=0`) turns the monitor page off.
- Stop it: `wendy device apps stop brick-sorter --device ...`.

## 4. First run with the Gemini 2 (required)

The network and the calibrations were made with the C920; the Gemini 2 sees colors
differently, so:

1. Operator panel -> Camera settings: every control of the Gemini 2 (exposure, auto
   exposure, brightness, contrast, ... whatever it offers) with a slider / menu; changes
   apply live and are kept for the next start. Nothing is tuned automatically: the first
   start uses a fixed 10 ms exposure (one 50 Hz flicker period: no dark bands). The
   "Flicker-free exposure" menu (10 / 20 / 30 ms) is the quickest way to set brightness;
   "Choose exposure automatically" is optional; "Camera defaults" undoes everything.
2. Operator panel -> Set area: drag a rectangle over the black table.
3. New calibration: capture every face of the labeled bricks, Finish. The 1-NN and the
   relative band use it at once; the network is retrained on the Jetson in the
   background (a few minutes, the demo keeps running a bit slower) and loaded when done.

## Settings

`wendy.json` `env` (or `wendy run --env KEY=VALUE`):

| Variable | Default | Meaning |
|---|---|---|
| `CLASSIFIER` | `nn` | `nn`, `knn` or `relative` at start |
| `REFERENCE` | `latest` | calibration at start (`latest` = newest) |
| `CAMERA_MAX_HEIGHT` | `720` | largest camera mode up to this height (1080 for full HD; calibrate at the resolution you run) |
| `DEMO_ARGS` | | extra `web_demo.py` arguments, e.g. `--camera-device /dev/video4` |

Checks on the device: `python3 scripts/v4l2_camera.py` lists the video nodes, the mode
chosen and the read fps.

## Device facts (wendy device info, 2026-10-27)

- Jetson Orin Nano, WendyOS 0.20.0, JetPack 7.2, CUDA 13.2, 25 W mode, 7.8 GB RAM.
- The Gemini 2 appears as three UVC nodes (`/dev/video0`, `/dev/video2`, `/dev/video4`,
  driver uvcvideo); `v4l2_camera.py` picks the one with color formats.
- The JetPack 6 base image runs on JetPack 7 only with the CUDA library fix in the
  Dockerfile (from Wendy's template).

Not measured yet: speed on the Orin Nano (PyTorch FP16, no TensorRT yet).
