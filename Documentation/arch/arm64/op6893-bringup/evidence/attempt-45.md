# Attempt45: bounded LVTS domain reset and device identification

Status: corrected implementation, host tests and hardware identification passed.
Current image:dfdd9316d585.
Image `cedcabbec6c6`, SHA256
`6ae991e368f85ba27b4434977da8b74c9fec2115b77612f866ba82cf0c33295c`.
Rollback:30a5bfb0c069. One-shot board experiment, not a thermal driver.

## Evidence and scope

Read-only live snapshot of7controllers found MONCTL,MONINT,PROTCTL,PROTTC,
CLKEN all0 and ID latches0x98. These latches were not updated by a device
command, so they are not failed identification results. No sensing or local
clock activity is visible. This does not establish exclusive firmware ownership.
The mainline LVTS driver explicitly warns that resetting MCU-owned LVTS can
cause firmware malfunction or AP reset. Accordingly, this experiment rejects
any nonzero monitored control/protection/local-clock state or busy serial port.

ACK reset offsets AP120/124 bit0,MCU730/734 bit10 are confirmed in
v1/inc/tscpu_settings.h. The existing TI syscon reset driver uses
regmap_write_bits (read-modify-write), so it is not reused for these SET/CLR
aliases. Existing UFS reset descriptors and behavior are left unchanged.
The one-shot helper writes exact masks via the shared infra regmap,asserts for
2us,deasserts,and makes one deassert retry if that write reports failure.
No new general reset provider is claimed. Pulse duration is an experimental
conservative delay; ACK itself leaves the minimum duration unspecified.

ARM64_OP6893_LVTS_IDENTIFY gates arch/arm64/kernel/op6893-lvts.c, additionally
checks realme,op6893 at runtime, gets the actual thermal clock by vendorID4,
and maps only AP1100b000+400 and MCU11278000+300. Hardcoded audited resources
are a temporary board diagnostic, to be replaced by proper DT resources in
a full driver. Preflight checks all7controllers before any domain reset.
Each controller:local clock on,0x8103ffff sensor reset,0x8502fc55 ID update,
expect81..87 in vendor controller order,then local clock off. Both commands
wait3us and poll DEVICE_ACCESS_START bit24 with2us intervals/200us timeout.
Busy/timeouts/mismatches propagate errors; later controllers are not touched
after an error. No sensing,interrupt enable,protection threshold,RGU route,
manual RCK or calibration writes. ID reset does change sensor state; returning
the local clock off is not claimed to restore every pre-reset device register.

## Host tests

Actual helpers compiled against fake MMIO underUBSan. Test all preflight
fields,seven valid IDs,both command timeouts,wrong ID,busy-before-command,
local clock cleanup,AP/MCU exact write addresses/masks,and write failures.
Build hashes and runs the test with existing regressions. Checkpatch file
check0errors/0warnings. Maintainer lookup retained, no communication sent.
No DT binding changes this round. Tests do not simulate external firmware.

AI-assisted code/tests/documentation with Codex. No commits or Signed-off-by.

## First hardware attempt and lifecycle correction

cedcabbec6c6 booted normally, but bare late_initcall returned-EPROBE_DEFER
before deferred_probe_initcall registered the top/infra clock providers.
No domain reset or identification occurred; all seven LVTS snapshots remained
at the original state. Converted the entry to a builtin board-specific platform
driver/device so driver-core deferred probing retries after clocks register.
No arbitrary delay or repeated MMIO loop. Suppress bind attributes to prevent
manual rerunning of the destructive one-shot test. Probe helper is not init
text, because deferred execution can outlive init memory. First logs retained.

Corrected image:dfdd9316d585, SHA256
0aaedb2e7073fb885e657dfe547250f74a368699ea06b0c0ef5cf0740b1744a4.
Host regressions and checkpatch passed again.


## Successful corrected hardware attempt

Image dfdd9316d585 boots and binds op6893-lvts-identify. The initial probe
returns-EPROBE_DEFER; after clock providers register, automatic reprobe at
0.191s performs the experiment successfully. Controllers0..6 return updated
ID81,82,83,84,85,86,87 respectively. All command operations complete without
timeout, and the probe returns0. No arbitrary boot-delay workaround is used.

Readback after probe confirms all seven local clocks,monitor enables,IRQ
enables,protection control and threshold words remain0,while ID latches retain
81..87. Five PLL/AXI/infra words and seven PMIF words match attempt44.
Thermal clock critical reference returns1/1; AXI/thermal nominal156MHz,
MAINPLL2184MHz. Eight CPUs,USB SSH,PMIC ADC,watchdog,cache ro,norecovery and
rootfs hash all pass the saved regression. No selected WARNING/BUG/Oops/Call
trace markers. Physical buttons not retested. Existing GPT warning expected.

This validates the audited AP/MCU reset sequence and LVTS command/ID path on
this bootchain. It does not validate temperature,calibration programming,
manual RC measurement,thermal protection,IRQ delivery or firmware ownership.
Next: implement bounded manual RCK and device initialization with error exits,
then calibration programming and raw sample validation before thermal zones.

Final live check at uptime122.31s: driver bound,8CPUs,thermal critical
reference1,USB SSH available,no selected kernel faults. Device left running
dfdd9316d585.
