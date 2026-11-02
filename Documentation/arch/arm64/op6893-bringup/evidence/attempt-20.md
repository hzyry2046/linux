# Attempt20: ACM + ECM success

Boot0952795f3ea3; SHA256
213b287508a2af98a213967d980896fae90a00db1da2d6a96d6e5bbdf0cfef08.
Only boot change from19 moves usb0 addressing after UDC bind, matching
ECM netdev registration lifetime. Composite1d6b:0104 enumerated normally.

Initial host run via ip netns exec couldn't discover libusb device;
lsusb in original namespace confirmed enumeration. Corrected host script
to open USB first, then os.setns via --netns op6893-usb20. This retains
USB discovery while isolating TAP and routes. Retried same running kernel,
no reflash. Live evidence: usb-attempt-20-resume/.

Bidirectional5-packet ping succeeded. HTTP262144-byte zero payload received
exactly; SHA2568a39d2abd3999ab73c34db2476849cddf303ce389b35826850f9a700589b4a90.
Bridge204 RX/127 TX frames at check; no bridge error. ACM commands remain
functional concurrently with ECM traffic. External root888f07f2297f and
full image hash verified, root/cache ro,norecovery; tmpfs writable.
This is a basic data-path test, not throughput/stress or Internet access.
Native host cdc_ether untested due missing matching module. Device provides
standard ECM; no host module loaded or host default routes changed.
Observation/reset pending.

All20 live commands passed. Both ping directions5/5,0% loss.35s
post-check observation kept8CPUs/USB alive. Final dmesg no I/O errors,
WARNING, BUG, panic or EXT4 errors. USB disconnected32.6s after stop
request. Host bridge closed and namespaceop6893-usb20 removed. Device
awaiting fastboot interception; mainline boot and existing cache image
retained. No cache writes occurred during attempts19/20.
