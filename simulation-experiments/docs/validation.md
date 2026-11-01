# Validation on 23 October 2026

Runtime: existing `unitree_sim_env`, Python 3.11, Isaac Sim 5.1.0.0, local
Isaac Lab 2.3.2 source checkout, Torch 2.7.0+cu128, Stable Baselines3 2.8.0.
BrickSim wheel: `0.1.0.dev645+gcbd5de3`, matching local commit
`cbd5de3238e6ac12f44ef699e1507a9f16bdafc3`.
Wheel SHA-256:
`145e7d838ef8f7ad5f848a5633492b57f5f894a7e9a3dfe7812767c7194af8fb`.

All simulator and learning runs used the default Pueue queue. Its concurrency
remained one. All listed jobs finished; no simulation was left running.

| Pueue ID | Check | Result |
| --- | --- | --- |
| 1653 | Two-brick connected column, 60 idle control steps | Finite observations, no task failures or timeouts |
| 1654 | Full 48-brick mixed-output workcell, 180 idle control steps | Source graph: 49 parts, 48 native connections; no failures/timeouts; USD export |
| 1655 | One-brick PPO, 256 timesteps | One training iteration completed; `policy.zip` saved |
| 1656 | Full 48-brick separate-shade workcell, 180 idle steps, explicit midpoint reset | Source graph restored to 49 parts; no failures/timeouts; USD export |
| 1657 | Load job 1655 checkpoint and evaluate for 90 control steps | Checkpoint inference completed; zero successful sorting episodes |
| 1660 | CUDA arithmetic and full-scene RTX rendering, 120 idle control steps | RTX 5070 CUDA 12.8 check passed; source graph reset; overview/detail images saved; no task failures/timeouts |
| 1664 | Final CUDA/render/idle-pose verification, 120 control steps | CUDA passed; 49-part source graph restored; arm drift 5.02e-8 rad; USD and physics hand positions agree; inspected images saved |

Six simulator-independent unit tests pass: exposed removal order, reject
exclusion, shade separation, output support/non-overlap, native interface grid
transforms and SI/WXYZ pose conventions. Python compilation and shell syntax
checks pass. The paper-tool option rejects an incomplete tool definition before
starting a simulator.

Initial attempts exposed a Conda activation hook that is incompatible with
`set -u` during activation (1651) and the difference between Isaac Lab's regex
asset path and a concrete native USD path (1652). Both were corrected. The job
wrapper now requires an explicit completion marker because Kit reported exit
code zero for the Python exception in job 1652.

The workstation exposes an RTX 5070 and `nvidia-smi` reports driver 580.178.04.
Earlier runs reported CUDA error 999 and skipped the graphics device. CPU PhysX
and CPU PPO completed despite that fault. No driver/module reset or global
environment change was attempted by these workcell validation jobs.

Follow-up: the [CUDA recovery investigation](cuda_recovery.md) found a fatal
UVM/MMU error at 09:25:46 and the driver's explicit `GPU Recovery Action: Reboot`.
Health-check job 1659 confirmed that state. After the user reported CUDA
recovery, job 1660 confirmed CUDA allocation/kernel execution on the RTX 5070
and RTX/Vulkan rendering. Its arithmetic result was 1240, as expected. Both
960x720 RGB captures were inspected. Physics and PPO still use CPU; GPU training
and interactive GUI operation are not claimed.

Visual review of jobs 1660–1662 exposed stale USD robot transforms: the Isaac
Lab experience disables USD updates while this task disables Fabric. The
launcher now explicitly enables per-process USD transform updates. Job 1663
confirmed exact rendered/physics hand-position agreement, but also exposed
idle gravity drift in the relative-IK controller. The arm now uses ideal gravity
compensation while bricks retain gravity and contact/clutch loads. Job 1664
passed the new 0.02 rad idle-drift bound with a measured maximum of
5.02e-8 rad. It also passed the 1 mm rendered/physics hand-position check
with identical coordinates. Its two images are the canonical current previews;
earlier images do not show the correct controlled arm pose. The original short
PPO check predates this control assumption and is not a trained solution.

No successful grasp, peel, insertion, full sorting episode, real-world transfer,
or physical comparison between tools has been demonstrated. The one-update
checkpoint exists to validate training/checkpoint plumbing only. Clutch/pad
parameters remain uncalibrated. The stock upstream FR3 asset also warns about
mass/inertia on the link8 and TCP dummy bodies. Treat that as a dynamics
calibration issue before drawing force/torque conclusions.

Artifacts are under ignored `runs/`:

- `20261023T165253.045807Z-smoke/`: full mixed scene, results and manifest.
- `20261023T165501.936213Z-train/`: training snapshot and checkpoint.
- `20261023T165502.256468Z-smoke/`: separate-shade scene, results and manifest.
- `20261023T165614.959635Z-evaluate/`: checkpoint inference results.
- `validation-pueue.json`: complete captured Pueue logs for jobs 1653–1657.
- `20261023T184556.243844Z-smoke/`: CUDA check, full-scene render captures and results.
- `20261023T185048.535944Z-smoke/`: final inspected preview images, synchronized poses, CUDA check and idle-arm validation.
- `validation-render-pueue.json`: complete logs for render verification jobs 1660–1664.

Each snapshot includes its own source and native dependency copy. The referenced
upstream FR3 USD still resolves NVIDIA assets from its original HTTPS location
or the workstation's asset cache. It is not an offline asset bundle.
