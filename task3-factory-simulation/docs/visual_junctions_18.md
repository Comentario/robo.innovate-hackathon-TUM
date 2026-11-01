# Visual junction update — revision 18

Open `artifacts/greenfield_18/index.html` in Edge or Chrome. Select **Inspection** for the inlet and reject transfer, or **Blending** for the loop outlet and row former. All displayed content is English.

- The receiving surface is now a supported steel sliding deck with a directional drive strip, rather than a passive ball table presented as a powered conveyor. The side pusher sends rejected bricks onto the flush red decline entry.
- Blue infeed, slate circulating belt and amber outfeed have distinct surfaces, direction arrows and supported frames. Curved decks have solid continuous undersides.
- A retracting inlet stop and a pivoting outlet guide follow the recorded loading/extraction commands. Their mounted bodies, transfer aprons and guide rails explain the intended merge and exit. These are conceptual mechanisms; contact forces and steering performance are not certified.
- The amber outlet ends before the row-former receiving rollers, with a short transfer plate instead of an overlapping belt.

## Verification

The revision reuses revision 17's exact `run.json`: no resimulation, timing changes or throughput increase. Estimated conforming delivery remains **4,236.9 bricks/h** for this batch; **5,000/h is a target**. Single-color pallet planning is not added by this visual update.

Eight flow regression tests pass. The browser initializes offline with WebGL and no runtime error. The exported scene audit checks 168,141 recorded strokes against 6,962 static bounds: 3,371,319 candidate checks, zero detected intersections. Shared loop curves are sampled at intervals of at most 50 mm. Moving mechanisms, material-to-material contact, friction and gripping forces are outside this audit's scope.

Screenshots, scene bounds, test log and audit are in `artifacts/greenfield_18/verification/`. The earlier revision 17 demo remains available as a return point.
