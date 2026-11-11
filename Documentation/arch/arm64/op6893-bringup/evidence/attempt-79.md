# Attempt79: fixed FM / thermal digital baselines under held analog prefix

2026-11-03. Image `86887415cd34`, release `7.3.0-op6893-d1-86887415cd34+`,
boot SHA256 `b95e80866292570ab8d415b04c6e1a3d46f38bc4655694d64d471747b671f779`.
The first watchdog reset returned to old mainline78 without interception.
The single queued serial-targeted flash/reboot subsequently completed; the
new release and raw boot partition hash matched, with attempted=0 initially.
Device now remains on mainline79, CONN off. ACK recovery backup is unchanged.
AI-assisted implementation, tests and documentation; no external submission
or AI Signed-off-by.

## Why reads precede route writes

Local ACK `mt6893.c:consys_thermal_query()` uses separate thermal semaphore13,
CAL_EN bit19, GPT2 bit0 and trigger bit18. Its cleanup clears bit19 but not
explicitly bit18, and comments that GPT2 disable has no effect on6893.
Thus held RFSPI semaphore11 or a zero GPT2 word alone cannot establish a
quiescent thermal engine. This round records fixed digital baselines before
implementing writes. Source `mt6893.c` SHA256 is
`6b8c401a3d743add86fa393393a30bd4500c8c2f27325d76b21e301cb8ca0de6`;
full source location and post-ID sequence are in [the design](../ADIE-POST-ID.md).

## Hardware result

One `adie-route-read` completed successfully. Fresh E3 ID66358a11 and two
rounds of TOP064=0/TOP0bc=1 preceded publishing the ID mailbox and applying
TOP064=7700/TOP0bc=21. While those values and the mailbox remained held,
all five digital words were read twice:

| Address | Name | Both readings |
|---|---|---|
| 1800400c | FM_CTRL | 0000801f |
| 18002018 | THERM_AADDR | 50305a00 |
| 18002004 | THERMCR1 | 7f0300ff |
| 18002024 | THERM_CAL_EN | 00000000 |
| 18007038 | GPT2 thermal enable | 00000000 |

All values are hexadecimal. `route_read=3ff stable=1 idle=1`; all passive
thermal ownership checks passed. These are sequential observations, not an
acquired thermal semaphore or proof of no autonomous activity. THERM_AADDR
already equals the vendor target in this prepared state; it is not proven
to be a universal reset default. No digital route/trigger/control writes
were made, and no efuse words were read.

Reverse analog restoration passed (TOP0bc=1 then TOP064=0, each with ID
separator and independent readback), followed by mailbox clear, A-die reset,
address restoration and semaphore11 release. No busy pulses were sampled;
TOP responses instead had changed RDAT. Total guarded idle polls191.
Remap4/4/4, RGU4/4/4, SPI36/36/36, SYSRAM4096/4096/4096 and strap6/7 passed.
All dirty/unsafe/cleanup fields are zero. Final domain control12, host0;
VCN13/18 off and established VS1/VS2 parent votes1/1 remain.

## Verification

Actual-C standalone test covers unchanged digital words, six mapping failures,
every AP/CSR guard point,50 sample-time state faults, four thermal owner
reports, three active-control cases and five unstable second-round samples.
The nested test runs real parent preparation and restoration with shared SPI
and SYSRAM, including90 read-time faults (mailbox and thermal owners included),
active/changing controls, mapping-failure unwind, analog and outer restoration
failure, one-shot refusal and status length below4096. Older prefix, mailbox,
ID and parent tests pass through the same test chains. Faults injected after
a fake MMIO read are modeled after its value capture; unsafe cleanup is not
relaxed to satisfy the tests.

Full ARM64 build,11 built-in suites, checkpatch (zero errors/warnings), binding
and DTB schema, pin-field model and boot limits passed. Aligned payload
7,460,864 bytes, free26,093,568 bytes within32MiB.

USB SSH/configured, CPUs0–7, read-only disk, ext4 cache ro/norecovery and
unchanged Debian SquashFS hash passed. Battery ADC/PMIC temperature and all17
LVTS samples were captured. GPIO155/172–182 ownership was recorded; AP pin
snapshots differ only by established common drive0→8248. Retry was refused
and all eight cached status hashes remained identical. No BUG/Oops/SError/
kernel panic found. Selected evidence is in [attempt-79](attempt-79/), full
dmesg outside Git in `mt6893-direct/evidence/attempt-79`.

## Next step

Test FM_CTRL clearing mask80ff (this baseline801f therefore targets0), verify
and restore801f while analog prefix/mailbox remain held. Recheck thermal
control/ownership conditions around that transaction. Keep THERM_AADDR at
50305a00 when already correct; a no-op match is not evidence that a new write
reached hardware. Do not deliberately misroute a thermal transaction to create
a changed readback. Thermal calibration, efuse and firmware remain separate
future steps. Wi-Fi and independent network SSH are still unavailable.
