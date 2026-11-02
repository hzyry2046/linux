# Attempt 1: fastboot boot, ff91ded71af8

2026-11-02 00:02:13 +08:00: fastboot accepted the diagnostic boot image.
Recovery subsequently returned to ACK. No claim is made about reset cause
from `androidboot.bootreason=kernel_panic` alone; it can be stale.

Positive evidence: the exact new kernel release
`7.3.0-op6893-d1-ff91ded71af8+` appears in a fresh DBGC ring embedded in both
recovered `console-ramoops` and `expdb.bin`. These markers were absent from
both pre-test captures. The extracted ring is
`after-ff91ded71af8/mainline-early.txt`.

The mainline kernel executed its normal entry and reached setup_arch. The
LK FDT pointer was 0x47c80000 and the synthesized board FDT had 7091 bytes.
It then BUGged at arch/arm64/mm/mmu.c:178. It did not reach userspace.

Cause in our new code: op6893_prepare_fdt maps LK via FIX_FDT, then
setup_machine_fdt maps board_fdt into the same window without first clearing
it. init_pte rejects replacing a valid PTE with a different PFN. The fix
clears each old LK FDT fixmap page (including TLB invalidation) after merging
and before setup_machine_fdt remaps the window. No upstream MMU check is
removed or weakened.

A separate measurement corrected the console placement: ACK's live sysfs
ramoops parameters are ftrace_size=4096, console_size=262144, pmsg_size=65536,
record_size=131072, mem_size=917504, ecc=0. ftrace was not zero just because
its cmdline option was absent: ram.c defaults it to MIN_MEM_SIZE. The correct
console address is 0x4811f000. Attempt 1's 0x48120000 put its own header 4 KiB
inside ACK's console zone, explaining the embedded fresh ring in stale ACK
text. The next image uses ftrace_size=0x1000 and the corrected address.

The hardware trace is the reproducer for the fix. This is a bug in the new
experimental local bring-up code, not an upstream regression or a reported
security vulnerability. There is no upstream Fixes commit to cite.

Boot partition remained byte-identical to the ACK backup after this attempt
(SHA256 976b5d311bdd812d72b3705491f5f0368b7a61feb018ae2bb4737f49251a3595).
The user subsequently authorized flashing boot and offered manual interception
into fastboot. Further tests use that path and restore the ACK backup afterward.
