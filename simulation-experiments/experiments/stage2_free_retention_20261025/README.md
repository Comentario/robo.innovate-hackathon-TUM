# Free-brick retention fixture

This diagnostic separates free-body retention from the native tower's release
load. It is not a perception-driven pick, native extraction, or a passed task
stage. The failed1819 extraction and1820 saved diagnosis remain unchanged.

One upright dynamic native2×4 coupon rests from initialization on a passive
8×8mm post, outside the source plate, at the existing initial robot pose. The
coupon root is its body base. Its body top is derived from the fixed initial
finger/TCP reference and the same3.082809mm nominal engagement band. Gravity is
on; the coupon has no native connections. There is no scripted release, pose
correction, attachment, or removal of any tower connection. The original source
remains300bricks/301parts/930edges, counted separately from the extra coupon.

The existing geometry, masses/inertias, controller, nominal14mm endpoint,
30-endpoint/three-fresh candidate rule, force-confirmed branch and2N/contact/
motion limits remain. No approach or color classification is tested. A fresh
stationary control precedes a separately initialized close→5mm lift→30-step hold.
Each episode is capped1500steps (12.5s), covering the planned9s sequence; the
control covers the entire maximum pick horizon. Reaching the cap without the
hold is failure. The earlier3600-step controls are not relabelled as this test.

The independent audit requires source stability, unchanged coupon properties,
complete native/tensor coupon-BODY contact mapping, qualified lateral contact,
no observed finger–post/metal/head contact, ≥4mm actual coupon rise, support separation
through the terminal hold and ≤1mm/3° coupon–TCP change since admission. Candidate
admission alone is not holding success. Whole-arm contact coverage remains unverified. A pass supports studying native release;
a failure directs attention to grip/model assumptions without proving a hardware
fault. The centered fixture also removes prior perception miscentering, so a pass
does not prove clutches were the sole earlier cause. No transfer or task-extraction
credit follows.

One foreground default-Pueue control/pick/audit job, ≤400s. The prospective
aggregate ceiling is2500s, retaining all2055.105461418 prior seconds; the worst
case is2455.105461418s. No retries, sweep, hidden pool reset or threshold tuning.
Pick is skipped if control fails or less than135s remains. The old2200s ledger
and all previous failures remain historical facts.

After final independent source review and commit:

```bash
python3 experiments/stage2_free_retention_20261025/submit.py
```

The same installed `unitree_sim_env`/Isaac5.1/BrickSim runtime is reused without
dependency changes. Source/configuration/helper hashes are snapshotted before
queueing. Tiny source/synthetic tests can run with that environment's Python;
all physical simulation and captured-array evaluation use Pueue.

## Result — Pueue1821

Source `bdd3880`; snapshot `runs/20261025T154448.823497Z-stage2-free-retention`.
The matched1500-step control passes with zero finger load, stable coupon and
intact301/930 source. The fresh pick lifts after a real1.5N force confirmation
at step424, only4 completed endpoint commands; position fallback is not used.
At step795 it aborts on finger speed and left lateral-contact qualification.
Final coupon rise is0.230mm, maximum admission-relative drift2.673mm/4.145°;
retention violates its bounds for232 frames. No completed5mm lift/hold. Peak
loads1.631/1.624N stay below2N. Tower state and private contact mapping pass.

This is a free-body retention failure: tower clutch resistance is not necessary
for the failure, but identical causes in the two tests are not established.
One separate audit-schema bug makes `candidate_record` false: the runtime's
force-confirmation record includes both commanded finger targets, while the
inherited expected record omitted that field. A two-file source/synthetic repair
now reconstructs the exact command vector; original1821 is not rescored or
relabeled. Independent reviewers accept the distinct physical failures.

Full Pueue232.401402697s is charged, yielding2287.506864115/2500s retained.
The one control/pick diagnostic is closed. A separately reviewed timing-only
comparison may wait through30 endpoint commands at the same14mm target; no
material, force, depth or trajectory tuning is implied by that hypothesis.
