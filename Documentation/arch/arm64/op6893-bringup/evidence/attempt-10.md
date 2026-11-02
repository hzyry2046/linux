# Attempt 10: foreground shell supervisor

Image dist/3ba35d79721e/boot.img
SHA256 385a5de43f85f1a33e202a85a7d7e74176f10eafd59930e6566886edba486f25
Only changed build input relative to attempt 9: initramfs/init.
PID 1 runs shell supervisor in foreground; diagnostics/heartbeat runs in a
background subshell. setsid -c supplies ttyGS0 as controlling terminal.
This avoids asynchronous-shell SIGINT/SIGQUIT ignore inheritance. Watchdog
feeder remains independent. Timed stop returned to 90 seconds for short check.

Built with FDT/image tests and BusyBox syntax check. Attempt 9 raw pstore
serves as immediately preceding baseline. No ACK boot between attempts 9/10.
Host script and init saved in attempt-10-sources/. Flash transcript saved.

USB live capture usb-3ba35d79721e/: correct release, ttyGS0, shell PPID 1,
SigIgn no longer includes SIGINT (2637828 vs 2637830). Ctrl-C interrupts a
20-second sleep after about one second; command CTRL_C_RECOVERED completes
within the five-second deadline. No no-controlling-tty/cttyhack warning.
Live command summary: {"commands": 14, "uptime": "106.96 105.35"}. Ctrl-C test is included in the
14 total successful commands, not 14 additional commands. Shell SigIgn changed
from 2637830 to 2637828, independently confirming SIGINT no longer ignored.
Host recorded disconnect and then detected fastboot near planned timeout.

IMPORTANT: peek-3ba35d79721e/pstore.bin is byte-for-byte identical to attempt 9
capture (True), containing a5523999d27c, not 3ba35d79721e. This capture is stale
and provides NO attempt 10 execution/stop-feeder evidence. All positive attempt
10 evidence comes from live USB and its new release. This shows stale peek
contents are not exclusive evidence of failure to boot, and we must not assume
manual recovery is the sole cause. Reset/bootloader capture behavior unresolved.

ACK backup flashed and rebooted after raw capture. Final identity and boot hash
verification in restored-ack-3ba35d79721e.txt.
