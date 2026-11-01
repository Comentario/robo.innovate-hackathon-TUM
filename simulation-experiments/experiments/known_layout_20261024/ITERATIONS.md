# Iteration record

## Historical separation

- Commit: `2a3431a` — workcell source and historical pretrained experiment.
- Evidence: 18 images, two pretrained pairs, canonical Pueue job 1666; neither
  pair provides reliable individual-brick recall.
- Larger weights, generated runs and original resources remain on disk with
  locations/hashes retained. No deletion or unrelated cleanup.
- Simulation comparison was incomplete; exact original 360-brick geometry is
  still a dependency, not silently approximated.

## Geometric baseline v0

- Status: evaluated; fails the coverage requirement and is not accepted as a
  demonstration baseline.
- Protocol checkpoint: `1dfeae8`; initial algorithm checkpoint: `7d6ae08`.
- Scope: manual coarse global registration, supplied observed grid/plane,
  projected stud/brick geometry, bounded refinement, grayscale stud and edge
  evidence, local lower-pattern counter-evidence, three-way decisions.
- Evaluation source: `2ccb3ac` (algorithm `7d6ae08`), Pueue **1667**, snapshot
  `runs/20261023T234525.001300Z-known-layout-v0-development/`.
- Fixed development batch: four images × ten cases. Nominal: 0/112 positive
  faces confirmed present; 106 uncertain and six unmatched. All six
  supplementary missing-face cells uncertain. No merges, duplicates or labeled
  lower-fragment selections; zero wrong decisions is explained by zero decisive
  coverage, not claimed reliability. All non-flat sensitivity cases also have
  zero confirmed present. Flat-image sanity: zero confirmed present.
- Projected-stud residual median 5.97 px, p90 9.10 px (32/32 manual development
  stud references), with no global registration correction. Median observability
  per image was 0.61–0.84, while accepted stud support was almost absent.
- Dominant failure: insufficient image-supported stud confirmation prevents both
  registration refinement and decisions, despite visible boundaries. The
  development registration error exceeds the initial local search radius;
  feature normalization could also suppress true studs. These explanations
  must be separated before changing the algorithm.
- Next bounded diagnostic: evaluate the unchanged feature at the 32 development
  reference stud centers, strictly in evaluation. This does not provide reference
  locations to the production perception path. Planner and reviewer both
  requested the diagnostic before proposing a single improvement.
- Evidence: `results/v0_development/`; large overlays/predictions stay in the
  frozen run. Held-out D remains reserved.
- Static validation: seven small tests passed, including the rule that a blank
  image with a supplied layout cannot confirm present or missing. This is not
  a substitute for the independent image batch.

## v0 feature diagnostic and proposed v1

- Diagnostic: Pueue **1668**, source `94cd781`, immutable run
  `runs/20261023T234904.706461Z-geometry-v0-stud-diagnostic/`.
- Evaluation-only probes at all 32 development reference stud centers: every
  fixed-center v0 score was zero; even the existing local search reached only
  0.113 maximum, below the frozen 0.35 feature confirmation threshold.
- Observability median was 0.786. Radial-gradient mean was below the
  whole-patch mean plus two at every historical marked location; the original
  concentration formula therefore clipped the response at those marked
  locations to zero. A later audit limits their interpretation as centers.
  Merely expanding registration search is not supported as the first change.
- Hypothesis: normalize radial alignment against gradient magnitude on the
  same annulus instead of comparing to the seam/shadow-contaminated whole-patch
  mean. Use the isotropic-gradient null (2/pi), angular support relative to the
  robust local median, and the existing observability gate.
- Proposed single code change: replace the stud response calculation only.
  Radii, search bounds, global registration and decision thresholds remain
  unchanged. A fixed 0.5 gradient-unit weak-gradient/noise floor is documented.
- Independent reviewer endorsed this bounded test. Acceptance still requires
  useful decision coverage with controlled errors on the identical development
  protocol; nonzero feature scores alone do not establish improvement.
- Diagnostic evidence: `results/v0_stud_diagnostic/`. Implementation and
  post-change measurements are pending this checkpoint; held-out D remains
  unopened for tuning.

## v1 radial-coherence result — retained working baseline

- Pre-change evaluated checkpoint: `817dbdc`; implementation: `4106bdc`.
  Pueue **1669**, snapshot
  `runs/20261023T235320.974842Z-known-layout-v1-development/`.
- Change: the single radial-feature correction described above, selected by an
  explicit configuration field. V0's formula remains reproducible. All radius,
  search, registration and decision thresholds were unchanged; frozen
  references/protocol hashes were verified unchanged.
- Nominal development: **37/112 correct present (33.0%)**, up from 0/112;
  69 uncertain and six unmatched. Zero wrong present/missing decisions.
  Conditional present precision is 100% on 37 confirmations, not a guarantee.
  All six supplementary missing cells remain uncertain. Blank confirmations: 0.
- Correct-present sensitivity counts out of 112: dark 17, bright 47, rotations
  -5/+5 degrees 29/30, x initialization -4/+4 px 42/27, y -4/+4 px 33/25.
  No wrong confirmations were measured in these cases. Coverage is inadequate
  and lighting/alignment sensitivity remains material.
- Registration residual median 6.31 px (32 references), compared with 5.97 px in
  v0: no localization improvement is claimed. Image-derived stud peaks matched
  14/32 selected references within 8 px, median 6.25 px for those matches only.
- Decision: **retain** the small feature revision as a better working baseline
  because it produces useful correct confirmations without measured false
  confirmations. It does **not** meet the 80% coverage or missing-decision
  demonstration targets. The complexity is justified by the measured gain,
  not by the feature's mathematical plausibility alone.
- Dominant remaining failure: incomplete stud support/low mean evidence under
  the coarse geometric registration. Image 10 is particularly weak. Strong
  registration consensus sometimes results in zero correction; assess its
  capture/fit bounds before proposing one bounded registration revision.
- Evidence: `results/v1_development/`; held-out D remains reserved.

## Reference audit and proposed v2 confidence simplification

- Independent evaluator and reviewer found that some historical stud marks
  lie on cap rims/highlights, not validated centers. All labels, hashes and
  scoring rules remain unchanged. Stud distances must be reported as distances
  to historical marked points, not true center accuracy. This also limits the
  true-center interpretation of the v0 diagnostic. Face polygons/decision
  comparisons remain usable at their documented annotation uncertainty.
- Reconstructing v1's saved feature offsets disproved the suspected translation
  norm-limit failure: image 1's 117-inlier proposal and image 7's 82-inlier
  proposal were both zero. No registration-bound change is justified by that
  mechanism, and none was implemented. Audit evidence is in
  `results/reference_audit/`.
- One predeclared confidence diagnostic on the frozen v1 nominal outputs found
  11 additional positive faces passing every present-condition except the
  whole-face mean-stud threshold, with none of the six supplementary missing
  faces passing those other conditions. This is a diagnostic upper bound,
  not an evaluated post-change result or a held-out claim.
- Hypothesis: six supported studs including both end rows, edge support,
  observability and top/lower counter-evidence already provide the intended
  partial-pattern criterion. Requiring the mean of all eight scores to exceed
  a higher threshold redundantly rejects some such patterns.
- Proposed v2: remove only the mean-score decision predicate, keeping that score
  visible diagnostically. Preserve all other feature, registration and decision
  conditions and the exact evaluation protocol. The independent reviewer
  endorsed the test. Expected nominal gain is only about 48/112, still below
  demonstration acceptance. Accept only after the full sensitivity/blank batch
  confirms useful gain without false-confirmation regressions.

## v2 result — rejected

- Pre-change evaluated checkpoint: `8f9a9d1`; implementation `1554d5c`.
  Pueue **1670**, snapshot
  `runs/20261024T000004.429624Z-known-layout-v2-development/`.
- Actual nominal result matched the diagnostic: **48/112 correct present
  (42.9%)**, zero nominal wrong confirmations, all six missing-face cells still
  uncertain. Blank-image confirmations remained zero.
- Correct-present sensitivity counts increased to dark 24, bright 58,
  rotations 40/41, x initialization 49/39, y initialization 48/39.
- Regression: the +4 px x-initialization case introduced one new confidently
  present unmatched candidate (`img_10`, `c1r4`). Case precision became
  39/40 = 97.5%. Its y extent 208–251 px differs materially from the reference
  face's 191–237 px; the independent reviewer did not excuse this as harmless
  annotation rounding. All fixed labels and rules remain unchanged.
- Decision: **reject and revert v2's production rule change** under the
  predeclared no-false-confirmation-regression expectation. Do not retroactively
  weaken that expectation to accept the nominal gain. Retain v1 as the best
  evaluated baseline. The failed source commit, exact evaluated configuration,
  predictions and measurements remain available for reproduction.
- Complexity assessment: removing a gate was simple but its measured protection
  against a misregistered candidate mattered. No further gate relaxation is
  justified. The missing-face goal also remains unmet.
- Evidence: `results/v2_development/`. Held-out D remains reserved.

## V2 rollback and proposed v3 illumination consistency test

- Rollback checkpoint: `e4bb5d7`, verified byte-for-byte restoration of the v1
  algorithm/documentation/test state preceding v2. The rejected v2 configuration
  is no longer in the active configuration directory; its exact copy remains
  with the failed experiment and in Git. Seven small tests pass.
- Independent analysis of saved v1 expected-site pairs found that changing
  brightness by 0.7/1.3 changes weighted stud responses substantially while the
  response divided by sqrt(observability) is nearly invariant. Dark paired
  response ratio median 0.8555 becomes 0.9960 without that weight; bright
  1.0896 becomes 0.9999. These are image-output diagnostics, not changed labels
  or a parameter sweep. Evidence: `results/v1_lighting_diagnostic.json`.
- Hypothesis: the fixed absolute contrast scale in the feature weight causes
  much of the measured lighting sensitivity. Test ROI-relative feature weighting
  based on the median local contrast at all projected stud sites. Retain the
  original absolute observability decision guard and every v1 structural,
  registration, edge and mean-score decision condition.
- Proposed single change: alter only the feature's observability weight. The
  reference-contrast denominator floor is 8.75 gray levels, derived from the
  existing 35 × 0.25 absolute observability guard; no image-specific exceptions.
- Planner and reviewer endorsed the bounded test. Predeclared acceptance:
  improved lighting consistency/useful coverage without false-present or blank
  regressions. The previously misregistered `c1r4` gets no exemption.
- If this test fails, restore v1 and report its measured limits. The remaining
  irregular layer geometry, unknown true plane height and unvalidated center
  references are concrete dependencies; do not add per-strip warps, relax more
  gates, or use held-out D to chase the acceptance target.
- Diagnostic wording correction: original 1668 JSON fields containing
  `true_center` mean historical marked locations. They are not validated true
  centers; the raw evidence and frozen references are preserved unchanged.

## v3 illumination-weight result — rejected

- Pre-change evaluated checkpoint `727dbe7`; implementation `e8ab714`.
  Pueue **1671**, snapshot
  `runs/20261024T000755.717569Z-known-layout-v3-development/`.
- Change: only the relative feature contrast weighting described above. The
  absolute observability guard and every v1 decision/geometry/search setting
  remained intact. No labels or scoring rules changed.
- Nominal development: **52/112 correct present (46.4%)**, zero nominal wrong
  confirmations, six missing-face cells all uncertain. Lighting consistency
  improved substantially: dark 52, bright 53, compared with v1's 17/47.
  Blank confirmations remained zero. The proposed mechanism has real evidence.
- Regression: `img_10`, +4 px x initialization again confirms the spatially
  misregistered `c1r4`. Its new mean score 0.454 exceeds the retained 0.45
  threshold. Case precision is 53/54 = 98.15%. This is the same failure that
  rejected v2, not justification for tuning a threshold for that image.
- Additional lower-fragment proxy flag: `img_3`, -4 px y initialization,
  `c4r3` covers 50.77% of the labeled fragment envelope. Its center is outside
  that fragment and it also matches a positive face, so this borderline proxy
  is not presented as proof of a true physical layer misselection.
- Decision: **reject and revert only v3** under the predeclared no-confident-error
  regression condition. Preserve its useful lighting result and exact evaluated
  source/configuration. V1 remains selected from development evidence.
- Stop assessment: confidence and photometric changes repeatedly promote the
  same wrong spatial hypothesis. The next defensible step requires a verified
  reference plane/current layer geometry and reliable feature-center reference,
  rather than per-strip warps or another confidence exception. Planner,
  independent evaluator and reviewer recommend pausing algorithm changes after
  auditing the already selected v1 on held-out group D.
- Evidence: `results/v3_development/`; held-out D has not yet been used.

## Final restoration, held-out audit and pause

- Exact v3 rollback checkpoint: `12dd890`. Algorithm, implementation README
  and tiny sanity test were verified byte-for-byte against the pre-v3 selected
  v1 state; v3's active configuration was removed. Historical results remain.
  Seven small geometry/sanity tests and five scorer tests passed; frozen
  reference/protocol hashes were unchanged. Subsequent edits are reporting only.
- V1 was selected before opening group D. Final Pueue **1672**, source
  `12dd890`, snapshot `runs/20261024T001228.831310Z-known-layout-v1-heldout/`,
  completed two views × ten fixed cases. No tuning followed these results.
- Nominal held-out: **21/54 correct present (38.9%)**, 33 uncertain, zero
  unmatched positives and zero measured incorrect confirmations on scored
  regions. Two additional present decisions lie in excluded ambiguous regions.
  Per-view coverage: img_13 14/28, img_16 7/26. No held-out missing-face labels
  exist, so missing accuracy cannot be evaluated there.
- Correct-present sensitivity /54: dark/bright 18/22, rotations 21/21,
  x initialization 24/11, y initialization 12/21. Flat confirmations zero.
  One rotated AABB lower-fragment overlap proxy also matches a positive face;
  this is not proof of a physical layer error. No further model selection.
- Decision: retain v1 as the best working baseline, **not demonstration
  accepted**. Nominal development remains 37/112 present and 0/6 missing.
  The planner, independent evaluator and reviewer explicitly agree to pause
  for verified current-layer/reference geometry, valid center references and
  calibration. The hidden 360-brick translations remain a simulation blocker.
- Final evidence and reproducibility: `results/v1_heldout/` and `REPORT.md`.
