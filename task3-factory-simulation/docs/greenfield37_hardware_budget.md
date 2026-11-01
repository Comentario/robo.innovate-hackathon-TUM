# Greenfield37 hardware and installed-budget handoff

**Planning budget: €2.70 million installed; fund up to €3.30 million including a 22% reserve.** This is a bottom-up concept allowance, not a supplier quotation or a validated price interval. Its €0.59 million reserve makes the funding envelope explicit; it does not prove that every custom mechanism can be bought within it.

Research date: **28 October 2026**. Currency: **EUR, excluding VAT**. Public prices are observed web benchmarks, subject to lead times and quotation. All other prices below are team engineering allowances; the linked manufacturers support the hardware class/specifications, **not the estimated assembly price**. Do not label the headline “quoted plant cost.”

Scope: our functional Greenfield37 with the adapted Jacob layout, as packaged with this report. The release commit is the reproducible source baseline; this document does not describe Jacob’s separate simulation engine. Canonical sources are `greenfield/cart_model.js`, `layout.js`, `viewer_cart.js`, `logistics.js`, `warehouse_view.js`, and `catalog.json`. Refer to these source files rather than counting instanced meshes or equipment popup duplicates. The CSV is the editable detailed bill, with individual source URLs and quantity traces.

## What is included

Two consecutive **identically distributed** input kiln carts, each 28,800 bricks in 36 stacks of 800; the second cart is additional feed, not a replacement definition. Each input stack remains 10 × 4 × 20 bricks. Each complete output pallet is 10 × 4 × 14 = **560 bricks**. Brick dimensions from the challenge remain 245 × 67 × 69 mm.

The scope contains 36 layer heads, 36 row heads, six inspection streams, six adaptive routing decks, 18 formers, 18 guided pallet wells, six layer-transfer portals, one finished-goods yellow-frame gantry, 128 floor stock positions, 16 handoffs, four autonomous vehicles and two loading bays. Discard goes through six supported V exits into three lower branches and one common collector, ending at one covered bulk store. There is **no reject pusher, circular conveyor, six separate discard carts, shared cross-lane recipe bridge, or buffer warehouse to buy** in this layout.

## Costed bill

Amounts include local supports/drives within each assembly. Quantities marked “lot” group components whose detailed procurement sizing is not established. Do not add a separate catalogue motor price to a complete assembly allowance a second time.

| ID | Assembly | Quantity | Unit allowance | Extended |
|---|---|---:|---:|---:|
| 01 | Kiln-cart rail/drive interface | 1 lot | €60,000 | €60,000 |
| 02 | Source unloading bridges and layer heads | 1 36-head system | €240,000 | €240,000 |
| 03 | Side-row extraction | 1 36-head system | €120,000 | €120,000 |
| 04 | Wide main loading belts | 3 belt | €30,000 | €90,000 |
| 05 | V1/V2 singulation feeders | 6 lane pair | €9,000 | €54,000 |
| 06 | Powered 90-degree turners | 6 turner | €5,000 | €30,000 |
| 07 | Inspection accumulation and tunnels | 6 tunnel | €7,000 | €42,000 |
| 08 | Basler ace2 camera bodies | 42 camera | €660 | €27,720 |
| 09 | Camera lenses | 42 lens | €180 | €7,560 |
| 10 | LED illumination modules | 84 module | €400 | €33,600 |
| 11 | Camera cabling and trigger kits | 42 kit | €100 | €4,200 |
| 12 | Industrial vision computers | 6 computer | €4,000 | €24,000 |
| 13 | Adaptive routing decks | 6 deck | €70,000 | €420,000 |
| 14 | Row/layer formers and ready-layer beds | 18 former | €8,000 | €144,000 |
| 15 | Layer transfer portals | 6 portal | €15,000 | €90,000 |
| 16 | Guided lowering pallet wells | 18 well | €6,000 | €108,000 |
| 17 | Empty-pallet feeders and short outfeeds | 18 set | €4,000 | €72,000 |
| 18 | Finished-goods yellow-frame gantry | 1 gantry | €160,000 | €160,000 |
| 19 | Autonomous pallet transport/loaders | 4 vehicle | €90,000 | €360,000 |
| 20 | Warehouse slots and bay interfaces | 1 lot | €24,000 | €24,000 |
| 21 | Common discard handling | 1 system | €110,000 | €110,000 |
| 22 | Plant PLC/motion/network cabinets | 1 lot | €60,000 | €60,000 |
| 23 | Process photoelectric devices | 96 device | €220 | €21,120 |
| 24 | Wheel/conveyor feedback encoders | 12 encoder | €500 | €6,000 |
| 25 | Motion limits and pneumatic accessories | 1 lot | €24,000 | €24,000 |
| 26 | Machine guarding and safety devices | 1 lot | €50,000 | €50,000 |
| 27 | Power/air distribution and field wiring | 1 lot | €40,000 | €40,000 |
| 28 | Mechanical/electrical installation | 1 lot | €100,000 | €100,000 |
| 29 | Engineering/software/commissioning | 1 lot | €180,000 | €180,000 |
| | **Installed base** | | | **€2,702,200** |
| | **Explicit funding reserve, 22%** | | | **€594,484** |
| | **Base plus reserve** | | | **€3,296,684** |

The base already includes €280,000 for installation, engineering, software integration and commissioning. The reserve is additional. The four-vehicle allowance includes a fleet/charging package; the PLC/cabinet allowance is separate plant control. Trucks, land, a new building, major civil works, a new electrical substation, the kiln and procurement of the two existing kiln carts are excluded. Recurring wood pallets, insurance, maintenance, operators/maintenance staff and operating energy are operating costs, not this capital bill.

## Real reference hardware and its limits

| Function | Manufacturer reference and useful published specification | How it maps to this demo |
|---|---|---|
| Layer/row axes | Güdel FP gantry family [S01]; Festo ELGC 8062793 [S02]: 1,500 mm stroke, 1.5 m/s, ±0.1 mm repeatability. ELGA family [S03] offers longer belt axes. | Mechanism references. The 36-head structure, tools, brake sizing, travel and simultaneous loads require custom selection. A bare belt axis is not a complete gantry. |
| General belt | mk GUF-P 2000 [S04]: up to 80 m/min; normal catalogue widths 50–800 mm; configuration-dependent loading. | Suitable light-feeder reference. It does **not** qualify the 2.4 m-wide main beds or the steep discard geometry; those are custom assemblies. |
| Pallet transport | Interroll PM9710 [S05]: 0.1–0.5 m/s, up to 3,000 kg per drive under its specified configurations. | Reference for full-pallet rollers, not a selected complete lift or every main belt. |
| Accumulation zones | Interroll EC5000 [S07]: 50 mm roller, 24/48 V platform. MultiControl [S08]: up to four RollerDrive zones per controller. | 48 inspection zones suggest 12 four-zone control modules as an initial topology; controller/drive prices are included in item 07, not additional. No independent motor is purchased for every rendered roller. |
| Colour + position cameras | Basler a2A2600-64ucBAS [S09]: 2600 × 2160, global shutter, USB3, hardware trigger. | 12 colour-inspection cameras and 30 position-tracking cameras. The demo uses synthetic classifications. Two matching views do not establish an independent statistical error reduction. |
| Lighting | Smart Vision Lights L300 [S12]: 24 VDC, 17 W, trigger/intensity control. | 84 reference light modules, with mechanical supports. Lens/FOV, exposure and dust/temperature protection remain selection work. |
| Presence/position | SICK WTB4-3P2162 [S17]: PNP, 10–30 VDC, 15–150 mm range, 0.5 ms response. ifm RO3100 [S18]: programmable 1–10,000 pulses/revolution and IO-Link. | 96 process photoelectric devices and 12 displacement encoders. The older SICK SKU has limited availability; procure a suitable current successor rather than promise stock. |
| Stops and guides | Festo DFM [S19]: 32 mm bore/160 mm stroke example; 482 N theoretical extension at 6 bar. | Reference for small guide/stop actuation only. This actuator is **not** a full-pallet lifting device. |
| Omnidirectional transport | Intralox Series 400 angled-roller belt [S06]: 50.8 mm pitch, minimum 152 mm belt width; application-specific engineered systems are quoted [S14]. | Commercial reference for powered directional routing. It is **not** our independently reserved 80 × 25 mm cell machine. Item 13 is a proposed custom-development allowance. |
| Full-pallet bridge | Demag KBK double-girder family [S10], published family capacity up to 3,200 kg; brick-stack grapple principle [S22]. | The yellow supported frame is retained. The approximately 38 × 33.6 m model structure is custom: the KBK page does not certify that span, frame or duty cycle. |
| Autonomous logistics | AGILOX OCF [S13]: family up to 1,500 kg, 1.4 m/s, maximum 1,600 mm lift/1,450 mm station height; configurations differ. | Four vehicles: two warehouse, two loaders. An appropriate industrial counterbalanced AMR class is intended; the pictured/reference OCF is **not an approved procurement selection** for this pallet. |
| Plant control/safety | Siemens fail-safe S7-1500 system [S16]; Troax ST20 guard panels [S20]; SEW gearmotor family [S21]. | Standard/safety PLC functions, drive isolation, emergency stops, protected access and feedback require implementation. These references do not certify a safety level for our demo. |

### Public price anchors

* **Basler camera body:** Edmund Optics Germany product 74-999 [P01] lists **€660 excl. VAT**. Budget uses 42 × €660 = €27,720; lenses and cabling are separate. This is an observed web benchmark, not a 42-unit firm quote.
* **Festo bare axis:** Rubix Netherlands [P02] search listing showed **€825.34 excl. VAT** for ELGC-TB-KF-80-1500. This cross-check excludes motor, drive, tool, frame and integration; it is **not** the price of item 03. The listing may require a fresh distributor quotation.
* **Photoelectric sensor:** BPX UK [P03] listed the old SICK 1028084 at **£189.20 excl. VAT**, with lead time on request. No currency conversion is implied. The BOM uses a separate **€220 planning allowance** for a suitable device/successor.
* No public price was verified for the complete AMR fleet, custom routing tables, industrial gantries or plant installation. Their prices are allowances, not manufacturer prices. No volume discount has been assumed.

## The important engineering boundaries

**Routing is the largest development uncertainty.** There are six approximately 16.27 × 3.8 m routing decks. The model reserves swept brick footprints in 80 × 25 mm control cells and tracks IDs/XY/yaw with five overlapping camera views per lane. This specifies simulated behaviour, not a proven actuator bill. It would be misleading to turn each drawn contact wheel/cell into a publicly priced servo or call the assembly a catalogue Intralox product. The €420,000 routing allowance includes fabricated decks, enclosures, local actuation/control and development, but a supplier feasibility test could change it substantially. The 22% reserve is a funding choice, not evidence that this risk is bounded.

**Payloads must use the actual load centre.** At the explicit planning mass of 2.2 kg/brick plus 30 kg wood, an output pallet weighs **1,262 kg**; a 40-brick layer weighs **88 kg**. The brick mass is an assumption requiring weighing, not an ACME confirmed specification. `forkOffset = 1.50 m` is the model chassis-centre-to-load offset, not an OEM fork-face load centre. The rendered mast near 0.72 m from chassis centre implies approximately **0.78 m** mast-to-load centre. Residual capacity at the real fork face, load geometry and required height must be confirmed by the vehicle supplier. A 1,500 kg headline rating alone does not establish suitability. The loader remains at ground level and raises its forks; it does not drive onto a lift platform.

**Kiln carts and discard are heavy custom interfaces.** A kiln cart contains about **63.36 tonnes of bricks** at that assumed mass, before the cart tare. The 1,200 kg Horstmann VWG example [S15] is a transfer-car principle only, not a suitable selected kiln-cart drive. Similarly, the old small 1 m³ discard-bin catalogue reference is superseded by the current covered **8,000-brick, 20 m³/20 t planning store**; do not include six little bins in the purchase list. A bulk-container/haulage interface needs selection; automatic brick sorting does not mean the bulk store can remain full indefinitely.

**Power is not energy.** The 84 reference 17 W lights imply **1.428 kW lighting nameplate only** if all are on at full power. It is not total plant demand or kWh per pallet. Motor loading/duty cycle, charging losses, compressed air and measured run time are not established; no credible complete kWh/pallet or energy bill is claimed here. Component nameplate maxima also must not be summed as measured consumption.

**Dimensions are concept geometry.** The drawing floor is 184 × 96 m; it is not a building quotation or an audited occupied footprint. Main beds are 22.3 × 2.4 m each; routing decks about 16.27 × 3.8 m each; finished-goods gantry about 38 × 33.6 m. Foundations, clearances, egress and dust/temperature provisions require detailed site design. These quantities support the demo narrative; the report does not certify physical collision freedom, plant performance or a guaranteed throughput.

## Sources

Manufacturer/distributor pages consulted for this handoff on 2026-10-28. Specifications describe product families or named references; the scope mapping above explains where the demo is custom.

- **S01** — [Güdel FP linear gantry family](https://de.gudel.com/produkte/linearachsen/fp)
- **S02** — [Festo ELGC-TB-KF-80-1500 / 8062793 datasheet](https://ftp.festo.com/public/PNEUMATIC/SOFTWARE_SERVICE/DataSheet/EN_GB/8062793.pdf)
- **S03** — [Festo ELGA-TB belt-axis family](https://ftp.festo.com/Public/PNEUMATIC/SOFTWARE_SERVICE/Documentation/2019/EN/ELGA-TB_EN.PDF)
- **S04** — [mk GUF-P 2000 belt conveyor](https://www.mk-group.com/en/products/conveyor-technology/belt-conveyors/guf-p-2000.html)
- **S05** — [Interroll PM9710 pallet conveyor datasheet](https://www.interroll.com/fileadmin/products/product_data/PM-9710/PM9710_EN.pdf)
- **S06** — [Intralox Series 400 90-degree angled roller reference](https://www.intralox.com/belt-finder/modular-plastic-belting/series-400/90-degree-angled-rollertm)
- **S07** — [Interroll EC5000 50 mm IP54 datasheet](https://www.interroll.com/fileadmin/user_upload/Downloads__PDF_/Drives___Controls/DC_Platform/EC5000_Catalog_PDF/EN/EC5000_50mm_IP54_EN.pdf)
- **S08** — [Interroll MultiControl AI](https://www.interroll.com/products/controls/multicontrol-ai)
- **S09** — [Basler a2A2600-64ucBAS technical documentation](https://docs.baslerweb.com/a2a2600-64ucbas)
- **S10** — [Demag KBK double-girder suspension crane family](https://www.demagcranes.com/en-au/products/cranes/kbk-light-crane-system/kbk-double-girder-suspension-cranes)
- **S11** — [LINGL Triangle Brick factory/dehacking precedent](https://lingl.com/wp-content/uploads/2018/03/Triangle_Brick_englisch.pdf)
- **S12** — [Smart Vision Lights L300 datasheet](https://smartvisionlights.com/wp-content/uploads/L300_Datasheet-1.pdf)
- **S13** — [AGILOX OCF manufacturer datasheet](https://www.agilox.net/media/agilox-ocf-datasheet-en.pdf)
- **S14** — [Intralox engineered-system quotation request](https://www.intralox.com/request-a-quote)
- **S15** — [Horstmann VWG transfer-car reference](https://www.horstmann-anlagentechnik.de/project/transfer-car/?lang=en)
- **S16** — [Siemens fail-safe SIMATIC S7-1500 system documentation](https://docs.tia.siemens.cloud/r/simatic_s7_1500_et_200mp_manual_collection_enus_20/basic-information/automation-system/system-overview/configuration/configuration-of-a-fail-safe-system-with-simatic-s7-1500)
- **S17** — [SICK WTB4-3P2162 manufacturer datasheet](https://www.sick.com/media/pdf/2/92/992/dataSheet_WTB4-3P2162_1028084_es.pdf)
- **S18** — [ifm RO3100 encoder](https://www.ifm.com/us/en/product/RO3100)
- **S19** — [Festo DFM-32-160-P-A-KF guided actuator](https://ftp.festo.com/Public/PNEUMATIC/SOFTWARE_SERVICE/Datasheet/EN_US/170937.pdf)
- **S20** — [Troax ST20 mesh guard panel](https://www.troax.com/product/panel-st20/?term_id=3786)
- **S21** — [SEW-EURODRIVE R helical gearmotor family](https://download.sew-eurodrive.com/download/html/33346739/en-EN/39593815307.html)
- **S22** — [Kinshofer brick-stack grapple principle](https://www.kinshofer.com/us/crane/general-construction/brick-stack-grapples)
- **P01** — [Edmund Optics Germany Basler camera price](https://www.edmundoptics.de/p/basler-ace2-a2a2600-64ucbas-color-usb3-basic-camera/56227/)
- **P02** — [Rubix Netherlands Festo bare-axis price](https://nl.rubix.com/nl/tandriemas/p-G2010175193)
- **P03** — [BPX UK SICK price/availability reference](https://www.bpx.co.uk/store/product/1028084)

## Team usage

Use **“€2.7M installed concept budget; €3.3M funding allowance including reserve”** as the short cost statement. Keep actual simulated bricks/hour and pallets/hour separate: the BOM does not recalculate them and the linked datasheets do not validate the complete line. Before procurement, obtain quotations for the custom routing surface, long-span gantry and load-rated AMRs first; these are the largest unresolved price/feasibility items.
