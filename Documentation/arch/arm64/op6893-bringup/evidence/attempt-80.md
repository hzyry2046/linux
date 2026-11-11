# Attempt80: FM SPI format clear and restore with thermal checks

2026-11-03. Image `f8b3b7574fe3`, release `7.3.0-op6893-d1-f8b3b7574fe3+`,
boot SHA256 `1b8c7a99f17718de9b932729d8309e5c5116d570c7df14584ff9ed0a10c86c98`.
The single serial-targeted queued flash/reboot succeeded after watchdog reset.
New release and raw boot partition hash matched; attempted=0 before testing.
Device remains on mainline80, CONN off. ACK backup unchanged. AI-assisted
implementation, tests and documentation; no external submission or AI DCO.

## Result

One `adie-fm-cycle` succeeded. Fresh E3 ID66358a11, two-round TOP064=0/0bc=1,
held ID mailbox and applied/read-back TOP064=7700/0bc=21 preceded the digital
transaction. Two digital baseline rounds matched attempt79:
FM_CTRL801f, THERM_AADDR50305a00, THERMCR17f0300ff, CAL_EN0 and GPT2 thermal0.

| FM_CTRL stage | Value |
|---|---|
| Saved immediate baseline | 0000801f |
| Target: saved value AND NOT80ff | 00000000 |
| Independent application readback | 00000000 |
| Independent restoration readback | 0000801f |

All values hexadecimal. `fm_issued=3 read=7 applied=1 restored=1 dirty=0
cleanup=0`. Thermal address/control words were repeatedly checked unchanged
around both writes and restoration, with AP/CSR, reset, SPI idle, WB, mailbox
and passive semaphore11/13 ownership checks. The last thermal samples were
50305a00/7f0300ff/0/0. No thermal address/control/trigger writes, no efuse,
calibration or firmware operations occurred. This tests the digital FM SPI
read-format field, not an FM radio or Wi-Fi function.

After confirmed FM restoration, TOP0bc restored1 then TOP064 restored0 with
ID-separated readbacks; only then mailbox cleared, A-die reset asserted,
TOP address restored and semaphore11 released. All dirty/unsafe/cleanup fields
are zero. Remap4/4/4, RGU4/4/4, SPI36/36/36, SYSRAM4096/4096/4096, strap6/7
passed. Domain ends control12/host0; VCN13/18 off; existing VS1/VS2 votes1/1
retained. Total A-die idle polls341, no busy pulses sampled. TOP responses had
changed RDAT; FM_CTRL uses ordinary digital MMIO readback, not TOP RDAT.

Sequential thermal/ownership sampling is not atomic exclusion. A change after
a sampled word can evade that observation. The experiment does not establish
absence of transients, arbitrary concurrent masters, internal analog rollback
or physical RF correctness. See [design](../ADIE-POST-ID.md) for bounded
failure retention and separate original/cleanup errors.

## Validation

Actual-C standalone tests pass45 dropped MMIO writes,30 FM-write-time state
faults,370 read-time AP/ownership/mailbox faults,27 changed FM/thermal samples,
every guard and mailbox sample, strict baseline refusals, corrupt application/
restoration readbacks and double-failure first-error preservation. Independent
MMIO words model the FM state; digital restoration is asserted before analog
cleanup. Fault-injection expectations distinguish observable sample faults
from changes after the last sample, which the sequential guard cannot promise
to detect. No production check was weakened to satisfy the model.

Nested actual-C tests pass both FM dropped writes,28 write-time state faults,
333 sample-time faults, readback corruption, digital-before-analog restoration,
outer cleanup failures, cached status size under4096 and one-shot refusal.
Existing route/prefix/mailbox/ID/preparation tests passed through the chains.
Full ARM64 build and11 build-time suites passed, as did checkpatch (zero
errors/warnings), binding/DTB schema, pin-field model and image limits.
Aligned payload7,462,912 bytes leaves26,091,520 bytes within32MiB boot.

Regression checks passed: USB SSH/configured, CPUs0–7, disk read-only, cache
ext4 ro/norecovery, unchanged Debian SquashFS hash, ADC/PMIC temperature and17
LVTS samples. GPIO155/172–182 ownership recorded; AP pin snapshot differences
are limited to the established common drive0→8248. Retry refused with all
eight cached status hashes unchanged. No BUG/Oops/SError/kernel panic found.
Selected evidence is in [attempt-80](attempt-80/); full dmesg remains outside
Git in `mt6893-direct/evidence/attempt-80`.

## Next vendor boundary

Next is A-die efuse reading and thermal trim. The local vendor helper actually
uses RFSPI semaphore11 (already held here), not a second acquisition of that
same semaphore or an assumed use of the EFUSE enum. Its TOP108 sequence clears
kick bit30, selects read mode/address0 with mask43ff00c0, kicks, polls bit30,
checks valid bit29 and reads four private words, then applies thermal trim.
That combines transport, engine control, private data handling and calibration;
it must be split into explicit error-checked stages. Do not copy its raw efuse
logging or continue after a transfer/engine timeout. No such operation ran in
attempt80; independent Wi-Fi SSH remains unavailable and stays the priority.
