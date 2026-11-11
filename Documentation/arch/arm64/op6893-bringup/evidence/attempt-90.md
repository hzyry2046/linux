# Attempt90: fresh no-op gate and repeated TOP070 baseline

2026-11-04 Asia/Shanghai. Image `9d1e950c4d59`, release
`7.3.0-op6893-d1-9d1e950c4d59+`. Boot SHA256
`913c7bc2808dee46bc9a33bd1913770d4a510454bda943797d42d79484957c8b`.
Device remains on mainline90; recovery backup unchanged. AI-assisted code,
tests and documentation; no external submission or AI DCO.

## Boot and result

Serial-targeted flash/reboot was queued before requesting89 watchdog reset.
Flashing succeeded, but device subsequently remained in fastboot; no evidence
of successful mainline execution was seen at that point. A second normal
fastboot reboot, without reflashing, started90. Cause of the initial fastboot
return is unknown; do not classify it as a kernel failure or assume key input.
Release, raw boot hash and attempted0 then matched before the experiment.

One `adie-pad-read` succeeded. Its freshly evaluated trim plan reported
vendor_noop1/bounded_noop1/policies_equivalent1; the command would refuse
before any TOP070 transaction if these conditions did not hold. This run
reconfirms the prerequisite rather than inheriting89's result.

TOP070 was read twice using ID→target→ID→CTRL, eight additional SPI transfers.
Both replies matched, but comparison against the public vendor target
80000000 was false: `pad_complete=1 pad_cleared=1 pad_issued=0x3 pad_read=0x3
pad_matched=1 pad_target_match=0 pad_transfers=8 pad_busy_count=0`.
No busy pulse was sampled; per-transfer changed RDAT provided freshness.
No raw baseline or its hash is published. Temporary baseline/response storage
was explicitly erased. Target mismatch is an observation, not a transaction
error, an electrical HighZ measurement, or permission to write the full word.
No pad/trim writes or firmware startup were performed.

Total data-stage time1554148616ns remains within the unchanged2s budget,
including private reads, handoff/erase, thermal reads, plan and pad reads.
Engine elapsed171050154ns, one kick, three stable controls with delta3b,
pending0/complete1. Earlier data32 transfers, thermal16 transfers and SYSRAM
handofff/f/f completed with dirty0.

Result0/cleanup_result0; all FM, analog prefix, mailbox, reset, semaphore and
outer restoration succeeded. Remap/RGU4/4/4, SPI36/36/36, initial SYSRAM
4096/4096/4096. All dirty/unsafe/uncertain flags zero; CONN off at both
preflight samples, with the established VS1/VS2 votes1/1 retained.
Wi-Fi and independent network SSH remain unavailable.

## Validation

Complete chained host suites through the new pad command passed with actual
extracted C and UBSan. The new suite covers fresh non-no-op refusal before
TOP070 access, target equality/inequality,16 dropped address/trigger writes,
64 write-time guard losses,eight SPI timeouts,repeat mismatch,two changed
controls,two deadlines,stale/zero/no-busy responses,15 later cleanup faults,
temporary erasure/redaction and one-shot refusal. Non-no-op refusal retains
parents conservatively, even though no pad transaction was issued.

An additional focused runner generated the same model without rerunning
parents, then compiled/executed only the pad suite. Its skipped parent calls
are not counted as passes; the separate complete chained run executed all
parents and passed. Independent private-read and262144-case planner/vendor
comparison suites also pass. No new host-test failure required a correction.

Full ARM64 build/11 built-in suites, zero-error/zero-warning checkpatch,
binding/DTB validation, pin model, capacity and diff checks pass. Payload
7,469,056 bytes leaves26,085,376 bytes in32MiB boot.

USB SSH/configured, CPUs0–7, read-only disk/cache ro+norecovery, Debian hash,
battery ADC/PMIC temperature and17 LVTS samples pass. AP register change is
limited to established shared drive0→8248. Retry refused with all nine cached
hashes unchanged. No BUG/Oops/SError/panic in captured log.
Selected records: [attempt-90](attempt-90/); full dmesg stays outside Git.

## Next boundary

The vendor's first post-efuse operation is TOP070=80000000 (WF_PAD HighZ),
followed by380/390=e8002, XTAL A18/A1C and384/394=2008. The first operation
cannot be marked complete on this baseline. Design a separate bounded pad
write/readback/restore experiment, first auditing register ownership and
restore semantics. Preserve the fresh no-op trim prerequisite and private
baseline handling. A stable read alone does not establish reversible analog
state, and equality alone would not prove electrical HighZ. Later CAL LDO,
XTAL sequence integration and AFE calibration remain separate work.
