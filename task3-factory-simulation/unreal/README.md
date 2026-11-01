# Brickflow, native Unreal

Project: `Brickflow/Brickflow.uproject`, Unreal Engine **5.8.4**, Linux x86-64. The complete
simulation runs in C++20. The JSON geometry contains no animations and no Python or JavaScript
replay. The pinned reference is `greenfield_30`.

## Run it

### Evaluating from a browser on this machine

Interactive access over a noVNC remote desktop through an SSH tunnel:
`http://localhost:6080/vnc.html?autoconnect=1&resize=scale&view_only=0&path=websockify`. The GPU and
Unreal stay on Brev. The browser transmits the image and the inputs; the engine is still the native
executable. It is not a public link and it only works on the machine where the tunnel is opened.

To bring it back from WSL if the tunnel closes:

```bash
./.deps/brev/bin/brev exec brickflow-cinematic-4gpu @unreal/tools/start_interactive_cloud.sh
./.deps/brev/bin/brev port-forward brickflow-cinematic-4gpu -p 6080:6080
```

The desktop uses Xvfb `:81`, x11vnc on loopback `5901`, and websockify/noVNC on loopback `6080`. The
PIDs and logs are in `Saved/Interactive/` on the VM. This VM's dependencies are
`xvfb x11vnc novnc websockify openbox x11-utils`. The WebSocket connection was verified in Chromium,
and camera switching was verified with clicks sent from the browser. Desktop streaming is used for
evaluation; neither latency nor streaming quality has been measured for a pitch.

### Linux executable

On Linux with an NVIDIA GPU, Vulkan and a graphical desktop:

```bash
./Brickflow.sh -vulkan -ResX=1920 -ResY=1080 -Windowed
```

On the `brickflow-cinematic-4gpu` VM, the build is at
`/home/shadeform/workspace/brickflow-native/Packaged/Linux/`. The editable project is at
`/home/shadeform/workspace/brickflow-native/`.

The current version creates no UI and no dashboard. It starts at 1x; `Space` plays or pauses. Right
button and drag orbit, and the wheel changes the distance. The keys `1` to `6` hold evaluation
framings. The metrics are still available in the JSON evidence, but they are not drawn over the plant.

The tracking video uses `-BrickflowFilm=/new/path` and computes its camera from the native events and
poses.

The `brickflow-cinematic-4gpu` replica has four RTX PRO 6000; an independent render per Vulkan
adapter was verified. The optional eighth argument of `render_film_cloud.sh` selects the adapter.
`launch_four_gpu_cloud.sh` splits a frame range across the four cards without changing the clock.

## Local deliverables from the previous version (with UI)

- `artifacts/unreal_native/brickflow-native-pitch.mp4`: 1080p tour, 24 seconds.
- `artifacts/unreal_native/brickflow-linux-native.tar.gz`: the complete Linux build.
- `artifacts/unreal_native/mixed-chapter0.png`: Unreal overview.
- `artifacts/unreal_native/perception-native.png`: inspection detail.
- `artifacts/unreal_native/evidence-native.png`: evidence panel.
- `artifacts/unreal_native/*verification.json`: numeric comparisons.

Extract the build with `tar -xzf brickflow-linux-native.tar.gz` and run `Linux/Brickflow.sh`. The
Unreal ZIP and the heavy tools are on the VM; the editor is not needed to run the packaged build.

## Building and capturing on Brev

The `tools/*_cloud.sh` scripts use explicit paths on that VM and are run with
`brev exec brickflow-cinematic-4gpu @path/to/script.sh`. The preparation order is: install the engine,
prepare the geometry, author the material in the editor, compile, and package. `prepare_geometry.py`
requires Playwright and Chromium, only when preparing assets; the executable does not need them.

`preview_cloud.sh` uses Vulkan over Xvfb with `-RenderOffscreen` for automated review. It accepts a
mode, chapter, time and width; `-BrickflowPackaged` selects the standalone executable. It generates a
PNG and JSON evidence with the complete pallets, their IDs and times. `tests_native/compare_unreal.py`
compares that evidence against the original caches.

The earlier 24-second tour is kept as a historical artifact. The current render is generated with
`tools/render_film_cloud.sh`: 30 fps, a continuous clock with no cuts, ramps to 16x during the
rebuild and 40x in the final timelapse, no UI, and a lossless NVENC master. The stride has to be 1 for
the final video; larger strides are only useful for reviewing framings.

## Scope and evidence

The scene reproduces inspection, rejection, finite channels and reservations, blending, forming,
stacking and dispatch for the pinned model. It preserves brick identity. Mixed and Single match the
reference numerically, including the 78 pallets. The poses are also compared against the original
JavaScript.

The current input is synthetic, with a seed. It does not represent independent perception from task 1
and it is not measured industrial capacity. The recipes are demo heuristics and the motion is
kinematic, with no independent physical validation.

The VM is billed while it stays active. Do not delete the instance before checking the backups of the
build and the project.
