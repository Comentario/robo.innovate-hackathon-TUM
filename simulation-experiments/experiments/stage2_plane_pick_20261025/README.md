# One position-controlled native extraction baseline

This is one simulation-only I trial after the private closing diagnosis and
retrospective screen comparison. It performs rendered RGB-D selection, approach,
position-controlled closing, a straight 5 mm lift and a 30-step hold. No transfer,
placement, color integration, RL, tilt primitive or reserved H execution occurs.

The new online contact screen remains UNVERIFIED. It retains the old grip-plane,
normal, rendered spatial and forbidden metal/head distance predicates, removing
only finite BODY-surface necessity. The old predicate is still logged as a
reference and is not relabelled as passing. Native collider/brick identities are
private evaluation inputs, never task-control inputs or point exemptions.

The endpoint is a **nominal commanded custom-pad gap of 14 mm in this model**.
It is derived from actual USD prismatic axes, composed inner planes, initial
joint/pose data and asset limits. It does not claim equivalence to Franka Desk's
14 mm setting, achieved opening under contact, or measured pad compression.
Closing ramps at the unchanged 1 mm/s per finger. On the third fresh sample with
both pads at least 1.5 N, the last commanded q is frozen before the lift. If the
endpoint arrives first, at most 30 completed endpoint commands may establish the
same confirmation; otherwise the trial abstains without lifting. Existing 2 N
sampled force aborts, motion limits and the 4 mm finger-travel limit remain.

Startup must explicitly bridge to the accepted 1808 stationary control and 1815
diagnosis: exact physical settings, initial q, model/cook, contact processing and
filter identity. The old control is reused evidence, not a newly run control or
a claim that its control-mode cameras equal active RGB-D selection. New passive
readers and the compatibility screen do not modify stationary physics. Failure
of this bridge stops before the task trajectory.

Independent evaluation retains actual native extraction requirements: every
loaded finger contact must map to BODY on the prebound selected source, with
matching source/finger reciprocal events; no metal/head/foreign finger load is
accepted. Source-to-support LEGO contacts during separation are recorded and
mapped separately. Observed source-to-other robot bodies are not treated as
support contacts. Only target-incident native edges may break; the target must
become a singleton, rise at least 4 mm and retain its TCP-relative transform
within 1 mm/3 degrees through the final hold. Force, motion, collateral, settings
and provenance checks remain strict. No teleport or synthetic attachment is used.

Online held identity remains UNKNOWN, so even an independently passing native
extraction does not authorize transfer. H is reserved and untested; it requires
its own control and resource decision. This I development trial alone is not
repeatability or generalization evidence.

The prospective aggregate ceiling changes from 1800 to 2200 seconds while
retaining all 1668.905245381 prior seconds and every failure. Exactly one I job
may use at most 360 seconds including capture and independent audit. There is no
automatic retry, fresh improvement pool, H trial or broader scope authorization.

After final source/control-bridge review and a clean committed experiment:

```bash
python3 experiments/stage2_plane_pick_20261025/submit.py
```

The submitter reuses immutable 1815 source plus the frozen 1817 pure screen,
records all code/configuration hashes, and submits a foreground default-Pueue
job. Runtime and dependencies are reused without shared environment changes.
