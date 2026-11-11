# Attempt83: unexpected efuse control changes confined to low six bits

2026-11-03. Image `4434b68988c7`, release `7.3.0-op6893-d1-4434b68988c7+`.
Boot SHA256 `4aa4bd270b870e7996617889a17b8aa315046cd41337f8735ca1b1ffdfaf1316`.
Queued serial-targeted flash/reboot succeeded; release, raw boot hash and
initial attempted=0 matched. AI-assisted implementation/tests/documentation.
No external submission or AI DCO.

## Observation and limits

One address0/read-mode kick again returned EIO at `adie-efuse-engine-state`.
The added cached XOR mask, excluding kick30/valid29, is **0x3b**: positions
0,1,3,4,5 changed. No other nonstatus bit changed in this first control sample.
This is a difference mask, not the original or resulting low-six-bit value.
Public flags remain20000000: kick0, valid1, address0, mode0.

Issued1, pending1, complete0, transfers3, polls1, confirmed0; no SPI or engine
busy pulse sampled. elapsed_ns60170769 includes guards, not hardware latency.
No timeout occurred. This identifies the location of83's mismatch;82 did not
record a difference mask, so identical bit changes in82 are not proven.

The strict acceptance rule is unchanged. The prerequisite requires original
kick/valid zero, making the XOR comparison equivalent to82's masked equality.
No extra hardware transaction was added. State remains uncertain and all
parents, FM, analog configuration, mailbox and semaphore11 were retained.
No private data register reads, thermal trim or firmware startup occurred.
This is not an accepted completion or a passed cleanup test.

Retry refused; all nine cached hashes unchanged. USB SSH/configured, CPUs0–7,
read-only storage and Debian image hash passed. No BUG/Oops/SError/panic in
captured log. ACK backup unchanged. Recovery to81 was queued before reset and confirmed: release/raw boot hash
match, attempted0, all dirty/uncertain states zero, CONN off at both preflight
samples, CPUs0–7 and USB configured. Device remains on stable mainline81.

## Register-semantic lead, not a cross-chip specification

The local MT6639 EEF_TOP header names bits5:0 `EFSROM_AOUT`; mode7:6,
kick30 and valid29 have matching positions, but its AIN field is27:16 rather
than the MT6893 vendor helper's25:16, and its register lives in a different
block. The local MT7601U driver also names bits5:0 AOUT and checks its all-ones
value after a kick. These are evidence for investigating an output-address
field, **not proof of MT6635 behavior**, mapping or error semantics.

MT6893's vendor helper only polls kick and valid; it does not require other
control bits to remain equal. Its initial clear-kick write remains another
sequence difference. Do not apply another chip's error values or remove all
nonstatus checks based solely on these similarities.

Next: find MT6635-specific field semantics, or design a separately bounded
observation of repeated low-six-bit state while retaining all parents and
keeping cleanup eligibility false. Such observation must not read private
fuse data or silently turn the current diagnostic failure into success.
Wi-Fi and independent network SSH are still unavailable.

## Validation

Actual-C/UBSan standalone and nested suites passed existing fault injection
and per-bit changed-mask checks for all30 nonstatus bits. Nested status output
and repeat cached reads passed; successful modeled completion reports changed0.
Full ARM64 build and11 built-in suites passed; checkpatch zero errors/warnings,
pin model, boot capacity and diff checks passed. Binding/DT unchanged this round.
Payload7,464,960 bytes leaves26,089,472 bytes in32MiB.

Selected records: [attempt-83](attempt-83/). Full dmesg stays outside Git.

Reference input hashes (local source):

- `/data/src/6.6-exp/android_kernel_modules_oneplus_mt6833/vendor/mediatek/kernel_modules/connectivity/wlan/core/gen4m/include/chips/coda/mt6639/eef_top.h`: `bb5903f476b62235bb0a6eb2f79f2ceff54b6677632419f33ad722633a640788`.

- `drivers/net/wireless/mediatek/mt7601u/regs.h`: `efe203400d13d0ea25f36027c06564143313721b55d76222de6b2e6d6261f163`.

- `drivers/net/wireless/mediatek/mt7601u/eeprom.c`: `968f5f27daaac9aae6d64973da847addbb6a2ae9a73eb89b3b88b0fbbe073a84`.
