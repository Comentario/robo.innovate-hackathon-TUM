# Scripts

Diagnostic and validation entry points live here. Production perception modules
remain under `perception/`.

Color-estimator diagnostics:

- `analyze_lab_distribution.py`: visualize measured Lab distributions.
- `experiment_lab_cluster_count.py`: compare K=1, K=2, and K=3 candidates.

Hackathon dataset annotation:

- `run_grounding_dino.py`: run Grounding DINO (`grounding-dino-tiny`, prompt
  `bricks`) locally on the clean `*_NS.jpg` brick scenes and write previews,
  per-image JSON and `detections.json` to `outputs2/grounding_dino/`. Boxes are
  stored both at the 1280 px detection size (`box`) and in original pixels
  (`bbox_px`).
- `clean_grounding_dino_boxes.py`: turn the raw Grounding DINO boxes into one
  box per brick (removes stack-level boxes, merges crack fragments in the same
  column, recovers bricks only covered by the stack box) and write previews and
  `detections_clean.json` to `outputs2/grounding_dino_clean/`.
- `clean_grounding_dino_fragments.py`: rebuild whole lying bricks from
  fragmented Grounding DINO boxes in top-down views using the brick aspect
  ratio (removes stack boxes, merges fragment pairs, extends lone fragments) and
  write `outputs2/second_dataset/grounding_dino_clean/`.
- `analyze_second_dataset_colors.py`: per-brick color features for
  `Second_Dataset_Bricks/` measured inside the corrected boxes (a hand-written
  grid only assigns labels), feature separability, plots, and a
  leave-one-scene-out good-prototype check, written to
  `outputs2/second_dataset/color_analysis/`. Run `run_grounding_dino.py`
  (`--images Second_Dataset_Bricks --output outputs2/second_dataset/grounding_dino`)
  and `clean_grounding_dino_fragments.py` first.
- `predict_good_prototype.py`: prototype A (distance to the mean good brick in
  L*-minus-wood, chroma, and L*/chroma spread). Leave-one-scene-out predictions,
  metrics, overlays, the final `prototype.json` and `variant_comparison.json`
  (spread variants V0-V4 under the same protocol) go to
  `outputs2/second_dataset/prototype_a/`. Run after `analyze_second_dataset_colors.py`.
- `run_mobile_sam.py`: segment each corrected box with MobileSAM (ultralytics,
  weights in the git-ignored `models/`), drop pixels claimed by two masks, erode,
  and write label maps and previews to `outputs2/first_dataset/mobile_sam/`.
- `evaluate_prototype_first_dataset.py`: test prototype V4 on the first dataset:
  direct transfer of the second-dataset prototype and leave-one-physical-brick-out,
  with box vs MobileSAM regions and table vs wall references. Outputs in
  `outputs2/first_dataset/prototype_v4/`.
- `capture_bricks.py`: capture `GOOD_xx`/`BAD_xx`/`MIX_xx` photos into
  `Third_Dataset_Bricks/` with the camera driver settings dialog (to disable auto
  white balance, exposure and focus), a clipped-pixel warning, and per-photo
  camera properties.
- `split_brick_row.py`: one box per standing brick for rows of touching bricks
  (darkness profile of the joints + dynamic programming over brick widths);
  uses the Grounding DINO boxes directly when the bricks stand apart. Writes
  `outputs2/third_dataset/row_split/`.
- `evaluate_third_dataset.py`: color classifiers on `Third_Dataset_Bricks/`
  (fixed camera) with MobileSAM regions, leave-one-photo-out; labels from the
  photo name and the hand-read "G" marks. Writes `outputs2/third_dataset/evaluation/`.
  Pipeline: `run_grounding_dino.py --images Third_Dataset_Bricks --pattern
  '^(?:GOOD|BAD|MIX)_\d+\.jpg$' --output outputs2/third_dataset/grounding_dino`,
  `split_brick_row.py`, `run_mobile_sam.py --detections
  outputs2/third_dataset/row_split/detections_clean.json --images
  Third_Dataset_Bricks --output outputs2/third_dataset/mobile_sam`, then this script.
- `live_brick_classifier.py`: the whole pipeline in one script (Grounding DINO
  -> row split -> MobileSAM -> color -> 1-NN against the third-dataset reference).
  `--calibrate` first photographs the labeled sample bricks in the test scene
  (saved to `outputs2/calibration/<session>/calibration.json`) and uses them as
  the reference; `--reference calibration.json` reuses one. The preview shows the
  scene lightness (table L*) against the reference and warns when it is too dark
  or bright, or when camera settings differ from the calibration. Feature sets:
  raw, table (L* minus table) and table_ratio (L* with the table as white, the
  default for new calibrations); `--features` overrides the stored one.
  `--method band` classifies with a lightness band instead (good if LOW <= L* mode
  <= HIGH, fitted on the calibration or set with `--band LOW HIGH`) and shows each
  brick's L* mode and its distance to the band. `--band-feature L_med` uses the median L*
  instead of the mode.
  Faces with large light stains (`--stain-unknown`, default 0.12) or perforated
  faces (`--perforated unknown|classify`) are reported as UNKNOWN with a hint to
  show another face; calibration flags them and fits one band per face type.
  `--detector yolo` uses the trained YOLO11n-seg brick detector instead of
  Grounding DINO + row split + MobileSAM (`--detector grounding_dino`, default). Camera mode: space
  classifies the current frame, then g/b enters the true label of each brick for
  the log. `--image photo.jpg` classifies a saved photo. Logs (frames, result
  images, `log.jsonl`, `log.csv`) go to `outputs2/live/<session>/`.
- `analyze_live_session.py outputs2/live/<session>`: re-run the pipeline on a
  logged live session and plot why bricks were misclassified (feature space vs
  reference, scene brightness and gain, per-capture distances, holes), plus
  alternative feature sets scored on the live labels. Writes `<session>/analysis/`.
- `analyze_calibrated_session.py <calibration> <live session>`: feature metrics of a
  calibration, live accuracy per feature set (raw, table difference, table
  ratio), and a memorization check (unseen calibration capture vs. live with and
  without the closest calibration capture). Writes `<session>/calibration_analysis/`.
- `visualize_pipeline_steps.py photo.jpg [--reference calibration.json]`: save every
  pipeline step for one photo (Grounding DINO boxes, row split, boxes, MobileSAM
  raw and final masks, measurement regions, per-pixel L* and C* maps, per-brick
  distributions and numbers) to `outputs2/pipeline_steps/<photo>/`.
- `evaluate_calibration_features.py <calibration> <live session>`: re-measure every
  calibration and live brick from saved frames and boxes (median and mode of L*
  and C*, a*, hue, table difference and ratio) and score nearest-neighbor feature
  sets and a lightness "band" rule: honest (unseen capture), live, and live
  without its twin. Writes `<calibration>/feature_evaluation/`.
- `diagnose_band_outliers.py <calibration> <live session> [--band LOW HIGH]`: per-brick
  diagnosis of the L* mode (face type, light stains, dark specks, scene light,
  position) with galleries sorted by lightness and a factors chart. Writes
  `<session>/band_diagnosis/`.
- `benchmark_pipeline.py [photos] [--runs N] [--cpu]`: time each pipeline step
  (Grounding DINO, row split, MobileSAM, color) on this machine.
- `build_yolo_dataset.py [--from-cache]`: YOLO segmentation dataset (class brick)
  auto-labeled by the current pipeline from calibration/live frames and the
  standing-brick datasets, with review sheets and an `exclude.txt` list. Writes
  `outputs2/yolo_dataset/` (data.yaml, images/, labels/, review/).
- `train_brick_detector.py [--epochs N]`: train YOLO11n-seg on `outputs2/yolo_dataset`
  (weights in `outputs2/yolo_runs/<name>/weights/best.pt`).
- `compare_brick_detector.py [--run brick_seg]`: YOLO vs pipeline labels on the
  validation sessions (missed/extra bricks, mask IoU), unseen stress photos and
  speed. Writes `outputs2/yolo_runs/<run>/comparison/`.
- `diagnose_feature_separation.py <calibration> <live session>`: re-measure every
  labeled brick (L*, C*, a*, b*, hue, stains, specks, spread), rank features by
  good/bad separability and plot feature pairs. Writes `<session>/feature_separation/`.
- `evaluate_two_face_rules.py <calibration> [--extra calNNN=brick]`: classify each
  brick from both solid faces (ordered 4-captures-per-brick calibration) with
  several band rules, evaluated leave-one-brick-out.
- `capture_top_view.py [--output Top_View_Dataset] [--exposure E] [--focus F]`:
  capture a top-view dataset (GOOD/BAD/MIX/IMG photos) with fixed camera settings,
  live light measures (frame, center, border L*, clipped share), one JSON per
  photo and a session `log.csv`.
- `build_yolo_dataset.py --view top`: same auto-labeling for the top-view photos in
  `Top_View_Dataset/` (no row split; stack and nested boxes removed), written to
  `outputs2/yolo_dataset_top/`. `outputs2/yolo_dataset_combined.yaml` joins both
  views for `train_brick_detector.py --data`.
- `top_view_marks.py`: YOLO crops of every brick in the top-view photos (straightened,
  full resolution) on contact sheets to read the hand-written G marks, plus
  `outputs2/top_view/labels.csv` to fill with g / b / ?.
- `evaluate_top_view.py`: good/bad color separation in the top view (top-view
  measurement: dark holes, stains, carpet ring), band / ellipse / 1-NN rules
  in-sample, leave-one-photo-out and leave-one-block-out, compared with the
  standing calibration. Writes `outputs2/top_view/analysis/`.
- `build_top_view_reference.py`: calibration file for the live classifier from the
  labeled top-view photos (same measurement as the live classifier), with a
  leave-one-photo-out check. Writes `outputs2/top_view/reference/calibration.json`.
- `capture_brick_faces.py [--bricks 10] [--target 24]`: per-brick, per-face top-view
  capture for synthetic data and YOLO retraining: brick (n/p), label (g/b), face
  (1-6), auto capture each time the brick is still after being turned. The brick
  mask comes from the difference to empty-background photos (k), refined with
  MobileSAM, so it does not depend on YOLO (YOLO is only logged as a check: number
  of detections and mask IoU). Writes `Brick_Faces_Dataset/<session>/`.
- `capture_four_faces.py`: simplest per-brick capture: space takes one photo per face
  (4 per brick), then g / b labels the brick. Writes `Brick_Faces_Dataset/<session>/`.
- `label_brick_faces.py [packages]`: brick masks for the one-brick packages
  (`Brick_Faces_Dataset/brick_faces_*`) with Grounding DINO + MobileSAM, plus review
  sheets. Writes `outputs2/brick_faces_labels/<package>/`.
- `build_yolo_dataset_v3.py`: detector dataset v3 (front view, top view on carpet,
  one-brick photos on wood and carpet, empty-table negatives) with a relative
  `data.yaml`, so it can be zipped and trained elsewhere. Writes `outputs2/yolo_dataset_v3/`.
- `compare_detector_versions.py [--old brick_seg_v2] [--new brick_seg_v3]`: two detectors
  on the v3 validation split per source and on unseen stress sets (overexposed wood,
  today's live frames, empty table). Writes `outputs2/yolo_runs/<new>/versions_comparison/`.
- `build_classifier_dataset.py`: straightened, grey-background brick crops for the
  neural-network classifier. Writes `outputs2/classifier_crops/`.
- `train_brick_classifier.py --experiment conditions|unseen|light|final
  [--include-calibrations]`: YOLO11n-cls good/bad classifier without color
  augmentation; `unseen` = leave-one-brick-out, `light` = leave-one-calibration-out
  (same bricks, light not seen), `final` = model for the demo. Results and weights in
  `outputs2/classifier_runs/<name>/`.
- `web_demo.py`: browser demo (http://localhost:8000): YOLO detector + ByteTrack, vote
  over frames, classifier switchable in the page (1-NN on a calibration, relative
  lightness band, neural network), counters in view / session, scene light and
  clipped-pixel indicators, calibration in the browser (saved like `--calibrate`, with
  crops and relative lightness) and network retraining after each calibration. Opens in
  presentation view (video, counters, one card per brick with its classifier crop, P(good)
  against the 50 % threshold and votes x/15, the last 12 decided bricks, the pipeline with
  timings, a status panel with the newest verdict and the session totals); bricks are
  numbered #1, #2, ... per session (reset starts again at 1) and a 3-step guide shows while
  the table is empty. The Present button, key `p` or `/#present` goes full screen without
  the operator controls; the Operator button, key `o` or `/#operator` shows the controls.
  "Set area" there keeps only the bricks whose center is inside a rectangle drawn over
  the table and zooms the video to it (saved in `outputs2/demo_roi.json`, `--no-roi`
  ignores it); detection still runs on the whole frame, so the area does not change the
  scale the detector sees nor the classification.
  The camera is read in its own thread and the stream is pushed per processed frame
  (~30 fps on an RTX 3050 with the neural network). On Linux it reads the V4L2 color
  camera (`v4l2_camera.py`); `--remote http://<jetson>:8000` serves the page on the
  laptop while the Jetson runs the pipeline (see `jetson/README.md`).
- `v4l2_camera.py`: Linux color camera for the Jetson (Orbbec Gemini 2 or any UVC
  camera): color mode up to `--camera-max-height` at 30 fps, every control settable from
  the page (Camera settings) and kept in `outputs2/camera_settings.json`.
- `stage_jetson_app.py`: copy the code, weights, base crops and calibrations the Jetson
  app needs into `jetson/bundle/` (build context of `jetson/`, deployed with `wendy run`).
- `analyze_calibration_separation.py <calibration>`: re-measure every calibration face
  (top view) and score simple rules (bands, ellipse, logistic, tree, 1-NN)
  leave-one-capture-out. Writes `<calibration>/separation/`.
