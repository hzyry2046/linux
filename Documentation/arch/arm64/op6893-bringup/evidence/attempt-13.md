# Attempt 13: per-CPU offline/online cycles

Reused immutable image dist/466ba2ab44d9/boot.img; no kernel rebuild or changes.
SHA256 6051809d03026cd5dc0fc802e0de719257aa70850bb24bf2ee8c2f80a4db6f55
ACK identity/boot hash verified before test. Pre-test raw pstore and flash
transcript saved. Host script snapshot: attempt-13-sources/usb-diagnose.py.

Live USB usb-attempt-13/ contains 58 successful commands. CPU1-7 individually
went offline then online; per-CPU online flag was zero while offline and full
online mask returned to 0-7 each time. Offline masks excluded exactly the
selected CPU. PSCI killed/secondary-boot messages confirm actual transitions.
Every re-onlined CPU passed a taskset affinity-mask check and a 16MiB zero-data
SHA256 check. USB remained usable throughout and during 45-second observation.
Final full dmesg/interrupts/cpuinfo captured before USB stop-feeding request.
No BUG/Kernel panic/WARNING markers in the final live dmesg capture.

Fastboot raw capture peek-attempt-13/ completed. Capture differs from pre-test
snapshot and contains the matching release, CPU transitions and stop sequence.
Only one cycle per CPU was tested; no all-core stress, whole-cluster powerdown,
DVFS or suspend claims. CPU0 was kept online.

User explicitly changed restoration preference: do not restore ACK by default;
restore if useful/needed. Device left in fastboot with mainline 466ba2ab44d9
still in boot. ACK backup remains intact. No ACK restoration performed.
