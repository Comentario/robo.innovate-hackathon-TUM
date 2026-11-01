# Task 1 - Brick Classifier: good/bad reclaimed bricks by color

Classify reclaimed clay bricks as **good** or **bad** from their color only, live
with a camera, in a browser demo (**Brick Classifier**). It runs on a laptop or on a
Jetson Orin Nano with an Orbbec Gemini 2 camera. **Facts and numbers for the pitch
slides are in [PITCH_NOTES.md](PITCH_NOTES.md).**

```
camera frame -> YOLO11n-seg brick detector (box + mask)         [detector v3]
             -> ByteTrack (one id per brick across frames)
             -> classifier on each brick: neural network YOLO11n-cls on the masked crop (default),
                1-NN on a calibration, or a relative lightness band
             -> vote: mean of the last 15 classifications -> GOOD / BAD
```

The YOLO detector was distilled from a slower zero-shot pipeline
(Grounding DINO -> row split -> MobileSAM, ~1.2 s per frame), which is still
available with `--detector grounding_dino` and was used to auto-label the training data.

## Weights (not in git)

Weights are kept out of the repository from now on (they make every clone heavy). Ask
the team for the files and place them at:

| File | Place it at |
|---|---|
| Detector v3 (YOLO11n-seg, 6 MB) | `outputs2/yolo_runs/brick_seg_v3/weights/best.pt` |
| Demo network (YOLO11n-cls, 3 MB) | `outputs2/classifier_runs/web_20261026_172444/weights/best.pt` |

Or pass them explicitly: `web_demo.py --weights <detector.pt> --nn-weights <network.pt>`.
The older detectors in `weights/` (v1, v2) were committed before this rule and still work.

## Web demo (main entry point)

```bash
pip install -r requirements.txt      # install torch for your CUDA first
python scripts/web_demo.py --classifier nn --reference examples/calibration_20261026_171541_demo.json
# open http://localhost:8000   (p = presentation mode, o = operator panel)
```

- **Presentation mode** (button Present, key `p`, or `http://localhost:8000/#present`):
  full screen, status panel with the newest verdict, session totals and yield, inspection
  log of the last 12 bricks; no operator controls. Best for the jury.
- **Operator panel** (key `o`): classifier choice, calibration in the browser (capture,
  label g/b per brick, finish; the network retrains in the background), detection area,
  camera settings, light and clipping indicators.
- Bricks are numbered #1, #2, ... per session; "reset" starts again at #1.
- Jetson Orin Nano (WendyOS) deployment: [jetson/README.md](jetson/README.md). The image also
  carries a kiosk (`jetson/kiosk.sh`, Firefox ESR) for a monitor on the Jetson; it needs a
  WendyOS image with a display compositor (0.20.0 on our device is headless, so the page is
  shown on a laptop through `web_demo.py --remote`).
- Every script and option: [scripts/README.md](scripts/README.md).

## Command-line classifier (earlier stage)

```bash
# 1. Calibrate in the test scene: photograph the labeled sample bricks (g/b per brick).
python scripts/live_brick_classifier.py --calibrate --method band --band-feature L_med

# 2. Classify live with that calibration (space = classify the current frame, q = quit).
python scripts/live_brick_classifier.py --reference outputs2/calibration/<session>/calibration.json \
    --method band --band-feature L_med

# Classify a saved photo with the example calibration:
python scripts/live_brick_classifier.py --image photo.jpg \
    --reference examples/calibration_20261025_201100.json --method band --band-feature L_med
```

Use a fixed camera (Logitech C920 settings in `scripts/capture_bricks.py`: manual white
balance 4520, exposure -5, gain 0, focus 20) and stable light; the preview warns when
the scene lightness or camera settings drift from the calibration. Logs (frames,
result images, `log.csv`) go to `outputs2/live/<session>/`.

## Results (for the pitch)

| What | Result | Folder |
|---|---|---|
| Pipeline step by step on one photo | detection, masks, L*/C* maps, per-brick numbers | `results/01_pipeline_steps/` |
| First datasets: which color features separate good/bad | lightness and chroma, bad bricks on both sides of good (under- and overfired) | `results/02_early_color_analysis/` |
| First live test, no calibration | 12/26 correct: light and scene differ from the reference | `results/03_live_first_test_20261024_153945/` |
| Live, calibrated 1-NN (table-relative lightness) | 39/43 (91 %) | `results/04_live_knn_calibrated_20261024_203017/` |
| Feature evaluation on a calibration | honest (unseen capture) vs memorized scores | `results/05_calibration_feature_evaluation_20261025_104739/` |
| Live, calibrated 1-NN, same bricks | 40/43 (93 %); band diagnosis and feature separability | `results/06_live_knn_same_bricks_20261025_192146/` |
| Live, lightness band (L* median 31.1-34.4) with a light change of 4-5 L* | 17/32 (53 %): narrow bands need stable light | `results/07_live_band_light_change_20261025_204353/` |
| YOLO detector v2 (standing + top view) | 126/126 standing and 48/48 top-view bricks, 0 false, mask IoU 0.95-0.96; v1 (standing only) failed on top view (37/48, 52 false) | `results/08_yolo_detector/` |
| YOLO detector v3 (+ carpet, wood, empty table) | 190/190 validation bricks, 1 false, mask IoU 0.95-0.98; overexposed wood 40/40 photos right (v2: 6/40); empty table 0 false (v2: 3) | `results/09_yolo_detector_v3/` |
| Top view: color rules on 127 clean faces | lightness band 77 % (balanced 83 %), chroma band 82 % leave-one-photo-out | `results/10_top_view_color_analysis/` |
| Neural network (YOLO11n-cls) | same bricks, light not seen: 114/133 (86 %); bricks never seen: 40/74 (54 %) | `results/11_neural_network_classifier/` |
| Web demo | reference run: every brick right (network + calibration 20261026_171541); interface screenshots | `results/12_web_demo/` |

What we learned:

- Color separates good from bad only partly: some bad bricks have good-brick colors
  and the faces of one brick differ. 1-NN works very well on the **same** bricks
  (it memorizes them); the band rule generalizes better to unseen bricks but scores
  lower (about 60-80 % leave-one-brick-out).
- Light is the main risk: too dark compresses colors, overexposure removes chroma.
  Best results with the table around L* 50-55 and a fixed brick position.
- The YOLO detector makes tracking possible (one detection per frame instead of 1.2 s).
  It knows our scenes; a new scene (e.g. the factory belt) needs ~100 new photos
  auto-labeled with `build_yolo_dataset.py` and retraining.

## Folder map

- `scripts/web_demo.py`: browser demo (main entry point); `v4l2_camera.py`: Linux / Jetson camera.
- `scripts/build_classifier_dataset.py`, `train_brick_classifier.py`: neural-network crops and training.
- `scripts/build_yolo_dataset_v3.py`, `compare_detector_versions.py`: detector v3 data and comparison.
- `scripts/capture_brick_faces.py`, `capture_four_faces.py`, `label_brick_faces.py`, `top_view_marks.py`,
  `evaluate_top_view.py`, `build_top_view_reference.py`, `analyze_calibration_separation.py`: top-view data and analysis.
- `scripts/stage_jetson_app.py` + `jetson/`: Docker image and WendyOS deployment for the Jetson Orin Nano.
- `scripts/live_brick_classifier.py`: command-line live / photo classifier and calibration (earlier stage).
- `scripts/capture_bricks.py`, `capture_top_view.py`: dataset capture with fixed camera settings.
- `scripts/run_grounding_dino.py`, `clean_grounding_dino_*.py`, `split_brick_row.py`,
  `run_mobile_sam.py`: zero-shot detection and segmentation pipeline.
- `scripts/build_yolo_dataset.py`, `train_brick_detector.py`, `compare_brick_detector.py`:
  YOLO distillation, training and evaluation (`--view standing|top`).
- `scripts/analyze_*`, `evaluate_*`, `diagnose_*`, `visualize_pipeline_steps.py`,
  `benchmark_pipeline.py`: analysis and diagnostics behind the results above.
- `scripts/predict_good_prototype.py`, `evaluate_prototype_first_dataset.py`,
  `experiment_svm_*.py`: early experiments on the first datasets.
- `weights/brick_seg_v2.pt`: final detector (default). `weights/brick_seg_v1_standing.pt`: standing-only v1.
- `examples/`: calibrations (the demo reference `calibration_20261026_171541_demo.json`, the
  top-view reference, an older one), the combined YOLO dataset yaml and the photo exclusion lists.

MobileSAM, the YOLO11n-seg base weights and Grounding DINO download automatically on first use.

## Datasets

The photo datasets are on Google Drive (not in git). Place them next to `scripts/`
with these folder names: `Initial_Dataset_Bricks_LEGO/`, `Second_Dataset_Bricks/`,
`Third_Dataset_Bricks/`, `Top_View_Dataset/`. Generated data (calibrations, live logs,
YOLO datasets and runs) goes to `outputs2/`.

## License note

YOLO11 (Ultralytics) is AGPL-3.0; a commercial deployment needs an Ultralytics
license or another detector.
