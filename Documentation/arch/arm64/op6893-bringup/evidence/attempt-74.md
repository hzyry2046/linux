# Attempt74: fixed TOP XTAL register reads

2026-11-03. Image `396b7c61f1ed`, release `7.3.0-op6893-d1-396b7c61f1ed+`,
boot SHA256 `4cd195347aabc8475bddcac94c91753b2575bd424d365ad3f68d3b3b9d6ba7a5`.
Device runs this mainline image. ACK recovery backup was hash-checked unchanged.
AI-assisted implementation, tests and documentation; no external submission.

## Result

One `adie-xtal-cycle` returned success. Fresh ID was `0x66358a11`; subsequent
fixed reads produced TOP `0xa18 = 0xf668fff5`, `0xa1c = 0x55555fff`.
Each RDAT differed from its immediately preceding latch value. Neither ID nor
XTAL transfers had an observed busy sample; this is data-change evidence,
not a captured SPI waveform or measured clock. `xtal_valid=3` describes
transfer evidence, not validation of the analog configuration itself.

The a18 value differs from the vendor init target `0xf6e8fff5` by bit23;
a1c equals the vendor E3 target. This experiment wrote neither target and
neither equality nor difference proves physical voltage or analog readiness.
Do not treat these samples as universal cold-reset defaults: boot firmware
and power history may affect them.

Reset2→3→2 and TOP address0→b02c→ba18→ba1c→0 completed with guarded readbacks.
The cached `addr_on` field still refers to the ID address; XTAL address
readbacks are checked by the helper. Total idle/status polls13.
Sem11 was released after reset/address restoration. Remap4/4/4, RGU4/4/4,
SPI36/36/36, SYSRAM4096/4096/4096, strap6 selections/7 snapshots passed.
All dirty/unsafe fields and cleanup results are zero. Domain ended at
control0x12, host0; VCN13/18 off, existing parent VS1/VS2 votes1/1 retained.

## Regressions and evidence

USB SSH/configured, CPUs0–7, UFS disk read-only, cache ext4 ro/norecovery,
Debian SquashFS hash, ADC/PMIC temperature and17 LVTS samples collected.
GPIO155 and172–182 pinctrl state/ownership captured. AP before/after words
match except the previously documented common drive change0→0x8248;
GPIO180 direction/latch/mux/shared Schmitt state restored.
A repeated command was refused and all eight cached status hashes matched.
Full dmesg has no BUG/Oops/SError/kernel panic; the existing boot alignment
warning remains. Full logs are outside Git under mt6893-direct/evidence/attempt-74.
Selected records and host test logs are in [attempt-74](attempt-74/).

The first collection script used a wrong SPI attribute name and expected
already-mounted debugfs. It did not affect the hardware cycle. The collector
was corrected to `spi_config`, debugfs mounted, and full cached cleanup plus
regressions collected successfully. Original collection output is retained
outside Git; no second hardware cycle was run.

## Validation and scope

Build, boot capacity/decompression bounds, DTB pin model, binding/schema and
checkpatch passed. New actual-C standalone/nested tests exercise per-transfer
freshness, all guard points, dropped writes, both XTAL busy timeouts, retained
outer state and reset-before-unlock. Existing ID/preparation test chain passed.
See [post-ID design](../ADIE-POST-ID.md) for source provenance and limitations.

Wi-Fi is still unavailable. No analog writes, efuse/calibration access,
firmware download or radio startup occurred. Next work is a reviewed bounded
analog configuration stage with explicit restoration/retention policy;
these two readable registers do not establish that every vendor write target
can safely be read back or rolled back.
