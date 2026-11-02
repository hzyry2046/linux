# Attempt43: read-only AXI rate observer

Status: implementation, host tests and initial hardware regression passed.
Image `9b805c863bf1`, SHA256
`763cae7025ae7a06172d6e0a406ccf7ebc3dcd3acc708e8df578345252e38ff9`.
Rollback image: `37e7231576c9`.

## Scope and design adjustment

ACK CLK_CFG_0 low3bits select26MHz,MAINPLL/16,/14,/8,/10,/12,ULPOSC/4.
AXI has no gate in ACK MUX_CLR_SET_UPD, so no assumption about bit7 is made.
CLK_TOP_AXI117 is a1:1 alias of CLK_TOP_AXI_SEL189; both reference the same
observer hw. mainpll is now a third explicit DT input to topckgen, obtained
before registering critical PMIF clocks. PMIF Kconfig selects the existing
board-gated read-only MAINPLL driver. Managed observer registration unwinds
on failed probe, and uses the same syscon regmap as the existing top mux.

The observer is intentionally parentless in CCF, not a full mux/factor tree.
clk.c clk_core_get_rate_recalc() refreshes the requested clock's subtree,
not ancestors; get_parent is not reread on every rate query. A plain read-only
mux would therefore risk stale input rates and firmware-selected parents.
The observer reads the real selector and queries the selected external input
with clk_get_rate(); its lack of a CCF parent link prevents recursive subtree
recalculation through MAINPLL. It reads the selector again after querying the
source and returns0 on errors,reserved7,zero source or an observed transition.
Readback cannot detect ABA transitions or make firmware accesses atomic.

Only recalc_rate is exposed. No PLL/mux/gate/reset writes are added. Existing
PMIF writes remain as before. No real hardware selector transition is induced.
ULPOSC and26MHz reference values remain nominal, not physical measurements.
No thermal consumer yet; DVFS, runtime PM, suspend and firmware ownership
remain unresolved. This is diagnostic observation, not full AXI management.

## Host validation

Actual C callback compiled with fake regmap/clock inputs under UBSan tests:
8selectors,7live input/source changes,49within-read transitions,first/second
read failures,inactive input and unrelated register bits. Build hashes and
runs the test. Existing MAINPLL,FDT,pwrap,ADC tests passed. Kernel build has
no warning/error markers. File and incremental patch checkpatch both report
0errors/0warnings. Maintainer lookup saved; no messages sent.
Binding example compiled and validated. A YAML line-length warning was fixed
and the final image rebuilt; final yamllint, dt-doc-validate and targeted DTB
validation passed. Logs retained separately.

AI-assisted implementation/tests/docs with Codex. No commits or Signed-off-by.


## Hardware regression

Serial-targeted flash boot and immediate reboot succeeded. Device reports
7.3.0-op6893-d1-9b805c863bf1+. CCF reports156000000Hz AXI and2184000000Hz
MAINPLL. Sixteen alternating AXI/MAINPLL/PMIC temperature queries all pass;
clk_summary also completes, with no recursive clock-query stall observed.
AXI appears as a parentless rate observer as intended, while MAINPLL lists
topckgen as a named consumer. This is not proof of general clock-tree PM.

Five PLL/AXI/infra readback words match pre-reset values; seven PMIF words
match attempt42. CPU0–7 online,USB SSH available,PMIC ADC reads succeed,
watchdog feeder alive,cache ro,norecovery,sdc read-only,Debian SquashFS SHA256
matches the expected4b831520cce5df878a6ddb1b428c235d1735f5eea9fe5148f0fa6d0783f90051.
No CPU WARNING/BUG/Oops/Call trace or read/write-failed markers in the saved
logs. Intentional GPT warning remains; physical keys not retested.

Next: add thermal gate with an explicit AXI input, preserving the inherited
on state, then handle AP/MCU reset resources separately before LVTS sampling.

Final health check: uptime 103.97 seconds (more than two30s watchdog
periods), USB SSH and both rates still correct; no selected kernel fault markers.
Device left running the successful mainline image.
