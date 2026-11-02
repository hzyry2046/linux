# Attempt18: external BusyBox root on cache

Temporarily booted known ACK6.6.30-4k-g6974e26f087e and verified boot hash.
Waited for sys.boot_completed=1. Existing cache normal ext4 mount; mainline
directory absent. Installed only /cache/mainline/rootfs.img via new file,
verified SHA256, synced, renamed, synced and cleanly unmounted cache.
Removed transferred staging file in /data/local/tmp. No raw cache writes,
formatting or GPT repairs. Installation transcript: attempt-18-install.txt;
exact commands: attempt-18-install.sh.32MiB file owned root:root0644.

Boot restored to d0a082f6ef67 (same as missing-image fallback attempt17).
Rootfs888f07f2297f SHA256:
0439c5bee62de569f59d5fea8fec27da709ff39b1eb7e559dac2d7ce00dddefe.
Host script snapshot attempt-18-sources/usb-diagnose.py validates root id,
root and backing cache ro,norecovery mounts, loop readonly flag, RAM tmp
write/read/delete, full backing image hash and live observation.
Results pending.

## Live external root verification

Exact release/rootfs id matched. Kernel log: SWITCH_ROOT_READY at1.065s,
DIAGNOSTIC_INIT root=external at1.069s, watchdog worker pid222.
PID1 cmdline /bin/busybox sh /sbin/init. Mounts:
/dev/loop0 / ext4 ro,relatime,norecovery
/dev/sdc55 /run/cache ext4 ro,nosuid,nodev,noexec,relatime,norecovery
/run and /tmp on tmpfs. /sys/block/loop0/ro=1; sysfs backing_file is
/run/cache/mainline/rootfs.img. losetup prints original attach pathname
/cache-stage/mainline/rootfs.img; this is stale display metadata, not a
missing backing file (sysfs and full file hash confirm real location).
RAM temporary file write/read/delete passed. Installed32MiB image full
SHA256 remains exactly0439c5bee62de569f59d5fea8fec27da709ff39b1eb7e559dac2d7ce00dddefe.
One watchdog process runs after switch; no initramfs feeder carried over.

All19 live commands passed.65s observation maintained8CPUs and USB
configured. Final dmesg has no I/O error, WARNING, BUG, kernel panic or
EXT4-fs error matches. Stop-feeding request succeeded, followed by USB
disconnect31.9s later. Device awaiting fastboot interception. Boot
remains mainline d0a082f6ef67; external rootfs remains installed in cache.
