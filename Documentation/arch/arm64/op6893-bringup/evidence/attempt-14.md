# Attempt 14: UFS read-only identification (in preparation)

Starting from hardware-verified 466ba2ab44d9, eight CPUs and USB ACM.
Device in fastboot; no default ACK restore requested.

Experimental DTS adds UFS 0x11270000/0x2300, SPI105 and three
infracfg reset mappings from evidence/ack-live.dts. No invented UFS PHY
mapping or fake UFS clocks/regulators: inherit LK resources, as permitted
by current platform driver. ACK vendor driver uses the same 0x144 refclk
register and 0x276 SiP ABI; its refclk_ctrl DT property has no consumer
in either inspected ACK UFS driver directory.

Board-gated diagnostic driver override disables runtime autosuspend,
clock gating/scaling, crypto and WriteBooster. DT disables AH8. Block,
SCSI disk, UFS and GPT built in. No filesystem support or mount added.
This is not complete MT6893 clock/PMIC/PHY support.

Host --storage checks exact release, marks all enumerated sd block devices
read-only, records sysfs partition identities/sizes, locates cache by
PARTNAME, repeats 4MiB reads three times with page-cache dropping and
checks SHA256 equality. No userspace block writes, discard, fsck or mounts.
UFS initialization necessarily includes controller/device configuration.

Sources prepared with Codex assistance. No Signed-off-by or commit added.
Hardware results pending.

## First hardware result

Image 8a5e63c274f4, SHA256
fd6494b9fc436d804a7c63c5407a6eeb893a185517be864cf69fbeb1d626eb89.
Build had no warning/error matches; FDT and packaging tests passed.
Live USB confirmed matching release and 8 CPUs. Reset provider probed;
controller read legacy IP 0x20160706; device reset completed. Probe rejected
legacy doorbell support (-EINVAL), before SCSI host/disk enumeration.
No sda after45s; script correctly failed. No cache reads/mounts occurred.

Next experiment adds existing mediatek,ufs-disable-mcq DT property,
which applies UFSHCD_QUIRK_BROKEN_LSDBS_CAP, to accommodate this older
controller reporting reserved bit29 set. No generic core change.

Second image built: dist/7508d9e5a04c/boot.img
SHA256 69e33be79bc895da44682653a7c4043b77a0a4343385a2c2d9ee4b74d470e2d0.
FDT/package tests passed. Not yet flashed/tested at this checkpoint.
First image USB reset request saved in usb-attempt-14-reset/.
