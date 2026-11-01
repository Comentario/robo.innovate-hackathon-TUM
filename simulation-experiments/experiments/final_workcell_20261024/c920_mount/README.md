# Superseded initial C920 proxy

The folded-holder interpretation below was corrected from the user reference.
Use [the reference-corrected model](../end_effector/README.md) for the current twin.
Historical captures and settings below are retained as evidence.

# Approximate C920 visual mounting

A procedural Logitech C920 visual proxy is attached to `fr3_hand` on hand −X,
opposite the preserved D435i housing on hand +X. Both folded stand leaves,
tape bands, hinge and housing are centered on hand Y=0. Centering in this
side view does not place the webcam on the wrist axis: it remains offset −X.

The folded stand is flat against the hand. Its armward edge is at hand Z=0,
used as a nominal wrist-face stop. This depicts the user-described contact;
it does not establish measured surface fit. Two black bands depict the tape.
The separate housing is rotated 60° about hand Y toward hand +Z/fingers,
remaining visibly angled to the stand. 60° is an illustrative end-stop pose,
NOT a measured mechanical hinge limit. Housing dimensions 94×29×24 mm and
stand dimensions/offsets are artist estimates configurable in scene_config.json.
No manufacturer's dimensional, kinematic or CAD accuracy is claimed.

The fascia/lens is decorative. Exact optical-center position, viewing direction,
intrinsics, hand-to-optical transform and true hinge limit remain unknown.
No optical camera is activated. No rigid-body, collision, mass or physics
material is added. Parenting the visual geometry to the hand keeps it attached
without changing either D435i joint or the robot's dynamics configuration.

The original diagnostic views, D435i assembly, joints, table layout, lighting,
exposure, all 300 source bricks and 930 native connections are preserved.
Additional close-ups are virtual inspection views only.

All rendering and image comparison used stable snapshots in default Pueue:
1712/1713 initial capture/check; 1714/1715 framing correction/check;
1716/1717 final unobstructed fascia framing/check. Only new diagnostic-camera
framing changed after the initial C920 geometry. Intermediate results remain
in their run directories. Source geometry commit: 8580c67; final framing:
aec7f2c. The final verification JSON records source/layout/arm/D435i/camera
invariance and the no-physics/no-optical-prim audit.

- [C920 side view](../../../runs/20261024T231138.248707Z-final-workcell-preview/output/images/diagnostic_c920_side.png)
- [Profile showing both housings](../../../runs/20261024T231138.248707Z-final-workcell-preview/output/images/diagnostic_c920_profile.png)
- [Updated USD](../../../runs/20261024T231138.248707Z-final-workcell-preview/output/final_workcell.usda)
- [Verification](../../../runs/20261024T231148.980882Z-c920-verification/output/verification.json)

Reproduce a fresh immutable queued preview from the repository root:

```bash
python3 experiments/final_workcell_20261024/submit_preview.py --cameras experiments/final_workcell_20261024/c920_mount/cameras.json --appearance experiments/final_workcell_20261024/appearance_config.json
```

Exact launchers, source commits and input hashes are stored in each snapshot.
