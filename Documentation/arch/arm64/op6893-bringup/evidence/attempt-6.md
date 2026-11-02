# Attempt 6: timed feeder suspension

Image: dist/e28dd18f296e/boot.img
Release: 7.3.0-op6893-d1-e28dd18f296e+
SHA256: adf96a1cf7816ec881bdd59d0b79ded5da9ab831a0ce5f1215181234a6520e06

Only init changed relative to attempt 5 (build input hashes checked).
After 18 five-second heartbeat intervals, log STOP_FEED_REQUEST and send
SIGSTOP to the saved BusyBox watchdog PID. On success log
STOP_FEED_SIGNAL_SENT and process status; otherwise log STOP_FEED_FAILED.
SIGSTOP avoids BusyBox's fatal-signal handler, which magic-closes the watchdog.
PID 1 continues heartbeats. With a working 30-second watchdog, expect reset
roughly 115-120 seconds after userspace begins, subject to scheduling.
This depends on actual userspace execution and watchdog operation; no reset
would not prove a specific boot failure or successful long-running kernel.

Build, FDT/packaging tests and shell syntax check passed. Pre-test ACK verified.
Raw pre-test pstore: pre-e28dd18f296e/. Flash transcript: flash-e28dd18f296e.txt.
Init snapshot: attempt-6-sources/init.
## Hardware result

User reported automatic reset and intercepted fastboot. Complete raw capture
in peek-e28dd18f296e/ was taken before ACK restoration: 917504 bytes,
SHA256 1cb85c5749e08ae306a03673f0ff6ea45084ead4363a9b8cc5e09a140597efb5. Console is fresh (73701 bytes),
with unique release e28dd18f296e; it differs from the pre-test snapshot.

- 0.024936: mtk-wdt enabled, timeout=30 sec, nowayout=0; probe succeeds.
- 0.162290: INITRAMFS_REACHED; watchdog worker PID 33.
- Five-second heartbeats continue past 30 and 60 seconds.
- 90.174581: STOP_FEED_REQUEST pid=33.
- 90.175155: STOP_FEED_SIGNAL_SENT.
- 90.175629: process status T (stopped).
- Heartbeats continue through 120.179436 seconds; user observes automatic reset.

This demonstrates mainline execution through 120 seconds, successful operation
past the previous ~30-second failure window with watchdog handling enabled,
and automatic reset consistent with deliberately stopping the feeder. Exact
reset time and hardware reset-cause registers were not measured. No new panic
or BUG was found. This does not establish arbitrary-duration stability.

Attempts 3 and 5 remain individually inconclusive: manual recovery left old
pstore contents. This experiment strengthens the reset-path/retention concern,
but does not retroactively prove those kernels ran or identify how the old
snapshot was retained/restored.

ACK backup flash/reboot succeeded. Runtime identity and full boot checksum
verification are recorded in restored-ack-e28dd18f296e.txt.
