# Startup material/contact-offset readback

The closed free-coupon trials1821/1822 fail retention despite simple14mm closure.
This one readback inspects configuration before another physical hypothesis.
It reuses the exact1822 initializer and replaces only its postassembly hook.
Existing reset, one explicit preassembly physics step and targeted mass/inertia
restoration remain disclosed. The original trial loop is never called; no extra
physics steps, closure, lift, material/offset setters or task changes occur.

Public runtime getters read three exact count1 body views: left finger, right
finger and free coupon. Every material triple, contact offset and rest offset is
saved with shape/dtype/status/errors. USD collider/material/binding/combine/offset
opinions are listed separately. No public tensor-row-to-collider mapping is
available here. Rows remain UNKNOWN by component; neither traversal order nor an
expected friction value identifies the PAD row. Uniform values across all
returned slots may be described without assigning a component index.

Runtime material values are not a measured friction coefficient for the contact
pair or proof of a retention cause. Missing/invalid getters remain UNKNOWN;
diagnostic completion and valid effective arrays are separate results. No grasp,
extraction, trajectory adjustment or retry follows automatically.

ONE default-queue startup/audit job, ≤90s, retaining2388.038652171/2500s prior
cost. Capture cap75s, JSON audit cap8s. Full source/API/reference hashes are pinned;
all three bodies, source301/930 and isolated coupon1/0 are checked before/after.
Existing `unitree_sim_env`/Isaac5.1/BrickSim is reused without dependency changes.

After final independent source review and commit:

```bash
python3 experiments/stage2_contact_readback_20261025/submit.py
```

## Result — Pueue1823

Source `11b7de7`; snapshot `runs/20261025T161523.798508Z-stage2-contact-readback`.
All60 contract checks and all9 runtime getter arrays pass. There are zero
measured steps/state changes; initialization and source/coupon graphs match1822.

| Exact body view | Returned shape slots | Runtime material triples: static/dynamic/restitution | Every returned contact/rest offset |
| --- | ---: | --- | --- |
| Left finger | 5 | four[0.5,0.5,0], one[2.5,2.0,0]; unordered | 1.3625mm /0 |
| Right finger | 5 | four[0.5,0.5,0], one[2.5,2.0,0]; unordered | 1.3625mm /0 |
| Coupon | 2 | both[0.5,0.5,0] | 1.3625mm /0 |

The coupon USD Body/Top collider-authored scalar attributes differ from these
uniform runtime values, and neither collider has a bound physics material. Do
not treat authored scalars as proof of runtime material assignment. The unique
high-friction finger slot is consistent with the pad binding but remains
unmapped to BODY; no index assignment or pair-traction claim follows.

The two returned offsets sum to2.725mm, comparable to the3.083mm nominal band.
This is not measured penetration, consumed band, stand-off or a retention cause.
PhysX defines contact generation using the offset sum and resting separation
using the rest-offset sum; these are different quantities ([primary contract](https://nvidia-omniverse.github.io/PhysX/physx/5.1.2/docs/AdvancedCollisionDetection.html)).
One future engineering hypothesis is a fixed100µm offset on only the exact BODY
collider paths, with every other property and guard unchanged. With the coupon
unchanged, the pair distance would remain about1.4625mm, not100µm. No such change
or trial was made or authorized by this readback.

Independent evaluator/reviewer accept this configuration evidence. Full Pueue
15.679833137s is charged, giving2403.718485308/2500s retained;96.2815s remains.
No retry or physical success. Detailed raw arrays/USD inventory remain in the
snapshot; machine-readable outcome/provenance is `results.json`.
