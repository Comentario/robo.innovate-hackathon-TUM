# Recipe-aware buffer workflow — control validation

Checkpoint: the existing motion model and upstream input are unchanged. This
iteration implements and exercises a separate controller, not a new physical
warehouse or a new plant-capacity simulation. No increase in production is claimed.

## Review

- Existing 3D plant with pallets/h: `artifacts/greenfield_27/index.html`.
- Executable control sequences: `artifacts/greenfield_27/buffer.html`.
- Previous executive checkpoint: `12d7cf6`; previous artifact remains intact.

The workflow review is deliberately separate from the 3D replay. Its small
capacities are test fixtures, not selected warehouse capacities. It demonstrates
transactions, not travel, mixing-loop encoder timing or contact dynamics.

## Functional architecture

Keep eight mixing loops and two output lines. Add a shared bank per line with
three independently accessible FIFOs: Warm, Copper and Russet. Rejected extremes
remain outside approved inventory. A direct path remains the preferred route.

1. Consume a requested colour already available in the loop.
2. Maintain admission headroom: route surplus incoming material to its colour FIFO
   when pressure reaches the high-water mark.
3. When the wanted colour exists only in storage, reserve a return position.
4. If the loop is full, first reserve storage for a nonrequested colour and transfer
   that brick out. Only acknowledged transfers free the source position.
5. Return the requested colour; the reserved position cannot be stolen by admission.
6. If both storage and the loop are full, retain material and inhibit admission.
   Do not discard approved material, manufacture inventory or silently change recipe.

The same bank can serve all four cells on its line. Lines do not share stock in
this controller. A single logical transport resource per bank serializes access;
its actuator, travel path and service time are NOT yet selected. A mechanical
adapter must not interpret a logical transfer as an instantaneous physical move.

## Recipe contract

`Recipe('mixed')` uses a rotating 4×10 pattern with no three adjacent equal
colours in either horizontal direction or through fourteen vertical layers.
`Recipe('single', 'Copper')` intentionally produces an entirely Copper pallet;
spatial-mix restrictions apply only to Mixed.

`PalletOrders` assigns fourteen layers to the four cell formers on one line.
A queued recipe changes only after fourteen stacker acknowledgements for the
current pallet. Layer formation alone does not close the pallet. The other line
can run another recipe independently. A single-colour order has no automatic
fallback to Mixed when stock is absent.

## Adapter contract

`RecipeBuffer.admit(...)` and `.plan(...)` return a `Transfer`, or `None` when no
safe move is currently reservable. The controller reserves destination capacity
and bank access before issuing the transaction. The transport adapter must:

- execute the actual route and await a destination confirmation;
- call `.complete(transfer)` only after that confirmation;
- preserve occupancy while a command is pending;
- use `.cancel(transfer)` only after confirming the brick is still at its source
  (or an external admission has not happened); an uncertain physical state cannot
  be resolved by cancellation alone;
- request the next transfer fairly across the four cells, not through an unbounded
  fixed-priority loop;
- call `.take(...)` only for a confirmed physical outlet delivery, then issue the
  brick to its reserved layer; acknowledge stacking separately.

The controller is independent of upstream batch size and feed strategy. The next
multi-pallet input design can use the same admission contract. This iteration
neither changes the current input nor sizes storage from its four-stack batch.

The default 560 slots per colour is a configurable test/planning placeholder, not
an optimized design. Storage capacity and path/service capacity must be selected
and verified together in the later physical integration.

## Verified sequences

- Full loop with absent requested colour: bypass, surplus evacuation, reserved return.
- Shared FIFO returns one cell's stock to a different cell on the same line.
- Full bank and absent colour: safe finite-capacity backpressure, no lost identities.
- Concurrent destination reservations cannot overfill a port.
- Shared-bank transport is serialized; cancelled reservations retain source ownership.
- Duplicate output and stale/double acknowledgements are rejected.
- Recipe changes wait for all fourteen stacker acknowledgements.
- Single-colour purity; Mixed has no three equal neighbours on any of three axes.
- 4,000 seeded randomized admission/transfer/cancellation/output operations preserve
  material identity, FIFO colour separation and capacity invariants.

These checks prove controller invariants. They do not prove mechanical clearance,
cycle time, a throughput increase or compatibility of new physical equipment.
The existing 3D trajectories are reused without changes.

## Pallets/h

Four complete pallets / 2,073.7157979 seconds × 3,600 = **6.94405666 pallets/h**.
This uses the same elapsed time and complete-pallet basis as **3,888.67173
estimated bricks/h**. The **4,166.434 formed bricks/h** remain visible separately.
Partial pallets are not counted as complete output. Rates remain finite-batch
hourly equivalents, not a new one-hour test.

The preserved plant UI now displays **3,889 estimated bricks/h**, **4,166 formed/h**
and **6.94 pallets/h**. No buffer timing is charged or credited to that old result:
the new controller is not yet connected to its physical model.

## Industrial principle references

- LINGL, Triangle Brick: mixing tables supply coloured rows before packaging:
  https://lingl.com/wp-content/uploads/2018/03/Triangle_Brick_englisch.pdf
- FlexLink: distinction between inline and bypass accumulation:
  https://www.flexlink.com/en/portfolio/production-flow/accumulation
- mk: horizontal/vertical accumulation using belts, chains or zoned rollers:
  https://www.mknorthamerica.com/engineered-solutions/accumulation-and-storage/

These support the buffering principle, not a selected brick-duty machine or price.

## Reproduce

```bash
PYTHONPATH=.deps/plant_sim python3 -m unittest discover -s tests_greenfield -p test_recipe_buffer.py -v
PYTHONPATH=.deps/plant_sim python3 -m unittest discover -s tests_greenfield -p test_presentation.py -v
python3 scripts/recipe_buffer_preview.py --output-dir artifacts/greenfield_27
python3 scripts/greenfield_refresh_view.py artifacts/greenfield_20_checked --output-dir artifacts/greenfield_27
```

Generate the workflow preview before refreshing the plant view to include its link.
No SimPy plant rerun is required for these two separate review views.
