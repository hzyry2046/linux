# Attempt87: private SYSRAM handoff, verified erasure and complete cleanup

2026-11-04 Asia/Shanghai. Image `4d408b45c192`, release
`7.3.0-op6893-d1-4d408b45c192+`. Boot SHA256
`0e006d3c1853f91347f04025ab0d46b8f20aa12208a9f75dc1f9a070eb5fb97d`.
Device began on user-restored Android; its differing boot image was not
copied over the existing recovery backup. Serial-targeted flash/reboot was
queued before adb reboot bootloader. Release, raw boot hash and attempted0
matched before the one-shot experiment. Device remains on mainline87.
AI-assisted implementation, tests and documentation; no external submission
or AI DCO.

## Result

One `adie-efuse-handoff-cycle` succeeded. After86's repeated private reads,
the four software-control slots at SYSRAM+2804/+2808/+280c/+2810 had zero
baselines. Each private word was written and read back, then all four slots
were cleared and individually verified, followed by a complete zero scan
and final access guard before any enclosing cleanup.

Handoff requested1/complete1, issuedf/verifiedf/clearedf/dirty0.
Data complete1/cleared1, issuedff/readff/matchedf,32 transfers/eight private
reads, elapsed935372615ns including handoff and guards, within2s. Engine
single kick, polls3/confirmed3, pending0/complete1, flags20000000, stable
low-six-bit delta3b, elapsed171028616ns. No SPI busy pulse was sampled;
transport freshness was established by per-transfer changed RDAT.

Result0/cleanup_result0. FM restored, analog prefix restored3, chip-ID
mailbox cleared, A-die reset/address restored, semaphore released. Remap
and RGU each4/4/4, SPI36/36/36, initial SYSRAM4096/4096/4096.
All dirty/unsafe/uncertain flags zero and CONN off at both preflight samples.
VS1/VS2 retained votes1/1 remain as in earlier experiments.

No private values or hashes are published. Temporary software buffers and
inherited private diagnostics are erased. This run verifies the designated
SYSRAM slots cleared; it does not claim all hardware latches are erased.
The command does not start firmware or apply thermal trim, and handoff data
is deliberately not retained for a future firmware consumer. Wi-Fi and an
independent network SSH path remain unavailable.

## Validation

Actual extracted C with UBSan: the new nested model shares SYSRAM with the
outer preparation model and enforces clear-before-mailbox-release ordering.
It covers map failure, four nonzero baselines, all eight dropped writes,
eight deadlines,32 write-time access/ownership faults,12 readback/final-scan
faults, valid zero data, one-shot refusal, temporary erasure and redaction.
Failure paths retain parents; even a final-scan fault after four successful
clear readbacks leaves conservative dirty metadata. Uncertain access never
triggers speculative clearing. Hardware may retain private words on failure
until reset. Model coverage cannot prove physical bus behavior or exclude
an asynchronous hardware writer.

Existing standalone private-read and full nested parent/engine/data suites
pass. Full ARM64 build and11 built-in suites, zero-error/zero-warning
checkpatch, binding/DTB validation, pin model, capacity and diff checks pass.
Payload7,469,056 bytes leaves26,085,376 bytes in32MiB boot.

USB SSH/configured, CPUs0–7, disk read-only, cache ro+norecovery, Debian hash,
battery ADC/PMIC temperature and17 LVTS samples pass. Pin-register changes
are limited to established shared drive0→8248. Retry refused with all nine
cached status hashes unchanged. Captured log has no BUG/Oops/SError/panic.
Recovery backup SHA256 remains
`455ed6cea037d6d6bd9af328d589ab39b8692edd4db2c3924e1f8da7b4722c88`.
Selected records: [attempt-87](attempt-87/). Full dmesg stays outside Git.

## Next boundary

Privately decode the thermal validity bits and target masks from the vendor
flow, with synthetic test vectors and no exposed calibration values. Audit
TOP thermal-register access, shared ownership and rollback prerequisites
before enabling a separate trim experiment. Preserve the verified handoff
as an independent diagnostic boundary; firmware-lifetime handoff still needs
integration with reset, ownership and error handling. Network support remains
prioritized before USB/Type-C takeover.
