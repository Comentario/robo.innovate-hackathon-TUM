# Pretrained model availability check

Checked on 24 October 2026, without running training or porting dependencies.

## Brickssifier Studwise: usable

Repository commit: `3aef8aade8cb74a04780d5e809e49dfa1fc57a47`.
Both published inference pairs were downloaded from that commit:

- January: `Brick_Model_best20250123_192838t.pt` and `Stud_Model_best20250124_170824.pt`.
- March: `bricks_model_kaggle50epoch_10032025.pt` and `studs_model_kaggle50epoch_10032025.pt`.

The YOLO inference wrapper `ultralytics==8.3.221` and helper
`ultralytics-thop==2.0.18` are isolated under this experiment's `.deps`.
The existing Conda Python, Torch/CUDA, NumPy, Pillow and OpenCV are reused
without shared-environment installation. Runtime and weight hashes are recorded
in each frozen inference snapshot and `predictions/inference_run.json`.

Upstream `utils/detection_utils.py` predicts a brick box, crops it, then applies
the stud detector. The experiment preserves this sequence but explicitly fixes
image sizes, confidence and NMS settings for reproducibility. A separate
full-frame stud baseline uses the same pretrained stud weights independently
of failed brick proposals. No shade classifier or training code is run.

## Xuanyi assembled-LEGO YOLOv3: skipped

Repository tree commit: `ee3ded6015d4624a1eea76e448c30fbf34ce231d`.
The complete file tree is saved in `xuanyi_tree.json`. No `.weights`, `.backup`
or LEGO `.h5` checkpoint is published in that tree. The notebooks reference
locally trained paths such as `backup/yolov3-tiny-obj_last.weights` and
`backup/yolov3_custom_train_2.backup`, which are absent from the repository.

The README's two YOLO ZIP links were also checked. Both Google Drive file URLs
returned HTTP 404; response evidence is saved in `xuanyi_drive_availability.json`.
The commented download of generic `yolov3.weights` is not a trained LEGO model
and was not substituted for one.

The availability investigation stayed below the requested approximately
20-minute limit. The missing LEGO checkpoints/archive URLs prevent a
straightforward pretrained inference run. No CUDA 8 installation cells,
Darknet build, notebook training, or framework port were attempted.
