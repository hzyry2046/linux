# Attempt51: CONN power prerequisites and live read-only snapshot

Kernel source checkpoint f12c1a18c; device still running06374ef46937.
No power-domain registration, firmware request, CONN-island access, MMIO write,
build or flash. New conn-power-snapshot.py reads seven fixed SPM/infra status
registers over existing USB SSH with an exact image/board guard.

## Live state

Two captures agree on all seven registers. SPM status0x16c/0x170 both
0x10580e01 (CONN bit1 clear), CONN_PWR_CON0x304 =0x12: reset asserted,
isolation and clock-disable set, both power request bits clear.
The domain is off. Do not access0x18000000 merely to identify the chip.
POWERON_CONFIG_EN reads0x1; this alone does not prove future writes are allowed.

Infrastructure status:0x228=e70c500e,0x258=519c0000,0x724=e7.
ACK protection bits13/14/bank2-bit2 read0/1/1 respectively. This is inherited
state, not a completed vendor power-down sequence. Mainline's additional
bit18 is1, bank1-bit10 is0. Static bits cannot establish the correct sequence.

After capture, USB SSH works, CPU0–7 online, sdc remains read-only.
The attempted /sys/class/watchdog/watchdog0/state check found no such file;
this round does not claim watchdog regression coverage or failure.

## Existing mainline provider: do not enable blindly

Contrary to needing a wholly new provider, drivers/pmdomain/mediatek already
contains mt6893-pm-domains.h and a mt6893-power-controller match. CONN control
and power status offsets match ACK. Bus-protection entries differ:

| Step | Mainline current table (SET/CLR/STA; mask) | ACK6.6 and4.19 |
|---|---|---|
|1|0x2a0/0x2a4/0x228; bits13+18|same offsets; bit13 only|
|2|0x2a0/0x2a4/0x228; bit14|same|
|3|0x2a8/0x2ac/0x258; bit10|0x714/0x718/0x724; bit2|

Mainline reuses MT8192 definitions. ACK6.6 clk-mt6893-pg.c and original4.19
clk-mt6885-pg.c agree with each other. This is a candidate hardware-table
mismatch, not yet an experimentally reproduced failure in mainline.

Ordering also differs: generic mainline clears protection in reverse table
order (3,2,1); vendor power-on clears2,3,1. Vendor writes the SPM key before
control writes, generic control path inspected does not do so. Resolve these
before assuming a table-only change is sufficient. No speculative patch or
power experiment made this round.

CONN KEEP_DEFAULT_OFF avoids initial power-on but initial bookkeeping and
consumer runtime PM still need review. Only represent the needed CONN child;
do not enable unrelated domains or add a consumer that automatically powers
it on before resources are ready.

## PMIC prerequisites

Current op6893_boot_defconfig disables REGULATOR_MT6359. Source already contains
VCN13/VCN18/VCN33 and VS2 descriptors, including BT/Wi-Fi wrapper entries;
their presence does not establish runtime rail mapping or correct DT supplies.
Audit MT6359P descriptor selection, real upstream supplies and direct vendor
VS2/low-power writes before enabling the regulator provider. Preserve unused
regulator suppression and existing PMIF transport.

## Next independent work

Resolve exact protection-table provenance and power sequencing, then build a
bounded CONN-only resource implementation. Audit the PMIC rail mapping in
parallel with userspace binary analysis. Firmware/NVRAM reverse engineering
is not a blocker for these tasks. Hardware power-on requires the resolved
sequence, supplies, clock-buffer and EMI/resource ownership; no guessed
compatible or fake success callback will be used.
