# CUDA recovery: 23 October 2026

The underlying failure is a driver-reported fatal GPU/UVM state, rather than a
failure in the LEGO task. The cause of the original MMU fault has not yet been
established.

At 09:25:46 CEST, before the Isaac workcell runs, the kernel logged:

```text
Xid ... 31 ... name=modprobe ... MMU Fault
uvm encountered global fatal error 0x60, requiring os reboot to recover.
Xid ... 154 ... Node Reboot Required
```

At the recovery investigation, `nvidia-smi -q` independently reported:

```text
GPU Recovery Action : Reboot
```

Queued health-check job **1659** independently recorded `reboot_required` in
`runs/20261023T180639.096400Z-cuda-check/cuda_check.json` and exited nonzero as
intended. It did not attempt CUDA initialization on the faulted device.

Driver/kernel and system `libcuda.so` both report version 580.178.04. No
reinstallation or package changes are justified by the evidence so far. CUDA
error 999 in Isaac is a consequence of the faulted device state. CPU physics and
CPU PPO can complete despite that state.

The default Pueue queue has concurrency one. At investigation time no task was
running or queued, and task 1062 remained stashed. The GPU serves the active
desktop, remote-desktop process, terminal and browser. A reboot will interrupt
those sessions and must be coordinated with the workstation user. Do not unload
driver modules or substitute a GPU reset for the explicitly required OS reboot.

## Recovery and verification

1. Save work in all sessions and coordinate an OS reboot. This investigation
   does not schedule an automatic reboot.
2. After reboot, check `nvidia-smi -q`: the recovery action should be `None`.
   Check the current boot's kernel log for new Xid/UVM faults.
3. Submit the bounded driver/PyTorch test:

   ```bash
   python3 scripts/check_cuda.py
   pueue log <job-id> --full
   ```

   This freezes the check in `runs/`, uses the project's existing Conda runtime
   and default queue, and writes `cuda_check.json`. Success requires driver
   initialization, device enumeration, allocation, a CUDA kernel, synchronization
   and the expected numeric result. A driver-requested reboot causes a clear
   failure before more CUDA work is attempted.
4. Once the CUDA check passes, submit the full-scene smoke test with rendering.
   CPU smoke success alone does not prove rendering.

   ```bash
   python3 scripts/submit.py --mode smoke --steps 120 --capture
   ```

If the fatal state returns after a clean boot, preserve the new kernel messages
and investigate the triggering workload/driver before further training. One
MMU fault does not establish a hardware defect or prove which process caused it.

NVIDIA's [Xid catalog](https://docs.nvidia.com/deploy/xid-errors/analyzing-xid-catalog.html)
defines Xid 154 as a recovery-action report; follow the action in its message.

## Recovery confirmed

After the user reported recovery, default-queue Pueue job **1660** passed CUDA
allocation and arithmetic on the RTX 5070 using CUDA 12.8. Isaac then rendered
the full 48-brick FR3 workcell through RTX/Vulkan and saved two inspected RGB
images. The scene remained stable over 120 control steps and its native
connection graph survived reset. Evidence is in
`runs/20261023T184556.243844Z-smoke/`. This clears the prior CUDA/rendering
blocker; it does not establish learned sorting performance or GPU RL support.

The final verification is job **1664** in
`runs/20261023T185048.535944Z-smoke/`, after correcting renderer/physics pose
synchronization and adding ideal arm gravity compensation. Both images were
inspected; the rendered hand matches its physical position, and the idle arm
drift is below 1e-7 rad over the tested interval.
