# MT6893 hardware and boot capacity audit — 2026-11-02

## 2026-11-14：当前接续方向

优先为基带等较大项目搭建框架，再逐层完善。基带内核对比、底本选择与
分阶段验收见 [MODEM-PLAN.md](MODEM-PLAN.md)；本轮完成源码分析，未启用基带。
随后完成 [M0 主机框架与验证](MODEM-M0.md)，默认关闭的检查节点已通过
`fe077e30d191` 显式实验的实机解析及 USB/Wi-Fi/存储回归，见 [R3](MODEM-R3.md)。
已形成 [M1 离线资源契约与补丁拆分](MODEM-RESOURCES.md)：MD 电源域、
四路供电、CCIF2 单一 owner、SCP RV 与 CCISM。
已实现 [R1/R2 第一批资源框架](MODEM-R1-R2.md)，供电描述、四个普通 CCIF
gate 和独立引用检查均默认关闭；未启用 MD 电源控制或 SCP。
已实现 [R3 MD1 电源序列](MODEM-R3.md)，尚未添加板级入口或实机上下电；
新增固件/用户空间分析与源码冲突整理在 [MODEM-PROTOCOL](MODEM-PROTOCOL.md)。
`7576d31c76a4` 已完成四路供电/四个普通 CCIF 引用的两次启动实机验收，
USB/Wi-Fi/存储回归通过；shutdown 尾部缺乏保留证据，启动电压恢复未实现，
后续优先 SCP RV/CCISM 的依赖框架。见 [供电生命周期](MODEM-RAILS.md)。
2026-11-15 完成 [R5.1 SCP mailbox 布局与 CCISM 协议基础](MODEM-SCP.md)：
完整表的有界布局、APCCCI 定位与消息格式主机验证/ARM64 编译通过；默认关闭，
没有新硬件入口或镜像；此前实测基线为资源检查镜像。SCP transport/固件和
真实 READY/CCISM 状态机仍待实现。
随后完成 [R5.2 TCM/恢复映射边界](MODEM-SCP-MEMORY.md) 的纯解析与校验；
严格 72-byte 版本、字节长度和双核恢复跨度通过主机验证，实际固件元数据
及保留区/加载责任仍待核对。用户已恢复 Android 供分析使用，当前不操作设备。
随后完成 [R5.3 共享 AP awake 后端](MODEM-SCP-AWAKE.md)：有界 SET/CLEAR
协议、引用计数与错误锁定的主机验证；没有 provider/caller，未运行硬件握手。
已准备固定白名单 Android metadata collector；当前停在需要设备软件 READY、
实际配置及后续固件/内存观测的检查点，不重启/刷写或占用设备。
用户随后允许只读检查并说明设备运行 6.6、暂不刷入。已完成
[6.6 被动观测](evidence/modem-scp-6.6-observation.json)：两次软件 READY，
DT 白名单与保存 ACK 一致；没有 awake/TCM 操作或重启/刷写。
实际 header 与动态 share 分配仍待独立观测，设备继续保留 6.6。
随后用户允许上机，已完成 [6.6 缓存/实际分配观测](MODEM-SCP-OBSERVATION.md)：
缓存 header 实为 68 字节，新增精确 68/72-byte 支持后上机解码通过；动态 share
实际为 0x8d000000/0x320000，与驱动缓存一致。loader/firmware/完整 DRAM
mapping 在静态保留区内，regdump 不在已确认窗口内，继续禁止映射。
临时模块已卸载/清理，设备保持 6.6；没有 awake/IPI、TCM、重启或刷写。
下一步闭合 LK→主线 READY/时钟和加载责任，不能用 ACK 状态替代主线验收。
随后用户授权包括刷主线，完成 [SCP AP 侧前提观测](MODEM-SCP-PREREQUISITES.md)：
镜像 c55ce7327907 的 selector=0/gated=0，主线实际 share 分配与 ACK 相同，
通过 USB/Wi-Fi SSH、8 核、只读存储和 rootfs 回归。没有 SCP/TCM 访问、awake
或 reset，真实 READY 仍未知；设备保留主线。下一轮先限定读取 core0 状态，
再私下校验精确 header，不把 AP 观测作为 SCP 已运行证据。
图形/GPU 的模块安装、控制台切换、runtime PM、缓存同步审查、压力/DVFS 和
完整显示接管保存在 [GRAPHICS-TODO.md](GRAPHICS-TODO.md)。
下文保留原审计与历次接续记录，时间和实测状态以各记录为准。

Baseline: mainline cbbddb6b08cc9900a87cccaa9b22bbe06aa4f50a;
boot dad2ee05c49c, Debian9825862f46b0. Device remains in fastboot during
this audit. No new hardware driver enabled or flashed.

## Capacity

The32MiB boot.img is padded. Effective aligned payload is7,430,144 bytes
(7.086MiB), leaving26,124,288 bytes (24.914MiB). Gzip kernel, including
embedded initramfs, is5,367,000 bytes; appended vendor DTBs1,846,225 bytes;
header DTBs210,407 bytes; external ramdisk48 bytes (empty archive).
Embedded compressed initramfs in current build output is1,166,558 bytes;
it is inside the kernel and must not be added again to compressed payload.
Uncompressed kernel memory footprint12,713,984 bytes; current packer checks
against first reservation0x48080000, leaving121,503,744 bytes from current
load address0x40080000. This is a packing bound, not validation of arbitrary
larger kernels or a guarantee about every LK decompression workspace.

boot-capacity.py independently reports existing images and rejects partition
or known memory-window overflow. pack.py already rejected oversize images;
its future manifests now also expose component sizes and remaining capacity.
No new boot required just for these reporting fields. Current normal image
passed; a7,000,000-byte hypothetical partition was correctly rejected.

Keep direct boot. Enable modules when adding suitable leaf devices; retain
UFS/SCSI/reset, cache ext4, loop/SquashFS/OverlayFS, watchdog, and emergency
USB dependencies built in. Modules belong to exact kernel release under
/lib/modules in the external root. Firmware loading is currently disabled;
introduce CONFIG_FW_LOADER with actual consumers. External Debian is already
outside boot. kexec is a later experimental fallback, not presently needed.

## First implementation target: pinctrl resource reconciliation

Evidence: evidence/ack-live.dts:1359–1430; current driver and binding;
ACK modules drivers/pinctrl/mediatek/pinctrl-mt6885.c. The live ACK uses
mediatek,mt6885-pinctrl, NOT its also-present mt6893 driver.

| Index | Resource | ACK physical base |
|---|---|---|
|0|base|0x10005000|
|1|rm|0x11c20000|
|2|bm|0x11d10000|
|3|lm|0x11e20000|
|4|lb|0x11e70000|
|5|rt|0x11ea0000|
|6|lt|0x11f20000|
|7|tm|0x11f30000|
|separate|eint|0x1000b000, GIC SPI212 level high|

Current mainline base_names is base,rm,bm,bl,br,lm,lb,rt,lt,tl (10 bases).
Binding describes eight bases followed by EINT. The probe maps all required
base_names before registering pinctrl; a binding-shaped node lacks bl/br/tl.
Even aliasing those names would assign incorrect bank indices. Do not add
dummy banks. Binding example also says EINT0x1100b000, unlike ACK0x1000b000;
its GIC example has four cells while our GIC uses three.

Reproducer evidence/pinctrl-audit.py compares parsed resource names and field
entries; output pinctrl-audit.json. Six tables (SMT,IES,PU,PD,DRV,PUPD) match
ACK entry-for-entry, including PIN/PINS grouping. R0/R1 have46 entries versus
ACK24, so complete electrical-feature equivalence is not established. Pin
function headers, RSEL/advanced drive and EINT internal PMIC routing require
further comparison before claiming full support. This audit establishes a
resource incompatibility, not successful hardware operation or a tested fix.

Proposed first hardware experiment after reconciliation: register the
controller with no pin state consumers or GPIO hogs; inspect registered
220 pins and bank mapping; confirm UFS/USB/SSH still work. Avoid arbitrary
GPIO requests, which can change mux/direction. Test an identified volume key
only after its routing and IRQ are verified. PMIC interrupt222 is distinct
from external GPIO count220 and needs explicit checking before PMIC use.

## Dependency inventory

|Block|Evidence in local trees|Work before enabling|
|GPIO/EINT|Mainline MT6893 driver; ACK mapping above|Resolve resources and compare pin/electrical tables|
|Clock/reset|Current USB uses26MHz placeholders; UFS inherits LK state; no mt6893/mt6885 match found in current clk/mediatek search|Inventory ACK gates, parents, resets; separate clock-driver work from pinctrl|
|PMIC transport|ACK pwrap0x10026000 + spi_mst0x10028000, SPI220; mt6885-pwrap|Compare pwrap register layout/protocol; actual clocks and EINT route first|
|Main PMIC|ACK mt6359-pmic and mt6359p-regulator; mainline MT6359 MFD/regulator exist|Verify chip revision, transport and binding adaptation; preserve rail state|
|CPU supply|ACK MT6315 via SPMI, slave IDs6/7/3; mainline regulator exists|SPMI controller and rail mapping before DVFS|
|Charger/ADC|ACK MT6360 on i2c5 at0x11f00000, DMA0x11000500, SPI117, IRQ GPIO24|I2C clocks/pins, chip address and interrupt; read-only identification first|
|Temperature|Thermal disabled in current config; no mt6893/mt6885 match found in mainline thermal/mediatek search|Identify controller revision and calibration/efuse, then validate readings|
|USB|ACM+ECM verified; forced VBUS and inherited supply/clock|Real VBUS/role detection and resource ownership before runtime PM|
|UFS|Read-only backing root verified; PHY/clock state inherited|PHY/rail/clock integration before autosuspend or link power saving|
|Display/touch|Disabled; reference qqcandy contains its own panel/touch notes|Identify this unit's panel/touch from ACK; reference only for approach|
|Wi-Fi/BT/audio|Not enabled|Identify exact hardware/firmware and transport; independent driver projects|
|DVFS/idle/suspend|Disabled|Clocks, rails, thermal and reliable wakeup first|

Reference tree linux-qqcandy-6.18 is useful for board organization, module
packaging and subsystem dependencies; no claim its MT6895 register maps or
panel/firmware apply to this device. Preserve GPT/geniezone arrangement and
clk_ignore_unused/regulator_ignore_unused/fw_devlink=off until each dependency
is represented and tested independently. No commits or Signed-off-by added.

## Follow-up: attempt25 completed

Resource names and EINT example corrected; pinctrl node registered on hardware
with unchanged Debian root. See evidence/attempt-25.md. Earlier assertion that
pinctrl was disabled referred to defconfig text; actual baseline config had
already enabled it through dependencies. GPIO0–219 function/EINT descriptions
match ACK;7 additional virtual descriptions explain gpiochip227. No IRQ consumer
or electrical configuration tested yet. Current image14c7e1602c1d remains booted.

## Volume-up resolved by live ACK (attempt27)

Current ACK event1 mtk-pmic-keys reports real KEY_VOLUMEUP press/release;
HOMEKEY49/HOMEKEY_R51 counters each6. Volume-up is PMIC HOMEKEY, not GPIO20,
GPIO59 or keypad matrix. Mainline integration depends on pwrap/MFD/PMIC IRQ.
Do not use the stale keypad volume-up GPIO/pinctrl properties. Device already
ran a newer ACK when checked; no flash/reboot made in this investigation.

## PMIF ownership audit (attempt31)

Actual clock topology and live selector/gates now established. See
evidence/attempt-31.md and pmif-snapshot.py. Next implementation is a real
MT6893 topckgen/infracfg provider subset with lifecycle review, then four
PMIF clock references. Preserve parent/rate and unused-clock suppression.
Wrapper group3 errors remain masked; ACK0x30 mask semantics need validation.
Both generic wrapper initialization paths contain sparse-offset hazards;
retain diagnostic bypass until a dedicated MT6885 path is implemented.

## PMIF clock subset implemented (attempt32)

Real topckgen factors/selector and infracfg AP/TMR gates now registered and
consumed by pwrap. All four references report nominal26MHz; register state
unchanged and physical PMIC keys validated. Critical clocks plus built-in
board gate preserve transport availability. No full oscillator control,
parent/rate changes, unused-clock cleanup or suspend support implied.

Next PMIF step: separate MT6885 type/register data from MT6873 alias, retain
only verified offsets and diagnostic init; audit error-source bits before
unmasking. Follow with a separate MT6359P ADC reset/calibration review. Supply
control/DVFS waits for complete clocks,rail mapping and thermal support.

## Dedicated MT6885 path verified (attempt33)

Independent type/table and register access guards implemented; generic
initialization explicitly rejected. Runtime transaction errors gain state
diagnostics without additional recovery writes. Build and hardware regression
pass. Wrapper error bits4/5 semantics and IRQ recovery remain unverified,
so keep sources masked. Next useful hardware work is a separate MT6359P ADC
reset/calibration audit before enabling the existing ADC driver.

## Battery ADC subset verified (attempt34)

MT6359/MT6359P register and reset audit completed. Only BATADC exposed,
with board/build-gated no-reset profile and inherited analog setup. Fixed
voltage type and digital scale;16 samples successful, nominal mean4.0393V.
No external calibration, current, temperature, charger or power_supply support.
Existing USB/root/CPU/watchdog/PMIF regression passed; see evidence/attempt-34.md.

Next step: audit PMIC temperature channel transfer law and calibration/efuse
dependencies against ACK before exposing another channel. Battery voltage
alone cannot establish state of charge or safe charging control. Preserve
regulator/clock suppression and disabled DVFS/idle/suspend until their resource
and thermal dependencies are verified.

## CHIP_TEMP diagnostic voltage (attempt35)

Boot `d353a067577a` verified; BATADC plus CHIP_TEMP voltage only. Sixteen
alternating pairs succeeded: CHIP_TEMP raw1565 (687.744mV) throughout,
battery mean4.0485V. USB SSH,8CPUs,watchdog,readonly root/cache and PMIF
snapshot regression passed; idle PMIC IRQ counts stable. Device left running.
Repeated identical CHIP_TEMP values do not establish fresh conversions or
thermal response. No Celsius/thermal zone/calibration support implied.

ACK MT6893 legacy calibration addresses conflict with MT6359P header names,
and saved ACK logs use fallback parameters. Resolve actual calibration layout
and conversion freshness before thermal reporting; do not copy those addresses
or claim the device has no fused calibration. See evidence/attempt-35.md.

## MT6359P calibration shadows resolved (attempt36; same boot d353a067577a)

4.19 field definitions and live fixed-range regmap reads identify thermal
calibration at0x11e8–0x11f0, not the6.6 legacy hardcoded addresses. Enable1,
calibration point24.5C,chip VTS1613,effective slope0. pmic-temperature.py
captures these shadows and IIO voltage samples; vendor-derived estimate near
37C matches extracted vendor C across all4096 raw codes for this calibration.
No physical accuracy validation or thermal-zone integration. Hand-contact
observation completed:120 samples trend from raw1564 to1562, nominal vendor
estimate37.0–37.6C. Output changes; absolute accuracy, precise contact causality
and per-request freshness remain unvalidated. See evidence/attempt-36.md.
No reboot needed; same mainline image remains running.

## PMIC temperature diagnostic interface verified (attempt37)

Boot `74e7947a974f` exposes `in_temp2_input` in milli-Celsius beside existing
voltage channels. Each read validates live ELR8/9 calibration; invalid data or
nonzero effective slope returns error, with no default temperature.16 hardware
comparisons at37587mC agree with adjacent raw1562 and vendor arithmetic.
Calibration and PMIF snapshots unchanged;8CPUs,USB SSH,watchdog,readonly root
and idle PMIC IRQ regression pass. Device left running mainline.

Diagnostic board alias only: no thermal-zone binding/trips/cooling, no absolute
accuracy validation. Next audit is SoC LVTS/calibration/resources; PMIC die
alone does not justify DVFS/suspend. See evidence/attempt-37.md.

## LVTS prerequisites audited (attempt38)

Current74e7947a974f lacks LK atag,devinfo after FDT merge. Saved ACK DTB
calibration22words matches ACK log and extracted C decoding:17 count_r,
7 count_rc,golden_raw60 =>30C. New lvts-calibration.py and host test preserve
this evidence without LVTS MMIO access. See evidence/attempt-38.md.

Next is validated calibration handoff, then thermal AXI clock/reset/IRQ
resources and MT6893 manual RCK support. A compatible/table-only reuse of
MT8195 is insufficient; coefficients and normalization differ. No kernel
change or reboot this round; SoC thermal control remains disabled.

## Live LK devinfo handoff verified (attempt39)

Boot `fa91b68792cf` preserves bounded little-endian atag,devinfo from LK.
All884bytes equal fresh ACK capture;22LVTS calibration words decode correctly.
Malformed/missing optional payload does not block boot; other vendor chosen
properties excluded. USB/root/8CPU/watchdog/PMIC regression passed. No LVTS
hardware enabled. Next:thermal clock/reset/domain mapping and manual RCK.
Device left running mainline. See evidence/attempt-39.md.

User reports moisture-affected power key may cause bootloader menu selection.
Queue serial-targeted fastboot flash boot before device arrival and reboot
only after flash success. Avoid simultaneous clients or persistent reboot loops.

## LVTS live clock audit and support inventory (attempt40)

Read-only clock snapshot:AXI selects MAINPLL/14,thermal gate enabled by inherited
state. No LVTS or clock/reset writes. Source resource/RCK audit recorded in
evidence/attempt-40.md. Current support matrix: [PERIPHERAL-STATUS.md](PERIPHERAL-STATUS.md).
Device remains running fa91b68792cf; no reboot scheduled.

## MAINPLL readback verified (attempt41)

Live PCW/postdiv with MT6893 pcwibits8 yields nominal MAINPLL2184MHz,
AXI156MHz.56 extracted-code arithmetic cases pass. ACK FHCTL/MCUPM path
and generic PLL power-write lifecycle reviewed: plan read-only CCF descriptors
before thermal gate ownership. No provider change or reboot yet; see
evidence/attempt-41.md and updated PERIPHERAL-STATUS.md.

## Current priority: independent Wi-Fi before USB changes (attempt49)

User-directed order supersedes the historical sequence above: bring up onboard
Wi-Fi and validate SSH without USB data, then change USB/Type-C power and role
handling. Keep attempt48 USB baseline during connectivity work. ACK identifies
AXI SOC3_0 WLAN with MT6635 analog die; CONN power, PMIC rails, EMI and
firmware are explicit prerequisites. See [attempt49](evidence/attempt-49.md).

ACK history follow-up: load connectivity after external rootfs/firmware are
ready; explicitly audit pre-calibration participants and vendor WMT activation
without Android HAL. Do not carry over blanket UBSAN disabling or GKI binary
compatibility workarounds. See [lessons](evidence/attempt-49/ack-history-lessons.md).

Attempt50 establishes that the current vendor calibration path needs real BT
and WLAN callbacks; NVRAM handoff can register WLAN callbacks and automatically
start calibration. Preserve BT calibration support in the initial Wi-Fi port;
Bluetooth user-facing service is separate. Do not treat final-module insertion
or NVRAM handoff as passive tests. See [state/activation audit](evidence/attempt-50.md).

Attempt51: existing MT6893 genpd CONN table differs from both ACK trees in
bus protection masks/banks and release order. Live SPM confirms CONN off;
seven status registers stable across two read-only snapshots. Resolve the
sequence before enabling the provider. See [51](evidence/attempt-51.md).

Attempt52: map conninfra supplies to real shared MT6359P rails, not vendor
name aliases. Probe conditionally merges VCN33 enable bits; audit all-rail
registration/constraints before enabling the provider. See [52](evidence/attempt-52.md).

Attempt53: extracted actual ACK6.6/4.19 CONN functions execute identical
MMIO sequences in a host model. Saved ACK compiler command confirms legacy
PG_CONN branch. Include wrapper SPM unlock/AP2CONN host clock/6ms wait; do
not combine inactive POS code. See [53](evidence/attempt-53.md).

Attempt54: MT6359P regulator provider registered on d873de3b8963; selected
18 PMIC and seven CONN status registers unchanged, all VCN rails/CONN off.
External inputs still resolve to dummy; this is partial registration, not
validated wireless power control. USB/root/8CPU/ADC/LVTS regression passed.
Audit clock-buffer/pinmux next. See [54](evidence/attempt-54.md).

Attempt55: read-only clock/pin snapshots confirm GPIO172--182 mode0, data
pull-downs, AP2CONN request off. Saved ACK object clock callback is a no-op;
DCXO configuration does not prove XO readiness. Preserve GPIO155: shipped
config selects co-clock, not external TCXO. See [55](evidence/attempt-55.md).

Attempt56: RE report received and reviewed. Correct framing:12 ASCII bytes
WR-BUF:NVRAM without NUL, followed by6144 record bytes, no padding. Actual
BTIF strips48-byte EMI header and uses middle address bytes, not UART30-byte
path. Offline preparation/tests and fresh ACK record validation passed. Device
currently in ACK; no delivery/calibration. See [integration](WIFI-INITIALIZATION.md)
and [56](evidence/attempt-56.md). Power prerequisites remain next.

Attempt57: staged unreferenced CONN active/idle pinctrl states compile and
match vendor field intent across four fills; shared drive fields resolved.
Fresh ACK PMIC state consistent with RC, VS2 vote4 and VCN13 VOCAL7; ACK is
not a quiescent off baseline. Extracted vendor common-power functions keep
returning0 under32 individual API failures. Use checked, bounded transaction
instead of trusting wrapper success. No new boot/activation yet; device ACK.
See [57](evidence/attempt-57.md).

Attempt58: board-only CONN read-only preflight implemented and physically
tested on d79c36ef9d28. Direct SPM RC bit=1; CONN and all VCN rails off;
six explicit real leaf handles, inherited dummy upstream inputs still visible.
16 serial/four concurrent captures pass; USB/root/8CPU/ADC/LVTS regressions
pass. Device remains on this mainline image. Next define inherited shared-parent
policy and implement a separately triggered bounded power transaction with
fault/cleanup tracking, before any digital-ID or firmware access. See
[58](evidence/attempt-58.md).

Attempt59: explicit one-shot RC common-rail cycle implemented and tested on
d46fc22c1b0c. VCN18/13 enable monitor acknowledgements and reverse shutdown
pass; selected PMIC/AP words restore, repeat trigger refuses, USB/root/8CPU/
ADC/LVTS regressions pass. Shared VS1/VS2 receive lifetime votes before leaf
operations to prevent recursive framework shutdown from cutting inherited
parents. Their voltages/modes remain inherited; external dummy inputs remain
unresolved. CONN stays off and pinctrl unselected. Next add exact legacy
PG_CONN/pin sequencing and guarded digital-ID reads, preserving supplies on
uncertain domain shutdown. See [59](evidence/attempt-59.md).

Attempt60: bounded legacy PG_CONN/pinctrl transaction tested twice. Both
attempts refuse before dark-domain mapping: protection bit14 reappears after
its successful release poll, during6ms settling. Follow-up6346689c1150
captures dual ACK on/control0xd/host1 but primary protect0xe70c500e.
Both normal shutdown and leaf cleanup succeed, USB/root/8CPU remain working.
The follow-up left CONN/VCN off with the one-shot fault latch set.
See [60](evidence/attempt-60.md).

Attempt61: image764614420260 captures seven AP-side protection snapshots.
At6.707ms after the final release capture, STA1 bit14 is set again but the
primary request remains0. No evidence of a new AP protection request; do not
attribute this to firmware or automatic sleep without further evidence.
The unchanged guard refuses all CONN mapping, bounded shutdown/rail cleanup
succeed, and USB/root/8CPU/ADC/LVTS regressions pass. Device remains on61.
ACK's register-readability check distinguishes AP-to-CONN bit13/bank2 bit2
from CONN-to-AP bit14, then checks HOST_CSR clock/timeout/internal sleep state.
Next separate HOST_CSR access from off-domain ID readiness with an isolated
CSR diagnostic; do not simply remove bit14 and access ID. No speculative
wakeup write, firmware, DMA or calibration. See [61](evidence/attempt-61.md).

Attempt62: image7c249e95b089 succeeds in explicit CSR-only cycle. AP-to-CONN
bit13/bank2 bit2 clear, host1 and dual power/control prerequisites permit
three on-domain reads even with reverse bit14 set. Clock raw0x4006 (not
refreshed), internal sleep raw0x100 (bit5 clear), timeout raw1. ID remains
unread. Normal shutdown/rail cleanup and USB/root/8CPU/ADC/LVTS regressions
pass; repeated request refuses unchanged. Device remains on62. Next refresh
the audited HOST_CSR clock detector and gate internal ID access on fresh
clock/sleep/timeout observations. See [62](evidence/attempt-62.md).

Attempt63: image0d19c805d6b6 completes guarded digital identification. After
HOST_CSR detector-reset request, both clock bits pass, timeout bit0=1 and
internal sleep bit5=0. Two ID words read as HW0x20010101/config3, despite
reverse-path bit14 set. AP-to-CONN direction gate plus internal readiness
checks are sufficient for this tested path; reverse ACK mechanism remains
unknown. Normal shutdown/rail cleanup and USB/root/8CPU/ADC/LVTS regressions
pass. Device remains on63 with CONN/VCN off and one-shot success latched.
Next audit D-die/SYSRAM setup and EMI remap with dynamic reserved memory
bounds and rollback before SPI/A-die or firmware. No firmware/DMA/RF support
claimed. See [63](evidence/attempt-63.md).

Attempt64: imageacbc438563c6 completes13 read-only post-ID baseline words
and validates actual Linux dynamic EMI allocation0x8fb00000/0x450000 using
of_reserved_mem_lookup. Current MCU remap low20=0x4000, not required0x8fb0;
three peripheral remaps0x1100 differ from ACK0x1000. RGU hardware control
words remain0xff/0/1/0 instead of ACK0/0xff/0/1. SYSRAM software words are
uninitialized/retained; ACK clears16KiB during A-die setup, so never interpret
them as current radio state. Next isolated remap transaction saves four
originals, writes masked targets from CURRENT allocation, verifies and restores
before shutdown; retain supplies if restoration uncertain. No MD/GPS EMI,
reserved-RAM, MPU, SYSRAM-policy, SPI/A-die or firmware writes yet. Runtime
regressions pass; device remains on64, CONN off. See [64](evidence/attempt-64.md).

Attempt65: imagee2a490e43787 completes isolated reversible remap writes.
MCU EMI low20 becomes current0x8fb0, three peripherals0x1000; all target
readbacks match, all originals restore in reverse before verified shutdown.
Counts4/4/4,dirty0, remap/domain/rail cleanup0. Host error tests confirm
uncertain restoration retains domain/pins/supplies without shutdown. Runtime
USB/root/8CPU/ADC/LVTS regressions pass. Device remains on65, CONN off and
original maps restored. No EMI payload/MPU/DMA/firmware validation claimed.
Next isolated RGU hardware power/sleep policy transaction, preserving failure
containment; SYSRAM clear/mailboxes and SPI/A-die remain separate stages.
See [65](evidence/attempt-65.md).


Attempt66: image362bb070becb completes isolated RGU policy transaction.
All four ACK targets read back, all originals restore in reverse, counts4/4/4,
dirty0 and RGU/domain/rail cleanup0. User reports recovery reflash of this
image after queued fastboot attempts; Linux release and raw boot SHA match.
CONN/VCN off, normal USB/root/8CPU/ADC/LVTS/pin regressions pass. No SRAM
content retention or firmware readiness inferred. Next audit SPI-master
configuration and A-die prerequisites, preserving full SYSRAM-clear/mailbox
ordering and GPIO180 strap requirements as separate steps. See [66](evidence/attempt-66.md).


Attempt67: imagefba0b6f25671 reads all39 SPI initialization baseline words
with fresh-ID prerequisites and per-word access guards. ADIE_CTL2 (reset
release0, top-clock request1), SPI_STA0, WB_STA80000 (bit26clear); these are
sequential samples, not persistent inactivity proof. Ten of36 non-BT sleep
configuration words match ACK,26 differ;4.19/6.6 local target tables agree.
Next guarded masked36-word programming/restoration experiment, followed by
separate SYSRAM clear/strap/semaphore prerequisites before A-die release.
Normal shutdown and runtime regressions pass. Device remains mainline67,
CONN off. Starting Android was actual4.19 with spoofed uname5.10.0; existing
ACK recovery backup deliberately unchanged. See [67](evidence/attempt-67.md).


Attempt68: imagee384bb8e140f verifies all36 masked non-BT sleep-command
configuration targets and restores all originals. Command length last on
apply/first on restore; full-word baseline and per-access ADIE2/SPI0/WB80000
checks pass. Counts36/36/36,dirty0,unsafe0,cleanup0; normal shutdown and
runtime regressions pass. Failed/changed guard states are latched and retain
resources, including after final restore. Device remains mainline68,CONN off,
original table restored. Next SYSRAM clear/mailbox ordering,26MHz strap and
RF SPI semaphore ownership (M2_OWN_STA reads acquire, not passive snapshot)
before composing a bounded A-die ID path. See [68](evidence/attempt-68.md).


Attempt69: imagef43f4198b1b4 confirms semaphore11 single acquire/release.
M2 acquire returns1, four reports show only M2bit11set, exact release clears
it on first passive poll; all other master reports0. No unresolved lock,
normal shutdown and runtime regressions pass. Pending/ambiguous ownership
retains resources in host fault tests. No RF SPI/A-die communication claimed.
Next SYSRAM clear/mailbox order and GPIO18026MHz strap, then composition
of established prerequisites for bounded A-die identification. Device stays
mainline69,CONN off; existing ACK backup unchanged. See [69](evidence/attempt-69.md).


Attempt70: imagedf82e6dfd58a completes full16KiB SYSRAM clear while all4
validated RGU targets remain held. Counts4096/4096/4096,complete1,unsafe0;
RGU4/4/4,dirty0, normal domain/rail shutdown. Runtime regressions and one-shot
retry refusal pass. No SRAM retention after shutdown or A-die communication
claimed. Next isolated GPIO18026MHz strap transition/restoration with explicit
mux/direction/output ownership, then bounded composition for A-die ID.
Device stays mainline70,CONN off; ACK backup unchanged. See [70](evidence/attempt-70.md).


GPIO180 prerequisite audit after70: read-only AP snapshot confirms input,
DO0, GPIO mode, shared SMT0 (GPIO178–182). Existing conn-idle does not restore
DIR/DO; Paris INPUT_ENABLE changes IES only, and Schmitt-enable would change
neighbours. Plan DIR-only OUTPUT_ENABLE support, then explicit staged
pinctrl preparation/mux/low/input restoration with guards and readback.
No strap write or new image tested; device stays70. See [GPIO180 audit](GPIO180-STRAP.md).


Attempt71 prepared: d8f40ea749e6 adds Paris DIR-only OUTPUT_ENABLE and
five explicit GPIO180 strap states. Actual C fault tests, domain containment,
compiled-DTB transitions/ownership, schema and full image build pass.
Serial-targeted flash/reboot queued and attempt70 watchdog reset requested.
Physical test passed: selected6/samples7/complete1,dirty0,unsafe0,ADIE2,
normal shutdown and runtime regressions. Active fields restored; idle
DIR/DO/mux restored, existing common drive0->8248 policy retained.
Next compose prerequisite lifetimes and reverse cleanup for bounded
A-die release/ID. No A-die response yet. See [71](evidence/attempt-71.md).


Attempt72 prepared: 681020f5b5b7 nests remap->RGU->SPI settings->SYSRAM
clear->GPIO180 high->semaphore acquisition/release, then reverse restoration.
A-die reset remains asserted. Whole-path host tests enforce held-parent
hardware values and prevent outer restoration after inner uncertainty.
Build/schema/capacity checks pass; queued flash and watchdog reset requested.
Physical results pass: remap4/4/4,RGU4/4/4,SPI36/36/36,SYSRAM4096/4096/4096,
strap6/7,semaphore grant/release confirmed,all dirty/unsafe clear and cleanup0.
Runtime regressions and cached EALREADY checks pass; device remains72,CONN off.
Next bounded A-die reset-release/ID inside this lifetime, reset reassertion
before lock release and outer restoration. See [72](evidence/attempt-72.md).


Attempt73 prepared: a75acab430b3 adds one TOP ID02c read inside the nested
preparation/semaphore lifetime. Verify reset2->3, addressb02c, trigger WD0,
finite busy polling, then reset3->2 and address restoration before unlock.
Unknown/stale ID cleans up; uncertain reset/access/ownership/busy retains
all outer resources. Unit/full-path fault tests, build and checks pass.
Physical test passed: ID66358a11 (MT6635 E3), RDAT0->ID, busy_seen0.
Reset/address restored, lock released and all outer restoration/cleanup0.
Runtime regressions pass; device remains73,CONN off,ACK backup unchanged.
Next audit E3 analog initialization and non-efuse register baselines, preserving
calibration privacy and separating firmware startup from chip identification.
See [73](evidence/attempt-73.md).

## Attempt74: XTAL read baseline

Two fixed TOP reads after fresh E3 ID succeeded, with per-transfer changed RDAT
and full cleanup. See [74](evidence/attempt-74.md) and [post-ID scope](ADIE-POST-ID.md).
Next: review bounded analog configuration and its restoration policy before
efuse/AFE/firmware integration. Independent Wi-Fi remains ahead of USB takeover.

## Attempt75: bounded analog write transport

[75](evidence/attempt-75.md) passed A18 target write/readback and verified saved-value
restoration before reset/unlock. This does not establish full vendor analog initialization.
Next integrate the initial configuration stages in vendor order, resolving per-register
readback and cleanup semantics before efuse/AFE/firmware. Wi-Fi remains the priority.

## Attempt76: shared ID mailbox

[76](evidence/attempt-76.md) passed the vendor SYSRAM ID mailbox write/read/clear
under held preparation and semaphore ownership. Initial analog configuration
registers0x064/0x0bc still need explicit readback/reset semantics; do not inherit
XTAL rollback assumptions. Firmware lifetime must preserve the mailbox, unlike
this bounded experiment. Independent Wi-Fi remains the priority.

## Attempt77: initial config read responses

[77](evidence/attempt-77.md) measured two stable rounds: TOP064=0 and TOP0bc=1,
with four matching ID separators and changed RDAT for all eight transfers.
Use these to constrain a future initial-config write experiment; this does not
establish rollback/reset semantics or no read side effects. No Wi-Fi yet.

## Attempt78: initial analog config with held mailbox

[78](evidence/attempt-78.md) passed TOP064=7700 then TOP0bc=21 with independent
readbacks and reverse saved-value restoration under the held ID mailbox.
Next integrate FM SPI format and thermal SPI address routing while those values
remain applied, restoring digital settings before analog/mailbox cleanup.
This remains bounded bring-up, not firmware startup or Wi-Fi support.

## Attempt79: digital route baselines before writes

[79](evidence/attempt-79.md) passed two fixed read rounds under held analog
prefix/mailbox: FM_CTRL801f, THERM_AADDR50305a00, THERMCR17f0300ff, CAL_EN0,
GPT2 thermal enable0. Passive thermal semaphore13 reports were clear; this
is not ownership or an atomic engine-idle proof. All restoration passed.
Next test FM_CTRL clear80ff/readback/restore801f with repeated thermal guards.
Thermal address already matches; do not create an invalid route to manufacture
changed readback evidence. Efuse/calibration/firmware and Wi-Fi remain pending.

## Attempt80: FM SPI format apply and restore

[80](evidence/attempt-80.md) passed FM_CTRL801f→0→801f with exact readbacks
and repeated thermal/ownership checks. FM restored before analog prefix and
mailbox cleanup; all outer resources restored. THERM_AADDR already matches
50305a00 and was not written. Next split the vendor efuse/thermal-trim helper
into checked transport, engine control, private-data and calibration stages;
no raw efuse logging or recursive acquisition of held RFSPI semaphore11.
Wi-Fi firmware has not run; independent networking stays ahead of USB takeover.

## Attempt81: efuse control baseline

[81](evidence/attempt-81.md) passed fixed ID/control/ID/control reads under
held FM/prefix/mailbox. Complete control words matched internally; known
kick/valid/address/mode fields were zero. All four responses had changed
RDAT and all restoration passed. No efuse engine trigger or private data
reads. Next design address0 read-mode trigger/completion with independent
transport and engine deadlines; keep private data and thermal trim separate.
Do not reacquire held RFSPI semaphore11 or restore a kick as ordinary data.

## Attempt82：efuse 触发后控制字变化，保护性停止

镜像 `89780a5bbea6` 实机只触发一次地址0读取；首轮观察到 kick=0、valid=1，
但完整控制字在这两个状态位以外发生变化，返回 EIO，未接受完成确认。
所有外层资源按设计保留，没有读取私有数据、强制清理或启动固件。
重复命令被拒绝，九组缓存状态哈希不变，USB SSH仍可用。
已复位恢复第81轮镜像，版本/boot哈希、CONN关闭及USB SSH通过；
下一步调查变化位与厂商控制字语义，不直接放宽检查。
这轮不是清理成功或Wi-Fi可用的证据。详见 [82](evidence/attempt-82.md)。

## Attempt83：变化位定位

新镜像 `4434b68988c7` 只增加缓存变化掩码，实测首轮CTRL变化为 `0x3b`，
仅涉及bit0/1/3/4/5，其他非kick/valid位未变；严格检查继续返回EIO并保留资源。
未读取私有数据，重试被拒绝，九组缓存哈希不变。其他芯片将低6位定义为AOUT，
这是调查线索，尚不是MT6635语义证据。后续先确认语义或受限观察稳定性，
不直接放宽完成/清理条件。Wi-Fi仍未可用。见 [83](evidence/attempt-83.md)。

本轮已恢复第81轮主线；版本/boot哈希、CONN关闭、CPU0–7与USB SSH均通过。

## Attempt84：低6位三次稳定观察

独立命令 `adie-efuse-observe` 实测三组新鲜ID/CTRL响应，变化掩码均为
`0x3b`，kick=0/valid=1，其余非状态位不变；耗时170531000ns（包含guard）。
只设置observe-stable，仍保持pending/unsafe，按设计返回EUCLEAN并保留资源。
未读私有数据，九组缓存哈希在拒绝重试后不变；USB SSH可用。
该结果支持下一轮单独测试“低6位稳定例外＋其余位严格比较”下的完成/清理，
不能称为MT6635字段定义或efuse数据有效性的证明。Wi-Fi仍未可用。
见 [84](evidence/attempt-84.md)。

已恢复第81轮主线，版本/boot哈希、CONN关闭、CPU0–7与USB SSH均通过。

## Attempt85：稳定状态完成＋完整清理通过

独立 `adie-efuse-stable-cycle` 在三次kick0/valid1、低6位变化稳定、其余位
严格一致后允许清理。本机E3实测delta均0x3b，confirmed3/complete1/pending0，
FM、模拟配置、mailbox和全部外层恢复成功，result/cleanup均0。
设备保留在 `68e4d632a8bb`，CONN关闭；USB SSH、存储、引脚、17组LVTS及
重试拒绝回归通过。该低位例外是本机经验规则，不是通用字段定义；
未读取私有数据、未应用trim或启动Wi-Fi。下一步先设计私有数据的临时存储、
诊断脱敏和清零，再实现受保护读取，thermal trim另行验证。
见 [85](evidence/attempt-85.md)。

## Attempt86：私有结果重复读取、清零与完整清理通过

新命令 `adie-efuse-data-read` 在稳定完成后读取四个结果字两轮，八次读取、
32笔ID/DATA/ID/CTRL传输，四项比较全部一致；数据阶段809727923ns。
原始数据只在临时缓冲区，全部退出路径显式清零；该命令的A-die诊断只输出
元数据，外层清理后还擦除继承RDAT的缓存。未发布数据值或数据哈希。
全部外层恢复成功，CONN关闭，设备保留在 `6033b3cb705f`；USB、存储、
引脚、17组LVTS及九组缓存哈希/重试拒绝回归通过。尚未交付私有SYSRAM槽、
应用trim、校准或启动Wi-Fi。下一步单独验证私有SYSRAM交付与清除。
见 [86](evidence/attempt-86.md)。

## Attempt87：私有 SYSRAM 交付、清除及完整清理通过

`adie-efuse-handoff-cycle` 实测四个槽位初始为零，写入和读回全部一致，
逐项清零、完整复扫及最终guard通过后才释放外层资源。
issued/verified/cleared均0xf，dirty0，数据阶段935372615ns；临时私有缓冲区
仍显式擦除，诊断只输出元数据。全部外层清理成功，CONN关闭；USB SSH、
八核、只读存储、ADC/17路LVTS、引脚及九组缓存哈希/重试拒绝回归通过。
设备保留在 `4d408b45c192`，恢复备份未更新。此实验结束即清除交付槽，
未为固件保留数据、应用trim或启动Wi-Fi。下一步私下解码thermal有效位和
目标掩码，并核对寄存器所有权/恢复条件，再单独验证trim写入。
见 [87](evidence/attempt-87.md)。

## Thermal trim 后续审计：写入位域存在额外一位

2026-11-04主机审计确认：厂商helper取值size+1位、清除size位，三个调用
可能额外置位TOP034 bit16和TOP038 bits26/28；两个TOP038操作还存在
中间状态/覆盖顺序。三棵源码各262144个合成用例通过，本地4.19编译对象
反汇编支持相同算术；尚未证明对象与设备Android镜像一致。
这不是硬件位定义或修复依据。下一轮先进行TOP034/038的私有只读重复验证，
写入前明确额外位含义和恢复条件。本轮未刷写，设备保持87，Wi-Fi仍不可用。
详见 [THERMAL-TRIM-AUDIT.md](THERMAL-TRIM-AUDIT.md)。

## Attempt88：TOP034/038 私有只读重复验证通过

`adie-thermal-read` 在SYSRAM交付清除后，读取两个thermal模拟寄存器各两次，
16笔ID/目标/ID/CTRL传输，四次目标读取和两项比较通过。仅输出元数据，
临时值显式清零；总数据阶段1342856846ns，原2s预算未扩大。
全部外层清理成功，CONN关闭；USB SSH、八核、存储、ADC/17路LVTS及
引脚/九组缓存哈希回归通过。设备保持 `bf54e7cab5af`，恢复备份不变。
未写入trim或启动Wi-Fi。后续需明确额外位含义、所有权与恢复语义，
不能由读取一致直接推断可以回写。见 [88](evidence/attempt-88.md)。

## Attempt89：两种 trim 候选在本次基线下均无需写入

`adie-thermal-plan` 在私有内存按厂商顺序计算两种候选，实测
vendor_noop/bounded_noop/policies_equivalent均1，complete/cleared均1。
比较覆盖每个中间步骤，不只是最终值；没有写入trim，也未输出有效位或
校准值。此结果不区分“无有效操作”与“已有匹配配置”，不证明物理校准有效。
总数据阶段1343797846ns，全部清理与回归通过，CONN关闭。
设备保持 `9c7b04db21e4`，恢复备份未变，Wi-Fi仍不可用。
下一步以每次重新验证的no-op条件为前提推进后续初始化；条件不成立则拒绝，
不能硬编码跳过，也不据此放开trim写入。见 [89](evidence/attempt-89.md)。

## Attempt90：新鲜 no-op 前提下 TOP070 重复读取通过

新命令 `adie-pad-read` 每次重新计算trim候选并要求两种序列均no-op且一致，
否则在TOP070访问前拒绝并保留资源。本轮前提再次成立；TOP070两次读取
一致，8笔传输通过，但不等于厂商80000000目标。没有写pad或trim配置，
临时数据清零；总数据阶段1554148616ns，全部清理/外设回归通过，CONN关闭。
刷写后的首次重启仍停fastboot，原因未确定；再次正常reboot后启动成功。
设备保持 `9d1e950c4d59`，恢复备份未变，Wi-Fi仍不可用。
下一步先设计独立pad写入/读回/恢复实验，核对所有权与恢复条件，不能把
读取稳定当作可以安全回写的证明。见 [90](evidence/attempt-90.md)。

## 2026-11-04：TOP070 固定值往返待实机验证

[attempt91](evidence/attempt-91.md) 已实现并构建 `adie-pad-cycle`，仅在新鲜
trim no-op 成立、重复基线为5时执行目标写入、读回及恢复。主机验证完成，
设备复位后正在等待 fastboot；尚未刷入或验证本轮，Wi-Fi 状态不变。


2026-11-15 SCP core0 限定读回：当前设备运行 `0a53a32dd3b3`，仅显式读取
CLR/SET bit0 与 STATUS gated/halt，各两次；六次调用均稳定且解释位全0。
USB/Wi-Fi SSH、8 核、UFS RO、cache/rootfs 回归通过。尚未访问 TCM、建立
READY 或启动 SCP/MD。详见 [core0 结果](MODEM-SCP-CORE0.md)。


2026-11-15 SCP TCM header：当前主线 `3ccec64b58d4`，精确 68-byte
header 六次显式读取一致；loader/firmware/DRAM/完整 mapping 的静态保留区
包含、payload 不重叠与 backup 公式检查通过。regdump 位于 firmware/share
外，未映射。USB/Wi-Fi SSH、8 核、UFS RO/cache/rootfs 回归通过。未建立
READY、启动 SCP/MD 或发送 awake。见 [TCM 结果](MODEM-SCP-TCM.md)。


2026-11-15 SCP RX 离线准备：默认关闭的 copy/board-completion/ACK/deliver
后端及 READY0 payload 校验已完成 sanitizer 与 ARM64 构建。尚无硬件
MMIO/IRQ caller，不记作 mailbox 外设已支持。设备保持 `3ccec64b58d4`。
下一步先做无 ACK/无 IRQ 的 pending 预检，见 [RX 接续](MODEM-SCP-RX.md)。


2026-11-15 SCP mailbox pending：当前主线 `b4456f5c54a5`，六次读取五组
pending/unknown 均0，两轮及前后 core0/mux 稳定；GIC specifiers 通过解析。
未申请 IRQ、清位、读 mailbox payload 或建立 READY。USB/Wi-Fi、8 核、
存储/rootfs 回归通过，见 [pending 实测](MODEM-SCP-PENDING.md)。后续先补
clock/shared-register owner，再接可控 IRQ 与 reset generation。


2026-11-15 SCP bootstrap 时钟：当前主线 `6d783d7288f4`，已有 TOPCK
provider 内的受限26M输出已正式持有，consumer unbind/rebind 实测 CCF
引用2→1→2，provider常驻引用保留，源/gate与既有core0/header/pending稳定。
USB/Wi-Fi、8核、存储/rootfs和boot回读通过。默认构建仍关闭实验；SPM资源
投票、共享cfg/IRQ owner和真实READY仍未完成，未启动SCP/MD。
详见 [bootstrap 时钟与资源边界](MODEM-SCP-BOOTSTRAP.md)。


2026-11-15 SCP SPM 26M资源：当前主线 `5393b5915579`，先验证只读 ATF
查询，再显式请求一次26M；SCP用户从缺失变为有效user1，资源mask=0x02，
多次USB/Wi-Fi读回 pin_verified=1、fault=0。CCF引用3/3、26M保持，既有
core0/header/pending、8核、UFS RO/cache/rootfs与boot回读通过。启用/默认
构建、schema和sanitizer通过，实验默认关闭。未启动SCP/MD、安装IRQ、
发awake或建立READY；下一步共享cfg/completion唯一owner，再接IRQ与
reset generation。见 [SPM资源实测](MODEM-SCP-RESOURCE.md)。


2026-11-15 SCP cfg 资源归属：当前主线 `80e79074de00`，已有SPM资源
owner通过资源管理器占有完整 `0x10724000/0x1000` 窗口，cfg状态
reserved=1、completion_enabled=0；不读写cfg寄存器。26M pin保持有效，
USB/Wi-Fi、8核、UFS RO/cache/rootfs、原观测和boot回读通过；启用/默认
构建、schema及sanitizer通过。未安装IRQ或建立READY，SCP/MD未启动。
下一步唯一IRQ/worker的预算与generation框架、completion写排序审计。
详见 [cfg 实现与实测](MODEM-SCP-CFG.md)。


2026-11-15 SCP接收排空离线后端：新增默认关闭的五邮箱有界drain与
STOP两阶段/generation校验，sanitizer与启用/默认ARM64构建通过。
尚无真实IRQ/worker/MMIO caller、目的队列或READY状态转移；不计作新增
硬件支持。本轮未刷写/重启，设备保持 `80e79074de00`，被动查询26M pin
有效、cfg预留且completion关闭。见 [drain边界与接续](MODEM-SCP-DRAIN.md)。


2026-11-15 SCP RX目的队列离线准备：默认关闭CPU FIFO覆盖17个RX pin，
整批容量不足时在硬件completion/ACK前拒绝，故障时擦除CPU队列并失效
全部RX。实际RX/drain/queue联动sanitizer、启用/默认ARM64构建通过。
未接真实IRQ/worker/MMIO或READY，不增加硬件验收；本轮未刷写/重启，
设备保持 `80e79074de00`。见 [队列边界](MODEM-SCP-QUEUE.md)。


2026-11-15 SCP mailbox IRQ初始归属：当前主线 `49092bac2836`，唯一cfg/SPM
owner以NO_AUTOEN申请五个IRQ，GIC hwirq 468–472均masked，所有CPU中断
计数0，USB/Wi-Fi重复读取unexpected/work_runs均0。26M pin读回mask=0x02、
pin_verified=1，CCF引用3/3；cfg无寄存器读写、completion关闭，原观测、
8核、只读存储/rootfs和boot回读通过。启用/默认构建、schema、实际C
sanitizer与strict checkpatch通过。尚未连接正常RX/worker、启用IRQ、建立
reset generation或READY，SCP/MD未启动，不计作基带可用。接续MMIO/
completion排序与可启用IRQ的锁/深度平衡，再闭合受控reset和本代READY。
详见 [IRQ归属及实测](MODEM-SCP-IRQ.md)。


2026-11-15 SCP RX MMIO离线后端：默认关闭，准备六个完整4 KiB页的
non-posted映射和实际readl/writel操作，completion/ACK后加屏障，避免未证实
的cfg读回。实际MMIO/queue/RX/drain模型sanitizer、启用/默认ARM64构建、
屏障反汇编及strict checkpatch通过。尚无platform caller或DT资源接线，
未进行新映射/寄存器操作，不增加硬件验收；本轮未刷写/重启，设备仍为
`49092bac2836`。接续唯一owner映射替换、正常IRQ/work、受控reset和READY。
详见 [MMIO后端与限制](MODEM-SCP-MMIO.md)。


2026-11-15 SCP MMIO映射接入准备：新增默认关闭的唯一owner六页non-posted
预留路径，替换旧cfg映射并在Kconfig排除旧pending observer；不调用prepare
或寄存器操作，五IRQ仍NO_AUTOEN。owner双路径及后端sanitizer、启用/默认
构建、定向schema/DTB与strict checkpatch通过。测试镜像`fba1be648ead`已就绪，
尚待上机，不增加硬件支持验收；设备仍运行`49092bac2836`。
详见 [映射接入与测试边界](MODEM-SCP-MMIO-OWNER.md)。


2026-11-15 SCP MMIO映射实测：当前主线 `fba1be648ead`，六个完整页均由
唯一resource owner占有，USB/Wi-Fi重复查询寄存器读写0、prepared=0、
generation=0；初始fault=1表示未prepared的主动封闭。五IRQ保持masked，
所有CPU中断计数和异常计数0。旧pending observer编译关闭，属性不存在，
不读取/清理继承消息。26M pin、CCF引用3/3、原core0/header/mux、8核、只读
存储/rootfs及boot回读通过。未进行真实RX/completion/ACK、IRQ使能或SCP/MD
启动，不计作基带可用；下一步接真实prerequisite及正常IRQ/work/STOP。
详见 [实机映射验收](MODEM-SCP-MMIO-OWNER.md)。


2026-11-15 SCP Linux IRQ/work 接收层离线准备：默认关闭 adapter 组合现有
MMIO/queue/drain，完成 IRQ 深度平衡、排队代号及 STOP 同步屏障；新增只读
资源检查 helper。实际 C sanitizer/既有回归、启用/默认 ARM64 构建和 strict
checkpatch 通过。尚未替换平台 IRQ owner、启用 IRQ 或执行真实接收；本轮
不刷写/重启，USB只读复查设备仍为 `fba1be648ead`，六页零寄存器操作、
五IRQ masked、26M pin有效。下一步先接 dormant constructor/prerequisite，
再完成真实 reset/旧消息隔离；不计作 SCP/基带可用。
见 [接收 adapter 和验证范围](MODEM-SCP-RECEIVE.md)。


2026-11-15 SCP receive 静默接入实测：当前主线 `4ed57fd98c40`，唯一资源
owner 以新 adapter 互斥替换旧 IRQ reservation，五个 `op6893-scp-rx` action
均 masked、所有CPU中断及worker计数0；generation/queued/events=0，六页
MMIO读写0且未prepare。probe无SMC请求，一次显式26M pin后mask=0x02、
pin_verified=1，CCF引用3/3。USB/Wi-Fi各三轮、8核、UFS/cache/rootfs只读
状态及boot回读通过。新增owner prerequisite wrapper已有模型验证，实际
reset generation仍0，无start caller；不启动SCP/MD、不计作基带可用。
下一步推进真实reset/旧消息隔离与固件/客户端前提，再考虑启用接收。
见 [唯一owner接入与实机验收](MODEM-SCP-RECEIVE-OWNER.md)。


2026-11-15 SCP reset/恢复布局离线准备：核对A/V/Q初始化释放与恢复worker的
不同路径、双核TCM/DRAM恢复公式及独立mailbox隔离缺口。编译确认header
结构A/V/Q为72/72/60字节，本机先前实测68，不照搬Q尾部。新增默认关闭纯
CPU restore planner，检查完整源/目标范围、重叠、精确header长度与backup
公式；ASan/UBSan、源码审计、启用/默认ARM64构建及strict checkpatch通过。
无device caller/映射/复制/reset/IRQ操作，本轮不连接或刷写设备，不增加
基带验收；上次实机验收为 `4ed57fd98c40`。下一步统一core0/core1/TCM资源
归属，再规划受限停止观测；真实旧消息隔离和备份来源尚需闭合。
见 [reset与恢复契约](MODEM-SCP-RESET-RESTORE.md)。


2026-11-15 SCP core0/core1/TCM 统一映射实测：新增默认关闭选项，与旧
core0/TCM/pending reader互斥，在现有唯一owner取得三块完整non-posted窗口。
主线 `db337399ee04` 的 /proc/iomem 确认cfg/五mailbox/core0/core1/TCM共九块
均归同一owner；读写仍0，五IRQ masked且全部CPU计数0，generation0。
一次26M pin、USB/Wi-Fi各三轮、8核/RO存储与boot回读通过；sanitizer、
Kconfig互斥、启用/默认ARM64构建、schema与strict checkpatch通过。
本轮只验收映射，不证明core1/TCM读取、复位或停止语义；未启动SCP/MD。
下一步将受限core/header观测迁到同一owner，审查core1只读allowlist，
再闭合双核停止和旧消息隔离。见 [统一资源归属](MODEM-SCP-CORE-TCM-OWNER.md)。


2026-11-15 SCP 统一 owner 双核/header 只读实测：主线 `cebf84a7d29e`，
新默认关闭选项在原九块独占映射内、同一mutex下读取。未pin两入口EAGAIN且
零读；pin后core0/core1仅0/4/0x70受限位均稳定0，TCM header68字节，CPU恢复
布局geometry检查通过。USB/Wi-Fi各三轮，core/TCM最终252/252读数与预期一致；
写入、cfg/mailbox读写、IRQ/worker事件仍0，CCF/八核/RO存储和boot回读通过。
模型/构建/schema/checkpatch通过。设备保留该主线；不把读回解释为reset/停止
或固件有效，不启动SCP/MD。下一步双核停止和旧消息隔离契约，见
[统一owner只读观测](MODEM-SCP-OWNER-OBSERVE.md)。
