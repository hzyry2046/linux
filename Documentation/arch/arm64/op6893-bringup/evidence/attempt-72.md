# Attempt72: nested preparation with A-die reset held

2026-11-03. Image `681020f5b5b7`, release
`7.3.0-op6893-d1-681020f5b5b7+`, boot SHA256
`a1b8b6e9a291310b19b9899d9b08814cb02c7bea3666b058467a672bdfcd020a`.
Full build and eleven existing build-time suites pass. Boot capacity,
decompression window, compiled-DTB pin model and schema checks pass.
Physical test passed; device now runs mainline72.
Existing ACK recovery backup unchanged. AI-assisted code/tests/docs;
no AI Signed-off-by or external submission.

## Why composition is a distinct experiment

Calling the previous independent cycle commands sequentially would restore
each stage before the next stage uses it. prepare-cycle instead holds the
parents across the child transaction:

1. Fresh digital IDs, apply four EMI/peripheral remaps.
2. Apply four RGU memory power/sleep policy controls.
3. Apply36 SPI sleep command settings, length last.
4. Clear/verify all16KiB SYSRAM with those parent settings still installed.
5. Preload GPIO180 high under peripheral mux, then select GPIO mode.
6. Acquire semaphore11 once, check ownership and release with passive poll.
7. Restore GPIO180 mux/latch/direction and ordinary active pin state.
8. Restore36 SPI settings, four RGU controls, then four remaps.
9. Normal domain/rail cleanup and idle pin selection.

A-die reset is never released. No RF SPI command/data write, A-die register,
firmware, efuse/mailbox population or EMI payload access is added. SYSRAM
contents are discarded, never restored. ADIE_CTL2 and existing sequential
access guards remain in use; no atomic exclusion against other masters is
claimed. This tests simultaneous prerequisite lifetimes, not A-die readiness.

## Failure containment

Each parent restores only after its children have released ownership and
verified restoration. Pending/unsafe semaphore ownership retains GPIO high,
SPI settings, RGU policy and remaps plus domain/pins/supplies. Failed strap
restoration retains the outer settings too. SYSRAM unsafe prevents SPI/RGU/
remap restoration. SPI restoration uncertainty retains RGU/remaps; RGU
restoration uncertainty retains remaps. All errors still release software
MMIO mappings, not hardware resources.

A clean semaphore denial (raw0 with all reports clear) permits normal outer
restoration while returning EBUSY. A semaphore mapping failure also permits
restoration. Preserve the earliest failure stage/result if later pin
restoration fails. Status completion bits describe their component only;
overall success requires rail_cycle.result0 and every cleanup result0.

Original individual commands remain available, with no duplicate nested
calls from the top-level identify function. The per-boot one-shot and both
board opt-outs are retained; no operation runs at probe or boot.

## Host evidence

Actual nested production functions run together with fake MMIO/pinctrl.
Assertions require remaps/RGU/SPI targets to remain installed during child
accesses, and GPIO high plus full SYSRAM verification during semaphore
acquire/release. The model uses one shared ADIE word for SPI/SYSRAM/strap;
the formerly isolated tests' separate ADIE fakes cannot model composition.
Success has4096 RAM writes,8192 RAM reads,111 other MMIO writes, and full
reverse cleanup. Tests cover every remap/RGU/SPI dropped write, five strap
failures and guard losses, seven SPI guard losses, five final SYSRAM-read
losses, four semaphore access losses, denied/inherited/ambiguous ownership,
release timeout, clean mapping failure and nested recovery failure. Original
failure stage/result, all outer-retention flags, opt-outs, bad IDs, invalid
EMI and one-shot refusal are checked.

Existing SYSRAM, SPI, semaphore and strap/glue suites pass. Driver compiles
for ARM64; C/header checkpatch and binding documentation validation pass.
Fake pinctrl/MMIO is not an electrical timing or full controller-core model.

## Physical acceptance

Verify image/release/hash, attempted0 and AP idle snapshot. Trigger
prepare-cycle once. Require remap4/4/4, RGU4/4/4, SPI36/36/36,
SYSRAM4096/4096/4096 complete1, strap selected6/samples7 complete1,
semaphore acquired/released with reports0->M2bit11->0, all dirty/unsafe0,
and normal domain/supply cleanup. Verify post-shutdown AP idle state, USB
SSH/8CPU/read-only root and cache/ADC/LVTS, cached status and EALREADY.
Next bounded A-die reset-release/ID work remains separate.


## Physical results

Queued fastboot flash/reboot succeeded; Linux release and raw boot SHA256
match. Initial attempted0 and unclaimed CONN pinmux confirm no automatic
cycle. One prepare-cycle returned0. Remap4/4/4, RGU4/4/4 and SPI36/36/36
all match target on apply and original on restore, every dirty/unsafe clear.
SYSRAM written/verified/scanned4096 each, complete1; GPIO selected6/samples7,
complete1; semaphore grant1, M2 reports0->800->0, release confirmed on first
passive poll. ADIE_CTL samples remain2. Normal domain/rail cleanup0,
control12/host0, parent votes1/1 and VCN13/18 off.

Post-shutdown AP snapshot matches boot idle except the established common
drive policy0->8248; DIR/DOUT/mux/IES/pulls/shared SMT unchanged. All11 CONN
pins owned by idle state, GPIO155 retained. USB configured/SSH, CPUs0-7,
sdc read-only, cache ext4 ro/norecovery and unchanged Debian hash pass.
Battery ADC20313, PMIC temperature39967 and all17 LVTS entries returned.
Retry refused with EALREADY; all seven cached status hashes unchanged.
No BUG/Oops/SError/kernel panic in captured dmesg; known image alignment
warning remains. No button event test or ACK backup update.

This is the first combined prerequisite cycle, with software nesting and
verified apply/restore results. It is not a simultaneous bus trace of every
register or proof against arbitrary external masters. No A-die reset release,
SPI transfer, A-die ID or firmware startup has occurred. Next implement the
bounded reset-release/ID operation inside this tested resource lifetime,
including reset reassertion before releasing the lock/restoring outer state.
