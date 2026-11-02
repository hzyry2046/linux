# Attempt40: LVTS clock dependency and peripheral support inventory

Status: source resource audit and live read-only clock snapshot complete.
No new kernel image, reboot, LVTS register access or clock/reset writes.
Device remains running fa91b68792cf.

lvts-clock-snapshot.py reads only TOPCKGEN CLK_CFG_0 at10000010 and infra
bank0 status10001090, with board/release checks. Actual values03000202 and0:
AXI selector2 => mainpll_d7_d2 (MAINPLL/14); thermal gate bank0bit10 enabled.
This establishes the inherited selector/gate state, not a measured frequency,
PLL validity, firmware ownership or a working LVTS block. A fixed26MHz thermal
parent would misdescribe this unit. No reset-register reads were attempted.

ACK clock parent list, factor and thermal gate extracted/asserted by audit.py.
Controller offsets/counts verified: MCU11278000/100/200 with2/2/4 sensors;
AP1100b000/100/200/300 with2/2/2/3. IRQ index0 SPI169 is vendor AP thermal;
index1 SPI170 is MCU. Both use the combined vendor interrupt handler. These
are source-level mappings, not live IRQ delivery tests. AP reset SET120/CLR124
bit0, MCU SET730/CLR734 bit10 relative to infracfg10001000.

Manual RCK audit: vendor measurement sequence selects sensor and single mode,
toggles sensor circuitry and starts RC counting. Refinement is enabled; zero
measured count or integer max/min*1000>1061 selects factory controller count_rc.
EDATA=(u64)count_rc_now*count_r >>14. This is source inspection, not a new
extracted-RCK execution test. Timeout helpers currently log and continue;
a mainline adaptation must propagate errors and avoid consuming failed reads.
Do not confuse a structurally valid devinfo block with ready-to-program EDATA.

Next implementation gate: establish MAINPLL readback/rate and AXI parent
ownership, then add the real thermal gate/reset resources. Design MT6893
manual-RCK initialization/error unwinding before enabling LVTS. Keep hardware
protection and AP-reset behavior separately audited; no CPU stress testing or
DVFS/suspend yet.

Live regression: expected release,8CPUs,USB SSH,cache ro,norecovery,watchdog
and key-device registration remain available. PMIC die diagnostic36397mC;
battery raw20883. Seven PMIF snapshot registers identical to attempt39;
captured dmesg has no CPU WARNING/BUG/oops/call trace or PMIF transaction error.
No physical key event retest. Hardware power-key fault reported by user remains
separate from software support status.

Created PERIPHERAL-STATUS.md as current support inventory with evidence links,
explicit partial support/inherited-state constraints and next dependencies.
Sources/hashes and assertions: attempt-40/audit.py and audit.json; live clock
snapshot clocks.json; live regression live.txt and pmif.json. Code/analysis
and documentation generated with Codex assistance; no commits or Signed-off-by.
