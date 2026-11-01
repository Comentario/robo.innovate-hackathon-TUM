# Greenfield 37 — functional model with adapted factory layout

This is the current delivery on `task3/simulation-handoff`. It keeps the full-cart production engine and incorporates the through-track input carts, shared reject collection, V-shaped receiving chutes, direct-access warehouse and two-sided truck loading. It does not replace or merge the separate `task3/jacob1` implementation.

## Open the single visual demo

From the repository root:

```bash
python3 scripts/open_cart37_checkpoint.py
```

Open the printed HTML path in Edge or Chrome. It is self-contained and plays the prepared full run; opening it does not rerun the simulation.

If an older extracted demo already exists, preserve it and use a new output directory:

```bash
python3 scripts/open_cart37_checkpoint.py --output-dir artifacts/greenfield37_layout
```

## Rendering handoff

Use the extracted `index.html` as the authoritative browser/replay reference for the prepared Unreal rendering workflow. Regenerate geometry and animation exports from this package; earlier exports contain the earlier layout. This delivery does not rebuild or modify the existing Unreal project.

Source modules are in `greenfield/`; `layout.js` must load before `logistics.js` and `cart_model.js`. The Python packager includes that dependency automatically. `task3_checkpoint/greenfield_37/provenance.json` pins the matching source hashes, visual package and replay cache.

To package the editable source after extraction:

```bash
python3 scripts/cart_demo.py --output-dir artifacts/greenfield_37
```

The extraction helper also restores the matching replay cache into its output directory. If using a custom directory, pass the same directory to the packager. It does not regenerate production trajectories.

## Verified results

The visual run processes two identical-distribution kiln carts: 57,600 input IDs, 50,664 approved bricks, 6,936 rejects accounted for in the single discard store. It completes 84 pallets and ships 64 pallets on complete customer orders.

| Recipe configuration | Bricks/h | Pallets/h | Status |
| --- | ---: | ---: | --- |
| Visual run: Mixed plus three pure shades | 8,019.05 | 14.3197 | Complete |
| All Mixed | 9,137.10 | 16.3162 | Complete |
| Pure pallets across all three shades | 7,670.93 | 13.6981 | Complete |
| Two Mixed wells plus Warm per line | — | — | Allocator blocked; no complete-run capacity claimed |

The complete measurements, WIP and assumptions are in `task3_checkpoint/greenfield_37/capacity-layout37.txt` and `.json`. Values use complete pallets and the full input-processing window. These are finite-batch kinematic model results, not supplier-certified industrial throughput.

Validation covers material conservation, cloned input, product purity/mixing, rigid transport, formation collisions, continuous vehicle/truck separation and fork/support contact heights. Evidence is under `task3_checkpoint/greenfield_37/layout_validation/`. Structural calculations, physical grip forces, friction and OEM load-chart qualification remain outside this proof of concept.

## Budget

See [the hardware/budget report](greenfield37_hardware_budget.md) and [editable BOM CSV](greenfield37_hardware_budget.csv). The installed concept base is €2,702,200; a 22% explicit reserve gives a €3,296,684 funding allowance. Use €2.70–3.30M as a planning envelope, not a supplier quotation. Public price anchors and custom-assembly allowances are distinguished in the report.
