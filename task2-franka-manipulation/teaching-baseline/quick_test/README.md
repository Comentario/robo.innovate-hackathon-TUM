Initial hardware check, separate from the sorting application.

- `bash quick_test/run.sh --cameras`: simultaneous short captures from both webcams and RealSense RGB/depth; saves images and `cameras.json`.
- `bash quick_test/run.sh --preview`: reads current robot state and checks seven proposed joint paths without motion.
- `bash quick_test/run.sh --execute`: **moves the real arm**. Clear the tool and arm links first; keep the physical stop available. Each joint moves 0.1 rad over 6 seconds and returns over 6 seconds, then settles. Seven tests take about 90 seconds.

The measured TCP is monitored against a 100 mm radius and a 2 mm downward tracking margin from its starting position; planned paths must stay within 75 mm and never lower the TCP. Wrist rotation can produce essentially zero TCP translation. These bounds do not establish obstacle clearance. Joint limits come from the installed FR3 description. No homing, gripper commands, automatic recovery, or changes to collision thresholds/tool settings.

Each motion run saves a timestamped log and overwrites `joint_trace.csv`. On a fault, failed verification, or Ctrl-C, the sequence stops without an automatic return or retry. Inspect the cell and robot state before restarting; every new invocation uses its current pose as the start. Camera device paths and installed-library paths are specific to this machine.
