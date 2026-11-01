# Optional Alex capability preflight

Read the official [SSH guide](https://doc.nhr.fau.de/access/ssh-command-line/)
and [Alex guide](https://doc.nhr.fau.de/clusters/alex/) before use. Reuse the
saved `alex` SSH profile and identity reference with strict known-host checking,
batch authentication and no agent forwarding. Do not copy keys, tokens or SSH
configuration into a snapshot. Stop for user interaction if authentication
requires VPN login, key unlocking or an interactive challenge.

Current read-only checks reach `alex2.nhr.fau.de` using that saved profile.
Login metadata shows Slurm/Apptainer, Python3.9.25 and glibc2.34. No matching
Isaac runtime was identified in the limited standard-path inventory; this is
not an exhaustive cluster search or proof that none exists.

The probe budget is one A40, five minutes, with the documented 16 CPU / 60 GB share assigned automatically; it exits immediately
when metadata collection ends. Alex's documented GPU allocations include the
associated CPU/memory share; explicit --mem is rejected and no CPU/memory
overrides are supplied. A100/H100 have no RT cores and are unsupported
for Isaac rendering according to the pinned [Isaac5.1 requirements](https://docs.isaacsim.omniverse.nvidia.com/5.1.0/installation/requirements.html).
A40 is a candidate only; scheduling it does not certify runtime compatibility.

The local default Pueue job submits the immutable payload through SSH and
records the Slurm ID. Slurm owns the remote hardware allocation; asynchronous
submission releases the local GPU queue while the remote job waits/runs.
Read-only status/result retrieval needs no GPU job. No application, package
installation, container pull or benchmark runs on the login node.

`probe.py` collects the allocated GPU name/driver/VRAM, Python/libc, container
runtime and package metadata. It does not import Isaac or launch CUDA. Without
an identified matching runtime it reports Isaac **NOT_TESTED**, not a pass.
No scaling follows this inventory. A later explicitly configured runtime probe
must exercise a tiny headless RGB/depth render and simulation step inside Slurm
before the cluster can be used for this demo. Keep that gate separate from the
currently failed local native-stack dynamics gate.

Snapshots include both source files, hashes, the resource budget, source commit,
SSH submission commands and returned Pueue/Slurm IDs. Shared environments,
concurrency limits and SSH settings remain unchanged.

The initial Pueue submission 1736 was rejected by Slurm before allocation because
it included --mem. Its immutable snapshot is preserved; the corrected payload
uses GPU-count-based automatic resources. This is a scheduler-argument fix,
not a second allocated GPU experiment.


## Recorded result

The corrected payload was submitted by local default-Pueue job **1737** as
Slurm **4685752**. It completed in 10 seconds, allocating 1 A40, 16 CPUs and 60000M on
one compute node. The allocated GPU reports driver 610.57.04. Apptainer 1.5.4
is available. The probe Python 3.9.25/glibc 2.34 reports no Isaac or Torch
package metadata. This is specific to that probe interpreter, not an assertion
about all cluster environments. Raw source hashes match the transferred payload.

Isaac startup/rendering and a CUDA kernel remain **NOT_TESTED**: no verified
matching runtime/container was supplied or identified. Do not turn inventory
success into a compatibility/scaling pass. No packages or images were installed
and the local native-stack idle failure remains a separate blocker.

- [Raw allocated-node result](../../runs/20261025T012356.087375Z-alex-capability-preflight/result.json)
- [Source and accounting verification](../../runs/20261025T012356.087375Z-alex-capability-preflight/verification.json)
- [Resource accounting](../../runs/20261025T012356.087375Z-alex-capability-preflight/sacct.txt)
- [Compact machine-readable result](results.json)
