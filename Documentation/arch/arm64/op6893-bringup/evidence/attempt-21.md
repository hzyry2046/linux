# Attempt21: Debian arm64 SquashFS + RAM overlay

Built Debian13/trixie minbase with network/diagnostic tools from verified
signed archive metadata. Host local debootstrap1.0.141, keyring2025.1.
Downloads needed curl/range retries; package hashes verified. Stage2
executed using qemu-aarch64 binfmt; finished successfully. dpkg audit
empty, glibc2.41, iproute2, curl and strace version checks passed.

Rootfsdebian-585e323d099c, approx50.87MiB SquashFS xz.
SHA256a9506fabf3c854068883c593db1007632a2597289732f1f54a1ab4762d0319ad.
Extracted final SquashFS with unsquashfs and repeated arm64 chroot identity,
glibc and dpkg audit checks. Custom BusyBox PID1 retains watchdog; shell
Debian bash. No systemd, SSH or internet routing yet.

Kernel adds SquashFS/XZ, OverlayFS, tmpfs xattrs and UNIX98 PTYs.
Loader selects debian.squashfs if present, verifies pinned hash, mounts
readonly loop/SquashFS lower and512MiB tmpfs upper/work. Move backing
mount tree to /run before switch_root. Missing Debian falls back to
previous BusyBox file; invalid hash/preparation to initramfs shell.
Install Debian alongside original32MiB BusyBox image, not overwrite it.
Hardware results pending.

## Hardware results

Boot963f3926cad1 SHA256
1bf88192532c47b6325f309c1b57b1e0a422d5f375228dede3b996c73efee6f0.
Build/FDT/package checks passed, no compiler warnings/errors. Installed
Debian image through ACK, hash verified, BusyBox image unchanged, cache
synced/unmounted. Installation transcripts saved.

Initial live run falsely rejected correct release because bash bracketed
paste escape prefix appeared before uname output. Host now strips ANSI
CSI sequences for parsing; raw serial.bin retained. Retried same running
kernel with --resume. usb-attempt-21-resume/ contains actual validation.

Debian13/trixie arm64,119 packages; dpkg audit output empty. glibc2.41,
bash5.2.37, iproute2 and curl work. strace actually traced /usr/bin/true.
PID1 remains custom BusyBox; not systemd. Root overlay rw; /run512MiB
tmpfs; /run/lower SquashFS ro; /run/cache ext4 ro,norecovery. /etc probe
appeared in /run/upper/etc only, absent from lower, then removed. Full
53,342,208-byte backing image SHA256 still matches pinned value.

USB ECM bidirectional5-packet ping,0% loss; HTTP262144 bytes exact data.
ACM bash works concurrently. No Internet/NAT, SSH, persistence or full
service-manager support claimed. Current known limitation: devpts default
ptmxmode000; no SSH PTY setup yet. Observation/reset results pending.

All19 live commands in resumed capture passed.45s observation retained
8CPUs and configured USB. Final dmesg no I/O error, WARNING, BUG, kernel
panic, EXT4 or SquashFS error matches. USB disconnected30.25s after
stop-feeding request. Host namespace removed. Awaiting user fastboot
interception. Device boot963f3926cad1 and both external images retained.
