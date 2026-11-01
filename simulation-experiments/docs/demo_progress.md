# Challenge 2 simulation demo: measured progress

Updated 2026-10-26. **Current priority:** align simulation with the real
`task2/jacob` branch, pinned at `13f37da`, before further demo development.
The exact real Python planner/catalog/policy is shared through a simulation-only
backend. Independent offline replay passes (Pueue 1835); Isaac validation does
not pass yet (1836 timed out; 1837 failed its source-pose recorder startup check
before control). The later [reader-only case](../experiments/pose_reader_20261026/REPORT.md)
resolves that startup mismatch: fresh per-actor/batch poses agree exactly for all
300 bricks; cached poses differ by up to 3.725 nm. Actual corrected-class audit
1840 passes, while shutdown still times out. Full grasp parity remains incomplete because the SDK held
flag and loaded gripper completion are unsupported. See the
[alignment report](../experiments/control_alignment_20261026/REPORT.md).
No physical robot was commanded, and previous results remain unchanged.

**Earlier manipulation state:** the corrected-material regression
(1830) passes its fresh 1500-step stationary control and configuration checks,
but fails retention: 1.687 mm / 6.80° maximum relative error, 0.766 mm final
rise, abort at step 716, no completed lift/hold. The original three-improvement
fixture comparison and this one-off correctness regression are closed. Native
tower extraction, reject transfer, insertion and repeated sorting remain
unproven. See the [corrected-model result](../experiments/declared_material_retention_20261025/README.md).

**New working-grasp evidence:** the operator supplied 15 recorded and 300 inferred
targets plus a labeled workcell photograph, and reports the inferred input-stack
poses were tested. Approach uses a 20 mm opening, closing requests 14 mm, the
loaded readback is 15.8 mm, and extraction is straight upward. The export names
its base/EE frames and includes its configured flange-to-EE transform. Its
15 mm base-Z downward offset is already applied. Original false validation flags
are retained separately from the later operator attestation.

The [data-only reference comparison](../experiments/hardware_grasp_reference_20261025/README.md)
checks the configured EE against the current model grip frame. It does not
change scene registration, pad mounting, width mapping, controllers or prior
results. The operator subsequently confirmed that a held needle approximately 10 mm
below the pads touched the flat brick body top, and identified #3 as trustworthy;
#11 is an uncertain recording and is no longer a cross-plate height anchor.
The ten-layer body top is 96 mm above the white plate's brick-supporting surface;
taught upper pad bottoms are approximately 106 mm, and after the already-applied
15 mm descent the grasp pad bottoms are approximately 91 mm: about 5 mm body
engagement. These are pad-relative estimates, not exported configured-EE heights
or a measured physical pad transform. Both physical plates are thin baseplates;
their exact thickness remains unmeasured. See the
[latest datum clarification](../experiments/hardware_grasp_reference_20261025/README.md).
The former #11 height discrepancy is retired, not fitted away. Physical width
mapping/model mounting remains unverified. No active simulation change or new
parameter sweep follows from this documentation update.


**Destination references:** the operator now specifies B (#11 XY), C (#14 XY),
and D (#15 XY), all using the trusted source's first-layer nominal EE height.
The new [destination helper and export](../experiments/destination_plan_20261025/README.md)
uses four ridges of three bricks, confirmed shared centers/two-stud gaps,
alternating orientation, and `destination_n_m_k` labels. Requested accepted
colors route to B; remaining accepted colors map consistently to C/D. Only
explicit caller confirmation advances placement counts. The legacy truth-based
SortPlan, raw taught poses and controllers remain unchanged. These nominal
base-frame references do not establish native insertion or hardware alignment. Saved-output audit
1833 checks all 900 slots, 63 routes, 42 preferences and 7 acknowledgment examples;
1832's original one-ULP metadata failure is preserved. Production coordinates
are unchanged between audits. See the linked results and raw orientation review.

Local pregrasp RGB color classification has limited saved-render evidence.
The current sensor-selected runner has an opt-in final-selection color hook;
job 1826 verifies 116 unchanged prior outputs and all 10 invalidation controls.
The actual Sensors helper is synthetic-tested; no fresh simulator/camera or
manipulation run exercises that hook. A source label does not establish held
identity. See the [handoff results](../experiments/stage1_handoff_20261025/README.md).
Challenge 1 is unrelated to this LEGO task. The measured Munich D435 calibration
is preserved in a passive registry and is not active workcell registration.
Earlier dated sections below are historical results, not the current summary.

The active objective is an incremental end-to-end **simulation**
demo. No hardware motion, ROS deployment or physical readiness is authorized or
claimed. Existing visual and perception experiments remain preserved.

## Classification scope correction

The user clarifies that Challenge 1 handles industrial bricks, not this LEGO
color task. Older references below to waiting for that classifier are superseded;
there is no external classifier dependency. Local RGB color classification is
implemented and benchmarked on saved rendered segmentation candidates (job1806), with limited detection coverage and no
real-image accuracy claim. An opt-in runtime hook is implemented and saved-data
replay-tested (1826); fresh live perception-to-grasp execution remains unproven.
The primary observation is the segmentation view before grasp; held
C920 confirmation is optional pending visibility/sharpness/association evidence.
A source-region label cannot confirm held identity.

## Current end-effector model

The reference-corrected folded C920 holder and supplied fingertip STL visuals
are complete as a nominal visual update. The D435i mount, arm configuration,
layout and native 300-brick design are retained. See
[registration, renders and limitations](../experiments/final_workcell_20261024/end_effector/README.md).
STL units/attachment remain nominal. The current manipulation experiment uses
the reviewed exposed custom-tip BODY hull and separate screw-head envelope, with
original mass/inertia restored. Lateral contact/reopen diagnostics pass; global
distal geometry validation and dynamic extraction do not. The passive Munich
D435 registry does not calibrate either C920 or register the active workcell.

Source review localized the known default-material discrepancy to missing native
physics-material schemas/bindings. An opt-in authoring correction now copies the
already declared Body/Top coefficients onto bound physics materials. Pure-USD
job 1827 passes binding/preservation/reload and eight rejection cases in 0.430 s.
It changes no active workcell or shared native code. Startup readback1828 and
separate saved-data adjudication1829 now verify the isolated coupon's unordered
material rows with all audited state/properties unchanged. The original1828
metadata-oracle failure is preserved. No pair traction or retention result follows.
See the [authoring check](../experiments/brick_material_binding_20261025/README.md)
and [startup evidence with both audits](../experiments/brick_material_runtime_20261025/README.md).

## Stage 1: ordinary candidate/mock interface smoke passed; coverage remains limited

Frozen R3 is reused with configured synthetic camera calibration and a translated
source ROI. Online code receives RGB, axial depth, calibration and opaque frame
IDs; actual brick poses/IDs/colors and reference metadata belong only to offline
evaluation. Candidate XY/shared ridge yaw/body-top-band assumptions are not full
poses or verified grasp access. Challenge 1 is separate from this LEGO task.
The historical four exact-ID classification fixtures were explicit mocks and abstained if no
PRESENT candidate existed. Later jobs 1806/1826 add the actual local RGB color
entry point and optional handoff; the original smoke results below remain
historical interface evidence.

The first integration smoke gate uses intact/interior-gap/endpoint states in
both current wide diagnostic views, requiring at least one eligible PRESENT per
state and no confident wrong/lower/absence claims. Sparse remnants and layer
transition are reserved for the frozen interface audit, not novel-stack evidence.

| Version / split | Pueue | Present matches / visible references | Decisive coverage | Supported bands | Result |
|---|---:|---:|---:|---:|---|
| Unchanged R3, development | 1723 | 0 / 171 | 0% | 0 / 6 | Fail; no candidate, mock blocked |
| Unchanged R3, reserved | 1724 | 0 / 64 | 0% | 0 / 4 | Fail; no candidate |
| R3 + fixed Z workspace, development | 1726 | 0 / 171 | 0% | 3 / 6 | Fail; height corrected, fragments rejected |
| Same R3/workspace, closer virtual views, development | 1729 | 41 / 176 | 23.3% | 6 / 6 | Ordinary integration smoke passes |
| Same closer views, reserved | 1730 | 19 / 66 | 28.8% | 2 / 4 | Sparse-state gate fails |

Zero detections give undefined precision, not 100% precision. No-match targets
are not uncertain *instances*. All-NaN controls and the fixed NaN patch produce
no false absence claims. Recovered/lost confirmed development faces: 0 / 0.

Development evidence: the wide overhead highest band selected forearm geometry
around 0.583 m rather than the source layer around 0.10 m. One reviewed fixed
work-volume prior [-0.005, 0.20] m converts excluded depth to unknown without
altering raw inputs or R3 thresholds. This finds the right overhead band but
all fragments remain too narrow (7–10 mm versus unchanged 16±4 mm). Oblique
bands remain unsupported. No threshold relaxation followed these failures.
A separately versioned fixed close-view experiment (render job 1728) subsequently
recovers confirmed candidates without changing R3 or workspace settings. Its
results are separate from the wide-view baseline.

Source and reproducibility:
[Stage 1 code/protocol](../experiments/stage1_20261025/README.md),
[development baseline](../runs/20261025T001958.593862Z-stage1-development/evaluation/evaluation.json),
[workspace comparison](../runs/20261025T002637.845861Z-stage1-development-workspace_v1/evaluation/evaluation.json).
Rendering jobs 1722 and 1728 preserve native links in each partial-state snapshot.

The close-view ordinary gate confirms 15 intact, 13 interior-gap and 13 endpoint
faces, all overhead. The complementary view confirms none. Conditional accepted
XY median is 0.50 mm and max 0.716 mm (N=41); these are ideal synthetic metric
checks, not verified grasp precision. There are 135 missed visible occurrences
(127 matched uncertain hypotheses and 8 no-match), and no confident false/lower/
merge/duplicate errors. Two lower-fragment **raw** hypotheses are unconfirmed.
The interior gap is correctly missing overhead and uncertain obliquely; a
removed endpoint remains unknown extent. NaN controls and all mock guards pass.
Of the 41 confirmed occurrences, 38 recover previously visible IDs and 3 concern
newly visible references; zero previously confirmed faces are lost. Reference
visibility changes from 171 to 176, so the two camera sets are not identical
samples. Reserved transition top confirms 19; sparse remnants confirm zero in
both views. No reserved-driven threshold or view tuning follows.

[Ordinary close-view evaluation](../runs/20261025T003437.436801Z-stage1-development-workspace_v1/evaluation/evaluation.json),
[reserved evaluation](../runs/20261025T003437.726220Z-stage1-reserved-workspace_v1/evaluation/evaluation.json),
[representative sensor overlay](../runs/20261025T003437.436801Z-stage1-development-workspace_v1/inference/f000/overlay.png).
The actual Challenge 1 service is still unavailable; passing mocked joins is
not actual classification integration. These views are virtual inspection
views, not calibrated wrist-camera or hardware reachability evidence.

## Stage 2 prerequisite: full-stack dynamics — failed baseline

Job **1725** attempts a frozen 120-step, one-second idle test with the same
300 bricks/930 native connections, nominal arm target and stock collisions.
It stops at step 7 (about 0.058 s after graph initialization): connections
836 and 837 on top-edge brick `brick_9_0_3` break; the source component changes
from 301 parts / 930 connections to 300 / 928. Maximum source drift is 0.171 mm;
robot joints hold their nominal values. Thus the visual twin's prior zero-step
captures did not establish load-bearing native stability.

No preload, friction, cooldown, timestep, breakage rule or stack size is changed
to hide this result. Diagnostic job **1727** enables only native debug output
and records utilization; it reproduces the same first failure at step 7 and
collects seven native solver dumps. Debug completion is not an idle pass. The
failure mechanism is not yet established; queued analysis must distinguish
serialized force/solver evidence from conjecture. An idle pass alone would still not prove
extraction. Bilateral contact feedback and a checked updated-tip collision
representation are further prerequisites for that claim.

[Idle protocol and commands](../experiments/stage2_idle_20261025/README.md),
[first-failure trace](../runs/20261025T002411.589299Z-stage2-full300-idle/output/idle_report.json).

## Remaining stages — not demonstrated

Selection/grasp/extraction, reject transfer, empty-baseplate insertion,
brick-on-brick stacking and repeated sorting with bounded recovery have no
passing measurements yet. Do not credit legacy truth-driven task observations,
static graph authoring, mock labels or preview renders as these stages.
Native connections may be created only for reset initialization or by native
assembly detection during measured task execution; no post-reset teleportation,
scripted attachment or manually declared connection success is allowed.


## Closed numerical diagnostic round

Native debug/analysis jobs1727/1731/1732 are followed by the explicit coupled
numerical-epsilon pair1733/1734 and read-only comparison1735. Both1e-4 and1e-6
break the same two top-edge connections at step7. The tighter value lowers the
watched relaxed-bound violation from~5.52e-5 to~5.7e-9, but positive model
relaxation remains. Numerical tightening is not a sufficient fix; underlying
contact/angular-load origin is unresolved. No physical threshold, break rule,
source geometry or task motion is changed. Independent evaluation/review agree
to stop this bounded round with the failed idle gate intact, rather than hide it.

[Machine-readable dynamics outcome](../experiments/stage2_idle_20261025/results.json),
[perception outcomes and exact snapshots](../experiments/stage1_20261025/results.json).
The six-stage goal remains incomplete. The source later passes the bounded PGS idle checks recorded below. Further
controller work still needs checked updated-tip collisions/contact feedback; actual Challenge1
integration also remains unavailable. No extraction, transfer or stacking
success is established by the candidate/mock-interface pass.


## Updated technical starting points

The [revisable stage protocol](demo_stage_protocol.md) now governs classification
visibility/timing, held-offset/pivot/clearance experiments, receiving stud-grid
placement and online-vs-native attachment evidence. It caps each frozen stage at
three improvement rounds before reassessment and proposes a six-brick/eight-attempt
cyclic-color demo. No classification timing or25°/5mm extraction parameter is
promoted to validated status. PGS subsequently passes the initial idle gate;
updated-tip collisions and contact feedback remain prerequisites.


## Optional Alex compute check

The savedSSHprofile currently reachesalex2.nhr.fau.de with strict known-host
verification and no interactive authentication or credential copying. Local
Pueue1737 submits Slurm4685752: a bounded1A40/5minute inventory probe, which
completes in10seconds with16CPU/60000M and driver610.57.04. The first submission
1736 was rejected before allocation because Alex forbids explicit --mem forGPU
jobs; the corrected payload uses automatic per-GPU resource shares.

Isaac/CUDAapplication compatibility remains NOT_TESTED: no verified matching
runtime/container was identified. The default probe interpreter isPython3.9.25;
metadata absence there is not cluster-wide absence. No remote installation,
training, simulation or scaling follows. See [probe evidence and budgets](../experiments/alex_preflight_20261025/README.md).


## Bounded contact-observation diagnostic

Pueue **1738** enables only process-local contact reporting and native debug
logging for the unchanged full source, capped at eight steps/first failure.
Independent audit **1739** confirms equivalence to the default 1733 baseline:
source initial/terminal state files are byte-identical and available per-step
metrics/joints match; connections 836/837 still break at step 7. No API adaptation
or physics adjustment was made. All 42 watched body-step records report zero
normal/friction contacts, including zero aggregate normal impulses. Without a
positive reporting control, these zeros do not establish complete sensing or
zero physical loads. Native internal same-component contact suppression is
also present. Load origin remains unresolved and the idle gate still fails.

[Protocol and commands](../experiments/stage2_idle_20261025/README.md),
[independent contact audit](../runs/20261025T014929.925825Z-stage2-contact-evaluation/output/REPORT.md).
This diagnostic does not reset the stage improvement budget or validate grasping.


## Stage 2 round 2: solver-quality sensitivity did not fix idle stability

Pueue **1740**, source `1debd6e`, tests source-only velocity iterations 4→16
(position 32), retaining all physical/native break parameters and the original
120-step acceptance gate. Runtime properties on all 300 source actors verify
32/16 initially and terminally; the actual TGS scene clamps permit those values.
Audit **1741** passes all 25 experiment-integrity checks, but the same links
836/837 break at step 7. Initial states are byte-identical to both earlier
baselines and recorded per-step aggregate drift/speed metrics agree exactly.
No load/utilization comparison or executed-island iteration count is available.

This is a failed numerical sensitivity result. Default settings remain unchanged;
no reserved case or manipulation is run. Two Stage 2 improvement rounds are now
used; a third parameter guess is not justified. The source/load model needs a
concrete hypothesis before further contact work. The six-stage demo remains
incomplete.

[Round 2 protocol/results](../experiments/stage2_idle_20261025/README.md),
[independent audit](../runs/20261025T020255.062438Z-stage2-round2-evaluation/output/evaluation.json).


## Isolated bookkeeping signature and final-round hypothesis

The eccentric two-brick diagnostic **1743**, audited in **1744**, completes eight
steps/no break with all 36 integrity checks passing. Gravity-consistent linear
impulse accompanies a persistent native external angular residual, despite zero
observed angular velocity/momentum change. Independent source reviews find a
public PhysX TGS writeback expression predicting its exact sign/scale. The
loaded-binary-to-public-tag correspondence remains qualified. This does not clear
the failed full300 idle gate or justify removing BrickSim wrench transport.

[Fixture measurements, preserved setup failure and source hypothesis](../experiments/stage2_eccentric_20261025/README.md).
A single PGS workaround is being prepared as the final Stage 2 improvement round:
small-fixture gate, then full300 idle, then a reserved removal state, stopping at
any failed gate. It retains physical capacities, break rules, timestep and default
actor32/4. No native build or parameter sweep is planned.


## Final idle round passed with PGS; contact/manipulation gates remain

All three predeclared phases pass: A **1745/1746** suppresses the eccentric
angular-reporting signature; B **1747/1748** keeps all 300 bricks and 930 native
links through 120 steps; reserved C **1749/1750** keeps 299 bricks and 926 links
through 120 steps. Maximum drift is 0.208 mm in B and 0.582 mm in C, within the
unchanged 2 mm limit. No native break occurs. Actual PGS/source32/4, nominal joints,
initial poses and native physical settings are independently checked.

The sole change is TGS→PGS. Epsilon, clutch strength/friction, timestep, geometry
and stock collision assets are unchanged. A's operational artifact screen is not
force calibration; source/binary identity and broader physical validity remain
qualified. Three configuration rounds are now closed; no fourth tuning round.
New contact benchmarks must explicitly use this tested PGS setting and report
stationary controls over their own duration. The supplied fingertips still have
stock collision geometry, and no grasp, extraction, placement or integrated
sorting success is claimed.

[Commands, frozen gates, all six job IDs and independent audits](../experiments/stage2_pgs_20261025/README.md),
[machine-readable results](../experiments/stage2_pgs_20261025/results.json).

The original [next-contact proposal](demo_next_contact_gate.md) is preserved.
The stock baseline has now run as recorded below; the supplied-STL proxy remains
unvalidated. No fixture is claimed as a perception-driven grasp.


## Stock-pad positive contact/reopen passed

Contact benchmark B0 capture **1754**, independent audit **1755**, passes all 27
checks over 100 steps. Both stock pads exceed 0.2 N for three samples at step 49;
peaks are about 0.224 N. Force release first confirms at step 70, with controlled
return to initial opening complete at step 100. All signed force-carrying points
are pad-compatible; reciprocal/unit/buffer and source930-link guards pass. Arm
commands, source PGS32/4 and existing mass/material/actuator settings are retained.

Earlier **1751** stops before play on an unsupported Cube representation;
**1752/1753** fails the original nonnegative-scalar assumption at first small
contacts. Both failures remain preserved. Primary API examples and unmodified
signed vector checks justify the round-2 interpretation correction; no physical
force or motion threshold was tuned. Those two rounds were followed by the
final supplied-tip geometry attempt recorded below.

[Limits, exact commands and provenance](../experiments/stage2_contact_20261025/README.md),
[all outcomes](../experiments/stage2_contact_20261025/results.json).
This is a stock-pad fixture/feedback check. Actual supplied-STL collisions,
dynamic holding, extraction, insertion, classification timing and the integrated
demo remain unvalidated. Per-pad force availability on physical hardware and
shared sim/real completion semantics are not established by this diagnostic.


## Final contact round: supplied-tip geometry stopped before contact

Source `5e8ba6c`, Pueue **1756**, tests one experiment-local supplied-STL
collision decomposition in the full300 initializer. It stops after 13.373 s
before measured contact: normalized SDK hull planes fail to contain their own
vertices within the frozen 0.1 µm representation check. The raw left-tip
32-hull RESULT_VALID query is retained; the right tip and subsequent union/CAD
fidelity acceptance are untested. A representation-query failure is not proof
of invalid physical CAD. No updated-tip contact, reserved offset or grasp is
credited. The shared visual workcell and earlier stock-pad pass remain intact.

All three contact improvement rounds are closed. No recook, threshold change,
D/R trial or fourth configuration follows. Independent read-only audit **1757**
describes the retained partial geometry
without promoting G. Seventeen of 32 left hulls fail the frozen containment
check; maximum normalized residual is 48.703 µm (own-polygon residual 49.344 µm).
Maximum outer-bound difference is 0.102881 mm against the frozen 0.1 mm limit.
Capture plus audit consumes 13.437 s. Cause and full CAD/union fidelity remain
unresolved; there is no right-tip or measured-contact evidence.
The six-stage sorting demo remains incomplete, with supplied-tip collision
validation the immediate manipulation prerequisite.

[Current contact results](../experiments/stage2_contact_20261025/results.json),
[1756 failure](../runs/20261025T040508.534018Z-stage2-contact-R3-G/output/failure.json).


## Representation reassessment: observe active shapes next

Pueue **1758**, source `10177e6`, analyzes saved left-tip data only (0.109 s).
All32 indexed surfaces are closed/oriented/nondegenerate, but only16 meet the
original convexity precision. Maximum polygon nonplanarity is144.508 µm, and
fan convexity excess115.407 µm. For27 reference-free bore probes, a vertex-hull
interpretation reports27 outside, SDK halfspaces26 outside/1unknown, and
conservative indexed winding27unknown. These candidates do not establish the
actual collision shape or its suitability. OldG/bounds failure/right-tip
unknown and the closed three-round contact budget remain unchanged.

Planner, independent evaluator and reviewer agree to stop saved-data forensics.
One separately frozen, motion-free active-PhysX query diagnostic will inspect
the unchanged STL/registration/decomposition using fixed probes and controls.
It cannot promote the old benchmark or authorize D/R/contact. The full goal
remains active and incomplete.

[Reassessment evidence, versions and source contracts](../experiments/stage2_contact_20261025/reassessment/results.json).


## Active-shape observation: setup fixed, proxy discrepancies measured

Original setup1759/audit1760 stops at four empty controls; there are no target
observations. A reviewed process-local `enable_scene_query_support=True`
correction addresses the installed headless default. Corrected1761/audit1762
passes34/34 integrity checks and all250 fixed queries in15.047s including
the supervised audit command, with nominal
joints/full300/930/PGS32/4 unchanged and zero measured postassembly steps.

Each pad matches all42 CAD-predicted ray-hit cases outof96, but largest first-hit
differences are6.500mm left and1.346mm right (nongrazing/nonedge). Active pad
sphere queries overlap2/27 left and9/27 right independently CAD-free bore
locations; their clearance is~.598mm/.500mm against50µm probe radius. These
conditional local discrepancies reject the current automatic-decomposition
model for faithful updated-tip contact. Negative probes are not global void
proof. No contact/grasp result follows from the integrity pass.

The two observational attempts and old three-round contact benchmark are
closed. Planner/evaluator/reviewer recommend inspecting one explicit CAD-derived
convex compound with preserved bore/contact surfaces and unchanged registration.
Concrete parts need review before a single frozen approach attempt, with no new
three-round tuning pool. If this requires substantial geometry infrastructure,
obtain the original CAD/convex parts instead. No new proxy is implemented yet.
The full six-stage goal remains active and incomplete.

[Active-query commands, versions, raw data and outcomes](../experiments/stage2_active_query_20261025/README.md).


## Original fingertip inspection supports a concrete partition candidate

Pueue1763, source `b534b2c`, inspects only the supplied original STL in1.677s
(60s limit). The1256-triangle/630-vertex mesh is closed, consistently oriented
and nondegenerate. All35 component loops across20 fixed Xsections are closed
and unbranched, with no coplanar-face sections. Source-plane clusters identify
the boss front atX=-11mm, body front=-9.5mm, blind bore cap=-4.5mm and back=0mm.
Nominal STL volume is3366.462mm³ versus3574.971mm³ for its full vertex hull.

These measurements support a possible48-cell model-specific partition—16
sectors for each of the boss, bored-body and solid-body axial regions. It is
not yet constructed or accepted. Source-derived polygon supports, cell coverage,
original100µm fidelity/bounds and bore preservation need independent checks
before any cooking. No new framework, decomposition sweep or freshthree-round
allowance is proposed. Current CAD-to-finger registration is also unverified;
contact-face and distal-end confirmation questions are pending. CAD-frame part
construction can progress without inventing the physical mounting.

[Inspection evidence and plane/face provenance](../experiments/tip_partition_20261025/results.json),
[orthographic facet projections](../runs/20261025T050607.814521Z-original-tip-feature-inspection/output/orthographic.png),
[fixed raw cross-sections](../runs/20261025T050607.814521Z-original-tip-feature-inspection/output/sections.png).


## Explicit compound: resource guard stopped construction

Pueue1764 (source`8e1c4cd`) retains27 of48 cells and stops before cooking
at the frozen128-vertex guard. Logging-only replay1765 (source`0ab784e`)
reproduces all27 retained records exactly. Its independent audit confirms
that`front_body_bored_11` has133 extreme vertices,262 triangular facets
and3.245µm minimum vertex spacing. The124 exact plane rows are descriptive;
none of these counts establishes native cooked polygon count or cookability.
Both jobs together consume0.495s of supervised process time.

Original1764 remains failed and incomplete. One unchanged-shape CPU resource
guard reassessment is under review, with all48 cells and100µm fidelity
checks retained. There is no cooking/contact approval or fresh three-round
allowance. Mounting-face/distal-end questions remain unanswered.

[Preserved outcomes](../experiments/tip_partition_20261025/compound/results.json).


## Explicit compound passes offline sampled geometry checks

Pueue1766 (source`9d789ab`) completes the unchanged48-cell construction
with one reviewed128→255 offline vertex-guard correction. All27 earlier
records remain exactly equal. All16 independent checks pass; source-outside
maximum exact distance is59.735µm, candidate exterior sampled distance plus
its1µm bracket is60.667µm, bounds error is numerical noise and volume differs
by0.0530%. All27 reference-free50µm bore spheres remain free in the candidate.
Actual cumulative supervised time including1764/1765 is6.547s of180s.

This is sampled CAD-frame evidence, not a global Hausdorff guarantee, native
cookability, confirmed physical mounting, or contact/grasp success. Source
inside samples use a fixed100µm outward-normal endpoint bound, not nearest
Euclidean distance. Candidate filtering excludes internal interfaces;22
samples have unresolved exterior brackets. One narrow native cooking/query
gate is being reviewed before any contact is attempted. All previous failed
benchmarks remain failed; no new three-round allowance is created.

[Independent offline audit](../runs/20261025T061618.814542Z-explicit-tip-compound-255/audit/evaluation.json),
[exact27-record check](../runs/20261025T061618.814542Z-explicit-tip-compound-255/prefix_check.json),
[commands and source manifest](../runs/20261025T061618.814542Z-explicit-tip-compound-255/manifest.json).


## Native compound observation stops at physical-property preservation

Pueue1767 (source`0fbc0bf`) fails before any cooked-buffer capture or query.
Replacing collider geometry changes automatic mass/inertia/COM entries10/11;
all other body entries and all actuator arrays remain exact against1754. The
strict guard correctly rejects an unfair physical comparison. These entries
have not yet been mapped to saved historical body names. All target geometry
and query quality remain UNTESTED. Capture plus independent failed-capture audit
takes14.699s, with zero measured postassembly steps.

The team supports one explicit initialization-only preservation correction: a
same-instance scene.reset wrapper restores the declared frozen1754 mass model
before the existing explicit nominal initialization step, verifies current
finger mapping/nonfinger invariance and requires the same exact postreadback.
This is not an estimate of the real updated tip's mass. Engine-internal reset
initialization precedes this restoration. No CAD/geometry, query, tolerance or
actuator tuning is proposed. At most two native setup attempts and cumulative
180s including1767; no contact or new three-round allowance. Source review is
pending before the final attempt.

[Preserved native-test failure](../experiments/compound_native_query_20261025/results.json).


## Full-articulation property restoration fails on untouched arm links

Pueue1768 (source`cd7aca3`) completes the fixed three setters once but fails
strict readback before the explicit initialization step, cooking or queries.
Saved records show both finger property sets, all masses/COM translations and
actuators exactly restored. Only nonfinger inertia matrices/principal-axis
quaternions at indices0–7,9 differ; q/qdot and physics time are unchanged.
This is consistent with documented inertia re-diagonalization on rewritten
links; physical equivalence is not established. Both setup attempts remain
closed/failed, with29.797s cumulative process time.

A concrete source-supported reassessment targets only the two finger actors
through RigidBodyView setters, leaving arm actors unwritten. Same B0 model,
setter order, strict full-robot readback, shape, query and state guards remain.
This is under independent source review, not a fresh three-round pool or a
retroactive pass. At most one targeted-route run is proposed (aggregate three
native executions, cumulative180s including prior29.797s). Native cooked
geometry/contact and physical tool mounting remain unvalidated.


## Targeted restoration passes; native first-surface quality still fails

Pueue1769 (source`c6b141b`) preserves the declared full B0 physical model
using only two exact finger-body views. All42 observation-integrity checks
and250 fixed probes complete, with full300/301/930, nominal joints, PGS32/4
and zero measured postassembly steps unchanged. Each of96 cell colliders
returns one valid SDK hull. The aggregate three native executions are closed
at45.996s of180s; no automatic recook/contact/tuning follows.

All192 binary ray parities and54 sparse no-overlap bore observations pass.
However,7/42 left and5/42 right clear reference-hit depths exceed100µm;
both worst rays reach a rear-body cell about5mm after the expected front
surface. No CAD edge/grazing exclusions apply to these84 reference hits.
The native tested-feature gate therefore FAILS. This does not demonstrate
contact failure; no contact/grasp/extraction was tested.

Saved SDK descriptors have6–9 vertices/cell versus up to133 input vertices,
and descriptive bound deltas up to0.593mm. These observations motivate later
source/contract reassessment of cooking/active-shape geometry versus compound
query reporting; they do not establish the cause. The installed schema's
1mm minThickness fallback was not logged at runtime and is only a hypothesis.
The offline CAD pass and successful targeted property-preservation route remain
separate reusable evidence. Physical mounting is still provisional. The full
six-stage demonstration remains active and incomplete.

[Native outcomes and retained failures](../experiments/compound_native_query_20261025/results.json).


## User-corrected fingertip mounting and simple outside heads

User confirmation supersedes the old nominal mounting: tapered lowCADZ ends
point distal, broad CADX0 gripping faces point inward, and bosses point into
the supporting stock fingers. The user explicitly permits simple rigid visual
attachment without boss/hole form-fit. Source`3afda2d` applies a proper X/Z
flip and adds only round outside head proxies (6mm diameter,2mm protrusion,
configurable estimates), with no threads, shafts or fastener physics.

Saved-mesh inspection1770 found no unique distal recess and did not invent an
anchor. Static render1771 provides two closeups; independent1772 passes52/52
checks. Root/evaluator/reviewer accept the visibly connected assembly. Both
camera mounts, layout, nominal robot/source state, white-finger geometry and
stock collisions remain unchanged; full300/930/301 graph retained. Head
envelopes are recorded for later clearance work, not validated collision
behavior. The corrected mount makes the historical inward-boss/bore fidelity
gate physically inapplicable without reassessment; old failures remain saved.

This completes the requested visual subtask. The end-to-end sorting demo
remains active/incomplete; future external-contact modeling should follow the
user's simplified attachment scope instead of reopening hidden form-fit work.

[Current visual assembly and evidence](../experiments/final_workcell_20261024/end_effector/README.md).


## User-corrected proximal pad height

The user clarifies that replacement and stock pad upper/proximal edges share
height: added length belongs below the metal, with boss/screw axis setting
the mounting height. This supersedes1771's incorrectly retained distal
endpoint. Source`3cee3d7` changes only the Z anchor and derived head position.
Render1773 and independent1774 pass60/60 visual/invariance checks. Native
stock-pad upperZ36.09037mm remains aligned; supplied tip reaches61.64037mm
versus metal end53.85756mm (~7.783mm beyond it). Boss/head axis is45.09037mm
in finger coordinates. These are nominal asset dimensions, not robot-frame
calibration. All five views, physical camera mounts, layout, joints, source
300/930/301 and stock collision geometry are unchanged. Root/evaluator/reviewer
accept the visibly extended pads; no more visual work is needed.

Simple heads remain6mm diameter/2mm outward protrusion estimates. No threads,
form-fit, custom collision/contact or manipulation claim follows. Current
visual artifact pointers now reference1773; old images/results remain saved.
The full end-to-end goal remains active/incomplete.


## Exposed-tip model: small unloaded endcap residual, grip/taper probes pass

The user-authorized simple exposed-body/head model uses the corrected1773
mount. It omits buried boss/attachment void detail, with no full-STL form-fit
claim. Frozen one-configuration G/D/reserved sequence reuses the signed B0
force observer, targeted mass preservation and source PGS32/4. G1778
(source`a5a9cb1`) completes216 fixed queries and469/469 integrity checks in
16.550s supervised time. Allparities and clear gripping/taper/head probes
pass. Two distal endcap-axis rays retreat130.075/130.135µm versus the frozen
100µm limit, so original G remains FAILED and is not overwritten.

Independent planner/evaluator/reviewer support a DISTINCT limited lateral
normal-contact test of this same cook. Every loaded point must qualify at
the flat inward gripping plane within|separation|+50µm, be uniquely body
versus white/head compatible, and have signed outward-normal cosine>=.9.
All prior force, reciprocal, source, state and motion bounds remain. This
allows some off-axis normal component; it is not zero-axial-force proof.
No tip-Z exclusion or tolerance change is proposed. Nominal fixture overlap
is7.28mm; subtracting a sampled ray residual does not prove global support.
A separate pinned authorization is under source review before one D and
conditional reserved R; no new G, recook or improvement pool follows.


## Corrected exposed tips: lateral contact and reserved offset

The original global geometry G (1778) remains failed: two distal endcap rays
retreat about 130 micrometers against the frozen 100 micrometer criterion.
The independently reviewed side authorization retains that failure and permits
only the unchanged model's flat inward-face contact, with both sensor directions
checking body ownership, exclusion of metal/head contacts, plane distance and
signed normal direction. No global collision fidelity is established.

Invocation 1788 failed before simulator startup because argparse treated
`--geometry` as an abbreviation of `--geometry-audit`. One reviewed line disables
that abbreviation. A parser-only regression reproduces the failure and verifies
D/R forwarding without importing Isaac. The failed invocation remains UNTESTED;
its 0.879 seconds counts against D's original 180-second budget.

| Case | Pueue | Steps | Positive contact / release step | Peak left / right normal load | Independent result |
|---|---:|---:|---:|---:|---|
| Centered D | 1791 | 102 | 50 / 72 | 0.235 / 0.238 N | Pass: 42 integrity and 27 contact checks |
| Reserved, +2 mm hand X | 1794 | 100 | 49 / 70 | 0.224 / 0.225 N | Pass: 43 integrity and 27 contact checks |

D, including its failed invocation, took 46.466 seconds; R took 39.078 seconds.
The same model, cooked hashes, physical parameters and contact gates were used.
D's 394 loaded-point observations include 197 reciprocal reports and are
correlated, not independent trials. The source retains 300 bricks and 930 native
connections. The coupon is kinematic and unconnected: this does not show dynamic
holding, friction calibration, native extraction, insertion or hardware readiness.
Generic static-renderer close flags and premeasurement kinematic velocity-write
warnings remain recorded; contact markers, independent audit and cleanup status
are reported separately rather than claiming those warnings were fixed.

Reproduce the immutable invocation commands from each snapshot's `launch.sh`
and `manifest.json`, using the default Pueue queue. Snapshot source is `e65db67`;
D uses `runs/20261025T083717.764321Z-exposed-tip-D` and R uses
`runs/20261025T084049.478049Z-exposed-tip-R`. Model, weight-free geometry and
runtime identifiers are recorded in those manifests. Any future rerun needs its
own declared purpose; these completed one-attempt cases are not a tuning pool.


## Native pick benchmark: implementation frozen, stationary control running

Source `efe9757` implements one sensor-selected straight 5 mm lift, reusing the
frozen R3 detector, corrected exposed tool model and Isaac Lab DLS controller.
The benchmark keeps full I (300/930) for development and H (299/926, previously
known one-interior-removal geometry) reserved. Each case has a cumulative
600-second control/pick/audit budget and at most one attempt per version; at most
three independently reviewed development improvements are allowed.

The matched control holds exact joint targets for 3,600 steps. Job 1800 uses
`runs/20261025T093331.984420Z-stage2-pick-I-control`; a passing independent
control and remaining budget are required before any pick. Perception/control
receive configured virtual RGB-D, proprioception and unlabelled finger-contact
observations. Initial actor matching, native graph/root states and a reciprocal
source contact stream remain isolated evaluation instrumentation. No native
edge edit, grasp joint or post-initialization root pose write can establish a
pick. Engineered pose/clearance envelopes remain simulation assumptions.

Online held identity is reported separately from independently measured physical
extraction; UNKNOWN blocks transfer. Classification, reject transfer, insertion,
stacking and the integrated demo remain incomplete. No hardware readiness or
physical wrist-camera equivalence follows from this virtual-camera benchmark.

[Protocol](../experiments/stage2_pick_20261025/protocol.json),
[results ledger](../experiments/stage2_pick_20261025/results.json).


### Control audit correction before the first pick

Job 1800 captured all 3,600 stationary steps. All 48 physical/integrity checks
passed; its sole failing check was an evaluator bug that expected 6 by 5 world
indices in every layer. The frozen geometry alternates 5 by 6 and 6 by 5 world
indices. The original failed audit and raw capture remain unchanged. Maximum
source drift was 0.2083 mm and 0.002184 rad, with all native edges retained and
zero finger loads; this is source stability evidence, not grasping.

The independently reviewed correction derives the exact expected names from the
SHA-pinned geometry and re-audits the same capture without simulation. Before any
pick, the case limit is revised from 600 to 1,200 seconds based on the measured
218.550-second capture and 224.740-second audit. All 443.339 seconds already
spent remain charged, followed by the corrected audit and any future pick/audit.
Only that budget leaf may differ when accepting the exact old control protocol;
no force, geometry, motion or scoring threshold is relaxed. This uses preflight
correction round 1 of the three permitted improvements, without resetting the
pool. Alex has no matching Isaac runtime available per user confirmation; the
verified local runtime and default Pueue queue remain in use.


The audit-only correction (Pueue 1801, source `ca77991`) passes all 49 checks
on the same 3,600-step capture, without new simulation. Both independent agents
accept the corrected control; original job 1800 remains failed and unchanged.
Total charged case time is 673.090 seconds, leaving 526.910 seconds for one
intact-stack pick and its audit. This is stationary stability, with no extraction
or transfer established. The unchanged H case remains reserved.


The first I pick (Pueue 1802, source `ecd1dcf`) deliberately abstains before
motion. R3 emits 13 PRESENT and 17 uncertain hypotheses; all 13 PRESENT regions
pass local height/nominal overlap checks but fail the swept-envelope screen.
There is no selected target, contact measurement, holding or native extraction.
The first candidate has 85,162 unknown and 20 behind-first-return samples among
274,320 tested points. Behind a depth return means occluded or obstructed, not
proven solid penetration. The close view may clip the initial tool path.
Case runtime is now 817.321 seconds of 1,200, leaving 382.679 seconds.

One independently reviewed, at-most-30-second queued saved-data diagnostic is
being prepared: first candidate only, explicit FOV/invalid-depth/unresolved
categories, nominal finger-FK replay with disclosed mismatch, and projection-only
coverage for existing alternate presets. It cannot establish unseen free space
or authorize a pick. The same job checks an exact three-line audit cache change
on fixed zero/positive records, preserving every value, check and sample; no
full case reevaluation or performance search is included. No new camera or
manipulation parameter is selected before that evidence is reviewed.


Saved-data diagnostic 1803 (source `86381e9`) completes in 11.988 seconds with
zero physics steps. It exactly reproduces all 274,320 first-candidate samples:
85,162 outside the close image, 7,522 known-self samples, 181,616 measured free
rays, and 20 unresolved behind-return samples. Alternate-view coverage is
projection-only evidence; it does not prove clearance. The fixed 25-record audit
cache comparison is exactly equal with unchanged arrays. Its 0.784/0.125-second
old/cached timings are descriptive, not a general speed guarantee.

Round 2 adds only the existing wide-overhead preset as a measured geometry-safety
view. Close R3 detection and local height remain unchanged. Same-clock depth,
intrinsics/pose readbacks, restored close pose and positive per-point witnesses
are recorded and independently audited. Any sample without measured support
still abstains. The physics, controller and numeric limits are unchanged; the
accepted control is reused through an exact single-leaf protocol comparison.
The full 829.309 seconds already spent remain charged, leaving 370.691 seconds
for one retained I attempt and audit. This configured simulation view is not a
calibrated physical-camera claim. H remains reserved pending an independent I
pass. No extraction or transfer result follows from source approval.


Job 1804 (source `f17c6fd`) stops before clearance selection or measured motion:
`configured_pose.up_fallback_used` is a NumPy boolean that strict JSON cannot
serialize. This is INCOMPLETE_CAPTURE, not a grasp/contact or geometry result.
The original run is preserved. A local Python-bool conversion of that metadata
field leaves all camera math, science, controller and physics unchanged. The
independent evaluator/reviewer permit one repaired execution of the unexercised
round-2 trial, without resetting rounds. All 15.943 seconds remain charged:
845.251 seconds spent, 354.749 remaining of 1,200. H remains reserved.


The repaired round-2 execution, Pueue 1805 (source `5e1a4ca`), completes with
ABSTAIN and zero measured motion/contact steps. All 14 PRESENT hypotheses fail
the unchanged sampled clearance gate. For the first candidate, the close view
retains exactly the old counts; the measured wide view adds 5,899 unique free
witnesses but leaves 79,283 points without either witness. Its robot-occluded
returns cannot be interpreted as either free space or proven solid obstruction.
The 13-to-14 PRESENT change is one unchanged footprint whose far-end stud score
changes from .33905 to .37310 across the fixed .35 threshold; the cause of RGB
variation is unproven. R3 runs before the wide capture.

Both independent agents recommend approach reassessment, not a blind third
camera or unknown-as-free relaxation. Total spent is 1,026.551 of 1,200 seconds,
leaving 173.449; this all-rejected capture alone required 181.135 seconds. No
further trial is authorized in this pool. Round 3 remains unused; prior rounds,
failures and costs stay recorded. H remains untouched, and no grasp, extraction
or transfer has been established. Future transport/observation changes need
explicitly reviewed initialization/control compatibility and resource scope.


## Measured pregrasp RGB color classification

Pueue 1806, frozen source `cd0cc55`, completes the reviewed <=60-second saved-
image experiment in approximately 2.05 active seconds (1.740 inference, 0.032
audit). No new rendering, model, training or dependency changes are used. Five
human-labelled RGB rectangles provide screened float-Lab reference medians;
simulator colors/identities remain evaluator-only. Reference bricks are excluded
across every state/view, and other bricks keep one hash-defined evaluation split.

All 35 eligible non-reference PRESENT observations are classified correctly
across 14 distinct bricks, with zero wrong or unverified confident calls. The
all-UNKNOWN baseline has zero color coverage. Development has 18/18 correct
observations; reserved has 17/17 across six objects, but no visible reserved dark
red object, so reserved dark red is unvalidated. All five colors have correct
non-reference evidence overall. The forced-PRESENT mixed tan/ochre control
abstains specifically on mixed pixels; invalid-depth control has no confident
label. Settings were frozen before scoring and are not tuned afterwards.

Conditional color coverage is 35/35. Overall visible occurrence recall is 35/98
(35.7%); overhead is 35/73 (47.9%), while oblique supplies zero PRESENT targets
out of 25 visible references. Low recall remains a detector coverage limitation.
These are correlated views/states of the same arrangement, not independent-stack
generalization. A source color label does not establish held identity, physical
shade correctness, quality/defects or C920 focus. Stage2 still abstains, so this
is not actual color-to-manipulation integration. No further color tuning/job is
authorized for this frozen benchmark.

[Color settings and source](../experiments/stage1_color_20261025/),
[results](../experiments/stage1_color_20261025/results.json),
[representative overlay](../runs/20261025T112235.070296Z-stage1-color/predictions/f000_overlay.png).


## New annotated physical measurements, 2026-10-25

The user supplied a hand-annotated top view, archived with SHA provenance in
`experiments/final_workcell_20261024/measurements_20261025.json`. Source/target
32/48studs and approximate25/38cm sizes are reconfirmed; native8mm pitch and
plate geometry are preserved. Visual black tape overlap is updated16→14mm
(1.75nominal pitches), and yellow divider width15→20mm. Black width35mm stays.
Whole-stud working bounds still exclude two rows conservatively; this is not a
new validated insertion keepout or hardware calibration. The changed visuals
have not been rendered, and all earlier captures/results stay unchanged.

Base offsets21.5/26cm, board gap11.6cm, marker20versus22mm and fixed-camera
19cm offset/44cm height have unresolved endpoints/identity. Clarification is
pending; these numbers are recorded without inventing base-center or optical-
frame transforms. Bowl13/16cm offsets retain tentative endpoint interpretation.
The final-round initialization diagnostic source is independently reviewed,
but no job is submitted and its execution flag remains false while the scene
version is decided. No new simulation cost or manipulation credit is recorded.


## Final visibility hypothesis and explicit simulation-only reassessment

Job 1807 (source `decffbb`) runs on the immutable historical1805 scene, excluding
new tape/measurement changes. One actual-FR3-USD kinematic solve reaches the fixed
staging goal in 14 iterations. Independent nominal-FK agreement is 0.280um;
derived/live hand agreement is 0.444um (synthetic consistency, not calibration).
301 parts/930 native edges and zero post-native physics steps are confirmed.
The full-clearance diagnostic still FAILS: 37,773 of 149,040 samples lack a free
witness. All32 other checks pass; original full failure is preserved.

This closes the three-round all-path ray-certificate approach. Total charged
time is now1046.851 of the prospectively reviewed1800-second aggregate ceiling.
No dynamic grasp has been attempted. The independent team accepts source review
of one materially different, simulation-only finger-contact-guarded baseline:
fresh3600-step matched control, then one conditional I attempt, with raw
clearance remaining UNCERTIFIED_UNKNOWN. It is not a fourth visibility tweak,
a passing old predecessor, unknown-as-free, or another improvement pool.

All original physical/native/contact/pose/trajectory criteria remain unchanged.
The two finger streams do not monitor all arm contacts; whole-arm collision
safety remains unmeasured. An extraction pass would establish only that bounded
simulation outcome. Online held identity remains separate and UNKNOWN blocks
transfer. All source/model/force limits and prior costs are retained; no H,
automatic retry or budget extension is authorized. No exploratory job has yet
been submitted at this entry.

## Physical measurement clarification

21.5cm references the fixed FR3 front-center housing mark, and26cm the widest
outer lobe facing the printed board. Neither is silently treated as the robot
rotation axis. 11.6cm is a plate-to-printed-pattern boundary gap, not paper. The
20mm marker annotation is too imprecise to supersede the prior22mm nominal.
The third camera is a fixed C920, independent of both wrist cameras. Interpreting
its17cm lateral distance from the whiteplate bowl-side edge across toward the
robot side, the measured front-housing center is approximately TABLE
(-.32,-.04,.44)m. The native256mm-plate calculation is(-.318,-.042,.44)m; rounded
250mm dimensions give(-.315,-.045,.44)m. Those are arithmetic conventions, not
submillimeter physical accuracy. Position metadata is recorded, while viewing
direction, intrinsics and housing-to-optical transform remain unmeasured. No
new third rendered sensor or physical depth stream is claimed.


Fresh exploratory control1808 (source`4ab5ad2`) passes58/58 checks over3600steps
with301parts/930edges preserved,0.208293mm maximum source translation and zero
finger loads. Independent evaluator/reviewer accept exactly one conditional
I pick under unchanged source/science. Authoritative aggregate time is1298.525
of1800seconds, leaving501.475. Child termination after the complete marker is
bounded cleanup, not graceful shutdown; scientific capture/audit are complete.
This is source stability at the new q, not grasping or a ray-clearance pass.


The one-off exploratory pick1809 (source`e2ec2c9`) completes1711 measuredsteps:
783approach,620finaldescent,308closing. It stops on `unqualified_contact_right`
before the1.5N grasp trigger. Peak sampled loads are0.07895/0.02062N, far below
the2N abort ceiling. No detachment/lift/hold occurs;930edges and the301-part
source component remain. Both finger and reciprocal-source finite-body ownership
checks fail for one final-step event; flatness/normal/target association alone
do not establish BODY ownership. The original failure is retained.

This closes the one-off physical attempt with no retry authorized. Aggregate
time is1452.449/1800seconds. A single reviewed<=10s queued saved-data diagnostic
will compare fixed right/source points at1710/1711 (1709poseonly), exact authored
BODY/white/head distances and returned-cook representation distances. It cannot
rescale geometry, infer runtime offsets from None, loosen tolerances, promote
1809 to success or establish a new manipulation result.


Saved-point job1810 (source`a797518`) completes without truncation in0.454active
seconds (0.118script),0physics. At1710 neither right/source-right has a loaded
point; at1711 each reports three reciprocal points. One4.074mN point is1.300mm
from the authored BODY versus0.0511mm allowance, while metal/head are25.480/
18.716mm away. Both unchanged qualifiers reject it. Previous-pose sensitivity
is8.08um; the descriptive returned-cook fan distance is1.606mm, so neither that
representation nor a one-step pose correction establishes compatibility. The
underlying native reporting/cooking cause and effective offsets remain unknown.

Total charged time is1452.903/1800seconds. The failed grasp remains failed, with
no model/tolerance/force change or retry. The next narrow direction is read-only
inspection of installed native contact-report headers for exact known-robot
collider identity and per-point timing/impulse attribution. That could improve
component attribution, but cannot retrospectively pass the old finite-surface
gate or itself authorize new physics. Partner actor IDs must stay evaluator-only.


Installed primary source confirms `ContactEventHeader.collider0/1` separately
from actor IDs, with per-header point offset/count. BrickSim's native patch
forwards the wrapped contact callback, so a narrow observer may be possible
without a rebuild. Source availability is not tested runtime correspondence.
A future separately reviewed observation must establish unique same-step
point/impulse association and BODY/WHITE/HEAD attribution on positive/negative
fixtures, while exposing only known-robot roles online and keeping partner IDs
evaluation-only. No such probe, new physical run or ownership change has been
authorized by the source finding.


## Accepted Munich optical calibration import

The new report and33MB measured bundle are verified against the provided archive
SHA and all119file checksums, without executing exported software. Source-only
review confirms SDK RealSenseD435 serial943222073921, accepted12-pose PARK
hand-eye, fittedT_base_board and1280x720 alignedRGB/depth profile. This supersedes
older statements that no wrist optical calibration is available; application
to an active simulated sensor is still pending. Rejected webcam fits remain
inactive, and plate/bowl/Isaacworld registration is not supplied.

One<=10s queued metadata-only job1811 (source`0db955a`) passes251/251 checks over
all12actual poses in0.648active seconds (0.036check). It verifies rawactual
robot_afterq/O_T_EE/F_T_EE once-column-major, theUSD/URDFfixedframe relations,
base-relative modelFK and transform algebra without refit/exclusion. Maximum
USDconfiguredEE mismatch is5.08e-8m: computational model agreement, not surveyed
physical accuracy. Fixedboard closure reproduces1.330mmRMS/1.771mmmax and0.192°
rotationRMS. These are internal consistency, not placement accuracy.

The passive registry is
`experiments/final_workcell_20261024/calibration/munich_realsense_20261025.json`.
It preserves accepted base/board and camera transforms, plus explicit model
hand/color and modifiedgrip/color bridges. Calibrated configuredEE103.4mm and
modifiedgrip117.5576mm are never interchanged. Saved depth is already float32
meters/RGBaligned, zero invalid: use COLOR K/extrinsics with no extra scale.
Unknown world/base, plate, bowl and webcam registrations stayNULL.

No active camera, renderer, base placement, collision model, contact guard or
hardware setting changes follow from this import. It does not resolve the
failed contactpoint in1809 or validate close-range depth/held-brick registration.


## Native collider reporting probe

One independently reviewed observation-only probe, job 1812 (source `3887f8e`),
stopped after its first unloaded quiet step. Position matched exactly, all three
contact views reported zero load, and the 301-part/930-link source remained.
No BODY, WHITE or HEAD contact control ran, so native reporting semantics remain
unvalidated. The marker records an aborted sequence, not contact success.

The orientation guard reported 0.000272237 rad from a float32 quaternion norm.
Saved literal synthetic reproduction identifies arithmetic cancellation: casting
both quaternions to float64 and separately normalizing yields 2.98e-8 rad. The
repair retains the same 1e-4 rad threshold, with synthetic rotations on either
side checked. The original capture and its failed guard are not overwritten.
The independent audit also failed JSON serialization of a NumPy boolean; a
value-preserving scalar/container conversion repairs output only, without
changing acceptance checks. A separately reviewed audit-only replay will complete
the failure record; no physical probe retry is authorized by these repairs.

Authoritative 1812 Pueue start/end charges 16.199330879 seconds, including launch
overhead; the inner supervisor reports 15.796132840 seconds. Both are preserved.
The upward-corrected cumulative contact clock is 1469.101895342/1800 seconds.

Saved-audit job 1813 (source `9076e91`) completes successfully as an audit and
reports `UNKNOWN`, observation contract false. It measures zero loaded frames
for all three roles. The single-frame failure remains kinematic readback; the
capture/role/release completion checks also fail. The terminal-source conjunction
fails because its completion watchdog flag is false after the abort, not because
the measured 301 parts or 930 links were lost. No physics was run by this audit.
Its 0.524941879-second full Pueue duration is charged above the prior cost,
yielding 1469.626837221/1800 seconds. No repeated capture or grasp is implied.

The prospective correction was independently reviewed before execution: same
benchmark and physical/matching parameters, original plus exactly one corrected
capture, no new pool, no further retry. Job 1814 (source `2c8852d`) completes 286
steps and validates the observation contract: all 47 aggregate checks and every
per-frame check pass. LEFT BODY has 7 loaded frames/21 points, WHITE 18/66 and
HEAD 17/47. All 134 loaded points have unique native-event matches and reciprocal
cube observations. Peak loads are 0.298791, 0.220727 and 0.218577 N respectively.
All three release unloaded; RIGHT is an unloaded control, not positive evidence.
The full source retains 301 parts/930 native links, with unchanged physical
properties, cook identities and settings. Both independent agents accept this
limited result. Frames/points are correlated, not separate grasp trials.

This establishes low-load native/tensor component attribution for these three
LEFT fixtures. It does not establish finite-surface fidelity, the component
responsible for the old 1809 point, higher-load holding, actual extraction, or
hardware-equivalent tactile feedback. The original point guard is untouched and
the manipulation proceed gate remains false. Future use of component attribution
needs an explicit control/feedback reassessment; it is not an automatic grasp
retry or a substitute for rendered brick perception.

Pueue 1814 charges 39.118509011 seconds versus 38.827296949 supervised seconds.
The retained total is 1508.745346232/1800 seconds, leaving 291.254653768.
The two-capture observation phase is closed; no further automatic retry exists.
Machine-readable history and reproduction are in
`experiments/stage2_collider_probe_20261025/results.json` and its README.


## Current closing failure attributed without changing task control

Job 1815 (source `a32ee7d`) performs the prospectively reviewed closing-only
physical simulation execution: original 1809 RGB-D selection, q, controller,
geometry and guards; native headers strictly private; no lift or hold. It
reproduces `unqualified_contact_right` at step 1711, after 308 closing steps,
on the same sensor candidate and privately bound source. No diagnostic force
or step limit is reached. The old contact guard remains failed.

The independent audit passes all 41 observation checks and every frame. All 101
LEFT, 3 RIGHT and 104 reciprocal source loaded observations map uniquely. The
current rejected point belongs to RIGHT BODY mesh_3 and the selected layer-9
brick, with the same event seen from the reciprocal source stream. Its finite
authored BODY distance is 1.300374 mm against a 51.0849 um allowance. Flat-plane
distance is 8.0617 um, normal dot is 0.999999794, and rendered-candidate spatial
association passes. Metal and head distances are 25.480 and 18.716 mm. Both
independent agents accept this limited current-run finding. It identifies a
BODY-generated point rejected by the finite authored-surface predicate, not a
metal/head collision or a secure grasp. The underlying point-location/cooking
cause and effective offsets remain unmeasured. It does not relabel 1809.

Native identities never enter task decisions. The 301-part/930-link source and
physical properties remain unchanged. No grasp, extraction, transfer or insertion
has passed. Full Pueue 1815 duration is 158.135588985 seconds versus 157.875903051
supervised seconds. Retained total is 1666.880935217/1800 seconds, leaving
133.119064783. Another full same-path capture/audit does not fit this ceiling;
any next physical experiment requires an explicit prospective resource decision
with all previous costs retained.

The user reports successful Franka Desk closure to 14 mm and confirms that simple
finger position control suffices. Existing simulation already uses position
targets; its 1.5 N threshold was a phase trigger, not a force-control framework.
No complex grasp motion or RL is indicated by this failure. Desk setting versus
measured gap and the tip version used remain pending clarification. Source-only
kinematics give the nominal custom-pad gap `q1 + q2 + 2.81338 mm`; this is not
calibrated firmware behavior. The observation and conditional joint targets are
recorded in `experiments/stage2_closing_diagnostic_20261025/hardware_closure_reference.json`.

The smallest reviewed next policy direction is an explicitly unverified
grip-plane compatibility screen retaining the existing plane/normal/spatial and
forbidden-metal/head distance vetoes, while removing finite BODY proximity as an
ownership assertion. It must never claim the point became geometrically correct
or use native labels online. Actual BODY-only contact and native grasp outcomes
remain independent evaluation requirements. No such policy change or subsequent
physics run is implemented or authorized by the diagnostic result itself.


## Retrospective grip-plane screen comparison

One pure candidate removes only finite BODY-surface proximity from compatibility.
It retains the same abs(separation)+50 um grip-plane allowance, normal dot >=0.9,
metal/head clearance beyond that allowance+100 um, and rendered association.
Its API contains only numeric robot CAD, point/normal/pose and association; no
BODY mesh, native label or source identity. Compatible means UNVERIFIED, with
ownership and pick permission false. Existing task control is unchanged.

Initial saved-data job 1816 (source `866f332`) stops because its manifest omitted
an empty opposite-finger buffer the frozen evaluator also reads. Its incomplete
result and 0.873208584-second Pueue cost remain. A prospective manifest-only
repair adds exactly 18 missing dependencies, retaining candidate/scorer bytes
and all scientific settings. JSON-only completeness checks cover all 141 needed
contact files within the resulting 156 pins. No parameter tuning occurs.

Corrected job 1817 (source `31434ba`) completes all 1920 checks. Primary counts:

| Saved case | Native evaluation label | Points | Old compatible | Candidate compatible |
| --- | --- | ---: | ---: | ---: |
| LEFT fixture | BODY | 21 | 21 | 21 |
| LEFT fixture | WHITE metal | 66 | 0 | 0 |
| LEFT fixture | HEAD | 47 | 0 | 0 |
| Closing reproduction | BODY | 104 | 103 | 104 |

The only recovered point is the current step-1711 RIGHT rejection. No BODY point
is lost, no UNKNOWN appears, and all 113 forbidden fixture observations remain
incompatible. The 238 reciprocal observations agree but are verification only,
not extra independent positives. Fixture association was deliberately forced
true to stress the component veto; closing uses the original rendered spatial
association. Both independent agents accept the limited comparison. It was
proposed after seeing 1815 and is development/regression evidence, not held-out
generalization, whole-arm safety, actual BODY ownership or grasp success.

1817 charges 1.151101580 full Pueue seconds versus 0.932660199 supervised seconds.
Retained cumulative contact cost is 1668.905245381/1800 seconds. The two-job saved
comparison is closed. A future position-controlled native pick needs a separate
prospective policy/resource review; no such execution follows automatically.


## Position closure and first bounded lift — current result

Job 1818 reaches the nominal 14 mm endpoint with about 0.990/1.237 N pad
loads but abstains at the old 1.5 N phase trigger. Job 1819 preserves that
force-confirmed branch and tests one explicitly separate position-candidate
admission: three fresh bilateral/contact-resisted endpoint samples, then the
unchanged bounded straight lift. Its admission passes at step 1853 without
fabricating force confirmation. Step 2113 aborts on finger speed and nonlateral
left BODY contact. Target rise is 0.110 mm; all 930 native links remain.
The real operator's successful Franka Desk 14 mm closure supports keeping a
simple position primitive; model nominal gap is not calibrated Desk readback.

Independent evaluator and reviewer accept this negative physical result. The
one-round experiment is closed; no stronger squeeze, relaxed contact checks or
automatic repeat follows. Full Pueue 1819 duration is 210.190672297 s; the
retained aggregate is 2054.260747261/2200 s. Any further physics requires a
prospectively frozen reassessment, preserving that ledger.

Source `a2e1a2f`, results record `777402a`; snapshot
`runs/20261025T151026.796083Z-stage2-position-candidate-I-r1`.


## Free-body retention and position-only dwell — comparison closed

Known free-coupon control1821 passes1500steps without finger load, coupon drift
or source connection loss. Its pick advances at step424 after4 endpoint commands
on the old1.5N branch; retention fails before completion. One independent
bookkeeping defect in its force-record dictionary is fixed in source/synthetic
tests; the original1821 audit and physical failures are retained.

Timing-only1822 uses force crossing424 solely as telemetry and admits the lift
at450 after30 endpoint commands. The original matched control is reused through
pinned source/protocol and exact physical/proprio/fixture/observer evidence.
Retention still fails:2.808mm/3.312° relative drift,0.041mm final initialization-
relative rise, no completed lift/hold. One frame has UNKNOWN native-point
matching; do not claim complete contact ownership. Both trials are centered
fixtures, not sensor-selected extraction or generalization evidence.

Independent reviews close this one improvement without more tuning. All costs
remain retained:1821 full232.401402697s and1822 full100.531788056s bring the
aggregate to2388.038652171/2500s. Next investigate effective runtime material/
contact offsets; no stronger squeeze, tilt, new controller or hardware action
follows automatically.


## Effective contact/material readback — configuration evidence only

Startup-only1823 reuses the immutable1822initializer and replaces its trial hook.
All60 checks and9getter arrays pass with zero measured steps or state changes.
Each finger returns5 unordered material slots: four[.5,.5,0], one[2.5,2,0].
The coupon returns2 uniform[.5,.5,0] slots, differing from its unbound USD
collider-authored scalar attributes. All returned shape offsets are1.3625mm
contact and0rest. Do not identify a BODY row by expected friction or infer
measured pair traction.

The2.725mm offset-sum scale is comparable to3.083mm nominal overlap, but this
is not penetration, stand-off, exhausted band or a causal retention finding.
A fixed BODY-only100µm contact offset is a reviewed proposal for a later
sensitivity test, not an implemented fix; coupon unchanged means pair distance
would remain about1.4625mm. No physical retry follows this readback.

Full1823Pueue cost15.679833137s brings the retained total to2403.718485308/2500s.
See [raw configuration result and limits](../experiments/stage2_contact_readback_20261025/README.md).


## BODY-margin sensitivity — control/configuration pass, early-motion censored

1824 authors only the two known BODY contact offsets to100µm. Initial/terminal
readbacks corroborate one changed slot per finger, with coupon/rest/materials
unchanged and no row-to-component inference. A fresh1500control passes; the
position-only pick admits at450/30, then stops at488 solely on actual finger
speed. Relative error is0.197mm/0.938° and final rise0.077mm in the short prefix.
There is no5mm lift/30hold or full retention verdict. No claim that the old
normal-contact issue is fixed is supported.

Improvement2of2 closes without retry or offset tuning. Static review finds no
qdot units/index bug: the2mm/s actual cutoff came from an earlier slow-contact
diagnostic, independently of the1mm/s commanded ramp and implicit-drive asset
limits. Any revised criterion is a separately frozen engineering reassessment;
1824 remains FAIL/CENSORED. Full190.508734634s charges the retained aggregate
to2594.227219942/2800s.


## Fixed-target finger response — final fixture comparison closed

Job 1825 removes the earlier speed censoring through the reviewed prospective
lift-only criterion. The unchanged position admission occurs at step 450 after
30 endpoint commands. Maximum lift finger speeds are 3.947/3.991 mm/s, below the
20 mm/s ceiling; all model, margin and control-compatibility checks pass.

Retention nevertheless fails for 151 frames: maximum coupon–TCP drift is
1.861 mm / 7.946°, final initialization-relative rise is 0.854 mm, and the
capture aborts at step 740 on an unqualified right contact. There is no completed
5 mm lift or 30-step hold. This is a physical retention failure in the declared
fixture, not proof that the real Desk 14 mm method fails. The simulated custom-pad
gap and gripping band are not calibrated to that hardware grasp.

Independent evaluation and review close the third/final fixture comparison.
Reconcile actual jaw-gap and gripping-depth mapping before further physics;
no fourth cutoff, offset, force or trajectory variant follows. Full Pueue cost
88.718362536 s brings the retained total to 2682.945582478/2800 s.
Source `9c8dbb4`, snapshot `runs/20261025T165816.000989Z-stage2-finger-response`.
See [result and limitations](../experiments/stage2_finger_response_20261025/README.md).


## Pregrasp color handoff — saved replay integration passes

The current sensor-selected runner now has an opt-in source-color hook. It
retains the exact close-view RGB-D/calibration, classifies the final selected
candidate with unchanged job-1806 references/settings, and records frame/time/
content binding. Abort, slip and capture exceptions invalidate the current
attempt while preserving its source observation. Held identity remains UNKNOWN;
no color result grants transfer permission. Selection and motion are unchanged.

Job 1826 (source `2882ac3`) verifies 116 exact prior classifier outputs and all
10 invalidation controls, including the actual saved 1819 final selection and
its recorded abort. The selected tan brick was a calibration reference, so this
adds no held-out accuracy evidence. The prior 35 non-reference correct / 98
visible coverage remains unchanged. A tiny test exercises the actual Sensors
helper without Isaac; no fresh live render, grasp or transfer was run.

Full default-Pueue duration is 2.683540874 s within the separate 30 s saved-replay
budget. The closed retention ledger remains 2682.945582478/2800 s. Source/model
analysis still needs a physical bridge between Desk width, actual pad gap and
gripping depth before more contact physics. See
[handoff result and artifacts](../experiments/stage1_handoff_20261025/README.md).


## Coupon material runtime check — startup values verified, no new grasp trial

Startup-only1828 applies the opt-in declared-material helper only to an isolated
coupon using the immutable1822 initializer and1823 baseline. Expected unordered
rows `[.5,.4,.1]` / `[1,.8,.2]` are returned; fingers/offsets/rest and all audited
state/properties/native inventory remain unchanged. The original audit remains
FAILED on API-insertion order and the new Scope's empty built-in relationship.

Separate saved-JSON-only adjudication1829 corrects precisely those metadata
semantics, preserving all other criteria and all original inputs. Its75 contract
checks and15 runtime comparisons pass. No simulator rerun or physical tolerance
change occurred. Collider-row identity and pair traction remain UNKNOWN; this
is not retention, grasp, hardware equivalence or global model adoption.

Full costs14.646749434s +.538284444s bring the retained ledger to
2698.130616356/2800s. No fourth fixture trial follows. The remaining grasp-width/
depth mapping question is unresolved. See
[readbacks, both audits and provenance](../experiments/brick_material_runtime_20261025/README.md).


## Corrected-material retention regression — closed failure, grasp reference needed

Job1830/source2f20f7a first passes the full1500-step corrected-model control,
same-job bridge and combined declared-material/100µm/geometry/property/native
checks. The single pick admits at450/30endpointcommands, then aborts at716 on
an unqualified right contact. Relative holding limits fail129frames, reaching
1.687mm/6.80°; final rise.766mm; no completed5mm lift or30-step hold. Sampled
forces remain below2N and the reviewed finger-speed limits pass. This is an
uncensored retention failure. Smaller observed maxima versus1825 do not prove
improvement because this trial stopped earlier.

The material authoring defect was real and is corrected in this isolated test;
correcting it did not establish holding. Native clutch resistance is not the
sole cause because the coupon is isolated. No additional source-supported model
or controller defect, new parameter choice, downstream implementation, or
training experiment is currently justified by the reviewed evidence.

Full Pueue216.692133457s retains2914.822749813/3000s. The three original fixture
improvements and this one-off regression remain closed with no retries. The
repeated missing working-grasp width/depth reference is the current dependency;
the six-stage simulation objective remains incomplete. See
[full result, audits, configuration and provenance](../experiments/declared_material_retention_20261025/README.md).
