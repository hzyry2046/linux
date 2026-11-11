# Attempt77: first two analog configuration registers, bounded read responses

2026-11-03. Image `20ec42f843d7`, release `7.3.0-op6893-d1-20ec42f843d7+`,
boot SHA256 `6d80afd3a69128cfe51795c135f1c3f045f2e46b161f3de3e75d5a52169e3464`.
Flash/reboot completed through the queued serial-targeted client. Release/raw
boot hash matched and attempted=0 before testing. Device remains mainline77.
ACK recovery backup hash is unchanged. AI-assisted code/tests/docs; no external
submission or AI Signed-off-by.

## Results

One `adie-config-read` succeeded after fresh E3 ID `0x66358a11`:

| Sample | TOP address | Before RDAT | Response |
|---|---|---|---|
| 0 | 0x064 | 0x66358a11 | 0 |
| 1 | 0x02c | 0 | 0x66358a11 |
| 2 | 0x0bc | 0x66358a11 | 1 |
| 3 | 0x02c | 1 | 0x66358a11 |
| 4 | 0x064 | 0x66358a11 | 0 |
| 5 | 0x02c | 0 | 0x66358a11 |
| 6 | 0x0bc | 0x66358a11 | 1 |
| 7 | 0x02c | 1 | 0x66358a11 |

`config_read=ff config_valid=ff config_busy_mask=0 config_stable=1`.
Every response changed RDAT, all four separator IDs matched and both rounds
matched. No busy pulse was observed; total cycle status polls31. No TOP write
command was sent. Vendor target values7700/21 were not applied.

This establishes stable read responses in this specific prepared boot state.
It does not establish absent read side effects, a reset value, write masks,
rollback semantics, RF correctness or full analog initialization. Local vendor
source names these registers WRI_CTR2 and SMCTK11 and writes them first, but
still supplies no complete register/reset specification. See
[design/provenance](../ADIE-POST-ID.md).

Reset/address restoration, sem11 release, remap4/4/4, RGU4/4/4, SPI36/36/36,
SYSRAM4096/4096/4096 and strap6 selections/7 snapshots passed. All dirty/unsafe
and cleanup values are zero. Final domain control12, host0; VCN13/18 off,
existing VS1/VS2 parent votes1/1 retained. Mailbox and XTAL write commands were
not run in this boot. Firmware, efuse and calibration remain untouched.

## Validation and regressions

Standalone actual-C test covers21 dropped writes,105 write-time state faults,
all guards/ownership samples,8 busy timeouts, stale response, four bad separator
IDs, two unstable second-round values and original error preservation when
cleanup also fails. The double-fault test initially targeted the wrong cleanup
write index; it was corrected before building. Nested tests cover21 dropped
writes,84 state faults,8 timeouts, unstable-data unwind, outer restore failure
and one-shot command behavior. Existing ID/preparation/mailbox paths passed.

Full image build and eleven build-time suites, checkpatch, binding/DTB schema,
pin model and boot capacity/decompression checks passed. Aligned payload
7,460,864 bytes, remaining26,093,568 bytes in the32MiB boot partition.

USB SSH/configured, CPUs0–7, disk read-only, cache ext4 ro/norecovery, unchanged
Debian SquashFS hash, ADC/PMIC temperature and17 LVTS samples passed/collected.
GPIO155 baseline and172–182 idle ownership captured. All AP snapshot words
match except established common drive0→8248; GPIO180 direction/latch/mux/shared
Schmitt restored. Refused retry preserved all eight cached status hashes.
No BUG/Oops/SError/kernel panic found; full dmesg remains outside Git.

Selected logs: [attempt-77](attempt-77/). Full evidence:
`mt6893-direct/evidence/attempt-77`. Next experimental step can use these
measured baselines to constrain initial config writes, but must distinguish
readback/restoration evidence from claims about complete internal analog state.
Wi-Fi is not yet available.
