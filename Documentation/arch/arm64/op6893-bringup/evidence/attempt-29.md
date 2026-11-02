# Attempt29: PMIC interrupt and key delivery

Boot b8f0b0600beb, SHA2560b9b9bd4ab4e8e5c2b8919edac8d2bf5b1ba94fb6b32133c329b59c5a7f374eb.
Debian9825862f46b0 unchanged. After16-pair SWCID/DEW test, diagnostic
pwrap path creates regmap and populates MT6359 MFD; inherits LK clocks and
SPI master, still skips generic wrapper initialization. PMIC interrupt
EINT222 level-high. Standard MT6359 keys: power first (code116), home second
(code115). Board/build-gated skip of long-press reset setup preserves LK
recovery settings; actual long-press recovery not retested this attempt.

MFD initializes IRQ masks (disables all groups), keys enable four PSC key
IRQs; nested handler clears status via regmap writes. Regulator/RTC/IIO/sound
drivers disabled. MFD still creates unbound child devices; missing of_node
messages for auxadc/rtc/accdet expected, not evidence these drivers ran.
No supply configuration writes introduced by these bound drivers.

Hardware: transport reads pass0x5920/0x5aa5; MFD and keys probe succeed.
Physical user test exactly three KEY_VOLUMEUP down/up pairs and one KEY_POWER
down/up pair. PMIC hwirqs48/50 counts1each;49/51 counts3each. Parent EINT222
count23 (not necessarily one parent dispatch per nested event); all counts
unchanged during15s idle observation.8CPUs,USB SSH,watchdog alive,root image
hash and cache readonly confirmed. PMIC keys event0; volume-down gpio-keys
now event1 (do not hardcode event numbers across configurations).

Build/FDT/packing passed; no compiler warnings; all four incremental patches
pass checkpatch0errors/0warnings. Existing undocumented diagnostic MT6885
compatible/incomplete wrapper binding remains; no full schema check or claim
of production-ready PMIF clock/reset/error handling. New write transport is
exercised by actual IRQ setup/acknowledgement, not arbitrary PMIC writes.

Device left running mainline. No additional reset requested. No ACK restore;
if needed use original evidence/ack-boot.img as explicitly requested. Code and
analysis generated with Codex assistance, no commits or Signed-off-by.
Next: settle PMIF resource binding/clock ownership and error paths before
regulators/DVFS; optional ADC readout requires its own register/init review.
