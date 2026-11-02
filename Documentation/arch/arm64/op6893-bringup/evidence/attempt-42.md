# Attempt42: read-only MAINPLL CCF provider

Status: implementation, host tests and hardware regression passed.
Built image `37e7231576c9`, SHA256
`fee8e3c244290ef7cdb06bc8aac7ea2d803b72e4ce8b7b143ed7951083988217`.
Current hardware runs `37e7231576c9`; previous tested rollback is `fa91b68792cf`.

New board/build-gated clk-mt6893-mainpll.c exposes vendor clock ID6 via
apmixedsys1000c000. clk26m must resolve at26MHz, inherited enable/power must
be set, isolation clear and PCW nonzero. Invalid startup state fails probe.
recalc_rate reads live registers (CLK_GET_RATE_NOCACHE), uses22PCW bits with
8integer bits and rounds upward as generic MediaTek PLL arithmetic does.
Disabled/unpowered/isolated or zero-PCW runtime states report zero rate.
No prepare/unprepare/enable/disable/set_rate/set_parent callbacks or MMIO
writes. Managed mapping, clock registration and provider registration unwind
in reverse order. Builtin driver, unbind attributes suppressed. DT describes
only MAINPLL; AXI and thermal gate remain inherited and are not consumers.

Host tests compile actual rate/provider functions against fake MMIO under
UBSan:56 PCW/postdivider cases, inactive/power/isolation/zero-reference cases,
30 valid/invalid provider requests. Build includes and hashes this test.
Checkpatch file check:0errors/0warnings. Patch check has one informational
new-file MAINTAINERS reminder; existing MediaTek clock ownership applies,
lookup saved, and no experimental board maintainer entry was invented. Kernel build completed without warning/error
markers; existing FDT,pwrap,ADC scale/temperature regression tests passed.
Boot payload7432192bytes fits32MiB boot partition;26122240bytes free.
Binding checks (including yamllint and example DTB) and targeted validation
of the built board DTB passed. Logs retained. Hardware results below.

Limits: sequential register readback is not an atomic firmware snapshot, PLL
lock indication, physical frequency measurement or proof of firmware ownership.
No DVFS, suspend, new regulator control, LVTS access or stress testing.

AI-assisted implementation/tests/documentation with Codex. No commits,
Signed-off-by tags or maintainer communications. Maintainer lookup retained
in attempt-42/maintainers.txt. Before-register capture:attempt-42-before.json.


## Hardware results

Serial-targeted flash boot/reboot succeeded (flash.log). USB SSH reports exact
7.3.0-op6893-d1-37e7231576c9+. Driver probe and CCF debugfs report2184000000Hz;
16 subsequent reads agree. Five PLL/AXI/infra registers exactly match the
pre-reset snapshot. This comparison does not prove the absence of transient
firmware activity. No PLL writes exist in the added driver.

CPU0–7 online; PMIF parent and AP/TMR clocks nominal26MHz, seven-register
PMIF snapshot retained. PMIC temperature and voltage reads succeed, including
16consecutive temperature reads. Watchdog feeder alive. cache remains
ro,norecovery, disk sdc read-only, Debian SquashFS SHA256 matches
4b831520cce5df878a6ddb1b428c235d1735f5eea9fe5148f0fa6d0783f90051.
No CPU WARNING/BUG/Oops/Call trace in captured regression logs. Intentional
GPT warning remains. No physical key retest. Device left running mainline.

Next: separately implement read-only AXI parent/divider chain, then validate
thermal gate/reset resources before any LVTS controller initialization.
