# Attempt81: efuse control baseline under held FM configuration

2026-11-03. Image `b2d5ede80b81`, release `7.3.0-op6893-d1-b2d5ede80b81+`,
boot SHA256 `f9570f51111fc13762629f4a1249454885c8d7dde9549a8879c37eefcd6c733e`.
The single queued serial-targeted flash/reboot succeeded following watchdog
reset. New release/raw boot partition hash matched and attempted=0 initially.
Device remains on mainline81, CONN off. ACK backup unchanged. AI-assisted
implementation, tests and documentation; no external submission or AI DCO.

## Result

One `adie-efuse-ctrl-read` succeeded. It held the already-verified TOP064=7700,
TOP0bc=21, ID mailbox66358a11 and FM_CTRL0 while reading fixed TOP addresses
02c,108,02c,108. Both ID responses matched66358a11; both complete control
words matched inside the kernel. No busy pulse was sampled for these four
transfers, so each passed using its own changed-RDAT evidence.

| Sample | Object | Public result |
|---|---|---|
| 0 | Chip ID | Matches this cycle's E3 ID |
| 1 | EFUSE_CTRL | Known fields AND63ff00c0 =0 |
| 2 | Chip ID | Matches this cycle's E3 ID |
| 3 | EFUSE_CTRL | Known fields AND63ff00c0 =0 |

Thus sampled kick bit30, valid bit29, address bits25:16 and mode bits7:6 were
zero. This is not a claim that every undocumented bit was zero. State:
`efuse_ctrl_read=f valid=f busy_mask=0 stable=1 flags0=0 flags1=0`.
The software `valid` bitmap means verified transport/ID/control observations;
it must not be confused with the hardware efuse-data-valid bit29 (zero here).

No TOP108 write command, efuse kick or reads of private TOP130/134/138/13c
occurred. SPI WDAT0 triggered TOP register reads, not the efuse engine. No
thermal trim, calibration or firmware startup ran. Public control fields are
masked; the first subsequent analog-restore ID sample also masks its before/
value diagnostics, since its RDAT can inherit the control word. Internal
freshness and full chip-ID comparison remain unchanged.

FM restored801f and was verified before reverse analog restoration (0bc=1,
064=0), mailbox clear, A-die reset, TOP address restore and semaphore release.
All dirty/unsafe/cleanup states are zero. Remap4/4/4, RGU4/4/4, SPI36/36/36,
SYSRAM4096/4096/4096 and strap6/7 passed. Final domain control12/host0;
VCN13/18 off, established VS1/VS2 parent votes1/1 retained. Idle polls971.
Digital route samples and final thermal checks remained50305a00/7f0300ff/0/0.

These are sequential guarded observations, not atomic exclusion of all other
masters, an efuse reset specification, or physical SPI timing measurements.
No fuse contents or calibration quality were established.

## Validation

Actual-C standalone test passed53 dropped MMIO writes,128 write-time state
faults, all guard/mailbox points, four SPI timeouts, inherited kick/non-read
mode refusal, differing controls, bad IDs, stale responses and first-error
retention. Tests enforce fixed read-only TOP addresses for the new child and
held FM/mailbox/analog state. Independent fake control values include low bits
that must not appear in public status.

Nested test passed51 dropped A-die/mailbox writes,32 write-time guard faults,
four timeouts, held FM/mailbox assertions, engine-state refusals, no-busy
freshness, original-error preservation, masked status under4096 bytes and
outer restoration failure. It identified the inherited-RDAT diagnostic path;
masking that slot resolved the output test without weakening internal checks.
Older FM/route/prefix/mailbox/ID/preparation tests passed through the chains.
Full ARM64 build and11 build-time suites, checkpatch (zero errors/warnings),
binding/DTB schema, pin model and image limits passed. Aligned payload
7,464,960 bytes leaves26,089,472 bytes within32MiB boot.

Regression passed USB SSH/configured, CPUs0–7, disk read-only, cache ext4
ro/norecovery, unchanged Debian SquashFS hash, battery ADC/PMIC temperature
and17 LVTS samples. GPIO155/172–182 ownership captured; AP pin differences
limited to established common drive0→8248. Retry refused; all eight cached
status hashes unchanged. No BUG/Oops/SError/kernel panic found. Selected
records: [attempt-81](attempt-81/). Full dmesg remains outside Git under
`mt6893-direct/evidence/attempt-81`.

## Next step

Design the fixed address0 efuse read trigger with explicit transport checks,
separate SPI and engine timeouts, verified read mode, kick completion and
hardware-valid handling. The vendor helper holds RFSPI semaphore11; do not
reacquire it recursively in this nested implementation. Treat private data
storage and thermal trim as separate stages. Never infer successful read
completion from an old valid bit or continue after an uncertain transfer.
Do not blindly restore a control word containing a kick bit. Wi-Fi and its
independent SSH path remain unavailable and remain the development priority.
