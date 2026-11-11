# Attempt88: private TOP034/038 repeated reads and complete cleanup

2026-11-04 Asia/Shanghai. Image `bf54e7cab5af`, release
`7.3.0-op6893-d1-bf54e7cab5af+`. Boot SHA256
`d0b557b7ba5879b78698f82d4fdb9234b1fa108b4714a88cf318c2cda5836986`.
Queued serial-targeted flash/reboot before requesting mainline87 watchdog
reset. Fastboot was captured and flashing/reboot succeeded. Release, raw
boot hash and attempted0 matched before the one-shot experiment.
Device remains on mainline88; recovery backup unchanged.
AI-assisted implementation/tests/docs; no external submission or AI DCO.

## Result

One `adie-thermal-read` succeeded after the87 private SYSRAM handoff and
verified erasure. Fixed TOP034/038 were each read twice, with ID→target→ID→CTRL
for every word: four target reads,16 SPI transfers, two repeated comparisons
matched. Every CTRL equaled the accepted full post-kick state. No busy pulse
was sampled; freshness came from each transfer's changed RDAT.

Thermal requested1/started1/complete1/cleared1; issuedf/readf/matched3,
transfers16/busy_count0. Data elapsed1342856846ns includes earlier private
reads, SYSRAM handoff, thermal reads and all guards, within the unchanged2s
budget. Engine elapsed171045539ns, one kick, three stable controls with
low-six-bit delta3b, pending0/complete1. Earlier dataff/ff/f and handofff/f/f
also completed, with handoff dirty0.

Result0/cleanup_result0; FM, analog prefix, chip-ID mailbox, A-die reset and
SPI address restored; semaphore and all nested parents released as designed.
Remap and RGU each4/4/4, SPI36/36/36, initial SYSRAM4096/4096/4096.
All dirty/unsafe/uncertain flags zero. CONN off at both preflight samples;
VS1/VS2 votes1/1 remain as in previous experiments.

Thermal baseline/response values are private: they may contain calibration
inherited from bootloader/Android. Values and hashes are not published.
The temporary three-word structure and individual transport samples are
explicitly erased. Existing RDAT-derived diagnostic redaction/erasure applies.
Hardware RDAT may retain a private word on failure; software erasure is not
a claim of hardware-latch erasure.

There were no TOP034/038 writes, trim application, temperature calibration or
firmware startup. This result establishes repeated reading under the current
guards; it does not establish read side-effect freedom, register write masks,
extra-bit meaning, physical accuracy or analog rollback semantics. Wi-Fi and
independent network SSH remain unavailable.

## Validation

Actual extracted C with UBSan:32 address/trigger dropped writes,128 write-time
guard losses,16 SPI timeouts,two second-round mismatches,four changed controls,
four data-budget overruns,no-busy/stale/zero responses,15 later cleanup faults,
private temporary erasure/redaction and one-shot refusal. Error cases retain
FM/analog/mailbox/semaphore/parents; already-erased private SYSRAM stays zero.

Original standalone data suite and all nested parents through87 pass. New
harness initially had a misleading-indentation compiler warning and counted
unrelated12-byte diagnostic erasures as thermal-buffer erasures. Corrected
instrumentation wraps only the thermal temporary-buffer erasure; production
code did not change for these test corrections. The thermal suite was rerun
against a saved parent C model containing the full current A-die source
(byte-for-byte inclusion checked). Complete runnable chained test is in
`tools/test_conn_adie_thermal_integration.py`; focused runner/model and initial
failure logs remain outside Git. The public chip-ID stale-response fixture
is excluded from private-sentinel scans, as in86.

Final image was rebuilt after correcting tests so its source manifest includes
the final harness. Earlier image `a997f6677ea7` was not flashed.
Full ARM64 build/11 built-in suites, zero-error/zero-warning checkpatch,
binding/DTB validation, pin model, capacity and diff checks pass.
Payload7,467,008 bytes leaves26,087,424 bytes in32MiB boot.

USB SSH/configured, CPUs0–7, read-only disk/cache ro+norecovery, Debian hash,
battery ADC/PMIC temperature and17 LVTS samples pass. AP pin-register change
is limited to established shared drive0→8248. Retry refused and all nine
cached status hashes unchanged. No BUG/Oops/SError/panic in captured log.
Selected records: [attempt-88](attempt-88/); full dmesg stays outside Git.

## Next boundary

Continue the [thermal trim audit](../THERMAL-TRIM-AUDIT.md): establish meaning
and ownership of TOP034 bit16 and TOP038 bits26/28, register reset/writeback
semantics, and the exact sequential host behavior needed before any trim
write. Read success alone does not authorize choosing a mask interpretation.
Keep Wi-Fi as the next independent access path before USB/Type-C takeover.
