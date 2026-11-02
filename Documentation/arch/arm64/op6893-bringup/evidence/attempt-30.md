# Attempt30: inherited PMIF resource/state diagnostics

Boot `268105891ada`, SHA256
`ac8f8870e24c5c2f3a88a204b9bddf54cb55a5a1d96bb873fe0dec2027a1854b`.
Flashed boot successfully from fastboot; native USB SSH reconnected.
Debian `9825862f46b0` unchanged. No GPT changes or ACK restore.

Changes: map named SPI master resource 0x10028000/0x1000 alongside
PMIF 0x10026000/0x1000; resolve GIC SPI220 without requesting its IRQ;
record inherited initialization/SPI/IRQ state; annotate failed test reads
with register and sample index. Existing board/build gate retained.

Hardware startup snapshot: init=0x1, status=0x8441, spi_en=0x1,
irq_en=0x0, irq_flags=0x0. These are the sampled PMIF register values,
not proof that every error source is covered. Sixteen SWCID/DEW pairs pass
with 0x5920/0x5aa5. Both resources appear in /proc/iomem. MT6359 MFD
and mtk-pmic-keys probe successfully; gpio-keys also registered. No physical
key test repeated this attempt (attempt29 has actual press/release evidence).
PMIC parent and four nested IRQ counters all remain zero across 15s idle.

Eight CPUs online; root image SHA256 matches
4b831520cce5df878a6ddb1b428c235d1735f5eea9fe5148f0fa6d0783f90051;
cache remains ext4 ro,norecovery. Watchdog driver reports enabled 30s,
feeder process alive, uptime63s. watchdog0/state sysfs attribute absent;
that query failed, so watchdog evidence is dmesg/process/continued uptime,
not a state attribute reading. No watchdog reset test repeated this attempt.

Build and FDT tests pass with no compiler warnings. Incremental checkpatch
previously passed zero errors/warnings. Boot payload7409664bytes,
partition free26144768bytes (32MiB padded image). Full DT schema validation
still unavailable. Existing initial-console, UFS reset-resource and intentional
GPT warnings remain; MFD unbound auxadc/rtc/accdet node messages expected.

Still diagnostic: inherited LK clocks and SPI setup; wrapper error interrupt
not claimed/handled; binding and clock ownership incomplete. Regulator,
RTC, ADC and audio drivers remain disabled/unbound. ADC probe performs
reset/configuration writes, so enabling it needs a separate compatibility
review and must not be described as a read-only operation.

Device left running mainline. Next: audit real MT6893 PMIF clock mapping
and wrapper error handling before taking ownership or enabling supply/DVFS
control. Code and analysis generated with Codex assistance; no commits or
Signed-off-by. Recovery remains original evidence/ack-boot.img.
