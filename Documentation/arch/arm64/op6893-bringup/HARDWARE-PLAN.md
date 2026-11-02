# MT6893 hardware and boot capacity audit — 2026-11-02

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
