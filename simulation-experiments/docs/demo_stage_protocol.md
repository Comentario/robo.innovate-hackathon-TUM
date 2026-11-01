# Revisable Challenge 2 demo protocol

This supplements the six-stage simulation goal. It does not promote any
unmeasured candidate parameter to a validated method. The measured state is in
[demo_progress.md](demo_progress.md). Ordinary top-view candidates and the saved
RGB color benchmark have limited passing evidence; dynamic native extraction
still fails. The sensor-selected 14 mm position candidate loses qualified contact
during lift (job 1819). The subsequent free-brick fixture comparison is closed
after three improvement rounds: position-only dwell (1822), BODY contact-margin
sensitivity (1824), and the prospective fixed-target finger-response criterion
(1825). The final trial is no longer speed-censored, but fails relative retention
before completing lift/hold. See the [recorded result](../experiments/stage2_finger_response_20261025/results.json).
The simulated nominal pad gap and gripping depth are not calibrated equivalents
of the operator's successful Desk 14 mm grasp. Reconcile that mapping before
further contact experiments; no fourth fixture parameter variant follows.
Sparse remnants, held identity, transfer, native insertion and repeated sorting
are unproven. Existing PGS idle/contact evidence
is a prerequisite, not a completed manipulation result. Extra compute does not
establish physical-model correctness.

## Experiment discipline

Before executing a stage, freeze its cases, configuration, numeric motion/contact
limits, completion/failure rules, metrics, resource budget and reserved subset.
Use a baseline and at most **three reviewed improvement rounds**; each round
changes one observed-failure mechanism. Reassess at the limit, or earlier if the
method needs broader work. Renaming a camera/benchmark does not reset the count.
Log bounded diagnostic runs separately, with a predeclared run/step/time budget;
they are not unlimited free attempts. Preserve regressions, retries, misses and
uncertainty. Reserved observations cannot drive changes within the same round.

For accounting, Stage 1 already used two substantive changes (workspace filter,
closer views). The initial Stage 2 idle benchmark used all three improvement
rounds: coupled
numerical epsilon and source velocity iterations 4→16 failed; the source-supported
TGS→PGS workaround passed its frozen fixture, full300 and reserved-removal checks.
That configuration benchmark is closed; no fourth physics-configuration round.
Native logging/offline audits are diagnostics, not additional claimed improvements.
Each new experiment still needs its frozen budget and independent review.
The separate contact-feedback benchmark used two adapter corrections (actual
Cube geometry, then signed force coefficients); stock-pad positive contact/reopen
passes. Its final supplied-tip proxy round failed the cooked vertex/plane
consistency guard before contact (1756). All three contact rounds are closed;
no fourth contact tuning, recook or tolerance change follows. The subsequent
exposed-tip approach passes centered/reserved lateral contact diagnostics 1791/1794, but its global distal geometry gate remains failed. Latest
position-candidate extraction 1819 fails. These bounded results do not authorize
further proxy fitting or a hidden reset of any closed improvement budget.

## LEGO color classification and observation timing

User correction (2026-10-25): Challenge 1 concerns different, industrial bricks.
Its classifier is not a dependency of this LEGO demo. We must classify the LEGO
colors locally from RGB; historical Challenge 1 mock fixtures remain interface
tests, not an implemented LEGO color classifier.

**Recommended primary timing: the existing segmentation view before grasp.**
It already associates a visible region with the selected frame/candidate, avoids
covering it with the fingers, and adds no inspection motion or held-object
segmentation dependency. Job 1806 now provides limited evidence from saved
rendered images for this timing; runtime pick integration and physical image
accuracy remain unproven. R3 polygons are footprint hypotheses, not certified
masks: use
a supported interior, exclude neighboring surfaces and unreliable pixels, and
abstain if the region mixes bricks, glare or shadow. Distinguishing shades also
requires controlled exposure/white balance and representative color references;
hue alone does not establish the required shade distinction.

The C920 held view is an optional confirmation or fallback. It can isolate one
brick, but its framing, occlusion, pixel scale and close-range sharpness remain
unverified. The visual housing model and a sharp ideal render do not verify
physical focus. Do not make the main sorting path depend on that view until a
small visibility comparison shows usable, associated color regions.

Use a compact comparison covering the required shades in the segmentation view
and a few matched C920 held examples when available, with a whole brick or
lighting condition reserved from implementation choices. Existing captures are
preferred. Record color-region coverage, glare/shadow, blur, scale and identity
ambiguity; freeze any numeric quality screens before scoring. A manually
initialized held fixture tests visibility only and is not grasp evidence.

Store the color result with the exact observation and selected candidate. A
source color label describes that source brick; it does not prove that the
robot subsequently holds it. Preserve the transaction through grasp verification
and invalidate it on slip, regrasp or stale association. Missing/ambiguous results
abstain. Allow at most two captures per attempted brick. No simulator object
colors, quality labels or IDs may supply online classification results.

## Extraction and contact prerequisites

The operator's successful Desk 14 mm closure supports a simple position
primitive. The current composed custom-pad model instead uses
`gap = q_left + q_right + 2.813389 mm`: commanding a nominal 14 mm custom-pad gap
means a joint sum of 11.186611 mm. A 14 mm joint sum would give a nominal
16.813389 mm custom-pad gap, opening this model further. These are source-derived
relations, not a firmware-to-physical calibration. See the
[separate operator/model reference](../experiments/stage2_closing_diagnostic_20261025/hardware_closure_reference.json).
The missing evidence is the requested versus measured width and actual gripping
depth of the successful hardware grasp. Historical open-gripper and brick-top
photos do not establish these quantities. No replacement width, deeper insertion,
or new retention trial is selected from this comparison alone.

First pass the full-source native idle gate. Register the supplied tip model's
collision representation and material separately from its current visual fit.
Verify contact sensing and units before relying on force limits; width/closure
alone is not proof of a grasp. Native component truth remains evaluator-only.

In a small frozen contact benchmark, estimate and check `T_TCP_brick`, the held
brick's pose relative to the gripper/TCP. Log grasp depth, finger opening,
relative slip and swept finger clearance using the actual pad geometry. Do not
assume stock TCP offsets still describe the changed pads. A candidate can be
visually exposed yet physically inaccessible.

The earlier **25° tilt and 5 mm withdrawal are unverified trials**. Declare the
brick's long/short axes and outward top normal in the table frame. Distinguish
TCP-centered rotation from a bottom/contact-edge peel: for an edge pivot, compute
the TCP path using the held transform and estimated edge, not an in-place TCP
rotation relabeled as peeling. A fixed edge hypothesis is not a measured contact
pivot. Withdrawal candidate is 5 mm along the *tilted brick's outward top normal*,
not automatically gripper Z; record frame, sign and actual observed displacement.

Start with one exposed-brick/contact configuration and a reserved offset or
support configuration. Change one primitive parameter per improvement round.
Before any run, freeze SI force/torque thresholds, contact travel, tilt range,
withdrawal distance, speed, dwell and timeout ceilings. Unavailable force data
is unknown, not zero force. Permit at most one renewed whole-brick attempt after a safely recovered
failure, within the global eight-attempt budget; abort on lost association, slip, exceeded
bounds, ambiguous completion or observed neighboring-stack disturbance. Simulator
truth independently checks intended detachment and collateral native breaks.
The historical TGS idle failure prohibits treating spontaneous disassembly as
pick success. New contact trials must explicitly retain the tested PGS/32/4
configuration, report spontaneous/collateral failures, and include appropriate
stationary controls over their actual contact-trial duration. The one-second
idle pass does not validate longer contact behavior or updated-tip collisions.

## Placement and stacking

Use the configured/calibrated receiving-baseplate frame and explicit stud-grid
coordinates, excluding taped rows and zone boundaries. Convert a desired brick
pose to a TCP target through `T_TCP_brick`; include receiver height, orientation,
layer height and uncertainty. An empty-plate receiving surface differs from a
previously placed brick. Determine the receiving top/grid from observations and
placement history with verification, not privileged target poses.

Visual refinement precedes gentle contact with frozen travel/force/torque limits.
Check swept finger clearance through seating and release. Do not presume that
a side grasp permits full seating; a release/press alternative needs its own
contact test if clearance fails. Bound lateral refinement and attempts; do not
build a general search/scheduling system.

Keep **resting on studs**, **observed seated**, **native attached** and **uncertain**
outcomes separate. Online completion needs defined image/proprio/contact evidence
for seating, release and stability; attachment needs an explicitly tested observable
(e.g. a bounded retention check). Force increase or a plausible image alone is
insufficient. Native connection creation, intended grid/yaw and retained attachment
are evaluator-only ground truth. Until online feedback is validated against that
truth, report attachment unknown. Never set a connection to declare success.

## First bounded recipe

Use at most six processed input bricks and eight total manipulation attempts,
including retries. One attempt is a complete brick-handling try from approach
to verified destination or abort; individual waypoints do not consume separate
attempts. A failed try can be renewed only after observed safe recovery and
reassociation, never by post-reset teleportation. Target four accepted bricks in a small fit-checked 4×2-stud
column, so the demo includes placement on the plate and on an existing brick.
Include a reject case and, when applicable, an unrequested-good-color buffer case.
These counts are a proposed first fixture, not a guarantee of source availability.

Single-color requests repeat that label. Mixed requests use a fixed cyclic order
of the requested labels, chosen once in configuration (for example red/tan/red/tan).
No open-ended optimizer or general scheduling system is needed. If the next
required color has no usable accessible candidate/receiving slot, abstain or end
the bounded demo rather than silently changing the arrangement. Unrequested good
labels go to their fixed small zone; faulty bricks go to reject. Unknown labels
are not treated as faulty. When all good labels are requested, buffers stay empty.
Freeze a representative input/label sequence and a small reserved mismatch case;
explicit mock sequences remain interface tests, not actual classification success.
