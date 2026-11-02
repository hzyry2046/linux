# Attempt 8: scoped force-VBUS diagnostic

Image dist/3f3718c9b6b2/boot.img
SHA256 e03427b8f92891745b0efd333f7ea324f8f1415ad9369537258f994608cd7749
Only changed build input versus attempt 7: drivers/usb/mtu3/mtu3_core.c.
In mtu3_start after CSR init, CONFIG_ARM64_OP6893_BRINGUP + matching board
+ peripheral-only mode enables VBUS_FRC_EN|VBUS_ON and clears U2 OTG_SEL,
matching the relevant ACK helper operations. Register readbacks logged.
Diagnostic only, not a proposed generic upstream binding/driver solution.
Timed stop of feeder and init unchanged. Build/FDT/packaging/checkpatch passed.
Pre-test ACK hash verified; raw pstore captured; boot flashed and rebooted.
## Hardware result

Host enumerated 0525:a4a7, Gadget Serial v2.4, with the exact new kernel release
in its manufacturer string. User independently reported enumeration.
Host running kernel 7.2.11 lacked its cdc_acm module (installed modules were for
7.2.14), so no ttyACM was created. No host module was force-loaded.
Using existing PyUSB/libusb with sudo, claimed ACM interfaces, asserted DTR/RTS,
and exchanged data on bulk OUT 0x01 / IN 0x81. Shell returned:
Linux (none) 7.3.0-op6893-d1-3f3718c9b6b2+ ... aarch64 GNU/Linux
/proc/uptime: 74.40 74.23
USB_SHELL_CONFIRMED
Transcript: serial-3f3718c9b6b2.txt. The first command sent during configuration
was not observed executing; a later command after the prompt succeeded.

Shell has a cttyhack warning and no job control; interactive command execution
works but controlling-terminal setup needs repair separately.

Fresh fastboot raw pstore: peek-3f3718c9b6b2/. UDC reaches configured and remains
configured through 115.186819 seconds; last heartbeat at 115.186704.
STOP_FEED_REQUEST at 90.182023; signal sent and worker stopped. Host detected
fastboot after the timed test; capture preceded ACK restoration.

Only kernel input delta from failed-attachment attempt 7 is the scoped
force-VBUS code. This verifies the workaround for this experimental peripheral
configuration, not general role switching, unplug behavior, proper clock/PMIC
control, long-term stability, or an upstream-quality platform implementation.

ACK flash/reboot succeeded; final identity/hash saved in
restored-ack-3f3718c9b6b2.txt after verification.
