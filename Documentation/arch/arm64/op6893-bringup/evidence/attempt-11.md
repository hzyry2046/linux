# Attempt 11: late CPU online from CPU0-only boot

Image dist/0cc5159de251/boot.img
SHA256 7809d9fa533bb41b7dd2bf6630167a0ee90995172aa96a387138119db25a36ab
Changes versus attempt 10: CONFIG_HOTPLUG_CPU=y; init accepts an in-RAM
/tmp/op6893-stop-feeding request and otherwise times out after 600 seconds.
No other kernel changes; maxcpus=1 retained. ACK pre-test identity/hash verified.
Build/FDT/pack checks and shell syntax passed. Pre-test peek and flash saved.

Live USB captures: usb-0cc5159de251/ and usb-0cc5159de251-after-cpu4/.
CPU1/2/3 came online and passed 16MiB zero-data SHA256 while pinned with taskset.
CPU4 write to online returned EIO. Live dmesg explains:
3.681481: CPU features: CPU4: Detected conflict for capability 84 (Spectre-v4), System: 0, CPU: 1
3.681505: CPU4: will not boot
8.928717: CPU4: failed to come online
8.928730: psci: CPU4 killed (polled 0 ms)
8.928735: CPU4: died during early boot
CPU0-3 and USB remained responsive. CPU5-7 were not attempted.

Local source: proton-pack.c safe list includes Cortex-A55; cpu_errata.c marks
Spectre-v4 LOCAL_CPU_ERRATUM, which is not permitted newly on a late CPU when
system capability was absent. CPU4 rejection fits boot-time CPU0-only capability
finalization, not evidence of broken PSCI addressing. Next isolate by changing
maxcpus=1 to maxcpus=8, preserving mitigation and capability checks.

Post-failure live logs/cpuinfo/interrupts saved before USB stop request. The
request was accepted and USB disconnected around the watchdog expiry window.
Raw post-test capture and final ACK restoration pending (follow-up test planned).

Post-test pstore peek-0cc5159de251 contains the correct release, heartbeats
through 85.179952 seconds, and USB-requested feeder-stop evidence. Follow-up
attempt 12 changes only boot CPU count; final ACK restoration follows it.
