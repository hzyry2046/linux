# Attempt76: A-die ID mailbox in shared SYSRAM

2026-11-03. Image `375b79347f81`, release `7.3.0-op6893-d1-375b79347f81+`,
boot SHA256 `52ee36f45754e1fe4e0836de8d5f52316919a8737525fad892909bc03919ecb0`.
First watchdog reset was not intercepted; the existing serial-targeted flash
waiter remained queued. User re-entered fastboot, flash/reboot succeeded and
release plus raw boot hash matched before testing. No concurrent fastboot
client was started. ACK recovery backup hash remains unchanged.

## Result and scope

One `adie-mailbox-cycle` returned success. Fresh TOP ID was `0x66358a11`.
After full SYSRAM initialization, the fixed word at `0x18052800` was zero,
written with that ID, read back exactly, cleared and verified zero before
A-die reset/address restoration and semaphore release.

`mailbox_issued=1 mailbox_applied=1 mailbox_restored=1 mailbox_dirty=0
mailbox_cleanup=0 mailbox_on=0x66358a11 mailbox_after=0`.
ID used changed RDAT evidence; no busy pulse was sampled. The complete
cycle recorded14 SPI status polls. Mailbox accesses themselves are direct
shared-SRAM MMIO, not additional TOP transactions.

Remap4/4/4, RGU4/4/4, SPI36/36/36, SYSRAM4096/4096/4096 and strap6 selections/
7 snapshots passed. All dirty/unsafe and cleanup results are zero. Domain
ended at control12, host0, VCN13/18 off; existing VS1/VS2 parent votes1/1 retained.
The SYSRAM counters describe initial whole-region clearing/scanning; mailbox
clear/readback is recorded separately, not a second full-region scan.

This adds the vendor step preceding TOP0x064/0x0bc configuration. The test
clears its mailbox before stopping and therefore does not deliver an enduring
ID to firmware. Firmware, efuse/calibration and the first analog configuration
writes remain unimplemented. Existing XTAL read/write commands remain available
but were not run in this boot. No analog write occurred in this experiment.
See [design](../ADIE-POST-ID.md) for source definitions and cleanup rules.

## Validation and regressions

Actual-C standalone tests cover7 dropped writes,35 write-time state changes,
all guards/ownership samples,4 mapping failures,6 prerequisites and unexpected
nonzero mailbox containment. Nested tests use the very same SRAM array that
initialization clears, cover28 write-time state changes, clear-before-reset/
unlock, mapping failure, original-error preservation and outer restoration
failure. Prior ID, preparation and analog write integration tests passed.
Build and eleven build-time suites, checkpatch, binding/DTB schema, pin model,
boot capacity and decompression bounds passed. AI-assisted code/tests/docs;
no external submission or AI Signed-off-by.

USB SSH/configured, CPUs0–7, disk read-only, cache ext4 ro/norecovery and Debian
SquashFS hash passed. ADC/PMIC temperature and17 LVTS samples collected.
GPIO155 baseline and172–182 idle ownership recorded. AP snapshot words match
except the established common drive0→8248; GPIO180 direction/latch/mux/shared
Schmitt restored. Refused retry preserved all eight cached status hashes.
No BUG/Oops/SError/kernel panic found; full dmesg remains outside Git.
Selected records are in [attempt-76](attempt-76/), full records under
`mt6893-direct/evidence/attempt-76`. Device remains mainline76, CONN off.
