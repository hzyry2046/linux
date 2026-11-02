# Attempt17: external-root loader missing-image fallback

Boot d0a082f6ef67; SHA256
c803df48a0763cd3612a1a50593d586adcf1ac538a91cbd93d8506f326c88ac0.
Added builtin loop, split diagnostic PID1 and initramfs loader. Loader pins
rootfs image hash, mounts cache/loop readonly and prepares switch_root.
Kernel watchdog boot worker feeds until selected PID1 starts userspace feeder.
No processes or watchdog FDs intentionally span switch_root.

Host external image rootfs/dist/888f07f2297f/rootfs.img:32MiB ext4,
SHA2560439c5bee62de569f59d5fea8fec27da709ff39b1eb7e559dac2d7ce00dddefe.
Host e2fsck -fn and BusyBox shell syntax check through qemu passed;
kernel build/FDT/packaging checks passed. Image NOT installed on target yet.

Live USB usb-attempt-17 confirms exact boot release and fallback markers:
INITRAMFS_REACHED, EXTERNAL_ROOT_UNAVAILABLE fallback=initramfs,
DIAGNOSTIC_INIT root=initramfs, watchdog worker.8CPUs and USB remain
usable through35s observation. This tests missing-image fallback only,
not real external switch_root or post-switch watchdog lifetime.
Next installation planned via working ACK to normal cache filesystem,
not raw flashing/formatting. GPT intentionally retained for EL2.
