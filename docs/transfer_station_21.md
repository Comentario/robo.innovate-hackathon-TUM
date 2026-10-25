# Transfer station correction — revision 21

Open `artifacts/greenfield_21/index.html`. Previous demos remain available.

## Changes

- Removed the white sliding deck. Powered approach rollers now join inspection to the blue curved inlet. A separate powered cross-belt receives the reject-pusher stroke and meets the existing red decline. Visible drives, rollers, structural frames and transfer noses show the transport mechanism.
- Widened the blue inlet to 360 mm and amber outlet to 300 mm. Widened the row-pocket receiving roller bed from 820 to 1050 mm so the outlet has actual support. Yellow row-former edge guides start downstream of the branch mouth.
- Added explicit transfer plates at the four straight/curve module seams per cell. The receiving rollers, blue inlet and reject belt use flush nose/transfer connections.
- Replaced both loop junction sensor cantilevers with complete floor-anchored, two-post portals. Sensor body, suspension tube, crossbeam, uprights and baseplates form one visibly connected assembly.
- Added a visible, vertically actuated curved divert guide. Its contoured lower edge follows the selected transfer path beside the brick. It lowers during the extraction pulse and lifts clear for recirculating bricks. An actuator body, rod, crosshead and supported mast accompany the powered roller cassette.
- Updated equipment click descriptions to match the physical assemblies.

## Checks

The production run is byte-identical to revision 20: **3,888.672 conforming shipped bricks/h** for this synthetic batch. No new capacity claim or timing recalculation was introduced by these geometry changes. The new guide is a conceptual timed mechanism, not independently validated contact dynamics.

The browser support audit casts downward rays at 736 recorded guided-transfer points across eight cells: **zero missing support surfaces** after closing the module seams. This checks sampled centerline support, not complete footprint contact or load-bearing design.

Static clearance audit: 164,659 strokes, 8,010 static bounds, 3,183,702 candidate checks, zero detected intersections. Straight paths use swept-envelope tests; loop and guided curves use sampled oriented envelopes. Moving obstacles and full material/contact physics remain outside the static audit.

Screenshots record early, intermediate and late inlet/outlet transfer phases. Browser startup and playback capture report WebGL active and no runtime error. Evidence and the browser verification script are under `artifacts/greenfield_21/verification/`.

For the underlying motion revision and manufacturer principles, see [revision 20](guided_transfers_20.md).
