# Attempt73: one bounded A-die TOP chip-ID read

2026-11-03. Image `a75acab430b3`, release
`7.3.0-op6893-d1-a75acab430b3+`, boot SHA256
`cf50395db8fb9dc34c4fcabf69623b3f06234a1e0c92def0c82029776f5386e7`.
Full image build and eleven build-time suites passed; capacity, decompression
window, compiled DTB pin model and schema checks passed.
Physical test passed; device now runs mainline73.
ACK recovery backup remains unchanged. AI-assisted implementation/tests/docs;
no AI Signed-off-by or external submission.

## Scope and sequence

adie-id-cycle uses the full validated nested preparation path, with all
parent remap/RGU/SPI settings held and SYSRAM zeroed, GPIO180 high, and
semaphore11 granted. Before each guarded operation, sample AP/CSR access,
full A-die control, passive ownership reports (M2 bit11 only) and WB80000.
No repeated acquire-register reads occur during ownership checks.

Map ADIE_CTL18001900/4, RF SPI18004000/0x5c and WB18005008/4. Require
control2 and initial SPI status0. Save TOP_ADDR(+50) and initial TOP_RDAT(+58).
Mark reset dirty before writing control3; verify full readback. Poll SPI idle
with50us interval/20ms deadline, allowing only TOP busy bit5. Program/readback
TOP_ADDR=b02c (TOP read prefixb000, chip ID02c). Trigger one read by writing
zero to TOP_WDAT(+54), poll idle, then read TOP_RDAT once. Local4.19/6.6
vendor protocol identifies66358a00/66358a10/66358a11 as known MT6635 revisions.
No extra reset-settle delay is invented: the vendor path reads immediately;
the new guarded operations themselves take time before the command.

After idle/ownership verification, reassert reset with control2 and verify.
Then restore/readback saved TOP_ADDR and recheck idle/guards. Only after this
may semaphore release, GPIO restoration and outer register restoration run.
TOP_WDAT is never restored because writing it would trigger another transfer;
TOP_RDAT is read-only and its result remains cached. Register restoration is
not reversal of internal A-die state changes caused by reset release.

## Evidence and failure semantics

Known ID plus an observed post-trigger busy sample OR changed RDAT baseline
is required for id_valid. A recognized but unchanged RDAT with no observed
busy returns EAGAIN: it is not accepted as a fresh response. This conservative
check can reject a legitimate fast repeated read; it is not a bus trace.
Unknown ID returns ENODEV but still performs verified reset/address cleanup.
No analog configuration, efuse, calibration, firmware, radio-enable or DMA
operation is added. This is one identification read, not Wi-Fi startup.

Access/reset/ownership/WB mismatch, unexpected busy bits or poll timeout latch
unsafe and prevent further writes, including reset and lock release. Unknown
post-trigger state retains reset/lock/strap/parent settings/domain/rails until
reboot. Reset or TOP_ADDR restoration failure likewise retains resources.
The earliest primary error is retained if cleanup also fails. Component
id_valid/complete is not overall success: outer restoration may still fail.
Guards are sequential and cannot exclude arbitrary concurrent masters or
protect against an MMIO stall; stalled access requires watchdog recovery.

## Host validation

Actual A-die C is executed with all three recognized IDs, unknown/stale
results, fast/no-busy responses, all guard calls, every sampled M2 ownership
loss, three mapping failures, five dropped writes,25 write-time access/
reset/ownership/WB/busy changes, busy timeout and baseline refusal.
Actual full nested functions also execute together; parent settings and
GPIO-high are asserted during ADIE writes and reset/address restoration is
asserted before unlock. Cases cover clean unknown/stale cleanup,20 nested
write-time guard losses, mapping and dropped-write failures, busy timeout,
original-error preservation when reset cleanup fails, later SPI restoration
failure, cached status and one-shot/opt-out routing. Shared ADIE and busy
state represent the same physical registers across preparation and ID paths.
Existing preparation/SYSRAM/SPI/semaphore host suites pass. ARM64 object
build, C/header checkpatch and binding documentation checks pass.

## Physical acceptance

Verify release/raw boot hash and attempted0. Trigger adie-id-cycle once.
Capture adie_status, all component statuses, protection trace and preflight.
Require known fresh ID, verified reset/address restoration, lock release,
all outer dirty/unsafe clear, normal shutdown, and standard USB/8CPU/root/
ADC/LVTS/AP-pin regressions. On uncertain state, do not retry or manually
unlock/reconfigure the retained hardware; collect cached status and recover
through reboot. No requirement to call a recognized ID valid without the
freshness/cleanup evidence.


## Physical results

Queued fastboot flash/reboot succeeded. Linux release and raw boot SHA256
match; attempted0 before testing. One adie-id-cycle returned0 and read
**0x66358a11 (vendor MT6635 E3)**. Initial TOP_RDAT0 changed to the known ID.
No busy-high sample was observed (busy_seen0, seven total idle/status samples
across the operation); do not claim a captured busy pulse or measured SPI
clock. This meets the fresh-data acceptance branch rather than the busy branch.

Reset release readback verified; control returned to2 and TOP_ADDR0 restored
from programmedb02c. id_valid1/reset_restored1/complete1, both dirty flags0,
unsafe0 and cleanup0. Semaphore released and M2 report cleared on first poll.
Remap4/4/4,RGU4/4/4,SPI36/36/36, SYSRAM4096/4096/4096 and strap6/7 all pass.
Every target/readback and original/restored pair matches; all outer flags
clear. Final domain control12/host0, VCN13/18 off, parent votes1/1.

Runtime regressions pass: USB configured/SSH, CPUs0-7, sdc read-only,
cache ext4 ro/norecovery and unchanged Debian hash. Battery ADC20388,
PMIC temperature39967, all17 LVTS entries returned. GPIO155 retained;
CONN pins idle and owned. AP snapshot unchanged except established common
drive0->8248; GPIO180 direction/latch/mux and shared Schmitt restored.
EALREADY retry refusal leaves all eight cached status hashes unchanged.
No BUG/Oops/SError/kernel panic in captured dmesg; existing image-alignment
warning remains. No button event test, ACK backup update or calibration.

Device remains mainline73, CONN off. This establishes a bounded RF SPI TOP
identification read with verified cleanup, not firmware/radio/network support.
Next audit E3-specific analog initialization, beginning with non-efuse register
baselines and the vendor ordering around WRI_CTR2/SMCTK11, thermal setup,
efuse-derived calibration and later oscillator settings. Do not replay the
whole vendor function or expose private efuse/calibration contents in Git.
