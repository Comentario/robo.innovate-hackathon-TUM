# Equipment reference inspector — revision 25

Open `artifacts/greenfield_25/index.html` in Edge/Chrome. Hover over a functional assembly to see its category-colored dashed outline; click to open its equipment card. The dashboard layout is unchanged.

Each card contains the assembly purpose, current modeled configuration, official reference images, manufacturer specifications, direct source links and the relationship between that real product and the custom scene. When an assembly needs more than one reference, each product has its own image and specifications. All visible content is English.

The catalog has 26 records and 22 distinct local reference images; 24 records are used by the current scene. There are 289 selectable zones: 76 actuator, 120 sensor, 73 transport and 20 structural zones. These are selectable representations, not a bill of materials or a claim that 289 independent devices have been purchased.

## Reference families

| Equipment / function | Manufacturer reference | Relationship |
|---|---|---|
| Full-stack bridge | Demag KBK double-girder crane | 3,200 kg family envelope; custom bridge/trolley/EOAT integration |
| Layer handling gantry | Güdel FP-4 | High-load axis envelope, including payload derating; custom tool |
| Linear pushers | Festo ELGC-TB-KF-80-1500 | Axis reference, not the complete multi-axis tool |
| Longer transverse slides | Festo ELGA-TB-KF-70 | Long-stroke family reference |
| Guided divert lift | Festo DFM-32-160-P-A-KF | 160 mm guided actuator; custom cam and pneumatic timing unqualified |
| Inspection rollers | Interroll EC5000 | 50 mm roller / 35 W / 30:1 reference; supporting roller assembly is custom |
| Roller-zone controls | Interroll MultiControl AI | Four-zone controller; not a controller for every logical loop slot |
| Loop and curved branches | mk KMF-P 2040 | Curved modular-conveyor principle; speed and complete circuit unqualified |
| Cross-belt and decline | mk GUF-P 2000 | Powered belt principle; product traction and configured duty need validation |
| Merge transfer | Interroll RM 8230 | Driven angled-merge reference; custom branch widths/curves differ |
| Lateral roller transfer | Intralox Series 400 angled roller | Lateral-traction principle; not the exact steerable cassette drawn |
| Color cameras | Basler ace 2 a2A2600-64ucBAS | Global-shutter color / trigger reference; no live inference in viewer |
| Presence sensors | SICK WTB4-3P2162 | Short-range presence detection; not safety protective equipment |
| Inspection lights | Smart Vision Lights L300 | Trigger/intensity/power reference; scene diffuser and housing are custom |
| Encoder feedback | ifm RO3100 | Incremental feedback reference; ideal encoder positions in simulation |
| Shared drive motor | SEW R..DR.. | Broad gearmotor family; power, ratio and loop torque not selected |
| Pallet roller transport | Interroll PM 9710 | Published pallet-conveyor envelope |
| Output and inventory rail carts | HORSTMANN VWG | 1,200 kg reference; inventory design target is a different 8,000 kg custom cart |
| Pack side restraint | KINSHOFER KM332 family | Brick-grapple principle; custom supported fork/clamp hybrid |
| Grouping and guided lowering | LINGL Triangle Brick installation | Industrial process reference; no selected complete lift rating |
| Discard collection | BAUER RD 1000 | Real tipping-container reference; custom open-front bin differs |
| Perimeter protection | Troax ST20 | Guarding product reference; scene boundary rails are not a certified mesh guard |

## Important qualification differences

Product photos and family limits are **not** evidence that an integrated line has been selected or commissioned. The cards explicitly record differences rather than assigning a familiar brand to custom hardware.

In particular, the curved KMF-P 2040 reference publishes up to **0.50 m/s** while the current loop assumes **1.50 m/s**; the full circuit is also custom. The 1.50 m/s cross-transfer assumption is above the cited GUF-P 2000's 1.33 m/s European envelope. The inventory cart's 8 t target is not the 1.2 t reference VWG. The fast guide pulse is a visual/kinematic assumption, not a validated DFM pneumatic cycle. These open selections are visible in the corresponding cards; no performance assurance is inferred from the photos.

The 3,888.672 conforming shipped bricks/h batch remains the existing synthetic estimate. The production `run.json` is byte-identical to revision 20. This revision adds equipment information and selection coverage; it does not re-simulate or qualify that output rate.

## Evidence and maintenance

All 289 cards were opened offline, with 363 image instances decoded successfully and no missing references, missing images or undefined values. Real browser mouse-move and click events selected the intended light and opened its card. Two catalogue integrity tests pass, including local image hashes and separation of published ratings from modeled selections. Evidence is under the demo's `verification/` directory; `equipment-coverage.csv` maps every active selection zone.

`greenfield/catalog.json` is the equipment-reference source of truth. Viewer refresh loads the current catalog while preserving historical production data. Existing `run.json` files retain the catalog recorded when they were generated; the current displayed reference revision is supplied by the refreshed viewer. New pictures are attributed and hashed in `greenfield/assets/equipment-image-sources.json`; existing image provenance remains in `greenfield/assets/SOURCES.md`. There are no generated product photographs or added runtime dependencies.

Refresh with:

```bash
python3 scripts/greenfield_refresh_view.py artifacts/greenfield_20_checked --output-dir artifacts/my_equipment_view
PYTHONPATH=.deps/plant_sim python3 -m unittest discover -s tests_greenfield -p test_equipment_catalog.py -v
```
