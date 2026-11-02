# Attempt 5: watchdog only

Image: dist/ec0df4fa1a27/boot.img
Release: 7.3.0-op6893-d1-ec0df4fa1a27+
SHA256: 6540769bfe7c804383ff544cf26fc19edbb47811e9997b44a33056b3d358f57b

Compared with attempt 4, enable WATCHDOG, WATCHDOG_HANDLE_BOOT_ENABLED and
MEDIATEK_WATCHDOG, enable the existing watchdog node with timeout-sec=30,
and launch BusyBox watchdog with -F -t 5 -T 30. Retain five-second heartbeats.
USB and regulator subsystems remain disabled. No watchdog driver code changed.

Build, FDT tests, image packaging checks, shell syntax and DTS checkpatch passed.
ACK identity, completed boot and backup hash verified before reboot.
Pre-test raw capture: pre-ec0df4fa1a27/.
Flash/reboot succeeded: flash-ec0df4fa1a27.txt.

## Observation and capture

User waited an additional minute, observed no automatic reboot, and recovered
manually into fastboot. Raw capture completed before ACK restoration:
`peek-ec0df4fa1a27/`, 917504 bytes, SHA256
`1d995f8ee0fde44c09001b5c5e42c0731ada02ceca826bb65c9da023e17dbccd`.
The entire pstore region is byte-for-byte identical to the pre-test snapshot.
Console has only old release 468cb65b4df1 and its heartbeats through 25 seconds.
There is NO execution or watchdog-feeding evidence for ec0df4fa1a27.
No automatic reboot must not be interpreted as a successful watchdog test.

Both attempts 3 and 5 required manual recovery and retained an identical old
pstore snapshot; attempts 2 and 4 supplied fresh mainline evidence. Boot progress
and reset-path effects on captured memory remain confounded. A controlled
software/timed reset and capture would help isolate this, provided the kernel
reaches the code scheduling it. Absence of such a reset would remain ambiguous.

ACK backup flash/reboot succeeded; runtime identity and boot checksum are saved
in restored-ack-ec0df4fa1a27.txt after verification.


ACK restored and boot completed=1 verified; full boot hash matches backup.
Post-ACK console/expdb/dmesg contain no ec0df4fa1a27 build ID.
