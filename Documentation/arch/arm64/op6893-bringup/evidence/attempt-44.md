# Attempt44: preserve-on thermal gate with AXI reference

Status: implementation, host tests and initial hardware regression passed.
Image `30a5bfb0c069`, SHA256
`1b25285e9bf507623d3e4f95e03d3cde1bdaf4207d12337e4838af6e35955c83`.
Previous running/rollback image: `9b805c863bf1`.

ACK identifies CLK_IFRAO_THERM=4 as infracfg bank0bit10, parent axi_ck.
Bank0 SET80/CLR84/STATUS90 relative10001000. Existing live status0 means
thermal inherited on. Add the gate to the existing board-gated infra provider,
parent mt6893_axi_observed and CLK_IS_CRITICAL. onecell size grows to5;
unused IDs2/3 remain invalid. DT infra inputs now explicitly name pwrap,axi.
Resolve AXI before gate registration, reject zero rate, propagate regmap read
errors and reject an unexpectedly off thermal gate (-EBUSY). No attempt to
start the LVTS block from an unknown clock-off state.

CCF critical registration performs a CLR84 bit10 write to preserve on state.
This is an idempotent gate-enable operation, not a read-only addition. No
PLL,AXI mux,reset,LVTS controller,thermal IRQ or hardware protection writes
are introduced. No real gate-off cycle is tested. The critical reference is
a temporary bring-up hold, not an LVTS consumer or full runtime-PM lifecycle.
The gate's CCF rate uses its cached parent rate; refresh the AXI observer before
checking the child. No claim of autonomous firmware frequency synchronization.
Firmware changes during preflight/registration are not interlocked.

Tests compile the actual gate descriptor, preflight helper and generic MediaTek
gate operations against fake regmap underUBSan. Validate inherited-on/off,
zero input,read-error propagation;6initial status patterns demonstrate both
SET/CLR bit10 polarity and preservation of adjacent bits. Gate-off testing
is host-only. Build hashes/runs this test alongside existing regressions.

AI-assisted implementation/tests/documentation with Codex. No commits or
Signed-off-by tags. Maintainer lookup saved locally, no messages sent.

Host validation complete: kernel build, all integrated host regressions,
checkpatch(file and delta)0errors/0warnings, dt_binding_check including
yamllint/example, and actual board DTB validation passed. Payload7434240bytes
fits32MiB boot. Final DT infra clocks point to topckgen IDs150(pwrap),117(AXI).
Watchdog reset requested with serial-targeted flash/reboot already queued.


## Hardware results

Serial-targeted flash boot followed by immediate reboot succeeded. Exact
release7.3.0-op6893-d1-30a5bfb0c069+. CCF shows mt6893_therm under
mt6893_axi_observed, both156000000Hz, thermal prepare/enable counts1/1.
AXI also has1/1 references. Infra status remains0 (thermal bit10 clear/on).
All five PLL/AXI/infra words match before reset; all seven PMIF words match
attempt43. The matching snapshot does not mean no gate write occurred: CCF
critical registration uses the idempotent CLR bit10 operation described above.

Sixteen rounds AXI,thermal,MAINPLL and PMIC temperature reads passed with
156MHz/156MHz/2184MHz respectively. clk_summary completes. Eight CPUs online,
USB SSH working,watchdog feeder active,cache ro,norecovery,sdc read-only,
Debian rootfs SHA256 matches expected4b831520cce5df878a6ddb1b428c235d1735f5eea9fe5148f0fa6d0783f90051.
No CPU WARNING/BUG/Oops/Call trace or read/write-failed markers in captured
logs. GPT warning is expected. Physical buttons not retested.

Still not implemented: LVTS reset ownership,manual RCK,temperature sampling,
thermal zones,protection policy. No LVTS register access or IRQ enabling in
this attempt. Next step is AP/MCU reset handling and bounded LVTS initialization,
with calibration provenance and error exits retained from earlier audits.

Final health: uptime106.03s (over two30s watchdog periods); AXI/thermal
rates156MHz,thermal reference1,eight CPUs online,no selected kernel faults.
Device left running mainline30a5bfb0c069.
