# Attempt 3: watchdog and USB serial, c4814e49de5c

Image: `dist/c4814e49de5c/boot.img`
SHA256: `8df6229ac5915b9632424d2d6f662d502720e6fb9de518342b36574c25fd4c45`
Release: `7.3.0-op6893-d1-c4814e49de5c+`

Pre-test ACK release and boot-completed property matched the working baseline.
User authorization for boot partition tests persists. Flash and reboot completed
successfully; see `flash-c4814e49de5c.txt`. No other partition was written.

Host USB polling (`usb-c4814e49de5c.json`, ten samples at five-second intervals)
found neither an ACM tty nor the phone on USB. This alone says nothing about
whether the kernel reached userspace or whether the watchdog was serviced.

User observed no automatic restart and an unchanged screen, then used a long
power-key press because other recovery methods did not work. Intercepted fastboot.

Read all 917504 pstore bytes before restoring ACK. The entire capture is
byte-for-byte identical to attempt 2: True.
SHA256: `8052f8637abe5a30b15c6887f52571d492a7993edd71b4e0fcff208839b80f2b`.
Console contains only release `4377cca94e7d`, ending at its old PID 1 marker.
No execution evidence for `c4814e49de5c` was obtained. The old log must not be
attributed to this attempt. Reset retention / bootloader memory handling and
failure before early console remain unresolved possibilities.

ACK backup flash and reboot succeeded; see `restore-after-c4814e49de5c.txt`.
Runtime restoration verification is recorded in `restored-ack-c4814e49de5c.txt`
when available.


ACK restoration verified: `6.6.30-4k-g6974e26f087e`, boot completed=1,
and boot SHA256 matches the original backup. Post-ACK read-only collection is
under `after-c4814e49de5c/`. Neither its console, expdb nor dmesg contains the
new build ID. The retained old console is not evidence for this test.
