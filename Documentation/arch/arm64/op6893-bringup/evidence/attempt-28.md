# Attempt28: inherited PMIF read transport

Boot b0241ebb1493 SHA256 eafca9f51a517a6f4f532ba66a5d7676447ba455379277e839b6684de7d49292.
Debian9825862f46b0 unchanged, backing hash verified before and after boot.
Entered from current ACK via adb reboot bootloader, flashed boot only.
Original recovery ACK evidence/ack-boot.img retained per user instruction.

Compared ACK MT6885 with mainline MT6873:8 accessed transport/init offsets
match;16-bit command format and FSM/init bit match. Saved reproducer audit.py
and register-comparison.json. Mainline sparse MT6873 register table lacks
INT_FLG/INT_CLR/WDT_SRC_EN although generic code accesses them. Do not use
unmodified generic initialization as MT6885 support.

Temporary board/build-gated mt6885 match invokes a diagnostic path immediately
after mapping PMIF, before clocks/reset/watchdog/timer/IRQ/children changes.
Requires CONFIG_ARM64_OP6893_BRINGUP, realme,op6893, MT6359 slave and LK init
flags. Performs16 pairs of SWCID0xa and DEW0x40e reads with existing transport.
Validates high chip byte0x59, stable chip ID and test0x5aa5. No PMIC register
writes, although read transactions write PMIF command and valid-clear regs.
Timeout recovery may clear PMIF valid state. No MFD/regmap/IRQ children created.
Clocks and SPI master remain inherited from LK; this is NOT full pwrap support.

Hardware probe passed at59ms: SWCID0x5920,DEW0x5aa5,16samples.8CPUs,USB/SSH,
readonly cache/root hash and watchdog worker passed. No child platform device
under10026000.pwrap. Device left running mainline; no reset scheduled.

Build/FDT merge/image roundtrip passed. checkpatch0errors/1warning for
undocumented mt6885-pwrap compatible. Diagnostic DT omits full clock/IRQ
resources deliberately; it is not an upstream-ready binding or schema-validated
implementation. Keep this warning explicit rather than pretending full SoC
support. Changes generated with Codex assistance, no commits/SoB.

Next: reconcile full PMIF resource/clock binding and initialization, then add
MT6359 MFD IRQ via EINT222, initially keys only with regulator drivers disabled.
PMIC read success does not validate write transport, interrupts or supply control.
