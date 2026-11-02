# Attempt19: composite ACM + ECM USB networking

Existing external BusyBox image888f07f2297f retained unchanged. Enable NET,
INET and configfs ACM+ECM, replacing standalone g_serial. Initramfs builds
composite before root selection; persists through switch_root. Fixed local
MACs02:68:93:00:00:01/02, device192.0.2.2/30, host192.0.2.1/30.
No DHCP, default gateway, host routing change or external exposure.

Host running7.2.11 lacks matching cdc_ether module (installed modules7.2.14).
Use PyUSB ECM-to-TAP in dedicated op6893-usb19 netns; never force modules.
Serial endpoints discovered from descriptors. Planned test: bidirectional
5-packet ping,262144-byte HTTP download/hash, external-root checks, then
watchdog reset. User-space bridge validates transport, not native host
cdc_ether performance. Host namespace removed after test.
Results pending.

Image5bae05a9892c built and flashed, but no USB enumeration within40s.
Static inspection found definite setup ordering bug: ifconfig usb0 ran
before binding UDC, while f_ecm registers netdev in ecm_bind. With set-e,
this prevents reaching UDC bind. Moved interface addressing after bind.
This diagnosis is from source; target pstore not yet captured. Namespace
op6893-usb19 removed. No target rootfs/cache changes. Await manual reset.
