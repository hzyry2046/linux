# Attempt46: manual RCK and EDATA readback

Status: implementation, host tests and hardware RCK/EDATA validation passed.
Image34b572808760 SHA256
d9bce78c9c482d5a310e047689cd55adf4705d6082bb3f6b8c2bb0c4e4c1c604.
Rollback:dfdd9316d585. Still a one-shot board diagnostic, no thermal zones.

Decode the validated little-endian LK atag,devinfo (208..400words,exact length)
from /chosen before clock acquisition or reset. Use words116..119,190..207,
17count_r,7controller count_rc; reject absent/zero calibration and unsupported
golden values. No fake defaults and no physical efuse MMIO. Decoder matches
prior Python/ACK calibration extraction; fresh ACK fixture is hashed by build.

After all IDs pass, initialize and measure each controller independently with
sensor counts2/2/4/2/2/2/3. ACK MT6893 command sequence: release counting state,
20us window,chopper/bandgap/reserved setup,TS_EN toggle/latency,manual RCK.
Per sensor: select RCK,single mode/latency,TS_EN toggles,10us settling,start
counting,30us wait,200us bounded sensing-bit25 poll,serial RDATA read with at
least5us settling,disable TS_EN. Every serial command retains200us access-bit24
timeout. Restore sensor selection0x10 and disable TS_EN,then local clock off.
Failure stops processing; cleanup is best effort if the serial bus stays busy,
with an explicit error log. Clock-off alone does not prove analog shutdown on
an unresponsive bus. No subsequent calibration writes on RCK failure.

Refinement uses exact ACK integer max/min*1000 >1061 rule or raw0 fallback to
factory RC. Use64-bit multiplication and divide,then EDATA=(used_rc*count_r)>>14.
Reject zero/out-of32-bit-range EDATA. Only after all17measurements succeed,
write each controller's EDATA54..60 for its actual sensor count,verify readback,
and close local clock. If readback fails,abort remaining writes; already written
calibration is retained with sensing disabled. No calibration atomicity claim.

No periodic sensing,IRQ,thermal protection,RGU route,DVFS or CPU stress. EDATA
readback does not establish calibrated temperature accuracy. Controller state
will be reset/reinitialized again by the eventual thermal driver.

Host UBSan tests extract actual helpers: live saved calibration compared with
independent Python decoder,malformed payloads/zero values,1..4sensor flows,
serial timeout injected at every command,sensing timeout,RC fallback and
boundary rounding,overflow,EDATA mismatch and stopped local clocks. Existing
identification/clock/PMIF/ADC/FDT regressions remain build prerequisites.

AI-assisted implementation/tests/docs with Codex. No commits,Signed-off-by or
maintainer communications. Checkpatch and maintainer lookup retained.


## Hardware results

34b572808760 booted successfully. Clock-dependent probe deferred once and
then completed in about1.95ms; all seven IDs remain81..87. All17manual RC
measurements succeeded,raw range2745..2774,max integer ratio1005/1000 vs
factory,zero fallback cases. EDATA range5834..6010. The live devinfo blob
was captured,decoded independently by lvts-calibration.py,then compared with
each logged factoryRC/count_r/refinement result and every EDATA register.
All17entries match exactly (verify.py,verification.json).

After calibration,all7local clocks,monitor enables,IRQ enables,protection
control and threshold words read0. Outer thermal gate remains critical-on.
PLL/AXI/infra and seven PMIF snapshots match attempt45. Eight CPUs,USB SSH,
PMIC ADC,watchdog feeder,cache ro,norecovery,read-only disk and rootfs hash
pass the saved regression. No selected WARNING/BUG/Oops/Call trace or RCK/
cleanup/readback failure markers. Physical keys not retested; GPT warning
expected. No SoC temperature samples have been taken yet.

Next: configure controller timing/sensor selection for bounded raw sampling,
validate ready bits and raw-to-temperature conversion against ACK coefficients,
then consider a diagnostic temperature interface. IRQ/protection policy and
thermal zones remain separate work after readings are validated.

Final health at uptime140.65s:8CPUs,thermal critical reference1,driver
bound,PMIC read and SSH successful,no selected faults. Device left running
34b572808760.
