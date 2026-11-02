# Attempt22: USB SSH and SFTP

OpenSSH-server/client/sftp and16 total dependency packages installed from
signed index/hash-verified Debian archives. standalone sysusers used, no
systemd init added. dpkg audit clean. sshd -t in arm64 QEMU chroot passed.
New Debian root302e74d308e2 SHA256
509d0efb28bff23c4cfe14e6f2deaf6dac1859ec4e886ffd91a0aa932447f10d.
Final SquashFS extracted, init scripts syntax checked; no host private key
in /etc/ssh or /run/sshd. Dedicated client private key stays host-side
ssh/id_ed25519 (0600 in0700 directory). Public key embedded in rootfs.
Dedicated target host key installed separately cache/mainline/ssh with
root-only permissions; copied into /run/sshd at boot. Client pins public
host key via ssh/known_hosts, StrictHostKeyChecking=yes.

sshd listens192.0.2.2:22 only, publickey-only root login, password and
keyboard-interactive disabled, no forwarding. Root has random unknown
password hash to permit publickey account check without empty password.
Custom BusyBox PID1 retained. devpts gid5/mode0620/ptmxmode0666 and
/dev/ptmx link corrected for PTYs. Kernel seccomp/filter enabled for sshd.
Planned tests: SSH exec, PTY,1MiB SFTP upload/download equality, unchanged
backing image hash, serial/network and watchdog reset.
Hardware results pending.

## Live hardware result

Boot3bba3280fe2d, SHA256
87fc7d01a39a4909e9bc2b95d6b3eae65e434c3d57528223015de23f086fbdf7.
New rootfs56,963,072 bytes (~54.32MiB). Installed via ACK with verified
hash; old image preserved as debian-585e323d099c.squashfs, BusyBox intact.
Key permissions0700 directory/0600 file. Cache synced and unmounted.

USB live exact release/root id and full image hash matched. Kernel CRNG
initialized at5.888s, SSH_READY at5.952s. sshd listens only192.0.2.2:22;
effective config publickey-only and passwords/keyboard-interactive off.
Pinned host key verified by SSH client. SSH exec uname/root id/id passed;
PTY allocated /dev/pts/0 with both input/output terminal checks passing.
SFTP via scp1MiB random upload to /tmp and download matched byte-for-byte:
66a3b5e893d430c758d186b656779640f7ab31a23353552d371ec0c907b2af09.
Remote file removed; transfer remains RAM only. Device SSH logs captured.
Network ping/HTTP, dpkg audit, strace, RAM overlay and serial still pass.

Host ECM bridge now sends zero-length packet after maxpacket-sized frame,
ensuring USB transfer termination; no kernel modules forced.
Added usb-connect.py for persistent host ECM bridge; compilation checked,
standalone wrapper not separately hardware tested. Underlying bridge/SSH
path tested by diagnostics. It does not suppress target600s watchdog
stop schedule; long-lived sessions need that policy changed explicitly.
Observation/reset pending.

All21 live commands passed;45s observation maintained8CPUs/USB. USB
disconnected32.1s after stop request. Host test namespace removed.
Awaiting fastboot interception. No restoration to ACK after test.
