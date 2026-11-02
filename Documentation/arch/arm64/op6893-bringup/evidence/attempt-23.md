# Attempt23: native host USB drivers after host reboot

Host now7.2.14-arch1-1 with matching modules. modprobe cdc_acm and
cdc_ether succeeded (usbnet/mii dependencies). No target image changes;
booted existing3bba3280fe2d from fastboot. Native bindings:
/dev/ttyACM0 (stable by-id op6893-direct-if00), cdc_acm interfaces0/1;
enp0s20f0u1i2, cdc_ether interfaces2/3, MAC02:68:93:00:00:01.

Native ACM read/write confirmed exact release, Debian id and8CPUs.
Initial serial stream included a bash history-expansion error from pending
input, but explicit framed test command completed and output verified.
No PyUSB device claims or detaches. Moved native netdev into dedicated
op6893-native netns,192.0.2.1/30; no host default route changes.
Bidirectional ping3/3, SSH exec and PTY verified.1MiB random SFTP upload/
download matched byte-for-byte; remote RAM test file removed. Captures
in attempt-23-native/. Device remains running; did not request reset.
Native interface/namespace left ready for use. Added ssh-native.sh helper.
Current600s target stop-feeding timer remains active. This test does not
change it or imply long-lived operation is configured.
