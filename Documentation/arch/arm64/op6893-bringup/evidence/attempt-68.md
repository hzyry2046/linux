# Attempt68: guarded SPI sleep-command programming and restoration

2026-11-03. Image `e384bb8e140f`, release
`7.3.0-op6893-d1-e384bb8e140f+`, boot SHA256
`9d8d5c11ddaed6336d0534c51699c8d12d185bf1870f7a46ffa84cb50672709e`.
Physical test passes. Device remains on mainline68 with CONN/VCN off.
Existing ACK recovery backup remains unchanged as requested. Starting device
is mainline67; the earlier Android was actual4.19 with spoofed uname5.10.0.

## Transaction scope

New explicit root-only `spi-config-cycle` shares the existing per-boot one-shot,
rail/domain opt-in and fresh digital-ID prerequisites. Uses the36 non-BT
sleep-command values/masks independently audited against local4.19 and6.6
sources in attempt67. It is not an RF SPI transfer, a generic SPI controller
or A-die initialization. No remap/RGU policy, SRAM, firmware, semaphore,
strap or A-die reset/control writes are added.

Map only ADIE_CTL0x18001900/4bytes, SPI_STA0x18004000/4bytes and
WT0x18005000/0x9cbytes after access guards. Save all36 words and require
full originals to match the attempt67 observed baseline before any write.
This deliberately refuses other baselines, including unknown high-field
changes; it is a board diagnostic rather than general runtime PM.

Before every table read/write, freshly validate AP/clock/timeout/sleep,
ADIE_CTL exactly2, SPI_STA exactly0, WB_STA exactly0x80000 and AP/internal
readiness again. Check access before each status read too. Exact WB status
avoids inventing an idle mask for unknown bits. ADIE bit0 stays clear;
existing bit1 clock request stays set. These are sequential observations,
not atomic exclusion of autonomous hardware. No command-length-zero or
undocumented sequencer-disable semantics are assumed.

Program peripheral addresses then BG addresses, BG_ON and BG_OFF payloads;
command length is written LAST (0xf801->0xf808). This deliberately differs
from vendor length-before-BG order: do not advertise eight commands while
later payloads remain old. This reduces an incomplete-table interval, but
does not establish a hardware transaction barrier. On restore, return
length FIRST then reverse the remaining order. No A-die release or explicit
SPI trigger is issued during either phase. Ten matching words are still
written/read back so all36 audited entries are covered.

Target is `(original & ~mask) | value`; full readback verifies unrelated bits.
Mark a64-bit dirty bit BEFORE issuing each write, including bits32--35.
Count applied only after verified target readback. On error, restore dirty
originals with identical guards; clear dirty only on full readback. Check
status once more after the last restore readback. Retain original error and
failure_stage independently from spi_config_cleanup_result.

Any observed guard loss is latched unsafe: refuse subsequent writes even
if a later sample might look good. Unsafe status or unverified restoration
prevents domain shutdown, idle-pin selection and rail removal, including
when the final restore cleared every dirty bit. A normal verified rollback
after a target mismatch permits established shutdown. Retry requires reboot.
Cached root-only spi_config reports counts/dirty/unsafe/cleanup, last guard
samples and before/target/on/after for each saved word. Unfilled fields are
not evidence. No hardware reads occur from show; maximum full report fits
one sysfs page under tested worst-case values.

## Validation

Host suite executes extracted actual C with UBSan and an independent
attempt67 target/original fixture. Success has94 MMIO writes (existing22
plus36 target/36 restore),5 balanced mappings, exact application/restoration
order and preserved0xf800 control bits. Tests cover all36 baseline mismatches,
three mapping failures, both bad IDs, both opt-outs, each corrupted/dropped
apply and restore write, all apply/restore readback errors, combined primary
and cleanup errors, and seven state-loss types after each of72 writes and
108 table reads. Loss after final restore retains resources even with dirty0.
No writes outside the audited table are accepted by the fake. Unchanged
words legitimately tolerate dropped writes when readback already matches.
Existing preflight/rail/domain/ID/remap/RGU/baseline tests continue passing.

Full image and11 existing suites pass; C and both implementation headers
have zero checkpatch errors/warnings. Schema document, compiled-DTB and
boot/decompression capacity checks pass. AI-assisted implementation/tests;
no AI Signed-off-by or external messages/submission.


## Physical result

Queued serial-targeted flash and immediate reboot succeed after watchdog
reset/interception. USB SSH returns; running release and raw boot-partition
SHA256 match the selected image. Initial attempted0 and all configuration
counts/flags0 are checked before explicit spi-config-cycle.

Fresh IDs HW0x20010101/config3 pass. All36 observed originals match67,
all36 target readbacks match, all36 original readbacks match after reverse
restoration. An independent host comparison against67's vendor audit checks
every address, original and target in the physical log. Final summary:

```
saved=36 applied=36 restored=36 dirty=0 unsafe=0 cleanup_result=0
adie=0x2 busy=0 wb=0x80000
```

TOP_CK_ADDR0xa00->0x02c->0xa00; BG commands match the audited non-BT
payloads; final command length0xf801->0xf808->0xf801 preserves upper bits.
No sampled guard changed. Normal domain shutdown/idle pins/rail cleanup0;
dual power ACK off, control0x12, host0, no leaf refs/dirty flags, shared
parentvotes1/1 retained. Targets are restored, not left installed. This
proves programming/readback/restoration for this baseline only, not RF SPI
communication, command execution or A-die/firmware readiness.

Retry refuses EALREADY; cached configuration/protection hashes unchanged.
USB configured/SSH, CPU0--7, sdc RO, cache ro/norecovery/root hash, ADC/PMIC
temperature,17 LVTS channels and GPIO155/CONN idle pins pass. Collected
dmesg has no BUG/Oops/SError/kernel panic. Known boot alignment warning and
intentional GPT discrepancy remain. Full logs stay in mt6893-direct;
selected evidence is archived alongside this report.

## Next step

Establish the remaining A-die prerequisites as explicit stages: full16KiB
SYSRAM initialization and mailbox ordering, GPIO18026MHz strap, and RF SPI
semaphore acquire/release. The vendor M2_OWN_STA read attempts acquisition;
it is NOT a passive status read, so do not add it to a read-only snapshot.
Audit release/ownership confirmation before touching it. Then compose the
validated remap/RGU/table stages with a bounded A-die ID read, preserving
cleanup behavior and avoiding firmware/calibration until that path works.
