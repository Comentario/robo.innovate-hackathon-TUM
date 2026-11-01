# Bounded RGB ridge-chain experiment

The planner/implementation agent and independent reviewer agreed on a small
edge-proposal method before implementation. An independent evaluator owns
scoring and immutable references. The orchestrator freezes source/configuration
before one all-18-image batch. No threshold sweep or automatic follow-on method.

The selected variant uses RGB line segments without requiring SAM ridge masks.
Saved SAM and dimension-filter results remain unchanged comparison baselines.
There are no annotation polygons, historical manual registrations, stud marks,
camera extrinsics, simulator state or class labels in chain construction.

1. Merge supported collinear RGB line segments and pair ridge sides into
   projective strip hypotheses. Keep endpoint and side-segment evidence.
2. Estimate stud pitch from the strip's image profile, checked against its
   two-stud width and explicit subharmonic alternatives. Reject weak/ambiguous
   scale rather than choosing a dominant SAM mask-size population.
3. Jointly search a small range of integer counts and shared phases using both
   currently observed ends, surviving segments and distributed image evidence.
   Keep alternatives/margins. Perspective is modeled by the local quadrilateral
   warp, not by a calibrated camera or a global baseplate grid.
4. Keep that one chain phase through gaps. Internal seams can verify boundaries
   but are not required at every predicted boundary. Label boundaries observed
   or model-inferred separately. Unknown original full extent stays unknown;
   no six-brick count or missing end bricks are imposed.
5. Classify each modeled slot from distributed cap/side/contrast evidence.
   Perpendicular continuation competes with parallel-face presence. Interior
   low-support gap runs can use nearest supported present anchors on both sides
   without resetting phase; lower surfaces alone cannot establish absence.
   Ambiguous ridge identity, scale or phase leaves decisions uncertain.

The global numerical settings are recorded in `config.json` before batch use.
Output confidence is diagnostic, not a calibrated probability. Every result is
an image-space hypothesis with physical layer/accessibility unverified.

Evaluation uses the unchanged six-view 166-face/14-ambiguity/23-lower-fragment
references and six supplementary image-plane missing-face references. It
separates exact historical present-only box scores from joint tri-state slot
matching, known-reference missing precision and unverified missing claims.
Boundary/phase/strip consistency are conditional proxies where existing polygons
support them, not invented chain or stud-center ground truth.

All batch processing/scoring runs in default Pueue from a stable snapshot using
existing dependencies. No SAM rerun, new framework, training, simulation, ROS,
manipulation or hardware control is included. Stop after measured comparison,
overlays, reproducibility information and limitations are reported.
