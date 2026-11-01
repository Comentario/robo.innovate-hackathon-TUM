# Final Stage 2 idle round: tested PGS workaround

The full 300-brick source and a reserved interior-removal state pass the frozen
one-second native idle gate with PGS. This closes the initial stability benchmark
after three improvement rounds. It does not demonstrate grasping, extraction,
contact-force calibration, insertion or the integrated sorting demo.

Only the scene constraint solver changes, TGS → PGS. Actor position/velocity
iterations remain 32/4; the failed round-2 value 16 is not promoted. Geometry,
initial poses, nominal joint targets, timestep, epsilon 1e-4, collision assets,
materials and native clutch capacities/break rules remain unchanged. The shared
scene defaults are preserved; the experimental entry point applies PGS explicitly
and verifies the actual USD scene plus runtime source-actor properties.

| Phase | Capture / audit Pueue IDs | Frozen case | Outcome |
|---|---|---|---|
| A | 1745 / 1746 | Same eccentric two-brick fixture, 8 steps | 12 wrapper + 36 base checks pass; all angular residuals zero; linear gravity residual 9.24e-12 N s |
| B | 1747 / 1748 | Full 300 bricks, 301 native parts, 930 links, 120 steps | 33 checks pass; no breaks; maximum drift 0.208 mm, rotation 0.125° |
| C | 1749 / 1750 | Reserved H_mix: 299 bricks, 300 parts, 926 links, 120 steps | 33 checks pass; no breaks; maximum drift 0.582 mm, rotation 0.505° |

B/C retain every initial native link at every measured step. Final linear/angular
speeds are respectively 6.37e-7 m/s and 1.38e-5 rad/s in B, and 2.07e-6 m/s and
4.99e-5 rad/s in C. Frozen limits were 2 mm/2° drift and 0.02 m/s/0.2 rad/s final
speeds. C is a historically known perception layout reserved from dynamics
implementation decisions, not independent-stack generalization.

A's 100× angular-artifact reduction and 1e-8 N s linear-residual screens were
frozen before any PGS result. They are operational proceed rules, not calibrated
physical tolerances. Only its passing independent audit permitted B; only B's
passing audit permitted C. All three configurations and gates were frozen at
source `cacbae9` before A. There were no retries, sweeps, native builds or fourth
configuration round. All six jobs used the default Pueue queue without changing
its concurrency. Total measured physics budget was at most 248 steps.

The preceding [eccentric diagnostic](../stage2_eccentric_20261025/README.md)
exposed a torque-reporting signature consistent with the public PhysX 5.6.1 TGS
writeback path. PGS suppresses that signature and passes these native idle checks.
This supports the workaround; it does not establish exact source identity of the
vendor binary or prove all force reporting is correct. The initial TGS failures
and unsuccessful epsilon/iteration trials remain preserved in
[Stage 2 history](../stage2_idle_20261025/README.md).

## Reproduce the staged comparison

Use the existing `unitree_sim_env`; no dependencies were installed. Commands
below snapshot committed source/configuration and submit foreground children to
default Pueue. B/C reject an absent, failing or wrong-protocol predecessor audit.
Run the independent evaluator through Pueue using the corresponding frozen audit
`launch.sh`; never run its array processing directly.

```bash
python experiments/stage2_pgs_20261025/submit.py --phase A
python experiments/stage2_pgs_20261025/submit.py --phase B --predecessor-audit <passing-A-evaluation.json>
python experiments/stage2_pgs_20261025/submit.py --phase C --predecessor-audit <passing-B-evaluation.json>
```

Exact previously executed commands, input/source hashes and environment settings:

- [A capture manifest](../../runs/20261025T023902.662030Z-stage2-round3-PGS-A/manifest.json), [audit launcher](../../runs/20261025T023921.396642Z-stage2-round3-PGS-A-evaluation/launch.sh), [audit result](../../runs/20261025T023921.396642Z-stage2-round3-PGS-A-evaluation/output/evaluation.json).
- [B capture manifest](../../runs/20261025T024036.744684Z-stage2-round3-PGS-B/manifest.json), [audit launcher](../../runs/20261025T024055.481502Z-stage2-round3-PGS-B-evaluation/launch.sh), [audit result](../../runs/20261025T024055.481502Z-stage2-round3-PGS-B-evaluation/output/evaluation.json).
- [C capture manifest](../../runs/20261025T024214.471653Z-stage2-round3-PGS-C/manifest.json), [audit launcher](../../runs/20261025T024231.107173Z-stage2-round3-PGS-C-evaluation/launch.sh), [audit result](../../runs/20261025T024231.107173Z-stage2-round3-PGS-C-evaluation/output/evaluation.json).
- [Machine-readable outcome and all provenance](results.json), [frozen capture rules](protocol.json), [independent evaluation rules](evaluation/protocol.json).

Retain this explicit PGS configuration for subsequent contact validation. Do not
resume configuration tuning or fall back silently to the historical TGS default.
The next gate is actual supplied-fingertip collision geometry and contact feedback;
the existing fingertip STL is visual only. Camera/classification timing and
physical calibration are still unverified. No robot or camera hardware was moved.
