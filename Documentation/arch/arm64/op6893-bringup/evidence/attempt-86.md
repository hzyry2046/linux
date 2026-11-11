# Attempt86: repeated private result reads, erasure and complete cleanup

2026-11-04 Asia/Shanghai (2026-11-03 UTC). Image `6033b3cb705f`, release
`7.3.0-op6893-d1-6033b3cb705f+`. Boot SHA256
`66ca4b9b1daf20bcac73bbc46437bb6e54860bf0b1d15fc7663685d70351e16a`.
Queued serial-targeted flash/reboot succeeded; release/raw boot hash and
initial attempted0 matched. Device remains on mainline86, CONN off.
ACK backup unchanged. AI-assisted implementation/tests/docs; no external
submission or AI DCO.

## Result

One `adie-efuse-data-read` succeeded. It used85's accepted stable control
completion, then read fixed TOP130/134/138/13c twice. Each word used
ID→DATA→ID→CTRL. All four word comparisons matched across the two rounds.
Every ID was checked, every post-data CTRL equaled the full accepted control,
and every transfer had independent transport freshness. No busy pulse was
sampled; each RDAT changed from its own preceding value.

Data status: started1/complete1/cleared1, issuedff/readff/matchedf,
transfers32/busy_count0, elapsed_ns809727923, within the2s data budget.
Engine status: a single kick, polls3/confirmed3, pending0/complete1,
flags20000000, stable deltas3b, elapsed_ns171038231. Timings include extensive
software guards and do not measure physical hardware latency.

No raw data words, data hashes or calibration coefficients were published.
Only transport/compare masks, counters and validated public control fields
are exposed. Private words stayed in temporary local structures, explicitly
erased on success and failure. A-die diagnostic output for this command is
metadata-only. After all outer cleanup, inherited RDAT/ID/config/prefix
caches are erased and control caches reduced to validated public fields.
This also covers initial RDAT inherited from an earlier hardware state.

Result0/cleanup_result0. FM restored, analog prefix restored3, mailbox cleared,
A-die reset/address restored and semaphore released. Remap4/4/4, RGU4/4/4,
SPI36/36/36 and SYSRAM4096/4096/4096 passed. All dirty/unsafe/uncertain flags
zero; CONN off at both subsequent preflight samples. VS1/VS2 votes1/1 remain.

This establishes repeated reads under the empirical E3 completion policy,
not the meaning/validity of individual fuse fields, physical SPI timing,
calibration quality, or Wi-Fi functionality. No private SYSRAM handoff,
thermal trim, calibration or firmware startup was performed.

## Validation

Actual extracted C with UBSan uses independent synthetic result registers,
explicit fixed address allowlists and instrumented zeroization. Standalone
and nested tests cover64 new dropped writes,1024/256 write-time guard faults,
32 SPI timeouts,four second-round mismatches,eight lost-valid control replies,
the2s boundary,stale/no-busy refusal and successful no-busy transfers.
Standalone16/nested15 later cleanup write drops confirm temporary erasure
also when outer cleanup fails. A data uncertainty retains parents and avoids
FM restoration/semaphore release. Tests scan persistent diagnostic state for
synthetic private sentinels and poison RDAT-derived caches to verify output
redaction. The known public chip-ID fixture is excluded from private-sentinel
scans; its stale-response behavior is tested explicitly.

Earlier stable-completion, strict engine, FM and nested parent suites pass.
Full ARM64 build and11 built-in suites,checkpatch zero errors/warnings,
binding/DTB validation,pin model,capacity and diff checks pass. Payload
7,467,008 bytes leaves26,087,424 bytes in32MiB boot. One verification-script
format expectation was corrected for kernel `%#x` zero output (`0x0`);
no device operation was repeated to satisfy that parser.

USB SSH/configured,CPUs0–7,read-only disk/cache,Debian image hash,battery
ADC/PMIC temperature and17 LVTS samples pass. Pin-register differences are
limited to established shared drive0→8248. Retry refused; all nine cached
status hashes unchanged. No BUG/Oops/SError/panic in captured log.
Selected records: [attempt-86](attempt-86/). Full dmesg stays outside Git.

## Next boundary

Implement a separate bounded private SYSRAM handoff/clear experiment for
vendor slots+2804/+2808/+280c/+2810, alongside the existing chip-ID+2800.
Require zero initial contents, verified private writes without raw diagnostics,
clear/readback before mailbox/reset/semaphore cleanup, and containment if any
clear cannot be verified. Only then integrate the handoff lifetime needed by
firmware. Thermal trim remains separate: first decode validity and target
masks privately, then verify analog/digital ownership and recovery rules.

On a failed private transaction hardware RDAT can still contain a private word
until reset. Software-erased refers to temporary and diagnostic memory, not
hardware RDAT. Never issue an arbitrary WDAT write to erase a read-only latch.
Wi-Fi and its independent SSH path remain unavailable and the priority.
