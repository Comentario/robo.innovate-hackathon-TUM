# Executive presentation — revision 26

Open `artifacts/greenfield_26/index.html`. This is an interactive concept presentation, not the final pitch video.

## Production is preserved

**Estimated bricks/h stays at 3,889. Formed output stays at 4,166/h.** No production resource, trajectory, speed, timing or KPI has changed; the copied `run.json` has the same SHA-256 as revision 20.

The existing full-pallet metric is:

`2,240 conforming shipped bricks / 2,073.7157979 batch seconds × 3,600 = 3,888.6717303 bricks/h`.

Formed output uses 2,400 placed conforming bricks, including 160 on the incomplete pallet. These are separate output measures, not alternative labels for the same quantity. The 3,200 inspected limit is four demo input stacks × 800 bricks; it is not line capacity. A full organizer kiln cart is 36 × 800 = 28,800 bricks.

A full hour of simulation is not required to express a normalized hourly equivalent. This does not make the result a steady-state or commissioned one-hour capacity. Start-up and batch drain are included in the denominator. The production metric card opens the calculation directly.

## Presentation changes

- Dark executive visual language, four interactive headline metrics and a less cluttered replay.
- Removed the 5,000/h target and historical capacity-study panels from the primary view. The original configuration remains unchanged in historical production evidence.
- Primary metrics: Estimated bricks/h, preliminary investment, electricity per 1,000 shipped bricks, and current equipment envelope.
- Equipment click opens an image-led impact card: function, real reference image, planning allowance and assembly context. Published specifications, modeled settings, source links and integration gaps remain under **Technical evidence**.
- **Locate in the line** moves the view smoothly to the selected assembly.
- **Engineering view** restores deeper evidence and traceability. Labels start off, and the batch sidebar explicitly identifies the finite 4 × 800 replay. Clock uses minutes/seconds.
- Desktop and 390 px mobile layouts checked without horizontal overflow.

## Cost: scenario, not quotation

Current preliminary investment range: **USD 1,494,500–3,705,620** including a 25–45% integration/installation allowance applied after equipment costs. Rounded display: **$1.49–3.71M**.

`config/presentation_scenario.json` contains the unit-cost ranges, count bases, power ranges and exclusions. The budget covers the shared stack bridge, four layer gantries, receiving nests, transverse slides, eight loops and their branches/diverters, 64 inspection roller zones, 100 additional collector roller zones, 24 pusher assemblies, row decks, two guided lowering systems, pallet logistics, 16 camera kits, 16 lights, 188 drawn photoeyes, controls, bins and utilities reserve. Controller provisioning is 16 for inspection plus 13 per 50-zone collector, 42 total; collector wiring/design is not yet qualified.

These are engineering allowances, not current manufacturer quotations or a completed procurement BOM. A component's planning allowance is labeled by the budget assembly it belongs to; it must not be summed again across all selectable subcomponents.

Public market anchors are shown separately from those allowances:

- [Motion — Festo 8062793](https://www.motion.com/products/sku/11523397): USD 2,022.83 advertised bare-axis list price; motor, drive, tooling and integration are additional.
- [Teknihaus — SICK 1028084](https://www.teknihaus.com/1028084): USD 316.80 advertised sensor price.
- [NexInstrument — SICK WTB4-3P2162](https://www.nexinstrument.com/wtb4-3p2162): USD 345.00 advertised sensor price.

Price snapshots were checked during the source review; availability, taxes and negotiated prices may differ. Buildings, land, civil works/foundations, taxes/freight/import duties, kiln energy, maintenance, staffing and financing are excluded. No ROI or headcount-reduction claim is made.

## Energy: configurable power/utilization scenario

Current scenario: **6.924–13.085 kWh per 1,000 conforming shipped bricks**, corresponding to approximately 26.93–50.89 kW average during this finite batch. The browser exposes the exact per-item calculations.

`average kW = count × assumed per-unit power × utilization / assumed conversion efficiency`

`batch kWh = average kW × batch seconds / 3,600`

`kWh/1,000 = batch kWh / 2,240 shipped conforming bricks × 1,000`.

Pusher, transverse-slide and layer-gantry utilization use recorded command-time proxies. Other utilization fractions, motor power ranges, the 85% drive-conversion factor and air/auxiliary reserve are assumptions. Electronics and lights are treated as direct electrical inputs. The [L300 official datasheet](https://smartvisionlights.com/wp-content/uploads/L300_Datasheet-1.pdf) supplies the 17 W maximum light rating; this does not qualify the complete plant's energy consumption.

At the default **USD 0.10/kWh planning tariff**, electricity-only cost is approximately **USD 0.69–1.31 per 1,000 shipped bricks**. Editing the tariff updates electricity cost only; it cannot change production rate, hardware counts or budget. The [EIA May 2026 report, table 5.6.A](https://www.eia.gov/electricity/monthly/current_month/may2026.pdf) gives a March 2026 Texas industrial benchmark of USD 0.0626/kWh; it is not ACME's contract or the selected planning tariff.

This is not metered consumption, a motor-torque model, or a compressed-air sizing study. Demand charges and upstream kiln energy are excluded.

## Space

The visible equipment envelope measured at nine playback times is approximately **59.2 × 35.04 m = 2,074.37 m²**, with maximum scene height 6.45 m above ground. Ground slab, grid and UI are excluded; boundary rails and animated output travel are included. The original measurement and bounds are in `config/presentation_envelope.json`.

It is a sampled scene envelope, not a continuous swept-volume proof, an installation drawing or required factory building size. Service access, protective distances, foundations, utilities and exits need additional site planning.

## Verification and maintenance

Four presentation accounting tests pass. All 289 equipment cards were opened, their images decoded, and technical source text remained available. Browser checks confirm no runtime error, Estimated bricks/h unchanged by tariff edits, the target absent from the primary view, and no mobile horizontal overflow. Evidence and screenshots are under `artifacts/greenfield_26/verification/`.

Production remains read-only. `greenfield/presentation.py` computes the independent presentation layer from recorded production plus the two scenario configuration files. Existing manufacturer-reference limits remain visible; in particular, the reference curved conveyor does not validate the assumed 1.5 m/s loop speed.

```bash
python3 scripts/greenfield_refresh_view.py artifacts/greenfield_20_checked --output-dir artifacts/my_executive_view
PYTHONPATH=.deps/plant_sim python3 -m unittest discover -s tests_greenfield -p test_presentation.py -v
```
