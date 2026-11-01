# Individually selectable simulation views

The corrected stack has **300 bricks**: ten layers, each consisting of **six
parallel ridges of five 2×4 bricks**, with a two-stud gap between ridges.
Successive layers rotate by 90°. Their 20×22 / 22×20-stud footprints share a
center; a five-stud border places this center on the 32-stud source plate center.

The photo-supported phase remains horizontal origin `(1,0)` / vertical `(0,1)`
before the border. Each adjacent layer pair has 100 single-stud crossing patches,
for 930 native links total (900 interlayer + 30 baseplate), and 301 connected
parts including the plate. Whole-brick engaged-stud totals per interface are
2 for ten outer-ridge bricks and 4 for twenty other bricks. An individual
one-stud crossing and the total contact of a whole brick are distinct quantities.

The [current report](REPORT.md) links the completed corrected images (job 1681).
Capture validated; stalled Isaac cleanup was stopped separately. The prior
[360-brick report](REPORT_360_SUPERSEDED.md), geometry and `results/` files are
preserved unchanged as superseded artifacts. New captures use `results_300/`.

The existing FR3 workcell, pinned BrickSim and Isaac runtime remain in use.
Only render geometry changes; the legacy task configuration is untouched.
Unused square-factory brick assets are removed before scene creation, ensuring
that exactly 300 bricks are instantiated. Actual PhysX and USD poses, native
graph, physics state and time are checked throughout capture. These are static
initialized renders, with zero post-connection physics steps; dynamics and
load-bearing stability remain unvalidated. Virtual cameras are approximate,
not calibrated D435i/wrist poses. The image panel is display-only.

After committing source/configuration, from the repository root:

```bash
python3 experiments/sim_views_20261024/submit.py --views all
python3 experiments/sim_views_20261024/submit.py --views top
python3 experiments/sim_views_20261024/submit.py --views top,oblique_front
```

Names: `top`, `near_top_x`, `near_top_y`, `oblique_front`, `oblique_side`.
[Camera settings](cameras.json) specify resolution, nominal lens, offsets and
lighting. Each submission freezes a source/configuration/dependency snapshot,
uses `pueue add` in the default queue and reports its job ID. No global queue or
shared environment changes. RGB is separate from simulator evaluation truth.

Previous attempts exposed reset-induced pose drift and a cleanup stall. The
renderer restores exact geometry after reset, verifies both PhysX and USD,
and writes validated-capture and shutdown markers separately. If cleanup stalls
after `CAPTURE_COMPLETE_VALIDATED`, inspect that run's `output/run_complete.json`
and `output/shutdown.json`, then stop only its job with `pueue kill <job-id>`.
A killed job without validated outputs is not successful capture.

No detection, training, fusion, ROS integration, manipulation or hardware work
is performed by this view comparison.
