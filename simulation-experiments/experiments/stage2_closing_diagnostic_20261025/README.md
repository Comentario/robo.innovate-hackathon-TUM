# Closing-only contact diagnosis

This experiment performs one additional physical approach/closing execution in
simulation to explain the failed finite-surface contact check from job 1809.
It does not attempt lift, hold, extraction, transfer or placement. Old results
and the existing cumulative 1800-second contact budget are retained.

The 1809 scene, pregrasp joint configuration, rendered RGB-D target selection,
controller, geometry and original contact/motion guards are frozen. A read-only
native observer, validated in 1814, records contact headers privately. Its shape
and partner identities never select a target, qualify a contact or override an
online check. No source pose or identity is supplied to task control.

The execution records the earliest original abort or diagnostic limit, including
simultaneous reasons: either finger reaching 0.1 N sampled SUMABS normal load,
400 closing steps, 1800 total steps, or the wall budget. Lift/hold transitions are
removed. The stationary native-source watchdog retains all 301 source parts and
930 links, with no target exemption.

The independent audit matches every loaded point from both finger streams and
the selected source's reciprocal stream to fresh native contact reports. It
uses the unchanged 1814 matching rules, including the fixed actor-order sign.
Ambiguous, missing or unmatched data stays UNKNOWN. Only a uniquely matched
current-run bad point can receive a component label. If the failure does not
recur, report NOT_REPRODUCED. Nothing retrospectively attributes the 1809 point.

`observation_complete` is separate from physical contact acceptance and the
manipulation proceed gate, which remains false. A finite-surface-only description
must also exclude metal/head ambiguity and retain normal, flat-face and spatial
association evidence. RIGHT correspondence is checked from current observations;
the earlier unloaded RIGHT control is not positive validation.

After independent source review and a clean committed snapshot:

```bash
python3 experiments/stage2_closing_diagnostic_20261025/submit.py
```

The submitter copies immutable 1809 source/configuration and exact 1814 reporting
helpers, then submits one foreground default-queue Pueue job. Capture plus audit
is bounded to 240 seconds above the retained 1508.745346232-second prior cost.
No automatic retry, dependency installation or shared environment change occurs.
The snapshot records source hashes, commands, prior clock and job submission.

The operator reports that a 14 mm Franka Desk close command worked. This supports
a simple position-command baseline; requested width, stock-joint width and actual
custom-pad gap remain distinct until the mapping is checked. The user report is
preserved in `hardware_closure_reference.json`. It changes no parameter in this
unchanged diagnostic, which already uses position targets.
