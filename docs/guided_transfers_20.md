# Guided transfer correction — revision 20

Open `artifacts/greenfield_20_checked/index.html` in Edge/Chrome. **Inspection** shows the raised reject paddle and guided infeed; **Blending** shows the powered outlet transfer and row former. Previous demos are preserved.

## Physical sequence

The inlet servo waits for a reserved encoder gap, accelerates the brick along a guided tangent path, and matches the circulating belt speed at the handoff. The outlet uses a flush powered steerable-roller cassette: underside traction and side guides transfer the selected brick onto a tangent outlet. The brick follows the path tangent continuously and finishes parallel to the row-former rollers. There is no instantaneous change of yaw at the joins.

The amber branch is narrower and follows the centerline of the recomputed transfer. Long yellow row-former guides now start at the downstream deck rather than projecting into this branch. Transfer noses and plates meet the receiving deck; the branch and circulating deck are clipped at their physical seam. Both sensor brackets connect to the conveyor frame.

The reject paddle starts raised above approved material. For a rejection it lowers behind the stopped brick, pushes with its face against the brick, raises, then returns above the flow. Its complete cycle is now included in the simulation.

## Manufacturer principles consulted

- [Dorner diverting, pushers and gates](https://www.dornerconveyors.com/solutions/diverters-pushers-gates): guide/plow and actuated gate principles; side or overhead pushers.
- [Dorner FlexMove merges and diverts](https://sourcelinkcorp.dornerconveyors.com/products/flexmove/flexmove-pallet-system/merge-diverts): fixed merge guides, turning guides and mounted actuated divert assemblies. Pallet-system examples are principle references, not claims of loose-brick compatibility.
- [Intralox activated roller belt](https://www.intralox.com/belt-finder/modular-plastic-belting/series-400/90-degree-angled-rollertm): embedded driven rollers and complementary rails generate lateral transfer. Our compact cassette is a custom concept; it is not a dimensionally faithful or supplier-qualified Series 400 unit.

## Timing and validation

Motion records now include sampled cubic guide paths and tangent yaw. Distance is their arc length, used in the acceleration/cruise/deceleration profile. The inlet gap reservation uses that same duration. The viewer and clearance checks consume the recorded path rather than inventing a different visual route.

The new synthetic batch produces **3,888.672 conforming shipped bricks/h**, with 60 formed layers. Earlier 4,236.9/h timings are superseded for this revised cycle; 5,000/h remains a target.

- Regression suite: 87 discovered tests, 74 passed, 13 skipped, no failures.
- Static geometry: 164,659 recorded strokes, 7,746 static bounds, 3,134,412 candidate checks, zero detected intersections. Guided curves use 65 arc-length samples with tangent-oriented bricks; identical geometric paths are checked once. Loop curves remain sampled at <=50 mm intervals.
- Moving paddle-head check: 263,208 temporal samples across guided transfers and straight row-pocket approaches; no detected penetration against reject and row-pusher heads. Face contact within 0.1 mm is allowed.
- Browser: offline WebGL startup without runtime errors; inlet/outlet screenshots at 10%, 50% and 90% of actual transfer duration.

These are kinematic and geometric checks, not rigid-body/contact/friction validation or a full moving-machine collision proof. Evidence lives under the artifact's `verification/` directory.

Reproduce:

```bash
python3 scripts/greenfield_demo.py --output-dir artifacts/my_guided_demo
PYTHONPATH=.deps/plant_sim python3 scripts/greenfield_junction_audit.py artifacts/my_guided_demo/run.json --output /tmp/paddle-audit.json
GREENFIELD_FLOW_REPORT=artifacts/my_guided_demo/run.json PYTHONPATH=.deps/plant_sim python3 -m unittest discover -s tests_greenfield -v
```
