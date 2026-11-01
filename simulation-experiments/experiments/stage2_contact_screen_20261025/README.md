# Prospective grip-plane screen: saved-data comparison

Job 1815 showed a current native BODY contact rejected by finite authored-pad
surface proximity. This experiment removes that one necessity from a candidate
screen. It retains the old plane tolerance, lateral normal, forbidden metal/head
distance vetoes and rendered-candidate spatial association. The result is only
`UNVERIFIED_GRIP_PLANE_COMPATIBLE`, never BODY ownership or permission to pick.
The pure function has no BODY geometry, actor identity, native label or source
pose input. Existing task control is unchanged.

One frozen retrospective comparison scores every loaded finger observation from
1814's LEFT pad/metal/head fixtures and 1815's two-finger closing execution.
Fixture spatial association is forced true as a component-veto stress test;
1815 retains its actual rendered association. Native labels remain private
scoring truth. Reciprocal observations verify the same events and do not add
independent positives. Report retained/recovered/lost BODY observations and all
metal/head compatible errors, old/new contingency, UNKNOWN and coverage counts.

The candidate was proposed after seeing 1815: these are development and regression
data, not held-out validation, independent grasps or general component safety.
A favorable result can support a separately reviewed future policy experiment.
It does not validate holding or extraction, install the screen into control, or
authorize another simulation. The known limits of an unbounded grip plane remain
explicit. No training or parameter tuning is performed.

After source review and a clean experiment commit:

```bash
python3 experiments/stage2_contact_screen_20261025/submit.py --manifest-repair
```

This submits one foreground default-Pueue CPU comparison, with a stable source
snapshot and pinned saved input files. The maximum is 15 active seconds above the
retained 1666.880935217 seconds; there are zero new physics steps. Dependencies
and shared environments stay unchanged. Reproduction commands, source hashes,
job ID and results are retained in the snapshot and `results.json`.

Original job 1816 stopped on a missing input pin: its frozen evaluator reads both
finger buffers at any loaded frame, including empty opposite-side buffers. The
manifest repair adds those 18 dependencies only. Candidate and evaluator hashes
stay unchanged, with no completed scientific result to promote. The amended
history permits original plus one explicitly reviewed repair, under the same
prefix and cumulative clock, then refuses any additional submission.
