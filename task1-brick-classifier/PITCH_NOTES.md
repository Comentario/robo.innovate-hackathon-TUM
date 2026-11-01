# Brick Classifier: facts for the pitch slides

Every number below comes from a result file in `results/` (folder in brackets). "Same
bricks" means that the test bricks were also used in calibration or training. "Unseen
bricks" means that the test bricks were never used. Please keep this difference on the
slides.

## One line

A camera and a small neural network sort reclaimed clay bricks into **reusable (good)**
and **reject (bad)** by their color. It runs live at the edge on a Jetson Orin Nano, and
the result is shown in a browser.

## Problem → idea

- Reclaimed bricks must be sorted by hand. Under- and overfired bricks look different
  in color: bad bricks lie on **both sides** of the good ones, both darker and lighter
  `[02]`.
- Idea: detect every brick, look only at the brick (not the table), classify its color,
  and stay stable over time by voting across frames.

## Pipeline (one slide)

```
Camera (Orbbec Gemini 2, 720p) → YOLO11n-seg: box + mask per brick → ByteTrack: one id per brick
→ YOLO11n-cls on the masked 224 px crop (1.5 M parameters, ~1 ms per crop) → mean of 15 votes → GOOD / BAD
```

- The neural network sees only the brick, with the table masked out in grey. Its
  training uses **no color augmentation**, because color is the signal.
- Two classifiers without a neural network are kept as a baseline and fallback:
  - 1-NN on a calibration (L*, C* in CIELAB);
  - a relative lightness band (brick L* minus table L*).
- Calibration in the browser takes about 2 minutes: capture the labeled bricks and
  press g/b per brick. The network then retrains on the device in the background.

## How we got there (story slide)

1. **Zero-shot labeling.** Grounding DINO → row split → MobileSAM found and segmented
   the bricks with no training, but took about 1.2 s per frame `[01]`.
2. **Distillation.** Those automatic labels trained a YOLO11n-seg detector. It runs at
   ~17 ms per frame on an RTX 3050, which makes live tracking possible `[08]`.
   - Detector v3 (285 photos: standing, top view, carpet, wood, empty table) found
     **190 of 190** validation bricks with 1 false detection and a mask IoU of
     0.95–0.98.
   - On overexposed wood, v3 was right on 40 of 40 photos (v2: 6 of 40).
   - On an empty table, v3 made 0 false detections (v2: 3) `[09]`.
3. **Hand-made color rules.** Calibrated 1-NN reached 91–93 % live on the same bricks
   `[04, 06]`. A lightness band dropped to 53 % when the light changed by 4–5 L*
   `[07]`. Lesson: light is the main risk.
4. **Neural network** on the masked crop `[11]`:
   - same bricks under a light it never saw: **114 / 133 = 86 %**, balanced 85 %;
   - reference run of the web demo: **every brick right**, at about 22 fps on a laptop
     RTX 3050 `[12]`.

## Honest limits (one slide; juries like this)

- **Unseen bricks: 40 / 74 = 54 %** `[11]`, and top-view color bands 77–82 % `[10]`.
  We had only **10 physical bricks**, so the network learns those bricks and not yet
  "brick quality" in general. **More bricks** is the next step, not more photos of the
  same ones.
- Color depends on the light and the camera:
  - the light pill warns when the table lightness drifts from the calibration;
  - a new camera or light needs a 2-minute recalibration.
- The Gemini 2 sees colors differently from the C920 webcam we trained with. A network
  retrained with Gemini video got better on one brick and worse on stained edges, so the
  demo keeps the validated network.

## Engineering details worth one line each

- **Votes:** 15 votes beat a quick 5-vote lock. The lock froze early decisions taken
  while a hand was still moving the brick.
- **Detection area:** sending a crop to the detector made bricks look 2–4× larger than
  in training. The results fell from 35/35 to 30/35, and to 5/35 for tight areas. The
  demo now detects on the full frame, keeps only the bricks inside the area, and only
  zooms the video: 35/35 again.
- **Edge deployment:**
  - Jetson Orin Nano (WendyOS, JetPack 7.2, 25 W), Docker image with CUDA PyTorch;
  - the laptop only shows the page;
  - calibrations, retrained networks and camera settings persist across redeploys.

## Images for the slides

| Slide | File |
|---|---|
| Live demo interface | `results/12_web_demo/interface_normal.png`, `interface_present.png`, `reference_run_20261026/web_screenshot.jpg` |
| Pipeline steps | `results/01_pipeline_steps/0002/` |
| Detector v2 vs v3 | `results/09_yolo_detector_v3/v2_vs_v3/*.jpg`, `training/val_batch0_pred.jpg` |
| Why color is hard | `results/10_top_view_color_analysis/3_gallery_by_lightness.jpg`, `1_feature_separation.png` |
| Feature space | `results/02_early_color_analysis/` |

## Next steps

- More physical bricks, including bricks from the factory, for unseen-brick accuracy.
- A gray card / color checker in view for automatic color correction across cameras and
  light.
- TensorRT on the Jetson for more fps.
- Connect the decision to the robot that does the sorting.

## Not measured yet

- fps on the Jetson Orin Nano. Measure it during the demo: the page shows fps and
  milliseconds per step.
