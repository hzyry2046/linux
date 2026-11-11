# Attempt66: isolated RGU memory hardware policy transaction

2026-11-03. Image `362bb070becb`, release
`7.3.0-op6893-d1-362bb070becb+`, boot SHA256
`ccfe4ade8c8b68b1a5110a3e01ec7683aad81df0878646362862f3b9b8ce441b`.
Physical test passes; device remains on attempt66, with CONN/VCN off.

Explicit root-only `rgu-cycle` reuses the per-boot one-shot, supply/domain opt-in,
reset-requested clock detector checks, AP access gates, internal timeout/sleep
checks and both expected digital IDs. It does not require an EMI allocation,
program remaps or access EMI payloads. Probe and cached `rgu_status` reads
never initiate this transaction.

After fresh-ID success, guard and map only RGU0x18000000..0x18000057. Save
four full words at offsets0x38/3c/50/54 and require the attempt64 observed
baseline0xff/0/1/0 before any write. Program ACK's exact targets0/0xff/0/1
in that order: SYSRAM hardware power-down/sleep, coexistence-memory hardware
power-down/sleep. Check AP and internal readiness before every save, write
and readback. Mark dirty before a write, count applied only after exact
readback. Restore dirty words in reverse order, check readiness before write
and readback, and clear dirty only after full original value is observed.

Reverse restoration first returns coexistence sleep and power policies, then
SYSRAM sleep and power policies, before normal domain shutdown. Restoring
registers does NOT prove SRAM content retention; hardware policy transitions
can affect memory independently. No SRAM contents are read, cleared or
restored. No efuse/mailbox, SPI/A-die, firmware, RF, DMA, wakeup or DEADFEED
operations are included. MMIO stalls still require watchdog recovery.

Preserve original failure_stage and separate RGU cleanup errors. If any
RGU dirty bit remains, skip shutdown and idle pin selection; both domain
and independent rail cleanup retain supplies. Refuse another command until
reboot. Cached status reports saved/applied/restored counts, dirty mask,
cleanup and each before/target/on/after; unfilled fields prove nothing.

Extracted actual C integration tests with UBSan cover exact30-write success
(previous22 plus four targets/four restores), target/reverse restore order,
all baseline mismatches, mapping failure, four post-map access failures,
all dropped apply/restore writes and readback errors, mixed original and
cleanup errors, four readiness losses after each of eight RGU writes, bad
IDs, domain opt-out and retry refusal. Existing remap, ID, domain, recursive
rail and preflight cases pass. Full build and11 existing host suites pass;
C/header checkpatch has zero errors/warnings, schema document/compiled DTB
and boot/decompression capacity checks pass. No external messages or AI
Signed-off-by.

Next audit the SPI-master setup and A-die prerequisites, including the full
16KiB SYSRAM clear's ordering relative to D-die efuse/build mailboxes and
GPIO180 strap configuration. Keep those separate from this isolated policy
experiment; no firmware execution claim follows from RGU readback success.

## Physical result

First queued fastboot send failed in SendBuffer and did not reboot. The retry
logged successful flash/reboot, but the user observed recovery and explicitly
reported flashing this exact image there. Therefore record the recovery
installation as user-assisted, without claiming the queued fastboot sequence
alone reached Linux. USB SSH then returned; running release and SHA256 of
/dev/sdc48 both match the selected artifact. Before trigger, attempted0 and
all RGU counters/dirty flags are zero. An extra waiting fastboot reboot client
was terminated after Linux was confirmed, so it cannot affect a later test.

Explicit rgu-cycle returns success, with both expected IDs and:

```
saved=4 applied=4 restored=4 dirty=0 cleanup_result=0
offset=0x38 before=0xff target=0 on=0 after=0xff
offset=0x3c before=0 target=0xff on=0xff after=0
offset=0x50 before=1 target=0 on=0 after=1
offset=0x54 before=0 target=1 on=1 after=0
```

Normal domain shutdown, idle pin selection and rail cleanup all succeed:
dual power ACK off, control0x12, host0, no leaf refs/dirty flags, parentvotes1/1
retained. The policy targets have been restored, not left enabled. This
establishes register behavior only, not SRAM data integrity or firmware readiness.
Repeated trigger refuses EALREADY and cached RGU/protection hashes are unchanged.

USB configured/SSH, CPU0--7, sdc RO, cache ro/norecovery, root hash,
battery ADC, PMIC temperature and17 LVTS samples pass. Initial regression
used an incorrect pinctrl debug path; the separate pins.txt capture uses
the actual driver directory and verifies GPIO155 unchanged, CONN pins back
in GPIO idle mode with retained drive fields. No BUG/Oops/SError/kernel panic
in collected dmesg. Existing boot alignment warning and intentional GPT
discrepancy remain. Full logs stay outside Git; selected evidence is archived.
