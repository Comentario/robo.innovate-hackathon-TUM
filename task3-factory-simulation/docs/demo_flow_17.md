# Continuous-flow demo — revision 17

Return point: `4f10f74` on `persona2/planning`. The earlier demos remain available.

## Open the current demo

Open `artifacts/greenfield_17_final/index.html` in Edge/Chrome. Use **Blending** to see the shared-drive loops, **Inspection** for full-row dosing and the downward reject belt, and **Dispatch** for finished pallets. Hover/click the physical components for their information. All visible labels are English.

Reproduce a fresh run from the repository root:

```bash
python3 scripts/greenfield_demo.py --output-dir artifacts/my_flow_demo
# Explicit configuration:
python3 scripts/greenfield_demo.py --config config/greenfield_flow.json --output-dir artifacts/my_flow_demo_2
```

SimPy remains the only Python dependency. The HTML contains its graphics library and recorded trajectories and works offline. Choose a new output directory to preserve previous evidence.

## What changed in the demo

- Removed the green side-mounted cubes beside the red decline belts.
- Removed all 24 external reserve belts and 24 long shade-storage lanes.
- Removed the eight moving grade-routing shuttles and eight moving mix selectors.
- Added eight continuous, common-drive mixing loops. Every occupant follows the same belt speed and encoder phase; a brick that is not selected keeps circulating.
- Added synchronized inlet feeding into a reserved empty encoder position and a fixed selected-tone outlet. There is no independent drive or presence sensor for every loop position.
- Extended the process by 8 m and shifted row formation, guided palletizing and output logistics coherently. Each loop has 72 geometric encoder positions and an operational occupancy limit of 66; the count is finite, not unlimited hidden storage.
- Replaced ten individual inlet pusher cycles with one wide-paddle transfer per ten-brick row. A transverse belt indexes every remaining brick together; its leading brick then enters inspection.
- Separated the protected approach from the preceding brick's loading motion. Rejection retains its approach reservation until the ejector can actually move, avoiding two bricks occupying the same inlet.
- Prefetched one next selected brick while the independent row table indexes. The final approach to the row pocket is straight to avoid clipping its neighbor.
- Selected loop speed 1.5 m/s, small servo transfers 1.5 m/s, layer XY 1.25 m/s and pallet transport 0.50 m/s. Existing acceleration, braking and dwell profiles remain active. These are engineering timing assumptions, not commissioned cycle measurements.

The long transport now uses eight common loop drives instead of 480 independently driven tone positions. The 64 inspection zones and the inlet, outlet, row-dosing and other machine drives remain separate. Eight is not the total motor count of the plant.

## Measured finite-batch results

Same four-stack / 3,200-brick input size as the preceding demo. Output rates count only complete 560-brick pallets delivered, and include startup, handling, waiting and batch closeout.

| Input distribution seed | Status | Conforming shipped bricks/h |
| --- | --- | ---: |
| 8 | Completed with residual stock | 4,236.899 |
| 18 | Completed with residual stock | 4,124.782 |
| 28 | Completed with residual stock | 4,073.662 |

The reference run delivers four complete pallets / 2,240 bricks. Partial pallets, remaining accepted inventory and rejects remain accounted separately. The no-three-adjacent mix and the good/bad decisions are preserved. The visible capacity objective is 5,000/h; it is not substituted for the achieved rate. A kiln cart still contains 36 stacks / 28,800 bricks; this demo batch uses four of them.

The first 58-position candidate saturated on seed 28. The final conveyor length and 66-position operational capacity address that observed failure; the failed candidate is not used for the headline result.

## Verification and presentation limits

Tests cover complete delivery, material accounting, shared-drive motion, exact constant-speed trajectory compaction, full-row dosing and spatial mix. Browser initialization and screenshots verify the rendered scene. Straight trajectories are swept against static geometry; common curved paths are sampled with oriented bricks at intervals of at most 50 mm, and nose pitch transitions are sampled separately. This is a kinematic proof of concept: moving-tool mutual collision, traction, gripping and rigid-body dynamics are outside that audit.

The long constant-speed spans are stored once per brick instead of once per encoder tick. This reduces the HTML size without changing positions, timing, speed or reported throughput. No independent capacity study is required to open or explain this demo.

Final verification: 86 regression tests passed; all eight flow-specific checks also passed against the final report. The exported scene contains 7,282 static bounds; the final audit checked 168,141 strokes and eight shared curved paths, with zero reported intersections within its stated scope. Three input distributions completed with material conserved. Verification files and screenshots are beside the generated demo.
