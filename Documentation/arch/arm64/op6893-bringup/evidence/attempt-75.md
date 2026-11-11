# Attempt75: one analog register write and verified restoration

2026-11-03. Image `862dace1d7cc`, release `7.3.0-op6893-d1-862dace1d7cc+`,
boot SHA256 `65dec43531067220879d6e65aaa775f27a4d6c5de024c99ca172dbdb611d4019`.
Device remains on this mainline image. ACK backup hash remains unchanged.
AI-assisted implementation, host tests and documentation; no external submission.

## Scope and result

One `adie-write-cycle` succeeded with fresh E3 ID `0x66358a11` and exact
XTAL baselines `0xa18=0xf668fff5`, `0xa1c=0x55555fff`.
The added five-transfer sequence ran inside the existing preparation and
semaphore lifetime, before reset/address cleanup:

| Transfer | Action | Observed readback / evidence |
|---|---|---|
| 0 | Write TOP a18=f6e8fff5 | Issued; independent verification in next transfer |
| 1 | Read TOP a18 | RDAT 55555fff→f6e8fff5, full target matches |
| 2 | Write TOP a18=saved f668fff5 | Issued; verification follows separator |
| 3 | Read chip ID | RDAT f6e8fff5→66358a11, known ID matches |
| 4 | Read TOP a18 | RDAT 66358a11→f668fff5, full saved baseline matches |

`write_issued=3 write_read=7 write_busy_mask=0 write_applied=1
write_restored=1 write_dirty=0 write_cleanup=0`. There were29 SPI status polls
across the entire transaction. No busy pulse was sampled; independent changed
RDAT and exact values supply the readback evidence. Write-trigger issuance or
idle alone is not treated as proof of a successful analog write.

Only after analog restoration and guards passed did the code reassert reset,
restore the TOP address and release semaphore11. Remap4/4/4, RGU4/4/4,
SPI36/36/36, SYSRAM4096/4096/4096 and strap6 selections/7 snapshots passed.
All dirty/unsafe fields and cleanup results were zero. Final domain control12,
host0; VCN13/18 off, existing VS1/VS2 parent votes1/1 retained.

This verifies a bounded single-register transport experiment. The full vendor
analog init order was not executed, and its preceding efuse, pad and CAL LDO
steps are not declared optional for Wi-Fi startup. No physical voltage, crystal
quality, RF behavior or ability to roll back arbitrary analog state is proven.
See [design/provenance](../ADIE-POST-ID.md) for the exact baseline restriction,
per-transfer freshness checks and failure policy.

## Validation

The standalone test runs actual C with independent analog state, covering
19 dropped MMIO writes,95 write-time guard faults, all guard and ownership
samples, five busy timeouts, bad/stale responses, three baseline mismatches
and preservation of the first error if cleanup also fails. The nested test
covers19 dropped writes,76 write-time faults, five timeouts, opt-out/one-shot
routing and outer restoration failure. The model does not erase analog state
on reset and forbids reset/unlock before restoration. Previous ID, preparation,
XTAL and lower-level test chains passed.

The first nested test compilation exposed a test-harness declaration-order
issue; an accessor declared before the MMIO stub resolved it. The corrected
suite passed before image construction. No device test used the failed harness.

Full ARM64 image build and eleven build-time suites passed. Checkpatch, binding
and compiled DTB schema, pin model, boot capacity and decompression-window
checks passed. Aligned boot payload7,460,864 bytes, spare26,093,568 bytes;
padded boot image remains32MiB.

## Regressions and records

USB SSH/configured, CPU0–7, UFS read-only, ext4 cache ro/norecovery and unchanged
Debian SquashFS hash passed. ADC raw20475, PMIC temperature40561mC and17 LVTS
samples collected. GPIO155 retained its baseline; GPIO172–182 remained owned
and idle after cleanup. All AP snapshot words match except the already-known
common drive0→8248; GPIO180 direction/latch/mux and shared Schmitt restored.
Refused retry left all eight cached status hashes unchanged.

No BUG/Oops/SError/kernel panic found. Existing boot alignment and initial
console warnings remain. Full logs are outside Git under
`mt6893-direct/evidence/attempt-75`; selected logs and verified.json are in
[attempt-75](attempt-75/). No efuse/calibration/NVRAM data was read or archived.
Wi-Fi remains unavailable: firmware, full analog initialization and calibration
are still pending. Next work should integrate the initial configuration stages
in vendor order with explicit readback or reset/retention semantics for each.
