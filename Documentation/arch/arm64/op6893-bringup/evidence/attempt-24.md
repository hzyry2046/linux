# Attempt24: sustained Debian sessions and native USB reconnect

Prepared boot dad2ee05c49c, SHA256
 efe31595d0904e60b11942217d329b716054fc6c82d8b340f033f6519acebc35.
Prepared Debian9825862f46b0, SHA256
 4b831520cce5df878a6ddb1b428c235d1735f5eea9fe5148f0fa6d0783f90051,
56,967,168 bytes. Kernel code/config unchanged; updated init scripts and
pinned rootfs digest. Build/packing checks and chroot dpkg audit/init syntax
passed. Debian mode disables fixed600s stop; emergency initramfs retains
it. Watchdog remains5s feed/30s timeout. New op6893-reset syncs and requests
existing SIGSTOP-based reset via marker; watchdog PID recorded in /run.

native-connect.py identifies native host ECM by MAC, cdc_ether driver and
USB serial in default namespace; moves to dedicated op6893-native, assigns
192.0.2.1/30. Existing namespace interface reused by MAC. ssh-native.sh runs
setup before connecting; pinned keys unchanged. Repeated live setup/SSH
passed against previous rootfs; reconnect after reset still pending.

Installation and hardware validation pending.

## Initial hardware results

ACK installation passed pinned old/new hash checks; previous302e74d308e2
image retained. Cache synced/unmounted;214792KiB available. Boot flash
succeeded. Native reconnect discovered newly enumerated host interface
and restored isolated namespace/address automatically. Exact kernel/root
identities and image hash verified,8CPUs online, cache ro,norecovery,
SquashFS lower and RAM overlay confirmed. WATCHDOG_POLICY timeout_beats=0
logged at1.55s; SSH ready at5.77s. Watchdog process sleeping normally with
fd3 pointing to /dev/watchdog0. Driver does not expose timeleft/state/timeout
sysfs attributes here; these optional reads failed and are not evidence of
watchdog failure. Subsequent script syntax and dpkg audit passed.
Native SFTP1MiB random roundtrip passed. Sustained observation underway.

## Completed hardware validation

Periodic SSH checks through685.64s passed exact root identity,8CPUs and live
watchdog worker, crossing the old600s stop/630s reset window. Boot ID
unchanged; no STOP_FEED log before explicit request. Native SSH PTY and
1MiB SFTP roundtrip passed. op6893-reset subsequently disconnected USB
in31.2s, device intercepted in fastboot. Rebooted same image; native helper
automatically rediscovered/moved new interface. Exact kernel/root IDs,
8CPUs, timeout_beats=0 and running feeder passed on second boot. Device
left running mainline Debian, no further reset scheduled. This establishes
11-minute continuity, not hours-long stability or power-management support.
