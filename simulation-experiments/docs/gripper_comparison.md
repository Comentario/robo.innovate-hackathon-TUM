# Parallel FR3 hand versus passive insert-and-twist tool

The paper's figure 2 shows a replaceable tool stick and base adapter. Studs fit
into the tool to locate the brick. Rotation about a displaced local Y axis
peels one connection during disassembly and releases the tool after assembly.
The paper tunes duration, twist angle and pivot offsets with CMA-ES, using
force feedback. It does not supply a calibrated Franka implementation for this
workcell.

For the parallel hand, first establish whether the stock fingertips can reach
the side faces in the lattice without contacting neighboring bricks. Learn or
tune a gentle peel after grasping rather than assuming straight upward pulling
will detach exactly one brick. For the passive tool, model its actual stud
engagement and release in both directions. A permanent hand-to-brick fixed joint
would erase the release problem and invalidate the comparison.

Before enabling the paper configuration:

1. Obtain or design the tool stick and FR3 flange adapter. Populate
   `configs/paper_tool.interface.json` from CAD and physical measurements.
2. Replace the parallel hand in a derived FR3 asset, with valid mass, inertia,
   collision geometry, mounting transform and TCP. Do not use a convex hull that
   fills the engagement sockets.
3. Implement and validate the engagement interface using native connection
   mechanics, including attachment, holding, peeling and release. Keep tool
   connection events distinct from stack connection events.
4. Expose local-Y pivot trajectories and bounded duration/angle/offset parameters
   for CMA-ES or a residual policy. Define bounds from measured clearance.
5. Verify a single baseplate-connected brick, then two layers, then the lattice.

Use identical frozen seeds, brick inventories, output recipes and physics
parameter samples for both tools. Report per-brick detachment success, wrong
connection breaks, dropped bricks, final restack connections, shade purity,
scrap routing, cycle time and recovery rate. Measure wrist force/torque and
collisions after adding validated sensing. Do not substitute joint PD targets
for force measurements. Report grasp/engagement failures and release failures
separately. A tool's speed matters only among successful transfers.

Start with deterministic motion primitives and parameter search, then consider
residual RL for alignment and peeling. Full-task PPO is available as a research
baseline but has a difficult exploration problem and is not evidence that
end-to-end RL is the best method for this challenge.

Sources: supplied PDF section 3/figure 2 and section 4/algorithm 1,
[paper](https://arxiv.org/abs/2309.02354),
[native simulator](https://github.com/intelligent-control-lab/BrickSim).
