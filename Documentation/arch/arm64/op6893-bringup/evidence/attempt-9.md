# Attempt 9: controlling tty and ten-minute USB soak

Image dist/a5523999d27c/boot.img
SHA256 f39695331f5e34bb7692997471a7b71953ed83dca4412a0f62fd5e3bd31a46ec
Only build input change relative to attempt 8: initramfs/init.
Replace cttyhack with setsid -c to explicitly acquire stdin ttyGS0.
Stop watchdog feeder at heartbeat 120 (approximately 600s), not heartbeat 18.
No kernel/USB changes. Build/FDT/packaging and shell syntax passed.
ACK pre-test hash verified. Raw pre-test capture and flash transcript saved.

Initial host capture: usb-soak-a5523999d27c/. Shell tty=/dev/ttyGS0; /proc stat
shows a controlling tty. No cttyhack/no-job-control warning. Initial Ctrl-C
check timed out; stty output reported -isig -icanon, and watchdog sysfs files
were absent. Host test adjusted to use explicit external BusyBox stty and
sleep (avoids shell applet execution optimizations), explicitly enable isig
and icanon before sleep, and remove unsupported watchdog sysfs queries.
USB remained present. Follow-up capture: usb-soak-a5523999d27c-resume/.

Fresh pstore captured in peek-a5523999d27c/ (93741 console bytes).
STOP_FEED_REQUEST at 600.263063, signal sent at 600.263630. Heartbeats through
625.267994 seconds. No panic or BUG detected in this capture. Final live uptime
608.36 seconds, 43 successful commands and 20 matching 16MiB zero-data hashes
in the steady capture (not a comprehensive RAM or USB throughput test).
Initial terminal-interrupt failures remain recorded separately and were not
counted as successful commands. /proc shell SigIgn includes SIGINT.
BusyBox background-shell source and local reproduction confirm SIGINT is
inherited ignored; foreground launch does not inherit that setting.

After preserving pstore, proceeded directly to attempt 10 to verify this init
fix. No other partition touched; ACK restoration follows that short test.


Steady capture summary: {"successful_commands": 43, "last_uptime": "608.36 601.39", "hash_runs": 20, "last_event": {"disconnected": true, "error": "[Errno 19] No such device (it may have been disconnected)", "host_time": 1793588732.1091633}}

Final ACK restoration is shared with attempt 10; see its restoration record.
