# Revision 15 — continuous diagonal discard transfer

Return point: `d56c3b7`, revision 14. Working branch: `persona2/planning`.

## Mechanical change

The incoming reject pusher is retained: passive ball transfers do not propel a brick. Interroll explicitly identifies the RM 8130 as non-powered: https://www.interroll.com/products/mcp/rm-8130 . Its published properties are a principle reference, not qualification for dusty, perforated ACME bricks.

After rejection, one supported horizontal belt now feeds diagonally from the inspection exit directly to the docked elevator. The former receiving-deck stroke and its intermediate stop were removed. The upper deck is rendered as one continuous belt, with a visible drive and an open entry side so the pusher does not cross a guard. The elevator continues to lower onto the common collector; the new belt does not incline or pretend to lower the brick by gravity. Its geometry and drive are a custom concept, not an identified purchased module. Real belt tracking, guide contact, dusty duty and handover support require detail design.

## Measured comparison

Same configuration, seed 8, four stacks / 3,200 input bricks. Revision 14: 2,218.309 conforming shipped bricks/h. Revision 15: 2,264.219/h (+2.07%). Four full pallets / 2,240 bricks shipped, 200 in partial pallets, 364 residual and 396 discarded; material conserved. Rate is finite-batch simulated output, not commissioned capacity. Reference view: `artifacts/greenfield_15/index.html`.

A full kiln cart remains 36 stacks / 28,800 bricks. This four-stack reference is not a full-cart capacity test.

## Next optimization boundary

Preserve the two dehackers, eight cells and two guided palletizers while studying continuous transport for long runs and reducing individual selector round trips. Interroll RM 8210 documents one 400 V drive for up to 12 m: https://www.interroll.com/de/produkte/mcp/rm-8210 . This is a transport reference; short-edge-leading 67 mm bricks require closer support or a flat belt, not blindly copying 50 mm rollers.

LINGL Triangle Brick demonstrates bulk unloading, two dehacking robots, mixing tables, pushers and lowering frames: https://lingl.com/wp-content/uploads/2018/03/Triangle_Brick_englisch.pdf . Watsontown alternates two unloading tracks to mix firing variation: https://www.lingl.com/wp-content/uploads/2018/03/Watsontown_Brick_Company_englisch.pdf . These are historical industrial references. Whole uniform-row blending does not satisfy our no-three-consecutive requirement by itself.

Replacing long accumulation conveyors requires explicit end metering, full-lane stopping/queue behavior and finite buffers. It is not achieved by deleting sensors in the renderer or moving one brick independently on a common belt. Fixed-point tone dosing and row assembly must be screened before any claimed 10k–20k capacity. Those numbers remain design scenarios, not results of this revision.

## Verification scope

Browser initialization, screenshots and exported static scene are checked with actual recorded trajectories. Static-scene sweeps do not validate moving-tool mutual collision, friction or gripping forces. The geometry-dependent test now skips when either required file is absent instead of raising a missing-variable error.

Final verification: all 68 regression tests passed, including the exported static-scene sweep. Edge initialized offline with WebGL active and all 3,200 bricks; no JavaScript error reported. Legacy mobile-discard timing is retained; only the fixed-bin route uses the new diagonal transfer.
