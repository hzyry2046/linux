# Attempt 4: repeat minimal boot with five-second heartbeat

Image: `dist/468cb65b4df1/boot.img`
Release: `7.3.0-op6893-d1-468cb65b4df1+`
SHA256: `5b3c19ceded981e6f773db1fdb2272c60416c7b1e066989e7adb979f6f763d01`

All build input hashes match attempt 2 except initramfs/init. That script
matches the original minimal init with sleep changed from 30 to 5 seconds.
USB and watchdog configuration/DTS additions from attempt 3 are removed.
The attempt 3 init script is preserved in attempt-3-sources/init; its kernel
source snapshot remains in the immutable dist/c4814e49de5c directory.

Build, FDT tests, image round-trip and BusyBox shell syntax check passed.
ACK boot hash and completed boot were verified before rebooting to fastboot.
Pre-test pstore was captured in pre-468cb65b4df1 before flashing.
Flash/reboot transcript: flash-468cb65b4df1.txt.

## Hardware result

Raw pstore was collected in `peek-468cb65b4df1/` before restoring ACK.
The 917504-byte capture differs from the pre-test snapshot and its console
contains the new release `7.3.0-op6893-d1-468cb65b4df1+`.
PID 1 marker: 0.160061 seconds. Heartbeats: 5.160695, 10.161298,
15.161889, 20.162485 and 25.163086 seconds. No 30-second heartbeat.
No panic/BUG was observed in the new console.

User confirmed the device restarted automatically and was intercepted into
fastboot, rather than manually restarted. This demonstrates repeatable minimal
userspace boot and execution through 25 seconds, not sustained stability.
Watchdog reset is a leading hypothesis, not a proven reset cause. The actual
reset time was not measured. Next experiment should enable only watchdog
handling/feeding, leaving USB disabled.

ACK flash/reboot succeeded; see `restore-after-468cb65b4df1.txt`. Runtime
restoration verification is recorded in `restored-ack-468cb65b4df1.txt`.
