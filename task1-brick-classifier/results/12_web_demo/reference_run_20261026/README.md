# Demo snapshot 20261026_174942

Working state of the web demo when it classified correctly (neural network).
- classifier: nn, network web_20261026_172444 (copied to network/best.pt)
- calibration: 20261026_171541 (copied to calibration/), scene table L* 14.8
- scene table L* when saved: 17.9; clipped brick pixels 0.0
- camera: exposure -6.0, white balance 4520.0
- frame.jpg: the view when saved; web_stats.json: the page state

Run it again exactly like this:
  .venv\Scripts\python.exe scripts\web_demo.py --classifier nn --exposure -6 ^
      --reference outputs2/demo_snapshots/20261026_174942/calibration/calibration.json --nn-weights outputs2/demo_snapshots/20261026_174942/network/best.pt
Keep the light so that the page shows a table L* close to 14.8 (calibration) / 17.9 (now).

Reference: the user confirmed this configuration was classifying everything right
(web_screenshot.png): neural network web_20261026_172444, calibration 20261026_171541,
dark carpet on the table, table L* 17.9 vs 14.8 at calibration (+3.1, "drifting"),
0.0% clipped brick pixels, about 22 fps.
