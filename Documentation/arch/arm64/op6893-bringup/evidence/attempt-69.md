# Attempt69: RF SPI semaphore11 acquisition and verified release

2026-11-03. Image `f43f4198b1b4`, release
`7.3.0-op6893-d1-f43f4198b1b4+`, boot SHA256
`028ae377d143e725ae4ab29a68165a22e68efaf792cc543f8af52a963e986b3b`.
Physical test passes; device remains mainline69 with CONN/VCN off.
Existing ACK recovery backup remains unchanged as requested.

## Source and ownership contract

MT6893 ACK mt6893.h names RF SPI semaphore index11. mt6893_pos.c requests
ownership by reading M2_OWN_STA + index*4 and testing bit0; release writes
exactly1 to M2_OWN_REL + index*4. The offset header identifies base18070000,
M2 acquire202c/release222c, four passive master reports400/1400/2400/3400.
The vendor failure dump reads reports, but does not verify release.

Per-index report-bit semantics are explicit in related MT6899 CODA headers
(semaphore11 bit11), not a full MT6893 hardware specification. This round
therefore tests the correspondence on MT6893 using before/grant/after
observations; cross-chip documentation alone is not proof. Report mismatch
rejects the experiment and retains resources. Reports are sequential, not
an atomic exclusion snapshot or proof of all masters being quiescent.

## Implementation

Root-only explicit sema-cycle shares the existing one-shot, rail/domain
opt-in and fresh expected digital-ID gates. Map one semaphore aperture
0x18070000..0x18073403; the implementation accesses only the four passive
report words, M2 semaphore11 acquire word and its release alias. No arbitrary
register interface, other index acquire/release, RF SPI transaction, A-die
reset, table/RGU/remap programming, SRAM, firmware or calibration is added.

Guard AP/internal clocks/timeout/sleep before every report read, after each
complete four-master snapshot, before acquire and before release. Require
bit11 clear in all four initial reports. An inherited owner causes refusal
without acquire/release and retains domain/pins/rails. Unrelated semaphore
bits are preserved and never interpreted as ownership of index11.

Set pending BEFORE the single acquire read. Record full raw grant and bit0
acknowledgement. Take four reports; require raw1 and M2 bit11 set while the
other three bit11 values are clear. Raw0 plus all-clear reports is a denied
request: return EBUSY without a release and allow normal shutdown. Ambiguous
raw values or contradictory reports latch unsafe; do not blindly unlock.

Only a consistent acknowledged grant permits one exact release write.
Poll passive M2 report bit11 with a20ms deadline and50us interval, guarded
on every poll. Never reread acquire during release confirmation. Then take
four final reports and require all four bit11 values clear, with final
access recheck. Only then clear pending and mark released. A sampled new
owner after release is conservatively treated as unsafe and retains domain.

Any pending/unsafe ownership prevents domain shutdown, idle-pin selection
and rail removal. Preserve original failure stage/result separately from
sema_cleanup_result. Subsequent requests require reboot. Historical acquired
and released flags may both be1 after success; pending is the unresolved
ownership indicator. Cached root-only sema_status reports grant, action flags,
poll count, each phase's valid sample count and full raw reports. Zero or
partial samples do not prove an all-clear state. Probe/show never acquire.

## Host validation

Actual extracted C with UBSan executes against a read-to-acquire model.
Success: one acquire read, one exact release write (23 total MMIO writes
including existing22),13 passive report reads,3 balanced mappings. Tests cover
unrelated lock bits, delayed release, denied0/ambiguous2/3 grants, all four
inherited owners, all post-acquire/final-report contradictions, dropped
release with finite timeout, bad IDs, mapping failure, both opt-outs, four
access-loss types at each report read, acquisition and release, cached status
and retry refusal. No speculative unlock occurs on mismatches. Existing
preflight/rails/domain/ID/remap/RGU/SPI suites pass, including36-word config
fault cases. Full image plus11 existing suites pass. C/headers checkpatch
zero errors/warnings; schema/DTB and boot/decompression capacity pass.
AI-assisted local implementation/tests; no AI Signed-off-by or external message.

Next establish SYSRAM initialization/mailbox order and GPIO18026MHz strap
before composing the independently tested prerequisites into an A-die ID
read. Semaphore success alone does not establish RF SPI communication.


## Physical result

Queued serial-targeted flash/reboot succeeds after watchdog reset and
fastboot interception. USB SSH returns; release and raw /dev/sdc48 SHA256
match the artifact. Initial attempted0 and empty semaphore status verified.
Explicit sema-cycle succeeds after both expected digital IDs:

```
grant=1 acquired=1 release_issued=1 released=1 pending=0 unsafe=0
cleanup_result=0 polls=1
before: m0=0 m1=0 m2=0 m3=0
owned:  m0=0 m1=0 m2=0x800 m3=0
after:  m0=0 m1=0 m2=0 m3=0
```

All three phases have four valid samples. The observed M2 bit11 transition
0->1->0, together with acquire acknowledgement and exact release, validates
the tested report correspondence on this device. One passive poll observed
release. This does not validate contended multi-master operation, other
indices, RF SPI transfer, A-die identity or firmware/calibration.

Domain and rail cleanup0; dual power ACK off, control0x12, host0, no leaf
refs/dirty flags, parentvotes1/1 retained. No lock is left pending. Repeated
trigger returns EALREADY with cached semaphore/protection hashes unchanged.
USB configured/SSH, CPU0--7, sdc RO, cache ro/norecovery/root hash, ADC/PMIC
temperature,17 LVTS samples and GPIO155/CONN idle state pass. Collected dmesg
has no BUG/Oops/SError/kernel panic; inherited alignment warning and
intentional GPT discrepancy remain. Selected evidence accompanies this
report, full raw logs remain under mt6893-direct.
