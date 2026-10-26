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

Sources: the camera (fixed C920 settings, as in capture_bricks.py) or, for testing
without a camera, --source with a video file or a folder of images (looped).
Usage:
  web_demo.py [--classifier knn|relative|nn] [--reference calibration.json] [--nn-weights best.pt]
              [--weights detector.pt] [--source video_or_folder] [--camera 0] [--port 8000]
              [--calibration-features raw|table|table_ratio] [--exposure -6]
"""

import argparse
import json
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
from fastapi import FastAPI
from fastapi.responses import HTMLResponse, JSONResponse, Response, StreamingResponse
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
<title>Brick Sorter</title>
<style>
:root { --bg:#f6f5f2; --panel:#ffffff; --ink:#1d1c1a; --muted:#6b6a65; --line:#e3e1db;
        --good:#2a78d6; --bad:#eb6834; --accent:#1d1c1a; }
@media (prefers-color-scheme: dark) { :root { --bg:#141413; --panel:#1f1e1c; --ink:#f1efe9; --muted:#a3a19a; --line:#34322e; --accent:#f1efe9; } }
* { box-sizing:border-box; } body { margin:0; background:var(--bg); color:var(--ink); font:15px/1.4 system-ui, sans-serif; }
header { padding:16px 20px; border-bottom:1px solid var(--line); display:flex; gap:12px; align-items:baseline; flex-wrap:wrap; }
header h1 { margin:0; font-size:20px; } header span { color:var(--muted); }
main { display:grid; grid-template-columns:minmax(0,3fr) minmax(280px,1fr); gap:16px; padding:16px 20px; }
@media (max-width:900px) { main { grid-template-columns:1fr; } }
.video { background:#000; border-radius:8px; overflow:hidden; } .video img { width:100%; display:block; }
.panel { background:var(--panel); border:1px solid var(--line); border-radius:8px; padding:14px; margin-bottom:16px; }
.panel h2 { margin:0 0 10px; font-size:15px; }
.counts { display:grid; grid-template-columns:1fr 1fr; gap:10px; }
.count { border-radius:6px; padding:10px; border:1px solid var(--line); }
.count b { display:block; font-size:34px; line-height:1.1; font-variant-numeric:tabular-nums; }
.count.good b { color:var(--good); } .count.bad b { color:var(--bad); }
table { width:100%; border-collapse:collapse; font-variant-numeric:tabular-nums; }
td, th { text-align:left; padding:4px 6px; border-bottom:1px solid var(--line); font-size:14px; }
th { color:var(--muted); font-weight:500; }
.tag { font-weight:600; } .tag.good { color:var(--good); } .tag.bad { color:var(--bad); } .tag.pending { color:var(--muted); }
button, select { background:transparent; color:var(--ink); border:1px solid var(--line); border-radius:6px;
                 padding:6px 10px; cursor:pointer; font:inherit; }
button.primary { background:var(--accent); color:var(--bg); border-color:var(--accent); }
button:disabled { opacity:.45; cursor:default; }
button.on-good { background:var(--good); color:#fff; border-color:var(--good); }
button.on-bad { background:var(--bad); color:#fff; border-color:var(--bad); }
button.on-skip { background:var(--muted); color:var(--bg); border-color:var(--muted); }
.row { display:flex; gap:8px; flex-wrap:wrap; align-items:center; margin:8px 0; }
select { flex:1; min-width:0; }
#snap { width:100%; border-radius:6px; margin:8px 0; display:block; }
.brick { display:flex; gap:6px; align-items:center; margin:4px 0; } .brick span { width:34px; font-weight:600; }
small, .muted { color:var(--muted); }
.msg { margin:8px 0 0; min-height:1.4em; } .msg.warn { color:var(--bad); }
.light { margin-top:10px; padding:8px 10px; border-radius:6px; border:1px solid var(--line); }
.light b { font-variant-numeric:tabular-nums; } .light.warn { border-color:#c99a2e; } .light.bad { border-color:var(--bad); color:var(--bad); }
</style></head><body>
<header><h1>Brick Sorter</h1><span id="info">connecting...</span></header>
<main>
  <div class="video"><img src="/stream" alt="live camera with detected bricks"></div>
  <div>
    <div class="panel">
      <div class="counts">
        <div class="count good"><small>Good in view</small><b id="good">0</b></div>
        <div class="count bad"><small>Bad in view</small><b id="bad">0</b></div>
      </div>
      <p><small>Decided after <span id="minv"></span> votes. Session total: <b id="tgood">0</b> good,
        <b id="tbad">0</b> bad (one per tracked brick).</small></p>
      <button onclick="post('/reset')">Reset session total</button>
      <div class="row"><select id="method"></select><button onclick="setMethod()">Use method</button></div>
      <div class="muted" id="methodinfo"></div>
      <div class="light" id="nnbox">
        <div>Neural network: <b id="nnname">-</b> · <span id="nnstate">-</span></div>
        <div class="muted" id="nnscore"></div>
        <div class="row"><button onclick="trainNow()">Train now</button>
          <label class="muted"><input type="checkbox" id="nnauto" checked onchange="post('/nn/auto', {on: this.checked})">
          retrain after each calibration</label></div>
      </div>
      <div class="light" id="light">Light: -</div>
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
    <div class="panel">
      <table><thead><tr><th>Track</th><th>Decision</th><th>P(good)</th><th>Votes</th></tr></thead>
      <tbody id="tracks"></tbody></table>
    </div>
  </div>
</main>
<script>
let labels = [];
const $ = id => document.getElementById(id);
async function post(url, body) {
  const r = await fetch(url, {method:'POST', headers:{'Content-Type':'application/json'}, body: JSON.stringify(body || {})});
  return r.json();
}
function message(text, warn) { $('calmsg').textContent = text || ''; $('calmsg').className = 'msg' + (warn ? ' warn' : ''); }
async function poll() {
  try {
    const s = await (await fetch('/stats')).json();
    $('good').textContent = s.good; $('bad').textContent = s.bad; $('minv').textContent = s.min_votes;
    $('tgood').textContent = s.total_good; $('tbad').textContent = s.total_bad;
    $('info').textContent = `${s.classifier_name}, ${s.fps.toFixed(1)} fps, ${s.active.length} bricks in view`;
    const opts = Object.entries(s.methods).map(([k, v]) => `<option value="${k}" ${k === s.classifier ? 'selected' : ''}>${v}</option>`).join('');
    if ($('method').dataset.opts !== opts && document.activeElement !== $('method')) { $('method').innerHTML = opts; $('method').dataset.opts = opts; }
    $('methodinfo').textContent = s.classifier === 'relative' && s.relative_band
      ? `Good if ${s.relative_band[0]} <= relative L* <= ${s.relative_band[1]} (fitted on ${s.relative_band[2]} faces)` : '';
    $('ref').textContent = s.reference || '-';
    const L = s.light;
    if (L.scene !== null) {
      let text = `Light (table L*): <b>${L.scene.toFixed(1)}</b>`, cls = 'light';
      if (L.reference !== null) {
        const d = L.scene - L.reference;
        text += ` · calibration <b>${L.reference.toFixed(1)}</b> · difference <b>${d > 0 ? '+' : ''}${d.toFixed(1)}</b>`;
        if (Math.abs(d) > L.recalibrate) { text += ' · light changed: recalibrate'; cls += ' bad'; }
        else if (Math.abs(d) > L.warn) { text += ' · light is drifting'; cls += ' warn'; }
        else text += ' · OK';
      }
      if (L.clipped !== null) {
        const pct = (L.clipped * 100).toFixed(1);
        if (L.clipped > L.max_clipped) { text += `<br>Bricks clipped (pure white): <b>${pct}%</b> · too bright: lower the exposure`; cls += ' bad'; }
        else text += `<br>Bricks clipped (pure white): <b>${pct}%</b> · OK`;
      }
      $('light').innerHTML = text; $('light').className = cls;
    }
    $('tracks').innerHTML = s.active.map(t =>
      `<tr><td>#${t.id}</td><td class="tag ${t.decision || 'pending'}">${(t.decision || 'deciding').toUpperCase()}</td>` +
      `<td>${t.p_good === null ? '-' : Math.round(t.p_good * 100) + '%'}${t.value === null ? '' : ' (rel L* ' + t.value + ')'}</td><td>${t.votes}</td></tr>`).join('');
    const n = s.nn;
    $('nnname').textContent = n.weights || 'none';
    $('nnstate').textContent = n.training ? `training... ${n.elapsed_s}s` : n.message;
    $('nnscore').textContent = n.last_score ? `Before the last retraining, on the new calibration light: ${n.last_score}` : '';
    if (document.activeElement !== $('nnauto')) $('nnauto').checked = n.auto;
    const c = s.calibration;
    $('calwork').hidden = !c.active; $('newcal').disabled = c.active;
    if (c.active) $('calstatus').textContent = `${c.captures} captures, ${c.good} good and ${c.bad} bad faces (need ${c.min_per_class} of each)`;
  } catch (e) { $('info').textContent = 'no connection'; }
  setTimeout(poll, 700);
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
  if ($('labelbox').hidden) return;
  const v = {g:'good', b:'bad', s:'skip'}[e.key];
  const i = labels.indexOf(null);
  if (v && i >= 0) setLabel(i, v);
  if (e.key === 'Enter' && !$('addbtn').disabled) sendLabels();
});
loadList(); poll();
</script></body></html>"""


class Source:
    """Camera, video file or image folder (looped), one frame at a time."""

    def __init__(self, source: Path | None, camera: int, exposure: float | None = None) -> None:
        self.images, self.index, self.capture = [], 0, None
        if source is None:
            self.capture = open_camera(camera)
            if exposure is not None:
                self.capture.set(cv2.CAP_PROP_EXPOSURE, exposure)
        elif source.is_dir():
            self.images = sorted(p for p in source.iterdir() if p.suffix.lower() in (".jpg", ".png"))
        else:
            self.capture = cv2.VideoCapture(str(source))
        self.is_camera = source is None

    def read(self) -> np.ndarray:
        if self.images:
            frame = cv2.imread(str(self.images[self.index % len(self.images)]))
            self.index += 1
            time.sleep(0.2)
            return frame
        if self.is_camera:
            return read_frame(self.capture)
        ok, frame = self.capture.read()
        if not ok:
            self.capture.set(cv2.CAP_PROP_POS_FRAMES, 0)
            ok, frame = self.capture.read()
        return frame

    def camera(self) -> dict | None:
        return camera_properties(self.capture) if self.is_camera else None

    def release(self) -> None:
        if self.capture is not None:
            self.capture.release()


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


class Sorter:
    def __init__(self, args) -> None:
        self.detector = YOLO(str(args.weights))
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
        self.measured: dict[int, float | None] = {}
        self.lock = threading.Lock()
        self.jpeg, self.fps, self.active, self.frame_no, self.frame = None, 0.0, [], 0, None
        self.scene_lightness: float | None = None
        self.clipped: float | None = None
        self.calibration: Calibration | None = None

    def use_reference(self, path: Path) -> None:
        path = Path(path).resolve()
        reference = live.Reference.load(path)
        relative = self.relative_reference(path)
        # Calibrations are named by their session folder; other files by their path.
        name = path.parent.name if path.parent.parent == live.CALIBRATION_ROOT else path.relative_to(PROJECT_ROOT).as_posix()
        if hasattr(self, "lock"):
            with self.lock:
                self.reference, self.reference_name, self.relative = reference, name, relative
                if self.kind == "relative" and relative is None:
                    self.kind = "knn"
                self.votes.clear()
                self.decided.clear()
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
            self.decided.clear()
        return {"ok": True, "message": f"classifier: {METHOD_NAMES[kind]}"}

    def p_good(self, frame, polygon, masks, claimed, index, bbox, table, nearby) -> tuple[float | None, float | None]:
        """P(good) of one brick and, for the relative band, the measured relative lightness."""
        if self.kind == "nn":
            probs = self.nn.predict(brick_crop(frame, polygon, 224), imgsz=224, verbose=False)[0].probs.data
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
        if self.frame_no % LIGHT_EVERY == 1:
            self.scene_lightness = round(live.scene_lightness(frame), 1)
        result = self.detector.track(frame, persist=True, tracker="bytetrack.yaml", conf=CONFIDENCE,
                                     retina_masks=True, verbose=False)[0]
        canvas, active = frame.copy(), []
        if self.frame_no % LIGHT_EVERY == 1 and result.masks is not None:
            union = result.masks.data.cpu().numpy().astype(bool).any(axis=0)
            if union.any():
                self.clipped = round(float((frame[union].max(axis=1) >= CLIP_LEVEL).mean()), 4)
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
                if len(polygon) < 3:
                    continue
                votes = self.votes.setdefault(track_id, deque(maxlen=VOTES))
                every = CLASSIFY_EVERY if len(votes) < VOTES else SETTLED_EVERY
                if len(votes) < MIN_VOTES or (self.frame_no + track_id) % every == 0:
                    value, measured = self.p_good(frame, polygon, masks, claimed, index, bbox, table, nearby)
                    if value is not None:
                        votes.append(value)
                        self.measured[track_id] = measured
                p = float(np.mean(votes)) if votes else None
                decision = None if len(votes) < MIN_VOTES else ("good" if p >= 0.5 else "bad")
                if decision:
                    self.decided[track_id] = decision
                measured = self.measured.get(track_id) if self.kind == "relative" else None
                active.append({"id": track_id, "decision": decision, "p_good": p, "votes": len(votes),
                               "value": None if measured is None else round(measured, 1)})
                color = COLORS[decision]
                cv2.polylines(canvas, [polygon.astype(np.int32)], True, color, 6)
                text = f"#{track_id} {(decision or '...').upper()}" + (f" {p:.0%}" if p is not None else "")
                if measured is not None:
                    text += f"  rel L* {measured:.1f}"
                x, y = bbox["x"] + 8, max(40, bbox["y"] + 44)
                cv2.putText(canvas, text, (x, y), cv2.FONT_HERSHEY_SIMPLEX, 1.3, (255, 255, 255), 8, cv2.LINE_AA)
                cv2.putText(canvas, text, (x, y), cv2.FONT_HERSHEY_SIMPLEX, 1.3, color, 3, cv2.LINE_AA)
        if self.calibration is not None:
            cv2.putText(canvas, "CALIBRATING", (20, 60), cv2.FONT_HERSHEY_SIMPLEX, 1.8, (255, 255, 255), 10, cv2.LINE_AA)
            cv2.putText(canvas, "CALIBRATING", (20, 60), cv2.FONT_HERSHEY_SIMPLEX, 1.8, (0, 0, 0), 3, cv2.LINE_AA)
        scale = STREAM_WIDTH / canvas.shape[1]
        small = cv2.resize(canvas, (STREAM_WIDTH, int(canvas.shape[0] * scale)))
        ok, jpeg = cv2.imencode(".jpg", small, [cv2.IMWRITE_JPEG_QUALITY, 80])
        with self.lock:
            self.frame = frame
            self.jpeg = jpeg.tobytes() if ok else self.jpeg
            self.active = active
            self.fps = 0.9 * self.fps + 0.1 / max(1e-3, time.monotonic() - start)

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
        if result.masks is None:
            return {"ok": False, "message": "no bricks found: try again"}
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
        lightness = round(live.scene_lightness(frame), 1)
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
                self.decided.clear()


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
    parser.add_argument("--reference", type=Path, default=TOP_REFERENCE, help="calibration.json for knn")
    parser.add_argument("--nn-weights", type=Path, default=NN_WEIGHTS)
    parser.add_argument("--weights", type=Path, default=DETECTOR_WEIGHTS, help="YOLO segmentation detector")
    parser.add_argument("--source", type=Path, help="video file or image folder instead of the camera")
    parser.add_argument("--camera", type=int, default=0)
    parser.add_argument("--port", type=int, default=8000)
    parser.add_argument("--exposure", type=float, help="camera exposure (C920: -5 default, -6 / -7 darker)")
    parser.add_argument("--calibration-features", choices=sorted(live.FEATURE_OPTIONS), default="raw",
                        help="feature set stored in calibrations made in the browser")
    args = parser.parse_args()

    sorter = Sorter(args)
    source = Source(args.source, args.camera, args.exposure)
    running = True

    def loop() -> None:
        while running:
            frame = source.read()
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
                    "min_votes": MIN_VOTES, "active": sorter.active,
                    "reference": sorter.reference_name,
                    "light": {"scene": sorter.scene_lightness, "warn": LIGHT_WARN, "recalibrate": LIGHT_RECALIBRATE,
                              "clipped": sorter.clipped, "max_clipped": MAX_CLIPPED,
                              "reference": sorter.reference.scene_lightness if sorter.reference else None}}
        data["calibration"] = sorter.calibration_status()
        finished = sorter.trainer.poll()
        if finished:
            sorter.load_network(finished)
        data["nn"] = {**sorter.trainer.status(), "weights": sorter.nn_name, "auto": sorter.auto_train}
        return JSONResponse(data)

    @app.post("/reset")
    def reset() -> JSONResponse:
        with sorter.lock:
            sorter.decided.clear()
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

    @app.get("/stream")
    def stream() -> StreamingResponse:
        def frames():
            while True:
                with sorter.lock:
                    jpeg = sorter.jpeg
                if jpeg:
                    yield b"--frame\r\nContent-Type: image/jpeg\r\n\r\n" + jpeg + b"\r\n"
                time.sleep(0.05)
        return StreamingResponse(frames(), media_type="multipart/x-mixed-replace; boundary=frame")

    print(f"open http://localhost:{args.port}")
    try:
        uvicorn.run(app, host="0.0.0.0", port=args.port, log_level="warning")
    finally:
        running = False
        worker.join(timeout=2)
        source.release()


if __name__ == "__main__":
    main()
