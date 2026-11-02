# Attempt 12: boot-time heterogeneous CPU discovery

Image dist/466ba2ab44d9/boot.img
SHA256 6051809d03026cd5dc0fc802e0de719257aa70850bb24bf2ee8c2f80a4db6f55
Only changed build input versus attempt 11 is diagnostic board DTS:
maxcpus=1 -> maxcpus=8. No capability/mitigation code modifications.
Build/FDT/packaging passed. Attempt 11 pstore captured before this flash,
serving as pre-test baseline; no intervening ACK boot.

Live USB usb-466ba2ab44d9/ confirms all eight CPUs brought up at boot.
CPU1-3 MIDR 0x412fd050, CPU4-7 MIDR 0x411fd410; all CPUs entered at EL2.
Spectre-v4 and other A78 capabilities discovered before finalization.
Online mask 0-7. Per-CPU taskset tests on CPU1-7 reported masks 2,4,8,10,20,40,80
and each returned the expected 16MiB zero-data SHA256. Writes of 1 to online
on this boot were no-ops: CPUs were already online. This is NOT offline/online
cycle testing. CPU0 had baseline execution coverage, not a separate pinned
hash in this script. No sustained all-core load or DVFS/suspend validation.

Host observing 60 seconds, then captures full dmesg/interrupts/cpuinfo and
requests watchdog stop via /tmp/op6893-stop-feeding. Fallback remains 600 sec.
Initial test completed 37 successful live USB commands. A USB stop request
was logged at 70.126931 seconds; stopped feeder state confirmed. User missed
first fastboot interception and device booted mainline again.

Reconnected without manual power reset: usb-466ba2ab44d9-reboot2/ confirms
same release, eight CPUs booted again and online mask 0-7. Saved full logs
before a second USB stop request. This time fastboot was intercepted.

Raw capture peek-466ba2ab44d9/ is identical to attempt 11 (True), so it is
stale and NOT evidence for either attempt 12 boot. Positive execution evidence
comes from the two live USB captures, with unique release and CPU boot logs.

ACK backup flash/reboot succeeded; runtime identity and boot hash in
restored-ack-466ba2ab44d9.txt. No partition other than boot written.
