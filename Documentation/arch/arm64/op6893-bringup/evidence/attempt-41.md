# Attempt41: MAINPLL readback and ownership audit

Status: live read-only register capture and extracted-code rate tests complete.
No kernel/provider changes, reboot, PLL/gate/reset writes or LVTS MMIO access.
Image fa91b68792cf remains running.

ACK apmixedsys maps1000c000; MAINPLL CON0/1/3 offsets340/344/34c. MAINPLL
has22PCW bits, explicitly8integer bits (not the generic7bit default),14fraction
bits,postdiv bits26:24. Initial live values:CON0=ff8003e1,CON1=80150000,
CON3=80000001; AXI CFG0=03000202,infra gate status0. PLL enable and power
bits set,isolation clear. PCW150000,postdiv1,nominal reference26MHz =>
MAINPLL2184000000Hz and selected MAINPLL/14 AXI156000000Hz. Readback is not a
lock/frequency measurement or proof of clock stability under future transitions.

mainpll-snapshot.py captures only these five audited registers with board and
release checks; no writes. tests/test_mainpll_rate.py extracts actual mainline
__mtk_pll_recalc_rate(), supplies pcwbits22/pcwibits8 and compares56boundary/
rounding/postdivider combinations under UBSan. All match; live decode checks
2184MHz/156MHz. Failing to override integer bits would halve the calculated
rate; no such incorrect provider has been installed here.

ACK DT places mainpll in fhctl map0 with method fhctl-mcupm,fh-id10,perms1c.
This is evidence of a firmware-related control path, not proof of current MCU
activity. Generic mtk_pll_prepare/unprepare writes power,isolation,enable and
reset-bar registers. Therefore do not instantiate ordinary writable PLL ops
just to expose an inherited rate or enable a thermal consumer.

## Proposed first CCF implementation boundary

Use board-gated read-only MAINPLL and AXI descriptors: recalc_rate reads live
PCW/postdiv; get_parent reads actual AXI selector; no set_rate/set_parent,
prepare/unprepare power writes. Preserve26MHz and oscillator inputs and map
all documented AXI parents; unsupported/reserved state must not silently turn
into a fixed nominal rate. Set appropriate no-cache rate policy because LK/
firmware may own configuration. Require valid input/power state at probe.

Register thermal gate separately after read-only chain is validated. Preserve
existing PMIF provider, sparse clock IDs and shared syscon reset mapping.
Do not imply full PLL ownership or suspend support. Before hardware tests,
check lifecycle/unwind behavior and prove no PLL/mux writes in fake-MMIO tests;
compare before/after register snapshots on device. Gate/reset and manual RCK
remain subsequent changes. No new binding or driver is claimed in this audit.

Live regression: expected kernel,8online CPUs,PMIC temperature read and USB SSH
available; captured dmesg contains no CPU WARNING/BUG/oops/call trace or PMIF
transaction-error markers. Support inventory updated. Source hashes and
readback/test logs stored in attempt-41/. Code/analysis generated with Codex
assistance; no commits or Signed-off-by.
