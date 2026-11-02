# Attempt32: real PMIF clock provider subset

Status: flashed and booted successfully; native USB SSH and physical PMIC
key test passed. Final idle observation recorded separately in idle.txt.
Final boot ea6328ee080d, SHA256
f1b7eede30e3989d85db74572b33992a9d98ef09ed2bbf25155f3dae040945b6.
Earlier f24dc1c4bd76 artifact predates binding documentation; retained, not flashed.
Baseline/rollback boot268105891ada; Debian9825862f46b0 unchanged.

Built-in board-gated COMMON_CLK_MT6893_PMIF provides the audited topckgen
fixed factors+selector and infracfg PMIC AP/TMR gates. Retains vendor IDs;
sparse onecell arrays sized223 and2, unused entries unavailable. Parent
references resolved before registering clocks. Standard MediaTek set/clear
ops target top0x90/0x94/0x98,update0x8 bit2 and infra0x80/0x84/0x90 bits0/1.
Mux/gates marked critical to preserve supply transport through consumer
probe failure. No bind/unbind interface or module unload; no rate/parent
change requested. Registration/enable does perform gate-clear writes.
CLK_IS_CRITICAL is a diagnostic lifetime policy, not power-management support.

Root ULPOSC modeled using ACK nominal fixed260MHz declaration, with actual
fixed-factor children and hardware selector/gates. Oscillator calibration,
control and measured frequency remain inherited/unverified. Clock names
prefixed mt6893 to avoid unrelated SoC driver collisions. Existing infracfg
syscon reused by clock provider and TI reset child (no overlapping duplicate
node); UFS reset definitions unchanged.

pwrap diagnostic path enables four DT clock references before transport
reads, reports rates and requires four references. SPI protocol and wrapper
error initialization still bypass generic paths; PMIC keys unchanged. No
IRQ sources, regulators, ADC or DVFS newly enabled. clk_ignore_unused and
regulator_ignore_unused retained.

Validation: vendor ID comparison passes; kernel build has no compiler
warnings; host FDT tests and packing pass. New clock binding dt-doc-validate,
dt_binding_check example and actual board DTB limited clock-schema checks
pass. Initial dt_binding_check skipped yamllint; installed it and final binding
check plus direct YAML lint pass without diagnostics.
Both incremental patches pass checkpatch0errors/0warnings with SPDX tooling
dependencies installed. This does not validate the entire board or existing
experimental pwrap binding. Maintainer discovery saved, nothing sent.

Baseline clk_summary is now captured after mounting debugfs. Its earlier
absence was due to debugfs not being mounted, not missing CCF debug support.
Only clk26m and its inherited USB/PHY references existed before this change.

Hardware checks passed: eight CPUs, native USB SSH,UFS root checksum/cache
readonly, PMIF16read pairs (SWCID0x5920/DEW0x5aa5), four26MHz clock
references. CCF shows both PMIC gates enable/prepare count2, selector count3,
osc_d10 count2; topology rooted in nominal260MHz ulposc, no orphan parents
in the captured tree. All seven sampled clock/PMIF registers unchanged from
attempt31. TI reset child bound; devices_deferred empty. Feeder alive at81s.

Physical test: exactly three KEY_VOLUMEUP115 press/release pairs and one
KEY_POWER116 pair via event0 mtk-pmic-keys; event-check.json asserts the
sequence. This exercises PMIC interrupt setup/acknowledgement and key reads.
No long-press reset, clock disable, rate change, failure-injection, suspend or
wrapper-error recovery test performed. GPIO volume-down registered but no
physical volume-down test repeated. Existing console/UFS mphy_rst/GPT and
unbound MFD child messages remain. No new compiler/kernel WARN observed.
Device left running mainline; no further reset requested.
No changes to GPT, rootfs image or ACK recovery. Recovery remains original
evidence/ack-boot.img. Generated with Codex assistance; no commits/signoffs.

Final idle observation:15s with parent EINT222 count20 unchanged; PMIC
hwirq48/50 each1,49/51 each3, unchanged. Uptime107s at observation end.
Final dmesg contains no kernel WARNING/BUG/Oops/Call trace signatures.
