# Concept 1: autonomous greenfield installation

This proposal addresses the shortage of staff for physically demanding, repetitive work. It does
not model a human inspection station. The earlier prototype stays intact in `plant_sim` and
`artifacts/plant_automation_01`; its starting point is commit `86b820d`.

## Open and reproduce

From the repository root:

```bash
python3 scripts/greenfield_demo.py --compare --output-dir artifacts/greenfield_02
```

Open `artifacts/greenfield_02/index.html`. It works offline, with no server and no remote GPU.
`comparison.html` compares scenarios; each one has its own 3D playback. A run never overwrites an
existing folder: choose another name when repeating it.

Dependency already used by the prototype:
`python3 -m pip install --target .deps/plant_sim -r plant_sim/requirements.txt`.

Tests:

```bash
PYTHONPATH=.deps/plant_sim:. python3 -m unittest discover -s tests_greenfield -v
```

## The architecture, concretely

1. **Automatic dock:** receives a stack of 800 bricks, 10x4x20. The physical demonstration has two
   input positions, 1,600 pieces; the 36 stacks of a kiln cart are context from the challenge, not a
   complete geometry validated in this scene.
2. **Layer retention gantry:** removes a layer of 40 and carries it to one of the free trays. The
   industrial retention mechanism and gripper, and their load validation, are still open; we do not
   assume that the LEGO gripper works for real bricks.
3. **Row distributor:** separates the front row first, without passing through the remaining ones. It
   feeds two cells per distributor. A cell isolated before start-up receives no material.
4. **Each cell** doses pieces and has eight exclusive inspection zones, a camera with controlled
   lighting, and a divert path. Color and quality identification is synthetic in this study; it does
   not run perception on rendered images and does not modify task 1's module.
5. **Uncertain decision:** a second automatic exposure, once only. If the doubt persists, automatic
   quarantine. An observed defect means rejection. None of these paths waits for a human
   classification.
6. **Approved bricks:** three accumulation conveyors, one per accepted shade, with 20 physical zones
   of 0.30 m each. The next zone is reserved before moving. If the entry is occupied, an automatic
   reservation of up to 50 pockets per cell is used. Recovery reserves a zone before the return; the
   divert avoids waiting for that same zone while holding the mechanism the recovery needs
   (circular interlock). Deposit and recovery share the transfer mechanism: there are no fictitious
   simultaneous manipulations. Lack of space produces back pressure, without discarding approved
   material.
7. **Mechanical shade selector and row former:** reserves enough inventory for a complete layer with
   a 13/13/14 recipe, varying which shade gets the extra piece. It alternates neighboring shades and
   checks that no monochrome rows or columns exist. Finished rows are pushed into a layer nest.
   There is no robot doing one pick-and-place cycle per good piece.
8. **Shared gantry, centering guides and guided well:** deposits a layer, checks the position and
   lowers the support by 69 mm. The next layer arrives at the same plane; the earlier layers and the
   pallet physically descend together. After 14 layers it verifies quantities, product and vertical
   distribution, and releases 560 pieces. The conveyor advances the already finished pallets before
   unloading the next one; it does not pass through them. The guide panels rise and confirm their end
   stop before unloading the pallet and feeding the empty one; they close before stacking resumes.

The shades `Warm`, `Copper`, `Russet` and the recipe in thirds are illustrative team hypotheses for
**acceptable** shades of a single product. Dark does not automatically mean defective. Belonging to
the accepted quality depends on the product. Brands and SKUs are not mixed to fill quotas. Approved
leftovers and partial pallets are kept between batches; no unlimited replacement supply is invented.

## Automation and failures

SimPy owns the resources and the clock. Three.js replays the same positions and trajectories by ID,
with no independent visual copies. Virtual photoelectric sensors trigger on geometric presence. The
panel shows station events, travel, speed, time and progress. Grasp and end-stop confirmations are
assumed virtual signals; there is one case of a missing critical confirmation that inhibits motion.
There is no PLC and no connected hardware.

The reference run includes a jam at a known position, with limited retreat and return confirmation,
and an 8 mm centering error, corrected automatically. A 20 mm error or a missing critical
confirmation leads to `SAFE HOLD` and preserves the material. We do not promise autonomous recovery
from any mechanical failure; maintenance and repair stay outside the nominal production flow.

## Why it takes that long

Every movement uses `max(|dx|, |dy|, |dz|) / speed`: coordinated axes, with the duration set by the
limiting axis. Exposure, inference, confirmations, grasping and release are added on top. These are
engineering speeds and assumed, configurable times, not measured cycles. Buffer blocking, the
availability of the shared gantry, inventory mixing and failures all affect the final time. No
further 85 % availability factor is applied on top of the explicit failures.

The new architecture is a verifiable candidate, **not a demonstrated optimum**. Two and four cells use
the same material and the same per-ID decisions. The comparison includes high uncertainty, high
rejection, an isolated cell, an alignment failure and a missing confirmation. Stopped runs are
censored and are not compared as sustained capacity.

## KPIs that can actually be defended

- **Released conforming product:** conforming pieces on complete, physically unloaded pallets
  x3,600 / total time. It includes filling and emptying the batch.
- **Conforming material formed:** adds the partial pallet. It is not equivalent to delivered product.
- Complete pallets, partial material, rejection, quarantine and retained stock and WIP, with a
  balance by identity.
- Recipe compliance per layer, monochrome rows and columns, and vertical columns per pallet.
- Reinspections and recoveries that were actually confirmed.
- Duration of movements and scheduled waits per station. Their sums can exceed the total time when
  several pieces move in parallel; they are not automatically utilization percentages.

Real conformity is known only because the synthetic generator has ground truth. That truth is used to
evaluate, **never to prevent a false acceptance**. A scenario with classification errors can form
incorrect product: the model has to show it. The default error rates are ideal assumptions and need
task 1's measurements to estimate a real plant.

The configurable goal is 3,000 conforming pieces per hour; the simulation may fall below it. The clock
is not adjusted to reach it. There is no measured manual baseline, no quoted CAPEX and no
demonstrated saving or ROI. The mentor's staffing estimates are context for the demand for
automation, not jobs whose removal is guaranteed.

## References and limits

URLs, values and scope ship with every report in `catalog.json` and `run.json`, and are visible under
**Engineering basis**:

- [Gudel FP](https://www.gudel.com/products/linearaxis/fp): FP-4 profile, 2,000 N and 75 m/min. Do not
  combine with the light profile's speed. We select 1 m/s and a layer load of 40x1.8 + 30 = 102 kg.
  This is an axis reference; EOAT, the vertical axis, dynamics and the complete configuration need
  validation.
- [mk GUF-P 2000](https://www.mk-group.com/en/products/conveyor-technology/belt-conveyors/guf-p-2000.html):
  up to 125 kg and 80 m/min, depending on the variant. Each selected buffer is 6 m, 36 kg and 0.35 m/s.
- [Interroll PM9710](https://www.interroll.com/fileadmin/products/product_data/PM-9710/PM9710_EN.pdf):
  1,250 kg/m, 3,000 kg per drive and 0.1-0.5 m/s. Assumed stack: 1,465 kg including an assumed 25 kg
  pallet; a 1.2 m support distribution is still to be verified. Published temperature +5 to 45 C:
  confirm the real product and environment temperature before selecting equipment for a kiln exit.
- [Basler a2A2600-64ucBAS](https://docs.baslerweb.com/a2a2600-64ucbas): color, global shutter,
  triggered camera; its frame rate does not demonstrate classification accuracy.
- [SICK WTB4C](https://www.sick.com/media/docs/7/97/097/operating_instructions_wtb4c_3pxxx_axx_de_en_fr_pt_es_it_ja_zh_ru_im0070097.pdf):
  0.5 ms response as a presence reference; it is not a safety sensor.
- [LINGL/Triangle Brick](https://lingl.com/wp-content/uploads/2018/03/Triangle_Brick_englisch.pdf):
  industrial reference for blending, row formers and descending frames. It is not a datasheet for this
  scene's custom selector.

External dimensions and quantities: the organizer's material, 245x67x69 mm, 800 in and 560 out.
**Provisional orientation:** 10 short edges across and 4 long edges in depth, footprint 0.67x0.98 m. Do
not infer the orientation from the number 10x4 alone. Mass **assumed at 1.8 kg**, not a confirmed ACME
SKU; a datasheet from [US Brick King](https://usbrick.com/wp-content/uploads/2025/05/USBrick-TechSpecs-1.pdf)
serves only as a comparator, not as ACME certification.

We audit trajectory continuity, exclusivity by ID, derived times, pallets without repeated IDs, and
mixing. Brick envelopes are checked on a sample of positions; this is **not a continuous proof that no
collision occurs**, it does not include tools or cables, and it does not validate contact, friction,
tipping, retention or structural integrity. The guide aligns a rigid load: it does not deform fired
bricks and does not assume their irregularities disappear. The next step towards industrialization is
to validate grasping, tolerances, temperature, dust and timings with the integrator.

## Evidence for this version

Fifteen tests of the concept cover balances, identity, rigid layer transfer, guides opened before
unloading and feeding pallets, the 69 mm descent, mixing, classification errors, quarantine and
failures. The earlier core keeps its 89 tests. The scene is checked offline in Edge, with 1,600 IDs,
mixing and stacking views, and a movable width. The run report is regenerable and the bulky artifacts
are not included in git.

The four-cell reference falls below the goal of 3,000 conforming pieces per hour. The activity of the
shared divert and reservation mechanism shows a concrete constraint that has to be investigated:
deposits and recoveries consume vertical travel and cannot run at the same time. Optimizing that
mechanism or redistributing stock between cells needs another scenario and hardware validation;
raising the graphical playback speed is not enough.

One important observation: the scenario with the most uncertainty can show a higher rate of pallets
released per hour in this batch because it sends more pieces to quarantine and reduces later work.
That **does not demonstrate a process improvement**: material yield and residual inventory change.
Always compare rejection, quarantine, formed material and retained stock together with throughput.

### Reproduced result (seed 8)

Reference: 3,014.86 s; 1,600 inspected; 1,120 released on two pallets; 120 on a partial pallet; 176
rejected; 6 in quarantine and 178 in stock and WIP. Two confirmed recoveries. The envelope sampling
found no intersections at 130 instants; that is not equivalent to validating continuous collisions or
tools.

| Scenario | State | Conforming released/h |
|---|---|---:|
| Autonomous reference | completed_with_residual_stock | 1337.38 |
| Two-cell alternative | completed_with_residual_stock | 779.52 |
| One cell isolated before dispatch | completed_with_residual_stock | 1107.77 |
| More uncertain observations | completed_with_residual_stock | 1702.76 |
| High rejection | completed_with_residual_stock | 781.22 |
| Alignment outside recovery range | safe_hold | Not comparable: censored |
| Missing source confirmation | safe_hold | Not comparable: censored |
