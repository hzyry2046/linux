# Attempt 7: USB2 ACM on timed-watchdog baseline

Image: dist/114510a78e1d/boot.img
Release: 7.3.0-op6893-d1-114510a78e1d+
SHA256: 5cc7ecba5ab589ebebf82038af996b9bdae17281b042a0d9f8fb3f21b7671430

Enable MTU3 gadget, TPHY, legacy ACM serial and fixed regulator framework.
Reuse attempt 3's experimental USB2-only board overrides; clock gates and
PMIC rail control still rely on LK-inherited state. No USB driver patches.
Retain regulator_ignore_unused and clk_ignore_unused. PID 1 retains attempt 6's
90-second timed SIGSTOP of watchdog feeder, logs UDC state each heartbeat,
and starts a background unauthenticated ttyGS0 diagnostic shell.

Build, FDT tests, image round-trip, shell syntax and DTS checkpatch passed.
Pre-test ACK completed boot and boot hash verified. Pre-test raw pstore saved.
Flash/reboot succeeded; see flash-114510a78e1d.txt.
## Hardware evidence

Fresh raw pstore collected in peek-114510a78e1d/ before ACK restore.
MTU3 probe succeeds at 0.028998 seconds; IP version 0x1001, high-speed.
g_serial ready at 0.029291, D+ pullup requested at 0.029304.
PID 1 reached at 0.162956; five-second heartbeats through 115.188076.
UDC 11201000.usb reports not attached on every sample. Host observed no ACM.
regulator_ignore_unused is confirmed at 31.712696: Not disabling unused regulators.
STOP_FEED_REQUEST at 90.183383, signal sent and process stopped. Host then
observed fastboot. No USB enumeration or interactive shell was established.

ACK flash/reboot succeeded; final identity/hash in restored-ack-114510a78e1d.txt.

## Next hypothesis from local ACK source

ACK live DT carries mediatek,force-vbus. The vendor mtu3 driver parses it and
ssusb_set_force_vbus() sets VBUS_FRC_EN|VBUS_ON and clears U2_PORT_OTG_SEL
when !keep_ao. Its gadget start calls this helper. Vendor struct documentation
explicitly describes controllers without a VBUS pin. Mainline instead clears
the force bits in mtu3_regs_init and relies on hardware detection. This is a
concrete difference to test, not yet proof of this device's failure cause.
Clock gates, PMIC rail and other PHY differences remain possible contributors.
