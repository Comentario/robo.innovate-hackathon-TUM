"""Live web demo: brick detection + tracking + good/bad classification in the browser.

  camera frame -> YOLO11n-seg brick detector + ByteTrack (one id per brick across frames)
               -> classifier per tracked brick, every few frames
               -> vote over the last frames of that brick -> GOOD / BAD / ... (deciding)
Open http://localhost:8000 : live video with outlines, track ids and decisions,
counters of good / bad bricks seen (one count per track id), the active tracks,
and a calibration panel.

Classifiers (--classifier, also switchable in the page):
  knn       1-nearest-neighbor on color features against a calibration (default: the
            top-view reference from build_top_view_reference.py)
  relative  band rule on the brick lightness relative to the table around it
            (L* of the brick surface minus L* of a ring of table around the brick);
            the band is fitted on the calibration in use (balanced accuracy)
  nn        YOLO11n-cls neural network on the brick crop (train_brick_classifier.py)
The big counters show the bricks in view now; the session total is shown below.
The page opens in presentation view (video, counters, one card per brick with the
crop the classifier sees, the pipeline with its timings); the Operator button or
key o shows the classifier, network and calibration controls.

Detection area: "Set area" in the operator panel shows the whole camera frame and lets
you drag a rectangle over the table; only bricks whose center is inside it are
classified and counted, and the stream shows only that part (zoom), so the floor or a
wall at the border is never taken for a brick. The detector still runs on the whole
frame: on a crop it would see the bricks larger than in training (it always resizes its
input to 640 px), which changed the masks and the classification. It is saved to
outputs2/demo_roi.json and used again at the next start (--no-roi ignores it).

Speed: the source is read in its own thread (only the newest frame is processed) and
the stream sends each processed frame as soon as it is ready; the fps shown is the
real processing rate.

Neural network retraining: after each calibration made in the browser (and with the
"Train now" button) the network is first scored on the new calibration's bricks (a
light it has not seen yet), then retrained in a separate process on the base crops
plus the bricks of every calibration (train_brick_classifier.py --include-calibrations);
the new weights are loaded when it finishes. The newest such run is used at start.

Calibration in the browser (for a new place or light): Capture freezes the frame
and numbers the bricks left to right; give each one Good / Bad / Skip (buttons or
keys g / b / s) and add the capture; repeat with every face of every brick, then
Finish. The calibration is saved to outputs2/calibration/<session>/ in the same
format as live_brick_classifier.py --calibrate and used at once (knn). Saved
calibrations can also be selected and used from the panel. The page shows the
scene light (table L*) next to the light of the calibration in use, so a light
change that calls for a new calibration is visible, and the share of clipped
(pure white) brick pixels: above 2% the exposure is too high (--exposure -6 / -7).

Sources: on Windows the C920 (fixed settings, as in capture_bricks.py); on Linux
(the Jetson) the V4L2 color camera, e.g. the Orbbec Gemini 2 (v4l2_camera.py), set by
the operator in the page: Operator -> Camera settings lists every control of the camera
and applies changes live; they are kept for the next start, nothing is tuned
automatically ("Choose exposure automatically" is an optional button); or, for testing
without a camera, --source with a video file or a folder of images (looped).

Jetson + laptop: the Jetson runs this script (see jetson/README.md) and does the
detection and classification; the laptop runs it with --remote http://<jetson>:8000,
which loads no model and serves the same page, passing every request and the video
stream through to the Jetson.

Usage:
  web_demo.py [--classifier knn|relative|nn] [--reference calibration.json|latest] [--nn-weights best.pt]
              [--weights detector.pt] [--source video_or_folder] [--camera 0] [--camera-device auto]
              [--port 8000] [--calibration-features raw|table|table_ratio] [--exposure -6] [--half]
  web_demo.py --remote http://wendyos-brick-hackathon-1.local:8000 [--port 8000]
"""

import argparse
import importlib.util
import json
import platform
import shutil
import subprocess
import sys
import threading
import time
from collections import deque
from pathlib import Path

import cv2
import numpy as np
import uvicorn
from fastapi import FastAPI, Request
from fastapi.responses import HTMLResponse, JSONResponse, Response, StreamingResponse
from starlette.background import BackgroundTask
from ultralytics import YOLO

PROJECT_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(PROJECT_ROOT))

import scripts.live_brick_classifier as live
from scripts.analyze_second_dataset_colors import bgr_to_lab
from scripts.build_classifier_dataset import brick_crop
from scripts.capture_bricks import camera_properties, open_camera, read_frame
from scripts.evaluate_top_view import fit_band as balanced_band
from scripts.evaluate_top_view import measure as top_view_measure

DETECTOR_WEIGHTS = PROJECT_ROOT / "outputs2" / "yolo_runs" / "brick_seg_v3" / "weights" / "best.pt"
TOP_REFERENCE = PROJECT_ROOT / "outputs2" / "top_view" / "reference" / "calibration.json"
# Detection area chosen in the page (fractions of the frame), kept for the next start.
ROI_FILE = PROJECT_ROOT / "outputs2" / "demo_roi.json"
# Fixed exposure / gain / white balance of the Linux camera (v4l2_camera.py).
CAMERA_SETTINGS = PROJECT_ROOT / "outputs2" / "camera_settings.json"
CAMERA_INFO_EVERY = 3.0
MIN_ROI = 0.1
CLASSIFIER_RUNS = PROJECT_ROOT / "outputs2" / "classifier_runs"
TRAIN_EPOCHS = 30


def latest_nn_weights() -> Path:
    """Newest network retrained by this page, else the `final` run."""
    runs = sorted(CLASSIFIER_RUNS.glob("web_*/weights/best.pt"))
    return runs[-1] if runs else CLASSIFIER_RUNS / "final" / "weights" / "best.pt"


NN_WEIGHTS = latest_nn_weights()
CONFIDENCE = 0.5
VOTES = 15
MIN_VOTES = 3
# A brick is classified every CLASSIFY_EVERY frames until it has VOTES votes, then
# only every SETTLED_EVERY frames; tracks are staggered so they do not all fall
# on the same frame.
CLASSIFY_EVERY = 3
SETTLED_EVERY = 15
STREAM_WIDTH = 960
# Decided bricks kept in the page's history strip (newest first).
HISTORY = 12
# Scene light: L* of the table strip at the bottom of the frame (as stored in the
# calibration), measured every LIGHT_EVERY frames. A difference to the calibration
# above LIGHT_WARN is shown as a warning, above LIGHT_RECALIBRATE as "recalibrate".
LIGHT_EVERY = 15
LIGHT_WARN = 3.0
LIGHT_RECALIBRATE = 6.0
# Brick pixels at this level or above are clipped (no color left); above
# MAX_CLIPPED of the brick area the camera exposure should be lowered.
CLIP_LEVEL = 250
MAX_CLIPPED = 0.02
COLORS = {"good": live.GOOD_BGR, "bad": live.BAD_BGR, None: live.PENDING_BGR}
# Relative lightness: the table ring around a brick spans 20-60 px (evaluate_top_view),
# so crops keep RING_MARGIN px around the brick; P(good) of the band rule moves from
# 0.5 to ~0.9 over RELATIVE_SCALE L* inside the band.
RING_MARGIN = 70
RELATIVE_SCALE = 5.0
METHOD_NAMES = {"knn": "1-NN (calibration)", "relative": "relative lightness band", "nn": "neural network"}
ERODE_KERNEL = cv2.getStructuringElement(cv2.MORPH_ELLIPSE, (2 * live.ERODE_PX + 1, 2 * live.ERODE_PX + 1))

PAGE = """<!doctype html>
<html lang="en"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width, initial-scale=1">
<title>Brick Classifier</title>
<style>
:root { --bg:#121417; --panel:#1a1d21; --raised:#20242a; --ink:#e6e8eb; --muted:#8b929b; --line:#2b3037;
        --good:#4a8fe7; --bad:#e8733f; --pending:#6b737d; --ok:#3fb47a; --warn:#d9a53a; --accent:#e6e8eb; color-scheme:dark; }
* { box-sizing:border-box; }
body { margin:0; background:var(--bg); color:var(--ink); font:15px/1.45 "Segoe UI", system-ui, -apple-system, Roboto, Helvetica, Arial, sans-serif;
       font-variant-numeric:tabular-nums; }
header { display:flex; align-items:center; gap:20px; flex-wrap:wrap; padding:14px 24px; border-bottom:1px solid var(--line); }
.brand { display:flex; align-items:center; gap:12px; margin-right:auto; }
.mark { width:14px; height:28px; border-radius:2px; background:#b4532a; }
.brand h1 { margin:0; font-size:19px; font-weight:600; }
.brand p { margin:0; color:var(--muted); font-size:13px; }
.status { display:flex; align-items:center; flex-wrap:wrap; color:var(--muted); font-size:13px; }
.stat { display:inline-flex; align-items:center; gap:7px; padding:0 14px; border-left:1px solid var(--line); white-space:nowrap; }
.stat:first-child { border-left:0; }
.stat i { width:7px; height:7px; border-radius:50%; background:var(--pending); }
.stat.live i, .stat.ok i { background:var(--ok); } .stat.warn i { background:var(--warn); }
.stat.bad i { background:var(--bad); } .stat.bad { color:var(--bad); }
.actions { display:flex; gap:8px; }
main { display:grid; grid-template-columns:minmax(0,1fr) 360px; gap:20px; padding:20px 24px; }
@media (max-width:1100px) { main { grid-template-columns:1fr; } }
.stage { min-width:0; display:flex; flex-direction:column; gap:14px; }
.side { display:flex; flex-direction:column; gap:16px; min-width:0; }
.panel { background:var(--panel); border:1px solid var(--line); border-radius:8px; padding:16px; }
h2 { margin:0 0 12px; font-size:12px; font-weight:600; color:var(--muted); text-transform:uppercase; letter-spacing:.05em; }
.video { position:relative; background:#000; border-radius:8px; overflow:hidden; border:1px solid var(--line); }
.video img { width:100%; max-height:max(320px, calc(100vh - 380px)); object-fit:contain; display:block; }
#roilayer { position:absolute; inset:0; cursor:crosshair; display:none; }
body.roiedit #roilayer { display:block; }
#roibox { position:absolute; border:2px dashed #fff; background:rgba(255,255,255,.12); display:none; }
#roihint { position:absolute; left:12px; bottom:12px; background:rgba(20,20,20,.85); color:#fff; padding:6px 10px;
           border-radius:4px; font-size:13px; }
#guide { position:absolute; left:0; right:0; bottom:0; display:none; justify-content:center; gap:28px; flex-wrap:wrap;
         padding:12px 16px; background:rgba(18,20,23,.82); color:#e6e8eb; font-size:15px; pointer-events:none; }
body.idle:not(.roiedit) #guide { display:flex; }
#guide b { color:var(--muted); font-weight:600; margin-right:6px; }
#guide .g { color:var(--good); font-weight:600; } #guide .b { color:var(--bad); font-weight:600; }
.flow { display:flex; flex-wrap:wrap; gap:6px 0; color:var(--muted); font-size:13px; }
.step { padding:0 14px; border-left:1px solid var(--line); min-width:0; }
.step:first-child { padding-left:0; border-left:0; }
.step b { color:var(--ink); font-weight:600; margin-right:6px; }
.sechead { display:flex; justify-content:space-between; align-items:baseline; }
.sechead h2 { margin:0; } .sechead small { font-size:12px; }
.history { display:flex; gap:8px; overflow-x:auto; padding:2px 0 4px; min-height:40px; margin-top:10px; }
.hist { flex:0 0 auto; width:100px; border-radius:6px; overflow:hidden; background:var(--panel); border:1px solid var(--line); font-size:12px; }
.hist img, .hist .noimg { width:100%; height:58px; object-fit:cover; display:block; background:#4a525b; }
.hist div { padding:5px 8px 6px; border-top:3px solid var(--pending); }
.hist.good div { border-top-color:var(--good); } .hist.bad div { border-top-color:var(--bad); }
.hist b { display:flex; justify-content:space-between; font-weight:600; } .hist.good b { color:var(--good); } .hist.bad b { color:var(--bad); }
.hist b em { font-style:normal; font-weight:400; color:var(--muted); }
.hist span { color:var(--muted); display:block; }
.hist.live { border-color:var(--muted); }
.verdict { background:var(--panel); border:1px solid var(--line); border-left:5px solid var(--pending); border-radius:8px; padding:16px 18px; }
.verdict.good { border-left-color:var(--good); } .verdict.bad { border-left-color:var(--bad); }
.verdict .big { font-size:52px; font-weight:700; line-height:1.05; }
.verdict.good .big { color:var(--good); } .verdict.bad .big { color:var(--bad); } .verdict.ready .big { color:var(--muted); font-size:36px; }
.verdict .what { font-size:16px; font-weight:600; margin-top:4px; }
.verdict .sub { color:var(--muted); font-size:13px; margin-top:2px; }
.kpis { display:grid; grid-template-columns:repeat(4, 1fr); border:1px solid var(--line); border-radius:6px; }
.kpi { padding:10px 12px; border-left:1px solid var(--line); min-width:0; }
.kpi:first-child { border-left:0; }
.kpi small { display:block; font-size:12px; color:var(--muted); }
.kpi b { display:block; font-size:28px; font-weight:600; line-height:1.2; }
.kpi.good b { color:var(--good); } .kpi.bad b { color:var(--bad); }
.totals { display:flex; justify-content:space-between; align-items:center; gap:8px; margin-top:10px; color:var(--muted); font-size:13px; }
.totals b { color:var(--ink); font-weight:600; }
.bricks { display:flex; flex-direction:column; gap:8px; max-height:40vh; overflow:auto; }
.empty { color:var(--muted); font-size:13.5px; padding:4px 0; }
.card { display:grid; grid-template-columns:96px 1fr; gap:12px; align-items:center; padding:8px; border-radius:6px;
        background:var(--raised); border:1px solid var(--line); border-left:3px solid var(--pending); }
.card.good { border-left-color:var(--good); } .card.bad { border-left-color:var(--bad); }
.card img, .card .noimg { width:96px; height:54px; border-radius:4px; background:#4a525b; object-fit:cover; display:block; }
.card .top { display:flex; justify-content:space-between; align-items:baseline; gap:8px; }
.tag { font-weight:700; font-size:14px; } .tag.good { color:var(--good); } .tag.bad { color:var(--bad); } .tag.pending { color:var(--muted); }
.card .id { color:var(--muted); font-size:12.5px; }
.bar { position:relative; height:5px; border-radius:3px; background:var(--line); margin:7px 0 5px; overflow:hidden; }
.bar i { position:absolute; inset:0 auto 0 0; background:var(--good); }
.bar u { position:absolute; left:50%; top:0; bottom:0; width:2px; margin-left:-1px; background:var(--ink); opacity:.6; }
.bar.p { background:rgba(232,115,63,.45); } .bar.p i { background:var(--good); }
.card .meta { color:var(--muted); font-size:12px; }
.vbar { height:2px; background:var(--line); margin-top:5px; overflow:hidden; }
.vbar i { display:block; height:100%; background:var(--muted); }
button, select { background:var(--raised); color:var(--ink); border:1px solid var(--line); border-radius:6px;
                 padding:6px 12px; cursor:pointer; font:inherit; font-size:13.5px; }
button:hover { border-color:var(--muted); }
button.primary { background:var(--ink); color:var(--bg); border-color:var(--ink); }
button:disabled { opacity:.45; cursor:default; }
button.on-good { background:var(--good); color:#fff; border-color:var(--good); }
button.on-bad { background:var(--bad); color:#fff; border-color:var(--bad); }
button.on-skip { background:var(--muted); color:var(--bg); border-color:var(--muted); }
button.link { border:none; background:none; padding:2px 4px; color:var(--muted); text-decoration:underline; font-size:12.5px; }
#operator { display:none; grid-template-columns:repeat(3, minmax(0,1fr)); gap:20px; padding:0 24px 24px; }
body.operator #operator { display:grid; }
@media (max-width:1100px) { #operator { grid-template-columns:1fr; } }
.row { display:flex; gap:8px; flex-wrap:wrap; align-items:center; margin:8px 0; }
select { flex:1; min-width:0; }
#snap { width:100%; border-radius:6px; margin:8px 0; display:block; }
.brick { display:flex; gap:6px; align-items:center; margin:4px 0; } .brick span { width:34px; font-weight:600; }
small, .muted { color:var(--muted); } #ref { overflow-wrap:anywhere; }
#campanel { grid-column:1 / -1; } #campanel .row select { flex:0 1 auto; }
.ctls { display:grid; grid-template-columns:repeat(auto-fill, minmax(240px, 1fr)); gap:12px 24px; margin:12px 0; }
.ctl { display:grid; grid-template-columns:1fr auto; gap:4px 8px; align-items:center; }
.ctl label { font-size:13px; text-transform:capitalize; } .ctl input[type=range], .ctl small { grid-column:1 / -1; }
.ctl input[type=range] { width:100%; accent-color:var(--good); } .ctl.off { opacity:.5; } .ctl select { min-width:0; }
.num { font-size:12.5px; color:var(--muted); }
.msg { margin:8px 0 0; min-height:1.4em; } .msg.warn { color:var(--bad); }
.light { padding:8px 10px; border-radius:6px; border:1px solid var(--line); margin-top:10px; background:var(--raised); }
.light.warn { border-color:var(--warn); } .light.bad { border-color:var(--bad); color:var(--bad); }
kbd { font:12px ui-monospace, Consolas, monospace; border:1px solid var(--line); border-radius:4px; padding:0 4px; }
/* Presentation mode (key p): full screen, larger, no operator controls. */
body.present #hwpill, body.present #opbtn, body.present #operator, body.present .totals .link { display:none !important; }
body.present main { grid-template-columns:minmax(0,1fr) 400px; }
body.present .verdict .big { font-size:68px; }
@media (max-width:1100px) { body.present main { grid-template-columns:1fr; } }
</style></head><body>
<header>
  <div class="brand"><span class="mark"></span>
    <div><h1>Brick Classifier</h1><p>Color-based quality inspection of reclaimed clay bricks · TUM Robo.Innovate Hackathon</p></div></div>
  <div class="status">
    <span class="stat live" id="livepill"><i></i><span id="fps">connecting...</span></span>
    <span class="stat" id="hwpill" hidden><span id="hwtext">-</span></span>
    <span class="stat">Model <span id="methodpill">-</span></span>
    <span class="stat" id="lightpill"><i></i>Light <span id="lighttext">-</span></span>
  </div>
  <div class="actions">
    <button id="presentbtn" onclick="togglePresent()" title="Presentation mode (key p)"><span id="presentlabel">Present</span></button>
    <button id="opbtn" onclick="toggleOperator()" title="Operator panel (key o)">Operator</button>
  </div>
</header>
<main>
  <div class="stage">
    <div class="video"><img id="video" src="/stream" alt="live camera with detected bricks">
      <div id="guide">
        <span><b>1</b>Place a brick on the table</span>
        <span><b>2</b>Wait about 1 s</span>
        <span><b>3</b><span class="g">GOOD</span> reuse, <span class="b">BAD</span> reject</span>
      </div>
      <div id="roilayer"><div id="roibox"></div>
        <div id="roihint">Drag a rectangle over the table area (Esc cancels)</div></div></div>
    <div class="flow">
      <div class="step"><b>Camera</b><span id="fcam">-</span></div>
      <div class="step"><b>Detection</b><span id="fdet">-</span></div>
      <div class="step"><b>Tracking</b><span id="ftrack">ByteTrack</span></div>
      <div class="step"><b>Classification</b><span id="fcls">-</span></div>
      <div class="step"><b>Decision</b><span id="fvote">-</span></div>
    </div>
    <div>
      <div class="sechead"><h2>Inspection log</h2><small id="histnote"></small></div>
      <div class="history" id="history"><div class="empty">Decided bricks appear here.</div></div>
    </div>
  </div>
  <div class="side">
    <div class="verdict ready" id="verdict">
      <h2 id="vlabel">Status</h2>
      <div class="big" id="vtext">Ready</div>
      <div class="what" id="vwhat">Waiting for a brick</div>
      <div class="sub" id="vsub">Place a brick under the camera.</div>
    </div>
    <div class="panel">
      <h2>Session</h2>
      <div class="kpis">
        <div class="kpi"><small>Inspected</small><b id="ttotal">0</b></div>
        <div class="kpi good"><small>Good</small><b id="tgood">0</b></div>
        <div class="kpi bad"><small>Bad</small><b id="tbad">0</b></div>
        <div class="kpi"><small>Yield</small><b id="trate">–</b></div>
      </div>
      <div class="totals"><span>In view: <b id="good">0</b> good, <b id="bad">0</b> bad</span>
        <button class="link" onclick="post('/reset')">Reset</button></div>
    </div>
    <div class="panel">
      <h2>In view</h2>
      <div class="bricks" id="tracks"><div class="empty">Place bricks under the camera.</div></div>
    </div>
  </div>
</main>
<section id="operator">
  <div class="panel">
    <h2>Classifier</h2>
    <div class="row"><select id="method"></select><button onclick="setMethod()">Use</button></div>
    <div class="muted" id="methodinfo"></div>
    <div class="light" id="light">Light: -</div>
    <div class="light" id="cambox" hidden>Camera: <span id="camtext">-</span>
      <div class="muted">Settings: Camera settings panel below.</div></div>
    <div class="light">Detection area: <b id="roitext">whole frame</b>
      <div class="row"><button onclick="editRoi(true)">Set area</button><button onclick="setRoi(null)">Whole frame</button></div>
      <small>Only bricks inside it are classified and counted; the video zooms to it.</small></div>
    <p class="muted"><kbd>o</kbd> shows / hides this panel · <kbd>p</kbd> presentation mode (full screen, no technical details).</p>
  </div>
  <div class="panel">
    <h2>Neural network</h2>
    <div>Weights: <b id="nnname">-</b> · <span id="nnstate">-</span></div>
    <div class="muted" id="nnscore"></div>
    <div class="row"><button onclick="trainNow()">Train now</button>
      <label class="muted"><input type="checkbox" id="nnauto" checked onchange="post('/nn/auto', {on: this.checked})">
      retrain after each calibration</label></div>
  </div>
  <div class="panel">
    <h2>Calibration</h2>
    <div class="muted">In use: <b id="ref">-</b></div>
    <div class="row"><select id="callist"></select><button onclick="useCal()">Use</button></div>
    <div class="row"><button id="newcal" class="primary" onclick="startCal()">New calibration</button></div>
    <div id="calwork" hidden>
      <div class="muted" id="calstatus"></div>
      <div class="row">
        <button class="primary" id="capbtn" onclick="captureCal()">Capture</button>
        <button onclick="calPost('/calibration/undo')">Undo last</button>
        <button onclick="calPost('/calibration/finish')">Finish</button>
        <button onclick="calPost('/calibration/cancel')">Cancel</button>
      </div>
      <div id="labelbox" hidden>
        <img id="snap" alt="captured frame with numbered bricks">
        <small>Label each brick, left to right (keys g / b / s).</small>
        <div id="brickbtns"></div>
        <div class="row"><button class="primary" id="addbtn" onclick="sendLabels()" disabled>Add capture</button></div>
      </div>
    </div>
    <p class="msg" id="calmsg"></p>
  </div>
  <div class="panel" id="campanel" hidden>
    <h2>Camera settings</h2>
    <div class="muted" id="camsummary"></div>
    <div class="row"><span class="muted">Flicker-free exposure</span><select id="expsel"></select>
      <button onclick="setExposure()">Set</button>
      <button onclick="lockCamera()">Choose exposure automatically</button>
      <button onclick="cameraDefaults()">Camera defaults</button></div>
    <div class="ctls" id="camctls"></div>
    <small>Changes apply at once and are kept for the next start. Recalibrate after changing the camera:
      the colors the classifier sees change.</small>
    <p class="msg" id="cammsg"></p>
  </div>
</section>
<script>
let labels = [];
const $ = id => document.getElementById(id);
async function post(url, body) {
  const r = await fetch(url, {method:'POST', headers:{'Content-Type':'application/json'}, body: JSON.stringify(body || {})});
  return r.json();
}
function message(text, warn) { $('calmsg').textContent = text || ''; $('calmsg').className = 'msg' + (warn ? ' warn' : ''); }
function toggleOperator(on) {
  const show = on === undefined ? !document.body.classList.contains('operator') : on;
  document.body.classList.toggle('operator', show);
  try { localStorage.setItem('operator', show ? '1' : '0'); } catch (e) {}
  if (show) $('operator').scrollIntoView({behavior: 'smooth'});
}
try { if (localStorage.getItem('operator') === '1') document.body.classList.add('operator'); } catch (e) {}
if (location.hash === '#operator') document.body.classList.add('operator');
function togglePresent(on) {
  const show = on === undefined ? !document.body.classList.contains('present') : on;
  document.body.classList.toggle('present', show);
  $('presentlabel').textContent = show ? 'Exit' : 'Present';
  try { localStorage.setItem('present', show ? '1' : '0'); } catch (e) {}
  try {
    if (show && !document.fullscreenElement) document.documentElement.requestFullscreen().catch(() => {});
    if (!show && document.fullscreenElement) document.exitFullscreen().catch(() => {});
  } catch (e) {}
}
try { if (localStorage.getItem('present') === '1') togglePresent(true); } catch (e) {}
if (location.hash === '#present') togglePresent(true);
const confidence = p => `${Math.round((p < 0.5 ? 1 - p : p) * 100)}% ${p < 0.5 ? 'bad' : 'good'}`;
let maxVotes = 15;
function card(t) {
  const d = t.decision || 'pending', p = t.p_good;
  const img = t.crop ? `<img src="/crop/${t.id}?v=${t.crop}" alt="brick ${t.n || ''} as the classifier sees it">` : '<div class="noimg"></div>';
  // P(good) from the left, the 50% decision threshold as a line.
  const bar = p === null ? '' : `<div class="bar p" title="P(good) = ${Math.round(p * 100)}%; GOOD from 50%"><i style="width:${Math.round(p * 100)}%"></i><u></u></div>`;
  const conf = p === null ? 'measuring...' : confidence(p);
  return `<div class="card ${d}">${img}<div><div class="top"><span class="tag ${d}">${d === 'pending' ? 'DECIDING' : d.toUpperCase()}</span>` +
    `<span class="id">${t.n ? '#' + t.n : 'new'}</span></div>${bar}<div class="meta">${conf} · votes ${t.votes}/${maxVotes}` +
    `${t.value === null ? '' : ' · rel L* ' + t.value}</div>` +
    `<div class="vbar"><i style="width:${Math.round(Math.min(1, t.votes / maxVotes) * 100)}%"></i></div></div></div>`;
}
function histItem(h, live) {
  const d = h.decision || 'pending';
  const img = h.crop ? `<img src="/history/${h.n}?v=${h.crop}" alt="brick ${h.n}">` : '<div class="noimg"></div>';
  const time = h.t ? new Date(h.t * 1000).toLocaleTimeString([], {hour: '2-digit', minute: '2-digit', second: '2-digit', hour12: false}) : '';
  return `<div class="hist ${d}${live ? ' live' : ''}" title="brick #${h.n} · ${h.votes} votes">${img}` +
    `<div><b>${d.toUpperCase()}<em>#${h.n}</em></b><span>${h.p_good === null ? '-' : confidence(h.p_good)}</span><span>${time}</span></div></div>`;
}
// Status panel: the newest decided brick (in view or the last one seen).
function verdict(history, active) {
  const h = history[0];
  if (!h) {
    $('verdict').className = 'verdict ready'; $('vlabel').textContent = 'Status'; $('vtext').textContent = 'Ready';
    $('vwhat').textContent = 'Waiting for a brick'; $('vsub').textContent = 'Place a brick under the camera.';
    return;
  }
  const inView = active.some(t => t.n === h.n);
  $('verdict').className = `verdict ${h.decision}`;
  $('vlabel').textContent = inView ? `Brick #${h.n} · in view` : `Last brick · #${h.n}`;
  $('vtext').textContent = h.decision.toUpperCase();
  $('vwhat').textContent = h.decision === 'good' ? 'Reusable' : 'Reject';
  $('vsub').textContent = `Confidence ${confidence(h.p_good)} · ${h.votes}/${maxVotes} votes`;
}
async function poll() {
  try {
    const s = await (await fetch('/stats')).json();
    $('good').textContent = s.good; $('bad').textContent = s.bad;
    $('tgood').textContent = s.total_good; $('tbad').textContent = s.total_bad;
    const total = s.total_good + s.total_bad;
    $('ttotal').textContent = total;
    $('trate').textContent = total ? `${Math.round(100 * s.total_good / total)}%` : '–';
    verdict(s.history, s.active);
    maxVotes = s.votes;
    document.body.classList.toggle('idle', !s.active.length);
    const live = new Set(s.active.map(t => t.n));
    $('history').innerHTML = s.history.length ? s.history.map(h => histItem(h, live.has(h.n))).join('')
      : '<div class="empty">Decided bricks appear here.</div>';
    $('histnote').textContent = s.history.length ? 'Newest first' : '';
    $('fps').textContent = `Live · ${s.fps.toFixed(0)} fps`;
    $('methodpill').textContent = s.classifier === 'nn' ? (s.nn.model || 'Neural network') : s.classifier_name;
    const T = s.timing;
    $('fcam').textContent = `${s.frame_size || '-'} · ${s.camera_fps.toFixed(0)} fps`;
    $('fdet').textContent = `${s.detector} · ${T.detect.toFixed(0)} ms`;
    $('fcls').textContent = `${s.classifier === 'nn' ? 'YOLO11n-cls' : s.classifier_name} · ${T.classify.toFixed(0)} ms`;
    $('fvote').textContent = `mean of up to ${s.votes} votes`;
    const opts = Object.entries(s.methods).map(([k, v]) => `<option value="${k}" ${k === s.classifier ? 'selected' : ''}>${v}</option>`).join('');
    if ($('method').dataset.opts !== opts && document.activeElement !== $('method')) { $('method').innerHTML = opts; $('method').dataset.opts = opts; }
    $('methodinfo').textContent = s.classifier === 'relative' && s.relative_band
      ? `Good if ${s.relative_band[0]} <= relative L* <= ${s.relative_band[1]} (fitted on ${s.relative_band[2]} faces)` : '';
    $('ref').textContent = s.reference || '-';
    const L = s.light;
    if (L.scene !== null) {
      let text = `Light (table L*): <b>${L.scene.toFixed(1)}</b>`, cls = 'light', pill = 'ok', short = 'OK';
      if (L.reference !== null) {
        const d = L.scene - L.reference;
        text += ` · calibration <b>${L.reference.toFixed(1)}</b> · difference <b>${d > 0 ? '+' : ''}${d.toFixed(1)}</b>`;
        if (Math.abs(d) > L.recalibrate) { text += ' · light changed: recalibrate'; cls += ' bad'; pill = 'bad'; short = 'Changed'; }
        else if (Math.abs(d) > L.warn) { text += ' · light is drifting'; cls += ' warn'; pill = 'warn'; short = 'Drifting'; }
        else text += ' · OK';
      }
      if (L.clipped !== null) {
        const pct = (L.clipped * 100).toFixed(1);
        if (L.clipped > L.max_clipped) { text += `<br>Bricks clipped (pure white): <b>${pct}%</b> · too bright: lower the exposure`; cls += ' bad'; pill = 'bad'; short = 'Too bright'; }
        else text += `<br>Bricks clipped (pure white): <b>${pct}%</b> · OK`;
      }
      $('light').innerHTML = text; $('light').className = cls;
      $('lightpill').className = 'stat ' + pill; $('lighttext').textContent = short;
    }
    $('tracks').innerHTML = s.active.length ? s.active.map(card).join('') : '<div class="empty">Place bricks under the camera.</div>';
    const n = s.nn;
    $('nnname').textContent = n.weights || 'none';
    $('nnstate').textContent = n.training ? `training... ${n.elapsed_s}s` : n.message;
    $('nnscore').textContent = n.last_score ? `Before the last retraining, on the new calibration light: ${n.last_score}` : '';
    if (document.activeElement !== $('nnauto')) $('nnauto').checked = n.auto;
    const c = s.calibration;
    $('calwork').hidden = !c.active; $('newcal').disabled = c.active;
    if (c.active) $('calstatus').textContent = `${c.captures} captures, ${c.good} good and ${c.bad} bad faces (need ${c.min_per_class} of each)`;
    $('livepill').className = 'stat live';
    fullSize = s.full_size;
    $('hwpill').hidden = !s.hardware; $('hwtext').textContent = (s.hardware || '').replace(/^NVIDIA (GeForce )?/, '');
    const cam = s.camera;
    $('cambox').hidden = !cam; $('campanel').hidden = !cam;
    if (cam) renderCamera(cam);
    document.body.classList.toggle('roiedit', s.roi_editing);
    $('roitext').textContent = s.roi ? `${Math.round((s.roi[2] - s.roi[0]) * 100)}% x ${Math.round((s.roi[3] - s.roi[1]) * 100)}% of the frame` : 'whole frame';
  } catch (e) { $('fps').textContent = 'No connection'; $('livepill').className = 'stat bad'; }
  setTimeout(poll, 500);
}
async function loadList() {
  const list = await (await fetch('/calibrations')).json();
  $('callist').innerHTML = list.map(c =>
    `<option value="${c.name}">${c.name} · ${c.good} good / ${c.bad} bad faces${c.lightness === null ? '' : ' · L* ' + c.lightness}${c.self_check === null ? '' : ' · self-check ' + Math.round(c.self_check * 100) + '%'}</option>`).join('');
}
async function trainNow() { const r = await post('/nn/train'); message(r.message, !r.ok); }
async function setMethod() { const r = await post('/classifier', {kind: $('method').value}); message(r.message, !r.ok); }
async function useCal() { const r = await post('/calibration/use', {name: $('callist').value}); message(r.message, !r.ok); }
async function startCal() { const r = await post('/calibration/start'); message(r.message, !r.ok); }
async function calPost(url) {
  const r = await post(url); message(r.message, !r.ok);
  $('labelbox').hidden = true;
  if (url.endsWith('finish') && r.ok) loadList();
}
async function captureCal() {
  const r = await post('/calibration/capture');
  message(r.message, !r.ok);
  if (!r.ok) return;
  labels = r.positions.map(() => null);
  $('snap').src = '/calibration/snapshot?t=' + Date.now();
  drawButtons(); $('labelbox').hidden = false;
}
function drawButtons() {
  $('brickbtns').innerHTML = labels.map((l, i) =>
    `<div class="brick"><span>#${i + 1}</span>` +
    ['good', 'bad', 'skip'].map(v => `<button class="${l === v ? 'on-' + v : ''}" onclick="setLabel(${i}, '${v}')">${v[0].toUpperCase() + v.slice(1)}</button>`).join('') +
    `</div>`).join('');
  $('addbtn').disabled = labels.some(l => l === null);
}
function setLabel(i, v) { labels[i] = v; drawButtons(); }
async function sendLabels() {
  const r = await post('/calibration/labels', {labels});
  message(r.message, !r.ok);
  if (r.ok) $('labelbox').hidden = true;
}
document.addEventListener('keydown', e => {
  if (e.target.matches('input, select, textarea')) return;
  if (e.key === 'Escape' && document.body.classList.contains('roiedit')) { dragStart = null; editRoi(false); return; }
  if ($('labelbox').hidden) {
    if (e.key === 'o') toggleOperator();
    if (e.key === 'p') togglePresent();
    return;
  }
  const v = {g:'good', b:'bad', s:'skip'}[e.key];
  const i = labels.indexOf(null);
  if (v && i >= 0) setLabel(i, v);
  if (e.key === 'Enter' && !$('addbtn').disabled) sendLabels();
});
let fullSize = null, dragStart = null;
let camKey = '', lastCam = null;
function camMessage(text, warn) { $('cammsg').textContent = text || ''; $('cammsg').className = 'msg' + (warn ? ' warn' : ''); }
function valueText(name, value, cam) {
  return cam && name === cam.roles.exposure && cam.exposure_unit_ms ? `${value} (${(value * cam.exposure_unit_ms).toFixed(1)} ms)` : `${value}`;
}
function controlRow(name, c, cam) {
  const off = /inactive|read-only|disabled/.test(c.flags || '');
  const label = `<label for="ctl_${name}">${name.replace(/_/g, ' ')}${name in (cam.saved || {}) ? ' <span class="muted">· saved</span>' : ''}</label>`;
  let input;
  if (c.type === 'bool') {
    input = `<input type="checkbox" id="ctl_${name}" ${c.value ? 'checked' : ''} ${off ? 'disabled' : ''} onchange="setControl('${name}', this.checked ? 1 : 0)">`;
  } else if (c.menu) {
    input = `<select id="ctl_${name}" ${off ? 'disabled' : ''} onchange="setControl('${name}', Number(this.value))">` +
      Object.entries(c.menu).map(([v, l]) => `<option value="${v}" ${Number(v) === c.value ? 'selected' : ''}>${l}</option>`).join('') + '</select>';
  } else {
    input = `<span class="num" id="val_${name}">${valueText(name, c.value, cam)}</span>` +
      `<input type="range" id="ctl_${name}" min="${c.min}" max="${c.max}" step="${c.step || 1}" value="${c.value}" ${off ? 'disabled' : ''}` +
      ` oninput="$('val_${name}').textContent = valueText('${name}', Number(this.value), lastCam)" onchange="setControl('${name}', Number(this.value))">`;
  }
  return `<div class="ctl${off ? ' off' : ''}">${label}${input}${off ? '<small>inactive: its automatic mode is on</small>' : ''}</div>`;
}
function renderCamera(cam) {
  lastCam = cam;
  const summary = `${cam.name || cam.device} · ${cam.width}x${cam.height} ${cam.format} · ${(cam.grab_fps || 0).toFixed(0)} fps` +
    (cam.decode_ms ? ` · decode ${cam.decode_ms} ms` : '') + ` · exposure ${cam.exposure_ms ?? '-'} ms` + (cam.status ? ` · ${cam.status}` : '');
  $('camtext').textContent = summary; $('camsummary').textContent = summary;
  const eo = (cam.exposure_options || []).map(o => `<option value="${o.value}" ${o.value === cam.exposure ? 'selected' : ''}>${o.ms} ms</option>`).join('');
  if ($('expsel').dataset.opts !== eo && document.activeElement !== $('expsel')) { $('expsel').innerHTML = eo; $('expsel').dataset.opts = eo; }
  const controls = cam.controls || {};
  // Rebuilt only when the set of controls, their kind or their flags change (not while a slider is held).
  const key = Object.entries(controls).map(([n, c]) => `${n}:${c.type}:${c.flags}:${n in (cam.saved || {})}`).join('|');
  if (key !== camKey && !document.activeElement?.id?.startsWith('ctl_')) {
    camKey = key;
    $('camctls').innerHTML = Object.entries(controls).map(([n, c]) => controlRow(n, c, cam)).join('');
  }
  for (const [n, c] of Object.entries(controls)) {
    const el = $('ctl_' + n);
    if (!el || document.activeElement === el) continue;
    if (c.type === 'bool') el.checked = !!c.value; else el.value = c.value;
    if ($('val_' + n)) $('val_' + n).textContent = valueText(n, c.value, cam);
  }
}
async function setControl(name, value) { const r = await post('/camera/control', {name, value}); camMessage(r.message, !r.ok); }
async function cameraDefaults() { const r = await post('/camera/defaults'); camMessage(r.message, !r.ok); }
async function lockCamera() { camMessage('trying each exposure (a few seconds)...'); const r = await post('/camera/lock'); camMessage(r.message, !r.ok); }
async function setExposure() { const r = await post('/camera/exposure', {value: Number($('expsel').value)}); camMessage(r.message, !r.ok); }
$('video').addEventListener('error', () => setTimeout(() => { $('video').src = '/stream?t=' + Date.now(); }, 1000));
async function editRoi(on) { const r = await post('/roi/edit', {on}); message(r.message, !r.ok); }
async function setRoi(box) { const r = await post('/roi', {box}); message(r.message, !r.ok); }
function imageRect() {
  // Where the frame is drawn inside the <img> (object-fit: contain), in page pixels.
  const r = $('video').getBoundingClientRect(), a = fullSize ? fullSize[0] / fullSize[1] : 16 / 9;
  let w = r.width, h = w / a;
  if (h > r.height) { h = r.height; w = h * a; }
  return {x: r.left + (r.width - w) / 2, y: r.top + (r.height - h) / 2, w, h};
}
function toFrame(e) {
  const r = imageRect();
  return [Math.min(1, Math.max(0, (e.clientX - r.x) / r.w)), Math.min(1, Math.max(0, (e.clientY - r.y) / r.h))];
}
$('roilayer').addEventListener('mousedown', e => { dragStart = toFrame(e); e.preventDefault(); });
window.addEventListener('mousemove', e => {
  if (!dragStart) return;
  const r = imageRect(), layer = $('roilayer').getBoundingClientRect(), end = toFrame(e), box = $('roibox');
  const x0 = Math.min(dragStart[0], end[0]), y0 = Math.min(dragStart[1], end[1]);
  box.style.display = 'block';
  box.style.left = (r.x - layer.left + x0 * r.w) + 'px'; box.style.top = (r.y - layer.top + y0 * r.h) + 'px';
  box.style.width = (Math.abs(end[0] - dragStart[0]) * r.w) + 'px'; box.style.height = (Math.abs(end[1] - dragStart[1]) * r.h) + 'px';
});
window.addEventListener('mouseup', e => {
  if (!dragStart) return;
  const end = toFrame(e), start = dragStart;
  dragStart = null; $('roibox').style.display = 'none';
  setRoi([Math.min(start[0], end[0]), Math.min(start[1], end[1]), Math.max(start[0], end[0]), Math.max(start[1], end[1])]);
});
loadList(); poll();
</script></body></html>"""


class Source:
    """Camera, video file or image folder (looped), one frame at a time."""

    def __init__(self, source: Path | None, camera: int, exposure: float | None = None,
                 camera_device: str | None = None, camera_max_height: int | None = None) -> None:
        self.images, self.index, self.capture, self.v4l2 = [], 0, None, None
        self.info, self.info_time = None, 0.0
        if source is None and camera_device:
            from scripts.v4l2_camera import V4L2Camera
            self.v4l2 = V4L2Camera(camera_device, settings_path=CAMERA_SETTINGS, max_height=camera_max_height)
        elif source is None:
            self.capture = open_camera(camera)
            if exposure is not None:
                self.capture.set(cv2.CAP_PROP_EXPOSURE, exposure)
        elif source.is_dir():
            self.images = sorted(p for p in source.iterdir() if p.suffix.lower() in (".jpg", ".png"))
        else:
            self.capture = cv2.VideoCapture(str(source))
        self.is_camera = source is None
        # A video file is played at its own frame rate (the reader thread would otherwise race through it).
        self.period = 1 / (self.capture.get(cv2.CAP_PROP_FPS) or 30) if source is not None and not self.images else 0
        self.due = time.monotonic()

    def read(self) -> np.ndarray:
        if self.images:
            frame = cv2.imread(str(self.images[self.index % len(self.images)]))
            self.index += 1
            time.sleep(0.2)
            return frame
        if self.v4l2 is not None:
            frame = self.v4l2.read()
            while frame is None:
                frame = self.v4l2.read()
            return frame
        if self.is_camera:
            return read_frame(self.capture)
        self.due = max(self.due + self.period, time.monotonic() - self.period)
        time.sleep(max(0.0, self.due - time.monotonic()))
        ok, frame = self.capture.read()
        if not ok:
            self.capture.set(cv2.CAP_PROP_POS_FRAMES, 0)
            ok, frame = self.capture.read()
        return frame

    def camera(self) -> dict | None:
        if self.v4l2 is not None:
            # Read through v4l2-ctl, so refreshed only every few seconds.
            if time.monotonic() - self.info_time > CAMERA_INFO_EVERY:
                self.info, self.info_time = self.v4l2.properties(), time.monotonic()
            return self.info
        return camera_properties(self.capture) if self.is_camera else None

    def set_control(self, name: str, value: int) -> dict:
        if self.v4l2 is None:
            return {"ok": False, "message": "only the Linux camera is set from the page"}
        message = self.v4l2.set_control(name, value)
        self.info_time = 0.0
        return {"ok": not message.startswith("unknown"), "message": message}

    def camera_defaults(self) -> dict:
        if self.v4l2 is None:
            return {"ok": False, "message": "only the Linux camera is set from the page"}
        message = self.v4l2.reset_defaults()
        self.info_time = 0.0
        return {"ok": True, "message": message}

    def set_exposure(self, value: int) -> dict:
        if self.v4l2 is None:
            return {"ok": False, "message": "only the Linux camera exposure can be set here"}
        message = self.v4l2.set_exposure(value)
        self.info_time = 0.0
        return {"ok": True, "message": message + " (recalibrate if the colors changed)"}

    def lock(self) -> dict:
        if self.v4l2 is None:
            return {"ok": False, "message": "only the Linux camera can be re-locked"}
        message = self.v4l2.lock()
        self.info_time = 0.0
        return {"ok": True, "message": message + " (recalibrate: the colors changed)"}

    def release(self) -> None:
        if self.capture is not None:
            self.capture.release()
        if self.v4l2 is not None:
            self.v4l2.release()


class FrameReader:
    """Reads the source in its own thread and keeps only the newest frame, so reading the
    camera overlaps with detection and the demo never works on a stale frame."""

    def __init__(self, source: Source) -> None:
        self.source, self.frame, self.seq, self.fps = source, None, 0, 0.0
        self.running = True
        self.ready = threading.Condition()
        self.thread = threading.Thread(target=self.loop, daemon=True)
        self.thread.start()

    def loop(self) -> None:
        last = time.monotonic()
        while self.running:
            frame = self.source.read()
            if frame is None:
                continue
            now = time.monotonic()
            with self.ready:
                self.frame, self.seq = frame, self.seq + 1
                self.fps = 0.9 * self.fps + 0.1 / max(1e-3, now - last)
                self.ready.notify_all()
            last = now

    def next(self, seen: int) -> tuple[np.ndarray | None, int]:
        """The newest frame after frame number `seen` (waits up to 1 s)."""
        with self.ready:
            self.ready.wait_for(lambda: self.seq > seen or not self.running, timeout=1.0)
            return self.frame, self.seq

    def stop(self) -> None:
        self.running = False
        self.thread.join(timeout=2)


def in_area(xyxy, box: tuple | None) -> bool:
    """Center of a detection box inside the detection area (always, without an area)."""
    if box is None:
        return True
    cx, cy = (xyxy[0] + xyxy[2]) / 2, (xyxy[1] + xyxy[3]) / 2
    return box[0] <= cx < box[2] and box[1] <= cy < box[3]


def box_iou(a: dict, b: dict) -> float:
    ax2, ay2, bx2, by2 = a["x"] + a["width"], a["y"] + a["height"], b["x"] + b["width"], b["y"] + b["height"]
    inter = max(0, min(ax2, bx2) - max(a["x"], b["x"])) * max(0, min(ay2, by2) - max(a["y"], b["y"]))
    return inter / (a["width"] * a["height"] + b["width"] * b["height"] - inter + 1e-6)


def to_bboxes(boxes: np.ndarray) -> list[dict]:
    return [{"x": int(x1), "y": int(y1), "width": int(x2 - x1), "height": int(y2 - y1)} for x1, y1, x2, y2 in boxes]


def measurement_region(masks: np.ndarray, claimed: np.ndarray, index: int, bbox: dict) -> np.ndarray | None:
    """Brick pixels as the live classifier measures them: own pixels only, inside the box, eroded."""
    x, y, w, h = bbox["x"], bbox["y"], bbox["width"], bbox["height"]
    pad = live.ERODE_PX + 2
    y0, y1, x0, x1 = max(0, y - pad), min(masks.shape[1], y + h + pad), max(0, x - pad), min(masks.shape[2], x + w + pad)
    own = masks[index, y0:y1, x0:x1] & (claimed[y0:y1, x0:x1] == 1)
    inside = np.zeros_like(own)
    inside[y - y0:y - y0 + h, x - x0:x - x0 + w] = True
    eroded = cv2.erode((own & inside).astype(np.uint8), ERODE_KERNEL).astype(bool)
    if eroded[y - y0:y - y0 + h, x - x0:x - x0 + w].mean() < live.MIN_BRICK_COVERAGE:
        return None
    region = np.zeros(masks.shape[1:], bool)
    region[y0:y1, x0:x1] = eroded
    return region


def color_features(frame: np.ndarray, region: np.ndarray, bbox: dict, table) -> dict:
    features = live.add_relative_lightness(live.brick_features(frame[region], table))
    features.update(live.surface_features(frame, region, bbox))
    return features


def bricks_nearby(polygons, shape) -> np.ndarray:
    """All brick masks, slightly grown: excluded from the table ring of every brick."""
    union = np.zeros(shape[:2], np.uint8)
    for polygon in polygons:
        if len(polygon) >= 3:
            cv2.fillPoly(union, [np.asarray(polygon).astype(np.int32)], 1)
    return cv2.dilate(union, np.ones((15, 15), np.uint8)).astype(bool)


def relative_lightness(frame: np.ndarray, polygon, nearby: np.ndarray) -> float | None:
    """L* of the brick surface (holes and stains handled) minus L* of the table ring around it."""
    polygon = np.asarray(polygon, np.float32)
    x, y, w, h = cv2.boundingRect(polygon.astype(np.int32))
    x0, y0 = max(0, x - RING_MARGIN), max(0, y - RING_MARGIN)
    x1, y1 = min(frame.shape[1], x + w + RING_MARGIN), min(frame.shape[0], y + h + RING_MARGIN)
    crop = frame[y0:y1, x0:x1]
    lab = bgr_to_lab(crop.reshape(-1, 3)).reshape(*crop.shape[:2], 3)
    value = top_view_measure(lab, polygon - (x0, y0), nearby[y0:y1, x0:x1])["dL_bg"]
    return float(value) if np.isfinite(value) else None


class RelativeReference:
    """Band on the relative lightness, fitted on calibration faces for balanced accuracy."""

    def __init__(self, values: list[float], labels: list[str]) -> None:
        self.low, self.high = balanced_band(values, labels)
        self.faces = len(values)

    def p_good(self, value: float) -> float:
        inside = min(value - self.low, self.high - value)
        return float(0.5 + 0.5 * np.tanh(inside / RELATIVE_SCALE))


class Calibration:
    """Calibration session built in the browser; same file format as live_brick_classifier.py."""

    def __init__(self, camera: dict | None) -> None:
        self.root = live.CALIBRATION_ROOT / time.strftime("%Y%m%d_%H%M%S")
        (self.root / "frames").mkdir(parents=True, exist_ok=True)
        self.camera = camera
        self.rows: list[dict] = []
        self.captures: list[str] = []
        self.pending: dict | None = None

    def counts(self) -> tuple[int, int]:
        goods = sum(r["label"] == "good" for r in self.rows)
        return goods, len(self.rows) - goods

    def finish(self, feature_set: str) -> tuple[Path, dict]:
        rows = self.rows
        scores = live.calibration_self_check(rows)
        bands = live.fit_face_bands(rows)
        band = bands["solid"] or live.fit_band(rows, live.BAND_FEATURE)
        goods, bads = self.counts()
        data = {"created": time.strftime("%Y-%m-%d %H:%M:%S"), "source": "web_demo", "camera": self.camera,
                "band_" + live.BAND_FEATURE: [band[0], band[1]], "band_self_check": live.band_self_check(rows),
                "bands_by_face": {k: (list(v) if v else None) for k, v in bands.items()},
                "band_self_check_perforated": live.band_self_check(rows, "perforated"),
                "scene_lightness": round(float(np.median([r["scene_lightness"] for r in rows])), 1),
                "feature_set": feature_set, "self_check": scores,
                "good_bricks": goods, "bad_bricks": bads, "rows": rows}
        path = self.root / "calibration.json"
        path.write_text(json.dumps(data, indent=2), encoding="utf-8")
        conflicts = [f"{a['photo']}#{a['position']} {a['label']} / {b['photo']}#{b['position']} {b['label']}"
                     for a, b in live.label_conflicts(rows)]
        return path, {"self_check": scores[feature_set]["accuracy"], "conflicts": conflicts}


class Trainer:
    """Retrains the network in a separate process (base crops + every calibration)."""

    def __init__(self) -> None:
        self.process: subprocess.Popen | None = None
        self.name, self.started, self.message, self.last_score = None, None, "idle", None

    def start(self) -> dict:
        if self.process is not None and self.process.poll() is None:
            return {"ok": False, "message": "the network is already training"}
        self.name = "web_" + time.strftime("%Y%m%d_%H%M%S")
        CLASSIFIER_RUNS.mkdir(parents=True, exist_ok=True)
        log = (CLASSIFIER_RUNS / f"{self.name}.log").open("w", encoding="utf-8")
        command = [sys.executable, str(PROJECT_ROOT / "scripts" / "train_brick_classifier.py"), "--experiment", "final",
                   "--include-calibrations", "--name", self.name, "--epochs", str(TRAIN_EPOCHS)]
        self.process = subprocess.Popen(command, cwd=str(PROJECT_ROOT), stdout=log, stderr=subprocess.STDOUT)
        self.started, self.message = time.monotonic(), "training"
        return {"ok": True, "message": f"retraining the network ({self.name}), a few minutes"}

    def poll(self) -> Path | None:
        """Weights of a run that just finished well (once), else None."""
        if self.process is None or self.process.poll() is None:
            return None
        code, self.process = self.process.returncode, None
        weights = CLASSIFIER_RUNS / self.name / "weights" / "best.pt"
        if code == 0 and weights.exists():
            self.message = f"ready: {self.name}"
            return weights
        self.message = f"training failed (see outputs2/classifier_runs/{self.name}.log)"
        return None

    def status(self) -> dict:
        running = self.process is not None and self.process.poll() is None
        return {"training": running, "message": self.message, "last_score": self.last_score,
                "elapsed_s": round(time.monotonic() - self.started) if running else None}


def hardware_name() -> str:
    """Board or GPU the models run on, e.g. "NVIDIA Jetson Orin Nano Developer Kit"."""
    model = Path("/proc/device-tree/model")
    if model.exists():
        return model.read_text(errors="ignore").strip("\x00 \n")
    import torch
    return torch.cuda.get_device_name(0) if torch.cuda.is_available() else platform.processor() or "CPU"


def latest_calibration() -> Path:
    """Newest calibration in outputs2/calibration, else the top-view reference."""
    paths = sorted(live.CALIBRATION_ROOT.glob("*/calibration.json"))
    return paths[-1] if paths else TOP_REFERENCE


def run_proxy(remote: str, port: int) -> None:
    """Laptop side: serve the page and pass every request (and the stream) through to the Jetson."""
    import httpx

    client = httpx.AsyncClient(base_url=remote.rstrip("/"), timeout=httpx.Timeout(30.0, read=None))
    app = FastAPI()

    @app.get("/", response_class=HTMLResponse)
    def page() -> str:
        return PAGE

    @app.get("/stream")
    async def stream() -> Response:
        try:
            response = await client.send(client.build_request("GET", "/stream"), stream=True)
        except httpx.HTTPError as error:
            return JSONResponse({"ok": False, "message": f"Jetson not reachable: {error}"}, status_code=502)
        return StreamingResponse(response.aiter_raw(), media_type=response.headers.get("content-type"),
                                 background=BackgroundTask(response.aclose))

    @app.api_route("/{path:path}", methods=["GET", "POST"])
    async def forward(path: str, request: Request) -> Response:
        try:
            response = await client.request(request.method, "/" + path, params=request.query_params,
                                            content=await request.body(),
                                            headers={"Content-Type": request.headers.get("content-type", "application/json")})
        except httpx.HTTPError as error:
            return JSONResponse({"ok": False, "message": f"Jetson not reachable: {error}"}, status_code=502)
        return Response(response.content, status_code=response.status_code,
                        media_type=response.headers.get("content-type"))

    print(f"open http://localhost:{port} (detection runs on {remote})")
    uvicorn.run(app, host="0.0.0.0", port=port, log_level="warning")


def load_roi() -> list[float] | None:
    try:
        return json.loads(ROI_FILE.read_text(encoding="utf-8"))["roi"]
    except (OSError, ValueError, KeyError):
        return None


def model_name(model: YOLO) -> str:
    """Architecture of a YOLO model as shown to people, e.g. YOLO11n-seg."""
    return Path(model.model.yaml.get("yaml_file", "yolo")).stem.replace("yolo", "YOLO")


class Sorter:
    def __init__(self, args) -> None:
        self.detector = YOLO(str(args.weights))
        self.runtime = "PyTorch FP16" if args.half else "PyTorch"
        # Separate instance for calibration captures (requests run beside the tracking thread).
        self.snapshot_detector = YOLO(str(args.weights))
        self.kind = args.classifier
        self.reference, self.reference_name, self.relative = None, None, None
        self.nn, self.nn_name = None, None
        self.trainer = Trainer()
        self.auto_train = True
        if args.nn_weights.exists():
            self.nn = YOLO(str(args.nn_weights))
            self.good_index = [k for k, v in self.nn.names.items() if v == "good"][0]
            self.nn_name = args.nn_weights.parent.parent.name
        elif self.kind == "nn":
            raise SystemExit(f"neural network weights not found: {args.nn_weights}")
        self.use_reference(args.reference)
        self.calibration_features = args.calibration_features
        self.votes: dict[int, deque] = {}
        self.decided: dict[int, str] = {}
        # Session number of each decided track (1, 2, 3, ... in the order they were decided;
        # the tracker ids keep growing) and the last HISTORY decided bricks by number.
        self.numbers: dict[int, int] = {}
        self.history: dict[int, dict] = {}
        self.measured: dict[int, float | None] = {}
        self.lock = threading.Lock()
        # Notified on every new stream frame (the MJPEG stream waits on it instead of polling).
        self.updated = threading.Condition(self.lock)
        self.jpeg, self.fps, self.active, self.frame_no, self.frame = None, 0.0, [], 0, None
        self.last_step = None
        self.timing = {"detect": 0.0, "classify": 0.0, "draw": 0.0}
        self.detect_size = {"imgsz": args.detect_imgsz} if args.detect_imgsz else {}
        # Newest classifier crop of each tracked brick (JPEG) and the frame it was cut from.
        self.crops: dict[int, tuple[bytes, int]] = {}
        self.detector_name = model_name(self.detector)
        # FP16 through `quantize` (the old `half` argument logs a deprecation warning on every call).
        self.infer = {"quantize": 16} if args.half else {}
        self.hardware = hardware_name()
        self.tensorrt = importlib.util.find_spec("tensorrt") is not None
        self.to_draw = None
        self.to_draw_ready = threading.Condition()
        threading.Thread(target=self.encode_loop, daemon=True).start()
        if args.tensorrt:  # started last: it swaps the detector under the lock created above
            threading.Thread(target=self.use_tensorrt, args=(Path(args.weights),), daemon=True).start()
        self.scene_lightness: float | None = None
        self.clipped: float | None = None
        self.calibration: Calibration | None = None
        self.roi = None if args.no_roi else load_roi()
        self.roi_editing = False
        self.full_size: list[int] | None = None
        self.reset_tracker = False

    def use_reference(self, path: Path) -> None:
        # absolute(), not resolve(): on the Jetson outputs2 is a link to the persistent volume.
        path = Path(path).absolute()
        reference = live.Reference.load(path)
        relative = self.relative_reference(path)
        # Calibrations are named by their session folder; other files by their path.
        if path.parent.parent == live.CALIBRATION_ROOT:
            name = path.parent.name
        elif path.is_relative_to(PROJECT_ROOT):
            name = path.relative_to(PROJECT_ROOT).as_posix()
        else:
            name = str(path)
        if hasattr(self, "lock"):
            with self.lock:
                self.reference, self.reference_name, self.relative = reference, name, relative
                if self.kind == "relative" and relative is None:
                    self.kind = "knn"
                self.votes.clear()
                self.clear_session()
        else:
            self.reference, self.reference_name, self.relative = reference, name, relative
            if self.kind == "relative" and relative is None:
                raise SystemExit("this calibration has no frames to fit the relative lightness band")

    def relative_reference(self, path: Path) -> "RelativeReference | None":
        """Relative lightness of every calibration face: stored, or re-measured from its frame."""
        rows = json.loads(path.read_text(encoding="utf-8"))["rows"]
        values, labels = [], []
        for photo in sorted({r["photo"] for r in rows}):
            faces = [r for r in rows if r["photo"] == photo]
            if all("dL_bg" in r for r in faces):
                values += [r["dL_bg"] for r in faces]
                labels += [r["label"] for r in faces]
                continue
            frame = cv2.imread(str(path.parent / "frames" / f"{photo}.jpg"))
            if frame is None:
                continue
            result = self.snapshot_detector.predict(frame, conf=CONFIDENCE, retina_masks=True, verbose=False)[0]
            if result.masks is None:
                continue
            boxes = to_bboxes(result.boxes.xyxy.cpu().numpy().round().astype(int))
            nearby = bricks_nearby(result.masks.xy, frame.shape)
            for r in faces:
                overlaps = [box_iou(r["bbox_px"], b) for b in boxes]
                best = int(np.argmax(overlaps))
                if overlaps[best] >= 0.5:
                    value = relative_lightness(frame, result.masks.xy[best], nearby)
                    if value is not None:
                        values.append(value)
                        labels.append(r["label"])
        if labels.count("good") < 2 or labels.count("bad") < 2:
            return None
        return RelativeReference(values, labels)

    def use_tensorrt(self, weights: Path) -> None:
        """Switch the detector to a TensorRT FP16 engine. The engine is built on this device the
        first time (a few minutes, while the demo keeps running on PyTorch) and kept next to the
        weights; on any failure the demo stays on PyTorch."""
        engine = weights.with_suffix(".engine")
        try:
            if not engine.exists():
                self.runtime = "PyTorch (building TensorRT engine, a few minutes)"
                YOLO(str(weights)).export(format="engine", quantize=16, imgsz=640, simplify=False, workspace=2,
                                          device=0, verbose=False)
            model = YOLO(str(engine), task="segment")
            model.predict(np.zeros((640, 640, 3), np.uint8), verbose=False)  # load the engine before switching
            with self.lock:
                self.detector = model
                self.restart_tracking()
            self.runtime = "TensorRT FP16"
        except Exception as error:  # noqa: BLE001 - any TensorRT problem: keep PyTorch
            self.runtime = f"PyTorch (TensorRT failed: {str(error)[:120]})"
            print(f"TensorRT: {error}")

    def set_kind(self, kind: str) -> dict:
        if kind == "nn" and self.nn is None:
            return {"ok": False, "message": "no neural network weights loaded"}
        if kind == "relative" and self.relative is None:
            return {"ok": False, "message": "this calibration has no frames to fit the relative lightness band"}
        if kind not in METHOD_NAMES:
            return {"ok": False, "message": "unknown classifier"}
        with self.lock:
            self.kind = kind
            self.votes.clear()
            self.clear_session()
        return {"ok": True, "message": f"classifier: {METHOD_NAMES[kind]}"}

    def p_good(self, frame, crop, polygon, masks, claimed, index, bbox, table, nearby) -> tuple[float | None, float | None]:
        """P(good) of one brick and, for the relative band, the measured relative lightness."""
        if self.kind == "nn":
            probs = self.nn.predict(crop, imgsz=224, verbose=False, **self.infer)[0].probs.data
            return float(probs[self.good_index]), None
        if self.kind == "relative":
            value = relative_lightness(frame, polygon, nearby)
            return (None, None) if value is None else (self.relative.p_good(value), value)
        region = measurement_region(masks, claimed, index, bbox)
        if region is None:
            return None, None
        result = self.reference.predict(color_features(frame, region, bbox, table))
        if result["prediction"] not in ("good", "bad"):
            return None, None
        return (result["confidence"] if result["prediction"] == "good" else 1 - result["confidence"]), None

    def step(self, frame: np.ndarray) -> None:
        start = time.monotonic()
        self.frame_no += 1
        if self.reset_tracker:
            # Done here, in the tracking thread, so the tracker is never reset mid-update.
            self.reset_tracker = False
            for tracker in getattr(getattr(self.detector, "predictor", None), "trackers", None) or []:
                tracker.reset()
        self.full_size = [frame.shape[1], frame.shape[0]]
        box = self.area_box(frame.shape)
        if self.frame_no % LIGHT_EVERY == 1:
            self.scene_lightness = round(live.scene_lightness(self.area_view(frame, box)), 1)
        result = self.detector.track(frame, persist=True, tracker="bytetrack.yaml", conf=CONFIDENCE,
                                     retina_masks=True, verbose=False, **self.infer, **self.detect_size)[0]
        detected = time.monotonic()
        for key, ms in result.speed.items():  # ultralytics' own split: preprocess / inference / postprocess
            self.timing[key] = 0.9 * self.timing.get(key, ms) + 0.1 * ms
        inside = ([] if result.boxes is None else
                  [in_area(xyxy, box) for xyxy in result.boxes.xyxy.cpu().numpy()])
        if self.frame_no % LIGHT_EVERY == 1 and result.masks is not None and any(inside):
            union = result.masks.data.cpu().numpy().astype(bool)[inside].any(axis=0)
            if union.any():
                self.clipped = round(float((frame[union].max(axis=1) >= CLIP_LEVEL).mean()), 4)
        bricks, crops = [], {}
        if result.boxes is not None and result.boxes.id is not None and result.masks is not None:
            ids = result.boxes.id.int().cpu().tolist()
            bboxes = to_bboxes(result.boxes.xyxy.cpu().numpy().round().astype(int))
            polygons = result.masks.xy
            masks = claimed = table = nearby = None
            if self.kind == "relative":
                nearby = bricks_nearby(polygons, frame.shape)
            if self.kind == "knn":
                masks = result.masks.data.cpu().numpy().astype(bool)
                claimed = masks.sum(axis=0)
                table = live.table_reference(frame, bboxes)
            for index, (track_id, polygon, bbox) in enumerate(zip(ids, polygons, bboxes)):
                if len(polygon) < 3 or not inside[index]:
                    continue
                votes = self.votes.setdefault(track_id, deque(maxlen=VOTES))
                every = CLASSIFY_EVERY if len(votes) < VOTES else SETTLED_EVERY
                if len(votes) < MIN_VOTES or (self.frame_no + track_id) % every == 0:
                    crop = brick_crop(frame, polygon, 224)
                    value, measured = self.p_good(frame, crop, polygon, masks, claimed, index, bbox, table, nearby)
                    if value is not None:
                        votes.append(value)
                        self.measured[track_id] = measured
                    ok, jpeg = cv2.imencode(".jpg", cv2.resize(crop, (128, 128), interpolation=cv2.INTER_AREA),
                                            [cv2.IMWRITE_JPEG_QUALITY, 85])
                    if ok:
                        crops[track_id] = (jpeg.tobytes(), self.frame_no)
                p = float(np.mean(votes)) if votes else None
                decision = None if len(votes) < MIN_VOTES else ("good" if p >= 0.5 else "bad")
                if decision:
                    self.decided[track_id] = decision
                    self.numbers.setdefault(track_id, len(self.numbers) + 1)
                measured = self.measured.get(track_id) if self.kind == "relative" else None
                bricks.append((track_id, polygon, bbox, decision, p, measured, len(votes),
                               self.numbers.get(track_id)))
        classified = time.monotonic()
        with self.to_draw_ready:
            self.to_draw = (frame, bricks, box)
            self.to_draw_ready.notify()
        with self.lock:
            self.frame = frame
            ids = {b[0] for b in bricks}
            self.crops = {k: v for k, v in {**self.crops, **crops}.items() if k in ids}
            self.active = [{"id": t, "n": number, "decision": d, "p_good": p, "votes": n,
                            "value": None if m is None else round(m, 1),
                            "crop": self.crops[t][1] if t in self.crops else None}
                           for t, _, _, d, p, m, n, number in bricks]
            # History entries follow their brick while it is in view, then stay as last seen.
            for t, _, _, d, p, _, n, number in bricks:
                if number is not None:
                    previous = self.history.get(number) or {}
                    crop = self.crops.get(t) or previous.get("jpeg", (None, 0))
                    self.history[number] = {"n": number, "decision": d, "p_good": p, "votes": n, "jpeg": crop,
                                            "t": previous.get("t", time.time())}
            while len(self.history) > HISTORY:
                del self.history[min(self.history)]
            for key, seconds in (("detect", detected - start), ("classify", classified - detected)):
                self.timing[key] = 0.9 * self.timing[key] + 0.1 * seconds * 1000
            if self.last_step is not None:
                self.fps = 0.9 * self.fps + 0.1 / max(1e-3, start - self.last_step)
            self.last_step = start

    def encode_loop(self) -> None:
        """Stream images, drawn and JPEG-encoded in their own thread while the next frame is
        detected (on the Jetson this takes ~16 ms of CPU per frame). Only the newest result is drawn."""
        while True:
            with self.to_draw_ready:
                self.to_draw_ready.wait_for(lambda: self.to_draw is not None)
                (frame, bricks, box), self.to_draw = self.to_draw, None
            start = time.monotonic()
            ok, jpeg = cv2.imencode(".jpg", self.draw(frame, bricks, box), [cv2.IMWRITE_JPEG_QUALITY, 80])
            with self.lock:
                if ok:
                    self.jpeg = jpeg.tobytes()
                self.timing["draw"] = 0.9 * self.timing["draw"] + 0.1 * (time.monotonic() - start) * 1000
                self.updated.notify_all()

    def draw(self, frame: np.ndarray, bricks: list[tuple], box: tuple | None = None) -> np.ndarray:
        """Stream image: the detection area (or the whole frame) scaled to STREAM_WIDTH, brick
        outlines and a label chip per brick. The bricks are not tinted, so their real color
        stays visible."""
        x0, y0 = (box[0], box[1]) if box else (0, 0)
        frame = self.area_view(frame, box)
        scale = STREAM_WIDTH / frame.shape[1]
        canvas = cv2.resize(frame, (STREAM_WIDTH, round(frame.shape[0] * scale)),
                            interpolation=cv2.INTER_AREA if scale < 1 else cv2.INTER_LINEAR)
        font = cv2.FONT_HERSHEY_DUPLEX
        for _, polygon, bbox, decision, p, measured, _, number in bricks:
            color = COLORS[decision]
            polygon = polygon - (x0, y0)
            bbox = {**bbox, "x": bbox["x"] - x0, "y": bbox["y"] - y0}
            cv2.polylines(canvas, [(polygon * scale).astype(np.int32)], True, color, 3, cv2.LINE_AA)
            # Only the decision and the session number on the video; confidence and votes
            # are on the brick cards.
            text = (decision or "deciding").upper()
            tag = "" if number is None else f"#{number}"
            (tw, th), base = cv2.getTextSize(text, font, 0.6, 1)
            (iw, _), _ = cv2.getTextSize(tag, font, 0.5, 1)
            x = min(max(0, round(bbox["x"] * scale)), canvas.shape[1] - tw - iw - 22)
            y = max(th + 12, round(bbox["y"] * scale) - 6)
            cv2.rectangle(canvas, (x, y - th - 10), (x + tw + iw + 22, y + base - 2), color, cv2.FILLED)
            cv2.putText(canvas, text, (x + 7, y - 4), font, 0.6, (255, 255, 255), 1, cv2.LINE_AA)
            cv2.putText(canvas, tag, (x + tw + 15, y - 4), font, 0.5, (235, 235, 235), 1, cv2.LINE_AA)
        if self.calibration is not None:
            cv2.rectangle(canvas, (12, 12), (190, 50), (20, 20, 20), cv2.FILLED)
            cv2.putText(canvas, "CALIBRATING", (22, 40), font, 0.8, (255, 255, 255), 1, cv2.LINE_AA)
        if self.roi_editing and self.roi is not None:
            h, w = canvas.shape[:2]
            x0, y0, x1, y1 = (round(v * s) for v, s in zip(self.roi, (w, h, w, h)))
            cv2.rectangle(canvas, (x0, y0), (x1, y1), (255, 255, 255), 2, cv2.LINE_AA)
        return canvas

    # Detection area -----------------------------------------------------------------

    def area_box(self, shape) -> tuple[int, int, int, int] | None:
        """Detection area in pixels (x0, y0, x1, y1); None = whole frame (also while a new
        area is being drawn in the page)."""
        if self.roi is None or self.roi_editing:
            return None
        h, w = shape[:2]
        return tuple(round(v * s) for v, s in zip(self.roi, (w, h, w, h)))

    @staticmethod
    def area_view(frame: np.ndarray, box: tuple | None) -> np.ndarray:
        """Part of the frame shown in the stream (zoom) and used for the scene light."""
        if box is None:
            return frame
        x0, y0, x1, y1 = box
        return np.ascontiguousarray(frame[y0:y1, x0:x1])

    def set_roi(self, box) -> dict:
        if box is not None:
            box = [min(1.0, max(0.0, float(v))) for v in box]
            if len(box) != 4 or box[2] - box[0] < MIN_ROI or box[3] - box[1] < MIN_ROI:
                return {"ok": False, "message": "area too small: drag a larger rectangle"}
        with self.lock:
            self.roi, self.roi_editing = box, False
            self.restart_tracking()
        if box is None:
            ROI_FILE.unlink(missing_ok=True)
            return {"ok": True, "message": "detection area: whole frame"}
        ROI_FILE.parent.mkdir(parents=True, exist_ok=True)
        ROI_FILE.write_text(json.dumps({"roi": [round(v, 4) for v in box]}), encoding="utf-8")
        return {"ok": True, "message": "detection area saved (used again at the next start)"}

    def edit_roi(self, on: bool) -> dict:
        with self.lock:
            self.roi_editing = on
            self.restart_tracking()
        return {"ok": True, "message": "drag a rectangle over the table area" if on else "kept the previous area"}

    def restart_tracking(self) -> None:
        """New image geometry: drop votes and track state (call with the lock held)."""
        self.votes.clear()
        self.clear_session()
        self.crops.clear()
        self.reset_tracker = True

    def clear_session(self) -> None:
        """Forget the decided bricks: totals, numbers and history start again at 0
        (call with the lock held)."""
        self.decided.clear()
        self.numbers.clear()
        self.history.clear()

    # Calibration ------------------------------------------------------------------

    def calibration_status(self) -> dict:
        c = self.calibration
        goods, bads = c.counts() if c else (0, 0)
        return {"active": c is not None, "captures": len(c.captures) if c else 0, "good": goods, "bad": bads,
                "min_per_class": live.MIN_CALIBRATION_PER_CLASS}

    def calibration_capture(self) -> dict:
        if self.calibration is None:
            return {"ok": False, "message": "start a new calibration first"}
        with self.lock:
            frame = None if self.frame is None else self.frame.copy()
        if frame is None:
            return {"ok": False, "message": "no camera frame yet"}
        result = self.snapshot_detector.predict(frame, conf=CONFIDENCE, retina_masks=True, verbose=False)[0]
        if result.masks is not None:
            box = self.area_box(frame.shape)
            result = result[[in_area(xyxy, box) for xyxy in result.boxes.xyxy.cpu().numpy()]]
        if result.masks is None or len(result) == 0:
            return {"ok": False, "message": "no bricks found in the detection area: try again"}
        masks = result.masks.data.cpu().numpy().astype(bool)
        claimed = masks.sum(axis=0)
        bboxes = to_bboxes(result.boxes.xyxy.cpu().numpy().round().astype(int))
        table = live.table_reference(frame, bboxes)
        nearby = bricks_nearby(result.masks.xy, frame.shape)
        bricks = []
        for index in sorted(range(len(bboxes)), key=lambda i: bboxes[i]["x"]):
            region = measurement_region(masks, claimed, index, bboxes[index])
            if region is not None:
                features = color_features(frame, region, bboxes[index], table)
                relative = relative_lightness(frame, result.masks.xy[index], nearby)
                if relative is not None:
                    features["dL_bg"] = relative
                bricks.append({"bbox_px": bboxes[index], "features": features, "polygon": result.masks.xy[index]})
        if not bricks:
            return {"ok": False, "message": "no usable bricks (hidden or cut by the border): try again"}
        snapshot = frame.copy()
        for k, b in enumerate(bricks, 1):
            cv2.polylines(snapshot, [b["polygon"].astype(np.int32)], True, (40, 220, 40), 6)
            x, y = b["bbox_px"]["x"] + b["bbox_px"]["width"] // 2 - 30, b["bbox_px"]["y"] + b["bbox_px"]["height"] // 2
            cv2.putText(snapshot, str(k), (x, y), cv2.FONT_HERSHEY_SIMPLEX, 4, (255, 255, 255), 16, cv2.LINE_AA)
            cv2.putText(snapshot, str(k), (x, y), cv2.FONT_HERSHEY_SIMPLEX, 4, (0, 0, 0), 6, cv2.LINE_AA)
        ok, jpeg = cv2.imencode(".jpg", cv2.resize(snapshot, (960, 540)), [cv2.IMWRITE_JPEG_QUALITY, 85])
        self.calibration.pending = {"frame": frame, "bricks": bricks, "jpeg": jpeg.tobytes()}
        return {"ok": True, "positions": list(range(1, len(bricks) + 1)),
                "message": f"{len(bricks)} bricks: label them left to right"}

    def calibration_labels(self, labels: list[str]) -> dict:
        c = self.calibration
        if c is None or c.pending is None:
            return {"ok": False, "message": "capture first"}
        if len(labels) != len(c.pending["bricks"]):
            return {"ok": False, "message": "one label per brick is needed"}
        capture_id = f"cal{len(c.captures) + 1:03d}"
        frame = c.pending["frame"]
        cv2.imwrite(str(c.root / "frames" / f"{capture_id}.jpg"), frame)
        (c.root / "frames" / f"{capture_id}_labels.jpg").write_bytes(c.pending["jpeg"])
        lightness = round(live.scene_lightness(self.area_view(frame, self.area_box(frame.shape))), 1)
        (c.root / "crops").mkdir(exist_ok=True)
        added = 0
        for position, (brick, label) in enumerate(zip(c.pending["bricks"], labels), 1):
            if label not in ("good", "bad"):
                continue
            crop = f"crops/{capture_id}_{position}.png"
            cv2.imwrite(str(c.root / crop), brick_crop(frame, brick["polygon"], 224))
            features = {k: (round(v, 4) if isinstance(v, float) else v) for k, v in brick["features"].items()}
            c.rows.append({"photo": capture_id, "position": position, "label": label, "scene_lightness": lightness,
                           "bbox_px": brick["bbox_px"], "region": "mask", "crop": crop, **features})
            added += 1
        c.captures.append(capture_id)
        c.pending = None
        return {"ok": True, "message": f"{capture_id}: added {added} faces"}

    def calibration_undo(self) -> dict:
        c = self.calibration
        if c is None or not c.captures:
            return {"ok": False, "message": "nothing to undo"}
        last = c.captures.pop()
        c.rows = [r for r in c.rows if r["photo"] != last]
        c.pending = None
        return {"ok": True, "message": f"removed {last}"}

    def calibration_finish(self) -> dict:
        c = self.calibration
        if c is None:
            return {"ok": False, "message": "no calibration in progress"}
        goods, bads = c.counts()
        need = live.MIN_CALIBRATION_PER_CLASS
        if goods < need or bads < need:
            return {"ok": False, "message": f"need at least {need} good and {need} bad faces"}
        path, summary = c.finish(self.calibration_features)
        self.calibration = None
        self.use_reference(path)
        check = summary["self_check"]
        text = f"saved and in use: {path.parent.name} ({goods} good, {bads} bad faces)"
        if check is not None:
            text += f"; self-check {check:.0%}"
        if summary["conflicts"]:
            text += "; check labels: " + ", ".join(summary["conflicts"][:3])
        score = self.score_network(c.root, c.rows)
        if score:
            text += f". Network before retraining, on this new light: {score}"
        if self.auto_train:
            text += ". " + self.trainer.start()["message"]
        return {"ok": True, "message": text}

    def score_network(self, root: Path, rows: list[dict]) -> str | None:
        """Accuracy of the current network on the bricks of a calibration it has not seen."""
        if self.nn is None:
            return None
        truth, guess = [], []
        for r in rows:
            image = cv2.imread(str(root / r["crop"])) if r.get("crop") else None
            if image is None:
                continue
            probs = self.nn.predict(image, imgsz=224, verbose=False)[0].probs.data
            truth.append(r["label"])
            guess.append("good" if float(probs[self.good_index]) >= 0.5 else "bad")
        if not truth:
            return None
        correct = sum(a == b for a, b in zip(truth, guess))
        goods = [b == "good" for a, b in zip(truth, guess) if a == "good"]
        bads = [b == "bad" for a, b in zip(truth, guess) if a == "bad"]
        self.trainer.last_score = f"{correct}/{len(truth)} ({sum(goods)}/{len(goods)} good, {sum(bads)}/{len(bads)} bad)"
        return self.trainer.last_score

    def load_network(self, weights: Path) -> None:
        model = YOLO(str(weights))
        with self.lock:
            self.nn = model
            self.good_index = [k for k, v in model.names.items() if v == "good"][0]
            self.nn_name = weights.parent.parent.name
            if self.kind == "nn":
                self.votes.clear()
                self.clear_session()


def list_calibrations() -> list[dict]:
    items = []
    for path in sorted(live.CALIBRATION_ROOT.glob("*/calibration.json"), reverse=True):
        try:
            data = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            continue
        feature_set = data.get("feature_set", "?")
        check = (data.get("self_check") or {}).get(feature_set, {}).get("accuracy")
        items.append({"name": path.parent.name, "created": data.get("created"), "good": data.get("good_bricks"),
                      "bad": data.get("bad_bricks"), "feature_set": feature_set, "self_check": check,
                      "lightness": data.get("scene_lightness")})
    return items


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--classifier", choices=list(METHOD_NAMES), default="knn")
    parser.add_argument("--reference", type=Path, default=TOP_REFERENCE,
                        help="calibration.json for knn, or 'latest' for the newest calibration")
    parser.add_argument("--nn-weights", type=Path, default=NN_WEIGHTS)
    parser.add_argument("--weights", type=Path, default=DETECTOR_WEIGHTS, help="YOLO segmentation detector")
    parser.add_argument("--source", type=Path, help="video file or image folder instead of the camera")
    parser.add_argument("--camera", type=int, default=0, help="camera index (Windows)")
    parser.add_argument("--camera-device", help="Linux V4L2 camera: /dev/videoN or auto (default on Linux)")
    parser.add_argument("--camera-max-height", type=int,
                        help="Linux camera: largest mode up to this height, e.g. 720 (default: the largest)")
    parser.add_argument("--half", action="store_true", help="FP16 inference (CUDA; recommended on the Jetson)")
    parser.add_argument("--detect-imgsz", type=int,
                        help="detector input size (default: 640, as trained; 512 is ~2x less work, slightly coarser masks)")
    parser.add_argument("--tensorrt", action="store_true",
                        help="detector as a TensorRT FP16 engine (built on the device the first time; Jetson)")
    parser.add_argument("--remote", help="laptop mode: URL of the web demo running on the Jetson")
    parser.add_argument("--port", type=int, default=8000)
    parser.add_argument("--host", default="0.0.0.0",
                        help="listen address; '::' on the Jetson also accepts IPv6 (the USB link to the laptop)")
    parser.add_argument("--exposure", type=float, help="camera exposure (C920: -5 default, -6 / -7 darker)")
    parser.add_argument("--no-roi", action="store_true", help="ignore the saved detection area (whole frame)")
    parser.add_argument("--calibration-features", choices=sorted(live.FEATURE_OPTIONS), default="raw",
                        help="feature set stored in calibrations made in the browser")
    args = parser.parse_args()
    if args.remote:
        run_proxy(args.remote, args.port)
        return
    if str(args.reference) == "latest":
        args.reference = latest_calibration()
    if args.camera_device is None and args.source is None and sys.platform.startswith("linux"):
        args.camera_device = "auto"

    sorter = Sorter(args)
    source = Source(args.source, args.camera, args.exposure, args.camera_device, args.camera_max_height)
    reader = FrameReader(source)
    running = True

    def loop() -> None:
        seen = 0
        while running:
            frame, seen = reader.next(seen)
            if frame is not None:
                sorter.step(frame)

    worker = threading.Thread(target=loop, daemon=True)
    worker.start()

    app = FastAPI()

    @app.get("/", response_class=HTMLResponse)
    def page() -> str:
        return PAGE

    @app.get("/stats")
    def stats() -> JSONResponse:
        with sorter.lock:
            decisions = list(sorter.decided.values())
            in_view = [t["decision"] for t in sorter.active]
            data = {"good": in_view.count("good"), "bad": in_view.count("bad"),
                    "total_good": decisions.count("good"), "total_bad": decisions.count("bad"), "fps": sorter.fps,
                    "classifier": sorter.kind, "classifier_name": METHOD_NAMES[sorter.kind],
                    "methods": {k: v for k, v in METHOD_NAMES.items()
                                if (k != "nn" or sorter.nn is not None) and (k != "relative" or sorter.relative)},
                    "relative_band": ([round(sorter.relative.low, 1), round(sorter.relative.high, 1), sorter.relative.faces]
                                      if sorter.relative else None),
                    "min_votes": MIN_VOTES, "votes": VOTES, "active": sorter.active,
                    "history": [{k: v for k, v in h.items() if k != "jpeg"} | {"crop": h["jpeg"][1]}
                                for _, h in sorted(sorter.history.items(), reverse=True)],
                    "timing": dict(sorter.timing), "camera_fps": reader.fps, "detector": sorter.detector_name,
                    "runtime": sorter.runtime,
                    "frame_size": None if sorter.full_size is None else "x".join(map(str, sorter.full_size)),
                    "full_size": sorter.full_size, "roi": sorter.roi, "roi_editing": sorter.roi_editing,
                    "hardware": sorter.hardware, "tensorrt": sorter.tensorrt,
                    "reference": sorter.reference_name,
                    "light": {"scene": sorter.scene_lightness, "warn": LIGHT_WARN, "recalibrate": LIGHT_RECALIBRATE,
                              "clipped": sorter.clipped, "max_clipped": MAX_CLIPPED,
                              "reference": sorter.reference.scene_lightness if sorter.reference else None}}
        data["calibration"] = sorter.calibration_status()
        data["camera"] = source.camera() if source.v4l2 is not None else None
        finished = sorter.trainer.poll()
        if finished:
            sorter.load_network(finished)
        data["nn"] = {**sorter.trainer.status(), "weights": sorter.nn_name, "auto": sorter.auto_train,
                      "model": model_name(sorter.nn) if sorter.nn is not None else None}
        return JSONResponse(data)

    @app.post("/camera/control")
    def camera_control(payload: dict) -> JSONResponse:
        result = source.set_control(str(payload.get("name", "")), int(payload.get("value", 0)))
        if result["ok"]:
            with sorter.lock:
                sorter.restart_tracking()
        return JSONResponse(result)

    @app.post("/camera/defaults")
    def camera_defaults() -> JSONResponse:
        result = source.camera_defaults()
        if result["ok"]:
            with sorter.lock:
                sorter.restart_tracking()
        return JSONResponse(result)

    @app.post("/camera/exposure")
    def camera_exposure(payload: dict) -> JSONResponse:
        result = source.set_exposure(int(payload.get("value", 0)))
        if result["ok"]:
            with sorter.lock:
                sorter.restart_tracking()
        return JSONResponse(result)

    @app.post("/camera/lock")
    def camera_lock() -> JSONResponse:
        result = source.lock()
        if result["ok"]:
            with sorter.lock:
                sorter.restart_tracking()
        return JSONResponse(result)

    @app.post("/roi")
    def roi(payload: dict) -> JSONResponse:
        return JSONResponse(sorter.set_roi(payload.get("box")))

    @app.post("/roi/edit")
    def roi_edit(payload: dict) -> JSONResponse:
        return JSONResponse(sorter.edit_roi(bool(payload.get("on", True))))

    @app.post("/reset")
    def reset() -> JSONResponse:
        with sorter.lock:
            sorter.clear_session()
        return JSONResponse({"ok": True})

    @app.post("/nn/train")
    def train_now() -> JSONResponse:
        return JSONResponse(sorter.trainer.start())

    @app.post("/nn/auto")
    def auto(payload: dict) -> JSONResponse:
        sorter.auto_train = bool(payload.get("on", True))
        return JSONResponse({"ok": True, "message": "retrain after each calibration: " + ("on" if sorter.auto_train else "off")})

    @app.post("/classifier")
    def classifier(payload: dict) -> JSONResponse:
        return JSONResponse(sorter.set_kind(str(payload.get("kind", ""))))

    @app.get("/calibrations")
    def calibrations() -> JSONResponse:
        return JSONResponse(list_calibrations())

    @app.post("/calibration/use")
    def use(payload: dict) -> JSONResponse:
        path = live.CALIBRATION_ROOT / str(payload.get("name", "")) / "calibration.json"
        if not path.exists():
            return JSONResponse({"ok": False, "message": "calibration not found"})
        sorter.use_reference(path)
        return JSONResponse({"ok": True, "message": f"in use: {path.parent.name}"})

    def discard_unfinished() -> None:
        c = sorter.calibration
        if c is not None and not (c.root / "calibration.json").exists():
            shutil.rmtree(c.root, ignore_errors=True)
        sorter.calibration = None

    @app.post("/calibration/start")
    def start() -> JSONResponse:
        discard_unfinished()
        sorter.calibration = Calibration(source.camera())
        return JSONResponse({"ok": True, "message": "calibration started: place labeled bricks and press Capture"})

    @app.post("/calibration/capture")
    def capture() -> JSONResponse:
        return JSONResponse(sorter.calibration_capture())

    @app.get("/calibration/snapshot")
    def snapshot() -> Response:
        pending = sorter.calibration.pending if sorter.calibration else None
        return Response(pending["jpeg"] if pending else b"", media_type="image/jpeg")

    @app.post("/calibration/labels")
    def labels(payload: dict) -> JSONResponse:
        return JSONResponse(sorter.calibration_labels(list(payload.get("labels", []))))

    @app.post("/calibration/undo")
    def undo() -> JSONResponse:
        return JSONResponse(sorter.calibration_undo())

    @app.post("/calibration/finish")
    def finish() -> JSONResponse:
        return JSONResponse(sorter.calibration_finish())

    @app.post("/calibration/cancel")
    def cancel() -> JSONResponse:
        discard_unfinished()
        return JSONResponse({"ok": True, "message": "calibration cancelled (nothing saved in use)"})

    @app.get("/crop/{track_id}")
    def crop(track_id: int) -> Response:
        with sorter.lock:
            item = sorter.crops.get(track_id)
        return Response(item[0] if item else b"", media_type="image/jpeg",
                        headers={"Cache-Control": "max-age=60"}, status_code=200 if item else 404)

    @app.get("/history/{number}")
    def history_crop(number: int) -> Response:
        with sorter.lock:
            jpeg = (sorter.history.get(number) or {}).get("jpeg", (None, 0))[0]
        return Response(jpeg or b"", media_type="image/jpeg",
                        headers={"Cache-Control": "max-age=60"}, status_code=200 if jpeg else 404)

    @app.get("/stream")
    def stream() -> StreamingResponse:
        def frames():
            sent = None
            while running:
                with sorter.updated:
                    sorter.updated.wait_for(lambda: sorter.jpeg is not sent, timeout=1.0)
                    jpeg = sorter.jpeg
                if jpeg is not None and jpeg is not sent:
                    sent = jpeg
                    yield b"--frame\r\nContent-Type: image/jpeg\r\n\r\n" + jpeg + b"\r\n"
        return StreamingResponse(frames(), media_type="multipart/x-mixed-replace; boundary=frame")

    print(f"open http://localhost:{args.port}")
    try:
        uvicorn.run(app, host=args.host, port=args.port, log_level="warning")
    finally:
        running = False
        reader.stop()
        worker.join(timeout=2)
        source.release()


if __name__ == "__main__":
    main()
