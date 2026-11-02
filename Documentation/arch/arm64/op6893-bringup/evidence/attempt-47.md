# Attempt47: refresh ACK recovery image and bounded LVTS samples

Status: ACK backup refreshed and verified; host and live sampling tests passed.
Current device runs mainline3e5080c359e5. Device initially runs ACK after user restored it.

## Recovery baseline

User explicitly requested replacing recovery backup with installed boot.
Read full32MiB /dev/block/by-name/boot -> sdc48 via serial-targeted root ADB.
Device hashes before/after transfer and local hash match:
455ed6cea037d6d6bd9af328d589ab39b8692edd4db2c3924e1f8da7b4722c88.
Android v2 layout parsed successfully. Kernel,DTB chains and ramdisk match
previous backup; header differs. Previous image976b5d... archived by full
hash; current evidence/ack-boot.img atomically replaced after verification.
This is now the selected restore and pack base. No device partition writes
were performed during backup. Details:ACK-RESTORE-CURRENT.md,ack-backup.json.
Host rebooted into7.2.14-arch1-1; cdc_acm/cdc_ether modules loaded successfully.

## Sampling experiment

After identification,RCK and EDATA readback,run each controller once. Reject
nonzero monitor/IRQ/protection configuration and stale valid MSR data before
starting. ACK configuration:TSSEL13121110,CALSCALE300,MONCTL1=10000c,
MONCTL2=10001,MSRCTL0=492; restore sensor selection10,device modeb8,TS_ENf5,
wait10us,enable sensing mask plus MONCTL bit9. Poll each MSR valid bit16 at
50us intervals for at most20ms per sensor. Reject raw0; do not substitute
vendor's dummy26111mC. Convert with explicit signed64-bit
(-252500*raw)>>14 + golden*500 +252500. Raw words and golden logged alongside
result. Values are diagnostic, not independently calibrated physical accuracy.

On success/error,pause sensing via MSRCTL1 bits10e,clear MONCTL,wait idle bits
481 with1ms timeout,attempt TS_EN shutdown,close local clock. Cleanup failures
are reported,not treated as successful shutdown. Hardware IRQ/protection and
RGU route remain untouched. No thermal zone or ongoing sensor interface yet.

Host fake-MMIO UBSan tests:1..4sensors,every setup/cleanup command failure,
valid/idle timeout,zero/stale/IRQ rejection,28signed conversion cases. Existing
RCK/ID/clock/ADC/FDT suites remain build prerequisites. No DT changes. AI-assisted
code/tests/docs with Codex; no commits,Signed-off-by or messages to maintainers.

Built image3e5080c359e5 SHA256
8b746a94a67b7f856a66bb54acfda07f321e2d0034cc396a2a9063d44692ac9d.
All integrated tests passed; build has no warning/error markers.


## Hardware results

Queued serial-targeted flash/reboot captured the ACK bootloader reboot and
installed3e5080c359e5. Native USB ECM/ACM and SSH work after host restart.
Seven IDs verified,RCK and EDATA pass again (raw RC2744..2772,no fallback).
All17MSR words have valid bit16 and nonzero raw data. Temperatures from this
boot range39431..44471mC,all matching independent signed arithmetic using the
live golden60 calibration. These are sequential one-shot readings,not a
simultaneous thermal map or external thermometer validation.

Readback confirms all7MONCTL,IRQ enables,PROTCTL,PROTTC and local CLKEN0.
EDATA matches logged values and independent normalization. Clock/PMIF snapshots
match attempt46. Eight CPUs,watchdog feeder,PMIC ADC,cache ro,norecovery,
sdc read-only and Debian hash pass regression. No selected WARN/BUG/Oops/
Call trace or sample/cleanup failures. Intentional GPT warnings remain.
No physical button retest,CPU stress,thermal zones or protection activation.

Next: turn bounded sampling into a diagnostic interface with explicit data
freshness and lifecycle handling,then validate repeatability/temperature
response before designing thermal zones and protection. Fixed board resources
and one-shot platform device remain experimental,not upstream-ready.

Final health at uptime158.97s:8CPUs,thermal reference1,diagnostic driver
bound,SSH available,no selected faults. Device left running mainline.
