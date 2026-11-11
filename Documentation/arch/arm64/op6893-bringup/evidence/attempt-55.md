# Attempt55: CONN clock-buffer and interface pin prerequisites

No kernel changes, build, flash or reset this round. Device remains on
attempt54 image d873de3b8963, with eight CPUs and USB SSH working.
New fixed-address read-only snapshot tool records seven AP GPIO/IOCFG/infra
registers and seven MT6359P registers; no dark CONN MMIO, SET/CLR access,
AUXOUT selector changes or oscillator/pin writes. Two snapshots agree on
all 14 registers. Values describe inherited configuration, not ownership
or electrical readiness.

## Observed prerequisites still missing

- GPIO172--182 are all mode0, not the mode1 CONN analog/digital interface.
  Framework pinmux records show these pins unclaimed.
- AP2CONN host-clock request bit0 at 0x1020e504 is clear.
- IOCFG_RT drive register is zero. CONN_TOP_DATA/CONN_BT_DATA have the
  vendor-selected pull-down bits set and pull-up bits clear.
- DCXO_CW00=0x4a4d: EXTBUF2 mode1, software-enable bit clear.
  XO_WCN vote register=0xf2, PMRC_CON0=0x4007, CW12=0x8100.
  Do not interpret the clear software-enable bit as oscillator-off: output
  behavior depends on selected control mode. Original4.19's mode-name table
  calls mode1 WCN_EN_BB_G. No output status/frequency measurement was made.

ACK's saved mt6893.o confirms consys_clock_buffer_ctrl is just
`mov w0,wzr; ret`. It does not call a clock-buffer API. The adapter capability
guard excludes this GKI target. The source comment saying HW-controlled
is not, by itself, a validation that the current mainline boot provides XO.

## Pin programming reference and constraints

Vendor first-on order is: select clock schematic, common PMIC rails,
clock-buffer callback, interface pinmux, MTCMOS/host-clock wrapper, chip-ID
poll, then EMI/digital/analog setup. Do not skip pinmux because the regulator
provider now exists.

Vendor mode writes are GPIO_MODE21 mask0xffff0000 value0x11110000,
GPIO_MODE22 mask0x0fffffff value0x01111111. Drive programming clears
0x3fff8 then sets0x8248 under mask0x38ff8; data pull-downs are cleared
and pull-ups set using mask0x4800. These are source references, not writes
performed in this round.

Mainline describes mode1 functions for GPIO172--182. Its drive-field table,
also present in ACK6.6, maps GPIO175--177 from bit3 with successive 3-bit
fields; vendor literal/comment associates GPIO176/177 with bits6/9. A
future pinctrl state must account for these shared fields and verify final
readback rather than independently setting every pin to2mA then4mA.
This table difference has not been established as a driver bug and no fix
was applied.

The external-TCXO branch writes GPIO155 mode4. This board uses GPIO155
for volume-down. Shipped conninfra.cfg contains co_clock_flag=1 and
pre_cal_mode=3, with no tcxo_gpio. Parser zeros its configuration before
loading, and mt6893 selects the external branch only when tcxo_gpio!=0.
Thus this configuration selects the co-clock branch; do not introduce the
external-TCXO branch or repurpose GPIO155. Missing configuration must remain
a reported error, not an assumed clock topology.

## Next implementation boundary

Resolve real upstream PMIC supply inputs and the vendor common-rail/voter
sequence, then prepare an explicit idle/active pinctrl state preserving
GPIO155. Reconcile shared drive fields before applying that state. The
first powered test needs bounded SPM ACK/ID polling and a reviewed failure
policy, with no firmware, DMA or RF activity. XO configuration observations
are recorded as such; further readiness checks belong to that controlled
transaction. Independent Wi-Fi SSH remains ahead of USB ownership work.

Reverse-engineering output directory evidence/wifi-re is still absent;
no binary-analysis result was available to integrate. Evidence includes two snapshots, source hashes and disassembly.
Reusable tool: [conn-clock-pin-snapshot.py](../tools/conn-clock-pin-snapshot.py).
