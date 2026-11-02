# Attempt39: bounded LK devinfo handoff

Status: image booted; live calibration handoff verified. Regression results below.
Image fa91b68792cf, SHA256
50d0ec954c0a7da324ea1d026abb482942910b4ac31dc50955e10665483c4207.
Mainline rollback74e7947a974f; original ACK recovery evidence/ack-boot.img.
User had returned device to ACK6.6.30-4k-gf3ddcd7f927a-dirty before this turn;
ADB root available, device idle. Saved fresh ACK DTB/devinfo and decoded LVTS
calibration;22words agree with prior ACK evidence. No ACK partition-table changes.

Early FDT merge now imports only chosen/atag,devinfo, with chosen@0 fallback
when chosen is absent. Little-endian unaligned count,208–400words,exact payload
length required. This is a bounded bootloader payload, not FDT big-endian cells.
Absent or malformed optional data is omitted without stopping the existing
memory/reservation handoff. This checks structure, not trustworthiness or
physical calibration validity; consumers must still validate their fields.
Existing board bootargs and initramfs policy retained, other vendor chosen
properties excluded. No LVTS MMIO,clock/reset,thermal zone or NVMEM provider.

Host test compiles actual merger. Valid original and fresh ACK inputs preserve
bytes; wrong endian,short header,short count,truncation,trailing bytes,overflow
count and oversized count omitted.208/400 boundary and chosen@0 cases pass;
unknown properties,phandles,external initrd excluded. Existing RAM and41memory
reservation checks pass. Old merger reproduces lost-property assertion failure.
New tests are included in the build's source identity and retained test log.

Build no compiler warnings; all FDT/PMIF guard/ADC scale/ADC temperature tests
pass. Incremental checkpatch0errors/0warnings with commit-message/signoff checks
excluded; git diff --check passes. /tmp tool environment was cleared by user;
checkpatch's ply/GitPython restored in tools/checkpatch-venv, outside /tmp.
No DTS change or binding/schema validation claimed in this round.

Hardware plan: ADB reboot bootloader from ACK, verify serial, flash boot and
reboot. Verify release, exact devinfo bytes against fresh ACK, LVTS decode,
root hash/readonly cache,USB SSH,8CPUs,watchdog,PMIC diagnostics and PMIF state.
No physical key or temperature-response retest required unless regression.
Code/analysis generated with Codex assistance; no commits or Signed-off-by.

## First handoff attempt

ADB reboot bootloader returned success and serial IF7HHUAUVSHIGMJR was briefly
visible via fastboot devices. Before flash could connect, device returned to
ACK (uname6.6.30-4k-gf3ddcd7f927a-dirty,uptime58.20s). Flash command only printed
waiting-for-device: no Sending/Writing stage reached. Waiting fastboot process
stopped with SIGINT; no boot image written. Cause of bootloader departure not
yet established. Manual fastboot coordination requested. Hardware validation
of fa91b68792cf remains pending.

## Hardware handoff verified

User reports moisture-affected power key can select bootloader menu items and
cause unexpected restarts. Future fastboot commands should be queued before
arrival, serial-targeted, with flash success followed immediately by reboot;
do not use simultaneous competing clients or an unattended reboot loop.
Continue using flash boot, not unreliable fastboot boot.

Manual fastboot flash/reboot succeeded (flash-manual.txt). Device subsequently
appeared in fastboot again; cause not established. A single reboot retry booted
fa91b68792cf, SSH ready at uptime14.12s. First early SSH attempt was refused
while sshd was starting. No repeat flash was necessary.

Live /chosen now contains atag,devinfo alongside bootargs/name. All884 bytes
(count220 plus data) equal fresh ACK capture exactly. Decoder validates22 LVTS
words,17count_r,7count_rc,golden_raw60 =>30C. This verifies live bootloader data
handoff; it does not enable LVTS or validate its sensor initialization. PMIC
temperature interface returned35802mC. Seven PMIF/clock registers unchanged
from attempt37 despite intervening ACK run. No LVTS registers touched.

Regression passed:USB SSH,8CPUs,watchdog feeder,unchanged Debian hash,cache
ro,norecovery and15s stable PMIC IRQ rows. Captured dmesg has no new ADC/PMIF
fault markers or CPU BUG/oops/call trace. Physical keys not retested. Device
left running fa91b68792cf; no pending fastboot flash/reboot commands.
