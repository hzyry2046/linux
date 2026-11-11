# Attempt54: MT6359P regulator provider registration

Image `d873de3b8963`, release `7.3.0-op6893-d1-d873de3b8963+`.
Boot SHA256: `7ad1299c5929b3bc991ffabc09e37dd320375f3e7973f548dd2691c3a007aef8`.
Serial-targeted flash of boot followed immediately by reboot succeeded.
Previous known working image: `06374ef46937`.

## Change and scope

Enable CONFIG_REGULATOR_MT6359 and describe VS1, VS2, VCN13, VCN18 and
shared VCN33_1/VCN33_2 rails. Map PMIC vs1-ldo2-supply to VS1 and
vs2-ldo2-supply to VS2. No voltage/mode constraints, boot-on, always-on,
CONN consumer or automatic wireless power sequence added.

The provider registers all 45 PMIC descriptors, including rails absent from
DT, rather than just the six described nodes. VCN33 Wi-Fi/BT aliases are
framework wrappers onto shared physical rails. Existing regulator_ignore_unused
remains essential. Current Wi-Fi enable bits were zero, so the driver's
conditional VCN33 probe synchronization was not expected to write them.

Registration is partial resource description, not complete supply ownership:
missing external VSYS inputs resolve to regulator-dummy, which has 32 open
handles. Internal VS1 -> VCN18 and VS2 -> VCN13 relationships are visible.
Do not enable wireless consumers on the assumption that dummy inputs are real
managed supplies. CPU supplies and MT6315/SPMI remain outside this change.

## Validation

Build and integrated host checks passed; provider patch checkpatch reported
zero errors/warnings. Boot capacity check passed. Filtered MFD dt-validate
reported the existing `start-year: missing type definition` schema warning;
this was not a completely warning-free schema validation run.

On device the provider bound successfully. Before/after snapshots match for
all 18 selected PMIC registers and seven SPM/infra registers. Four VCN rails
and CONN remain off. This comparison covers the selected registers only,
not every PMIC register or an electrical measurement.

USB SSH, eight CPUs, read-only sdc/cache rootfs, watchdog processes, PMIC
battery/temperature reads and MAINPLL/AXI/thermal clock observations work.
Both key devices remain registered; physical key events were not retested.
Debian SquashFS SHA256 remains
`4b831520cce5df878a6ddb1b428c235d1735f5eea9fe5148f0fa6d0783f90051`.
A fresh LVTS capture returned 17 valid samples, 36.919--42.252 C; independent
host arithmetic agrees. All seven LVTS controllers afterwards have sensing,
local clocks, interrupt enable and protection controls/thresholds zero.
No selected WARN/BUG/Oops/Call trace appeared in the collected regression.

The first regression collection stopped because debugfs was not mounted;
mounting it and rerunning succeeded. This was a collection prerequisite,
not a provider failure.

## Evidence and next step

Selected evidence is in attempt-54/: provider.patch, before/after snapshots,
verification summary, capacity/schema results and flash log. Full regression
and build captures remain in /data/src/mainline/mt6893-direct/evidence/attempt-54/.
Device remains running this image. Next audit clock-buffer/pinmux and external
supply dependencies before an explicitly triggered bounded CONN experiment.
