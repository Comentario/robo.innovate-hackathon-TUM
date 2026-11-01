# Manual image reference

This reference was created by visual inspection before viewing any detector
prediction overlays. It covers `img_1`, `img_3`, `img_7`, `img_10`, `img_13`, and
`img_16`, selected from all 18 uploaded 1280×720 JPEGs. The selection covers
rotation, alternate visible layer directions, long same-color strips, shadow,
and specular glare. There is no camera calibration metadata in these JPEGs.

`annotations.json` contains 166 confirmed **visual exposed top faces**, 14
ambiguous/excluded cell regions, 23 selected lower-layer visible surface
fragments, and 48 manually located stud centers. A visual exposed top face is
not a claim that the FR3 fingers can reach it. The lower-layer fragments are
non-exhaustive negative regions, not reconstructed full hidden-brick polygons.

Each selected image has six visible parallel strips with five complete
four-stud-length groups along each strip. This describes the photographs only:
the user corrected the full initial input to 10 layers of 6×6 bricks and
confirmed that layers were removed between the photographs. No image was
forced to contain 36 top-layer annotations, and the reference does not infer
hidden layer geometry or total remaining brick counts.

Polygons were manually specified from visible strip edges and visually
inspected four-stud groups/seams. `build_reference.py` uses bilinear interpolation
between those manually placed corners to draw regular neighboring polygons;
it does not detect bricks or read model outputs. Poorly visible same-color
seams, glare, and incomplete edge cells are explicitly marked `ambiguous`.
Individual top faces otherwise use the known 2×4 footprint and visible stud
rows to distinguish neighbors. Polygon boundaries are approximate (typically
about 3 px; some oblique corners can be about 5 px). Manual stud centers have
approximately 2 px annotation uncertainty.

Angles describe the undirected long axis in image coordinates: x increases
right, y increases down, angle is modulo 180°. These are image orientations,
not robot-frame yaw or calibrated metric poses. All 48 stud references belong
to confirmed top instances and were visually clear; none lies in an excluded
ambiguous cell.

Images are correlated views of one stack through a disassembly sequence.
Conservative correlation groups are A (`img_1`–`img_6`), B (`img_7`–`img_9`),
C (`img_10`–`img_12`), and D (`img_13`–`img_18`). These groups are descriptive,
not independent train/test splits or evidence of generalization.

Overlay colors: green confirmed visual top face, orange ambiguous/excluded,
blue visible lower fragment, magenta reference stud center. IDs are `cNrM`,
where `c` indexes the manually inspected strip and `r` its four-stud group,
including in horizontal views. Stack ROI excludes background loose bricks and
cables. `inventory.json` records source hashes and which views were selected.

To regenerate the annotation overlays using the existing Pillow runtime:

```bash
/home/faps/miniforge3/envs/unitree_sim_env/bin/python \
  experiments/detection_20261024/reference/build_reference.py
```

This command only draws existing manual annotations; it performs no ML or
simulation work.
