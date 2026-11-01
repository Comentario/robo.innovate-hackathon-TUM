# Wrist mount side correction

The inherited BrickSim camera occupied hand −X. Rotate both the camera and
bracket by 180° around hand +Z, keeping the gripper and all arm joints fixed.
The camera center now occupies hand (+0.0375, 0, +0.0526) m. These inherited
housing offsets remain nominal, not physical optical calibration. Both fixed
joint frames and authored initial body transforms change together. Native
BrickSim files are untouched; the override belongs only to this visual twin.

Pueue **1710** rendered frozen source **526fc7e**. Pueue **1711** verified source
**077b75f**. Both use the default queue. Checks confirm unchanged source states,
300 bricks/930 native links, layout apart from the mount configuration, robot
joints/hand pose, lighting, exposure and original diagnostic camera intrinsics
and poses. A third virtual close-up was added for inspection. The camera and
bracket hand-relative transforms agree with the corrected fixed joints.

- [Close-up](../../../runs/20261024T225412.612710Z-final-workcell-preview/output/images/diagnostic_wrist_mount.png)
- [Overhead before/after](../../../runs/20261024T225503.569156Z-wrist-mount-verification/output/diagnostic_table_top_before_after.png)
- [Verification](../../../runs/20261024T225503.569156Z-wrist-mount-verification/output/verification.json)
- [Updated USD](../../../runs/20261024T225412.612710Z-final-workcell-preview/output/final_workcell.usda)

Reproduce a fresh immutable default-queue preview:

```bash
python3 experiments/final_workcell_20261024/submit_preview.py --cameras experiments/final_workcell_20261024/wrist_mount/cameras.json --appearance experiments/final_workcell_20261024/appearance_config.json
```

Exact launchers, source revisions and hashes are recorded in each run snapshot.
No physical hardware, ROS, manipulation or optical calibration was performed.
