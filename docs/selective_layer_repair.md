# Selective layer repair — engineering capacity screening

## Decision

Preserve bulk delivery, two dehackers and two guided palletizers. Evaluate replacing the central per-brick grade-sort/queue/select/reassemble section with two layer-inspection and selective-repair stations. This is an alternative station architecture under study, not a completed replacement in the 3D demo.

A layer stays on a supported spreading table. Four row carriers open controlled gripper-clearance gaps (selected 2 s), inspection supplies a good/bad label and one of three accepted shades, and one or two heads remove only rejected bricks or positions that violate the mix. Accepted bricks removed for blending return to verified stock. Replacement stock is explicit and replenished automatically. The layer closes (selected 2 s), is checked (0.5 s), and transfers to the existing guided lowering concept.

The spreader and end effector are unresolved detail-design items: side-finger access, minimum gaps, compliance, brick temperature, dust and fragile edges must be tested. A pallet's ten-by-four count does not alone establish its metric footprint or brick orientation. Robot reach, tooling and the chosen orientation require a layout check. Two heads are assigned separate five-column territories in the capacity model; that division is not a collision-checked robot program.

## Evidence and what it supports

- [LINGL Triangle Brick](https://lingl.com/wp-content/uploads/2018/03/Triangle_Brick_englisch.pdf): historical installed bulk unloading, double-layer robotic handling, mixing tables/pushers and lowering frames. It supports preserving group handling, not our selective-repair cycle time or exact no-three pattern.
- [LINGL Watsontown](https://www.lingl.com/wp-content/uploads/2018/03/Watsontown_Brick_Company_englisch.pdf): alternating unloading tracks for color blending, two dehacking robots and regrouping layers. Historical reference, not a current hourly performance guarantee.
- [KELLER handling systems](https://www.heavy-clay-solutions.com/en/machine-solutions/handling-systems/): industrial robotic and servo-gripper handling in abrasive brick environments. It supports the machinery class, not qualification of a proposed end effector.
- [Epson GX specification](https://mediaserver.goepson.com/ImConvServlet/imconv/849d7aa550cf1b97051aa3c411ec81ffc1d62aa8/original?assetDescr=71555_Robotics_Spec_CTG_Dig_FNL.pdf): GX20 reach 850/1,000 mm, rated payload 10 kg, maximum 20 kg. Its standard 0.37/0.42 s cycles use a specified short arch and must NOT be used as brick replacement cycles. A robot is not selected until footprint, mounting, tool mass/inertia and industrial protection are checked.
- [Interroll continuous transport](https://www.interroll.com/products/mcp/rm-8210): one 400 V drive for a long transport module up to 12 m. This is suitable for transport, not proof that a shared belt can move a single brick while leaving its other occupants still. The model does not pretend that removing sensors increases throughput.

## Full-cart capacity model

`greenfield/layer_study.py` and `scripts/layer_repair_study.py` are separate from the 3D kinematic model. One cart contains 36 stacks × 800 = 28,800 bricks; each layer contains 40, and each output pallet 560. Two lines retain their partial pallets at the end; only full pallets count as shipped.

Timing inputs:

| Operation | Basis |
| --- | --- |
| Layer transfer | Explicit rest-to-rest triangular/trapezoidal profiles, XY 1.0 m/s, Z 0.7 m/s, 3.0 m/s²; selected 3 m source/destination separation; grip 0.25 s, release 0.20 s |
| Inspection | Selected 1.0 s per layer; synthetic labels, no live vision inference |
| Spreading / closing | Selected 2.0 s each, requiring mechanism validation |
| Final layer check | Selected 0.5 s |
| Full repair | Selected 5 s or 8 s for BOTH removal and replacement, not each pick; all heads finish removal before replacement begins |
| Stack delivery | One shared server, selected 40 s per 800-brick stack |
| Pallet change | Selected 18 s; guided lowering includes 69 mm travel at 0.12 m/s and centering dwell |
| Verified stock | Initial 250 bricks/shade/line; finite 500-piece lane limit; 100-piece replenishment in selected 30 s through one shared supply server |
| Effective-time sensitivity | 0.85 scales operation times; this is NOT measured OEE or a failure/recovery model |

The nominal synthetic input uses three uniformly sampled accepted shades and a 12% defect probability. It is not calibrated to an ACME SKU or the Task 1 camera. Search preserves acceptable positions heuristically and enforces no three equal consecutive shades across rows, columns and pallet height. Equal thirds is a soft preference, not a hard layer recipe. No claim of globally minimum replacements is made.

Final three-seed results (8, 18, 28):

| Heads per station / total | Full repair time | Effective-time factor | Shipped bricks/h range |
| --- | --- | --- | --- |
| 1 / 2 | 5 s | 1.00 | 4,545–4,577 |
| 2 / 4 | 5 s | 1.00 | 7,012–7,066 |
| 2 / 4 | 8 s | 1.00 | 4,686–4,709 |
| 2 / 4 | 5 s | 0.85 | 5,960–6,006 |

Seed 8 changes 7,801 of 28,800 positions (27.1%). Of these, 3,420 are bad bricks and 4,381 are acceptable bricks returned to stock for blending. The other 72.9% avoid individual repair handling. Replacement stock adds material to the accounting boundary: input plus initial/replenished good stock equals full pallets plus partial pallets plus rejects plus final stock. This is not equivalent to the old model, which sorts out defects without the same replacement-supply architecture. Do not market these capacity results as an apples-to-apples validated speedup of the 3D model.

One head is the lower-component-count option; two heads add capacity without duplicating the plant. There is no justified economic optimum until equipment quotations, tool trials and measured cycle times exist. The next engineering gate is a reachable, collision-checked repair/spreader layout with a demonstrated full repair cycle; not increasing a declared speed to hit a headline number.

## Reproduce

```bash
python3 scripts/layer_repair_study.py --output-dir artifacts/my_layer_study
python3 scripts/layer_repair_study.py --seed 18 --output-dir artifacts/my_layer_study_18
PYTHONPATH=.deps/plant_sim python3 -m unittest discover -s tests_greenfield -p test_layer_study.py -v
```

Open the generated `index.html`; `results.json` includes stage busy times, all layer grids, edit counts, pallet releases and material accounting. The visual language is English.

## Rejected local optimizations

The revision 15 reference achieved 2,264.219 shipped/h in a four-stack synthetic batch. Tests of independent-motion overlap (2,193.857/h), full-row dosing (2,099.167/h) and fixed orthogonal tables with faster supported roller settings (2,288.184/h) did not resolve the system bottleneck. Their configuration code was not adopted into the reference renderer. A common-drive tone-belt experiment reached a protected horizon with material retained, revealing cross-grade blocking. Those trial artifacts remain local for diagnosis; none is claimed as a working improvement.

These trials motivated changing the central station's handling principle instead of buying more of the same conveyors. No claim that longer belts increase service capacity or that linear plant replication is free is made.
