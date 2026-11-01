# Blending criteria v0.1 — team decisions

## Official basis

Source consulted on 2026-10-18:
https://roboinnovate.mirmi.tum.de/hackathon/hackathon-2026/ — challenge #08, Marmon.

The goal is to form visually balanced packages from fired bricks that have natural color
variations. Soft blends and deliberate color mixes are both allowed; the appearance of the finished
wall matters too. Textured and heterogeneous surfaces are mentioned. No proportions, quality
thresholds, dimensions or specific robot are published for this challenge.

## Provisional, configurable policy

1. **Global recipe:** weights per category, normalized to proportions. The examples use thirds only
   to demonstrate the system. Without a recipe, the API keeps the inventory's proportions.
2. **Availability:** never repeat IDs and never exceed stock. The demo uses `reject`: refuse if the
   rounded recipe cannot be met. The alternative, `redistribute`, substitutes according to
   availability and reports the deviation.
3. **Pattern:** `mixed` assigns quotas per layer and row and then avoids equal neighboring
   categories; `smooth` prioritizes reducing shade differences between neighbors. Balance across row
   and layer is sought afterwards. Both are greedy heuristics, not global optima.
4. **Sequence:** complete layers from the bottom up, in row and column order. The execution adapter
   has to validate support, grasp and accessibility.
5. **Evaluation:** L1 deviation from the recipe, same-shade neighbors, and, in smooth mode, the mean
   shade distance between neighbors. These are diagnostic metrics, not official scores or acceptance
   certificates.

`config/mixed.json` and `config/smooth.json` allow the recipe, shape, mode and shortfall policy to be
changed without editing code. The example shade values are synthetic, between 0 and 1; perception has
to supply a calibrated scale.

Reducing local distances can create zones or gradients. This is only our first approximation of
"soft": it has to be checked against samples and against Marmon's interpretation, including the way
bricks are taken out of the package to build a wall. We do not assume that minimizing local distances
is the correct industrial recipe.

## Module boundaries

- Perception delivers an ID and a category; changing its detector does not alter the planner.
- Blend selection decides quantities, with no robot coordinates.
- The pattern stage distributes categories over a logical grid.
- Sequencing assigns IDs and orders the steps.
- Integration turns logical positions into poses and handles failures and reservations.

To confirm during the event: recipe and tolerances, the desired appearance (package and wall),
categories and shade scale, visible faces, geometry, layer orientation, access to sources, and the
jury's criteria. If the geometric pattern changes, the pattern generator is replaced; if the robot
changes, its adapter is.
