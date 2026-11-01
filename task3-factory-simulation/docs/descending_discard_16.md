# Revision 16 — downward discard belt

Working branch: `persona2/planning`; return point `5fc99cb`.

The reject pusher feeds a supported upper entry. A powered belt descends approximately 19.9 degrees to the common collector. Eight discard elevators, upper docking cycles, vertical guides and empty-lift returns are removed from this variant. Side guides stop short of the pusher entry. The lower nose uses short supported poses to level the brick before it reaches the collection rollers. There is one reject stream and stationary bins remain finite.

[mk Technology Group](https://www.mk-group.com/en/products/conveyor-technology/belt-conveyors.html) describes typical straight-belt incline/decline capability up to approximately 20 degrees, conditional on belt, product and drive. This is a machinery principle reference, not a qualified purchased assembly. Selected belt speed is 0.60 m/s. High-friction material, controlled retention, nose radii, temperature and dust require trials; friction is not simulated. The Interroll RM 8210 is NOT used as an incline reference.

Open `artifacts/greenfield_16_final/index.html`, or reproduce with:

```bash
python3 scripts/greenfield_demo.py --config config/greenfield_decline.json --output-dir artifacts/my_decline_run
```

The original configuration remains unchanged. This is a hardware/transfer simplification, not the high-capacity architecture. Reference finite-batch output is 2,294.146 conforming shipped bricks/h, 62 formed layers, four full pallets; these are not the results of the separate full-cart layer-repair study.

Straight material paths are checked against static exported geometry. The straight slope uses an oriented moving brick; pitch-changing nose paths are sampled at 33 poses per short segment. Supporting-belt contact is excluded from penetration certification. Moving-machine mutual collisions, gripping and friction are outside the audit. Browser rendering, material accounting and regression tests are also checked. Review the generated verification evidence before interpreting these as commissioning results.

Verification completed: regression suite (77 checks at that point), plus an additional oriented-box unit check, passed. Final exported static scene: 15,038 bounds, 5,576,677 candidate checks, 211,549 material strokes, zero reported intersections within the declared scope. Edge rendered all 3,200 bricks with WebGL and no reported JavaScript error.
