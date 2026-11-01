# Greenfield 37 — Performance Measurement Method

Performance was calculated by running the functional plant model without rendering graphics. The model records simulated completion times and counts complete pallets; throughput is an output of scheduling, rather than a preset target.

## Fixed input

Two kiln carts repeat the same colour/quality distribution, with distinct brick IDs:

| Input class | Bricks | Share |
| --- | ---: | ---: |
| Approved: Warm, Copper and Russet | 50,664 | 87.96% |
| Rejected: dark and pale extremes | 6,936 | 12.04% |
| Total | 57,600 | 100% |

Quality labels are predefined. These runs evaluate material handling and production flow, not real-camera classification accuracy.

## Execution and counting

The model runs dehacking, row extraction, brick separation, inspection, rejection, routing, layer formation, palletizing, storage and dispatch. Configured motion/process times, resource availability and space-time reservations determine movement and waiting. Playback speed does not change simulated production time.

Only complete pallets count toward factory output. Each contains **10 × 4 × 14 = 560 approved bricks**. The current run completes 84 pallets, with material conserved:

**57,600 input = 47,040 bricks in complete pallets + 3,624 approved bricks in unfinished work + 6,936 rejects.**

## Hourly calculation

The factory comparison window ends at the later of the last complete pallet and the last inspection:

```text
T = max(last complete pallet time, last inspection time)
Bricks/h = complete pallets × 560 × 3,600 / T_seconds
Pallets/h = complete pallets × 3,600 / T_seconds

Current run:
T = 21,117.713792 seconds
84 × 560 × 3,600 / T = 8,019.05 conforming bricks/h
84 × 3,600 / T       = 14.32 complete pallets/h
```

These are normalized finite-batch averages, including startup and batch completion, rather than steady-state measurements.

## Order scenarios

Each calculation keeps the same input, hardware and motion parameters; only requested pallet recipes change. Scenario calculations do not require separate visual demos.

| Requested products | Complete pallets | Conforming bricks/h | Pallets/h |
| --- | ---: | ---: | ---: |
| All Mixed | 88 | 9,137.10 | 16.32 |
| Current: Mixed + all three pure shades | 84 | 8,019.05 | 14.32 |
| All pure, distributed across three shades | 83 | 7,670.93 | 13.70 |

Mixed pallets prohibit runs of three equal neighbouring shades along a grid axis; they do not require exact one-third proportions. Pure pallets contain one accepted shade. The two-Mixed/one-Warm-per-line scenario blocked in the current allocator and is excluded from valid capacity claims.

## Production versus dispatch

The current run produces **84 pallets**, ships **64** on eight complete customer orders, and retains **20** in inventory. Shipment rate uses the full replay duration, including logistics drain: **64 × 3,600 / 23,675.656923 = 9.73 shipped pallets/h**. It is a separate metric from factory production rate.

## Verification and scope

Checks cover material conservation, unique IDs, identical input distributions, product mixing/purity, order correctness and modeled movement separation. Results depend on the input distribution, requested products and configured equipment/control parameters. They are kinematic/event-model estimates, not physically validated industrial capacity or supplier guarantees.

Evidence: `task3_checkpoint/greenfield_37/capacity-layout37.json`, `capacity-layout37.txt`, `handoff_verification.json` and `layout_validation/`. Backend fingerprint: `dae71e17e51973bc`.
