# Attempt78: initial analog config writes under held ID mailbox

2026-11-03. Image `0d4e765c4b11`, release `7.3.0-op6893-d1-0d4e765c4b11+`,
boot SHA256 `2978a44953a3cca9446876a008afd3be1347cd2857d7b5407388e2e8e544480e`.
The queued serial-targeted flash/reboot completed after USB re-enumerations.
No second fastboot client was started. Release/raw boot hash matched, and
attempted=0 before testing. Device remains on mainline78, CONN off.
ACK recovery backup hash is unchanged. AI-assisted implementation/tests/docs;
no external submission or AI Signed-off-by.

## Result

One `adie-config-cycle` returned success. Fresh E3 ID was66358a11; two rounds
of fixed read responses confirmed TOP064=0 and TOP0bc=1 with ID separators.
SYSRAM mailbox was written/read back with that ID, then held while applying
TOP064=7700 followed by TOP0bc=21. Each independent read matched its target.
Reverse cleanup restored TOP0bc=1 then TOP064=0, each with an intervening
ID read and independent matching restoration readback.

| Read slot | Purpose | Before RDAT | Result |
|---|---|---|---|
| 0 | Applied064 | 66358a11 | 7700 |
| 1 | Applied0bc | 7700 | 21 |
| 2 | Restore0bc ID separator | 21 | 66358a11 |
| 3 | Restored0bc | 66358a11 | 1 |
| 4 | Restore064 ID separator | 1 | 66358a11 |
| 5 | Restored064 | 66358a11 | 0 |

All table values are hexadecimal. Each RDAT changed, both separator IDs
matched; no busy pulse was sampled. The complete cycle recorded86 status
polls. `prefix_issued=95 applied=3 restored=3 dirty=0 read=3f busy_mask=0
cleanup=0`. Writes issued alone were not used as success evidence.

Mailbox contents were checked by guards throughout the analog subtransaction.
Only after both dirty bits cleared did the code clear/read back mailbox0,
reassert A-die reset, restore TOP address and release semaphore11. Guards are
sequential observations, not atomic exclusion of arbitrary other masters.

Remap4/4/4, RGU4/4/4, SPI36/36/36, SYSRAM4096/4096/4096 and strap6 selections/
7 snapshots passed. All dirty/unsafe and cleanup results are zero. Domain
ended at control12, host0; VCN13/18 off, existing VS1/VS2 parent votes1/1 retained.

This verifies the two vendor target words and saved-value restoration in
this prepared state. It does not prove reversal of all internal analog state,
absence of transients, RF correctness or a general rollback/reset protocol.
FM SPI settings, thermal routing, efuse, calibration and firmware were not
activated. XTAL write experiment was not run in this cycle. See
[design/provenance](../ADIE-POST-ID.md) for strict E3/0/1 baseline checks,
partial-application cleanup and containment rules.

## Validation

Standalone actual-C tests cover43 dropped writes,215 write-time faults, all
AP/CSR guard calls, ownership and mailbox samples,10 transfer timeouts,
baseline refusal, corrupted/stale responses and partial application. Nested
tests use shared SYSRAM plus independent analog state, covering172 write-time
faults, analog-restore-before-mailbox-clear/reset assertions, cleanup double
failure, uncertain ID separator retention and outer restore failures.
Old ID/mailbox/preparation/config-read paths passed. The no-busy dropped-read
test initially expected cleanup success; it was corrected to expect retention
because the cleanup separator remained unchanged and therefore lacked fresh
response evidence. Production semantics were not weakened to pass this test.

Full ARM64 image build and eleven build-time suites, checkpatch, binding/DTB
schema, pin model and boot/decompression limits passed. Aligned payload
7,462,912 bytes; free26,091,520 bytes within32MiB boot.

## Regressions and next step

USB SSH/configured, CPUs0–7, disk read-only, cache ext4 ro/norecovery and
unchanged Debian SquashFS hash passed. ADC/PMIC temperature and17 LVTS samples
collected. GPIO155 baseline and172–182 idle ownership captured. All AP snapshot
words matched except established common drive0→8248; GPIO180 direction/latch/
mux/shared Schmitt restored. Refused retry preserved all eight cached status
hashes. No BUG/Oops/SError/kernel panic found; full dmesg remains outside Git.
Selected records are in [attempt-78](attempt-78/); full logs are under
`mt6893-direct/evidence/attempt-78`.

Next vendor stages are FM SPI read-format settings and thermal SPI address
routing, before efuse handling. They must execute while these config values
and mailbox are held, then restore before analog cleanup in a bounded test.
Wi-Fi remains unavailable; no firmware has run.
