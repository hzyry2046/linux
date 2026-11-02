# Attempt16: ext4 cache read-only mount

Kernel delta from7508d9e5a04c: enable CONFIG_EXT4_FS only.
Host script repeats UFS reads, marks all sd disks/partitions read-only,
mounts cache by PARTNAME at /tmp/cache-ro with ro,noload,nosuid,nodev,noexec,
records mounts, directory and free space, unmounts and compares first4MiB
against pre-mount bytes. No filesystem repair, data writes or formatting.
User confirmed GPT mismatch intentional for disabling GenieZone/preserving
EL2; preserve this layout and do not auto-repair.
Hardware results pending.

## Hardware result

Image9e0389e05f3e, release7.3.0-op6893-d1-9e0389e05f3e+
SHA256 dc9caa0fa74b997d6d387c395a2bbaf0266169ec207f469b62f9b1e28d83c438.
Build/FDT/package checks passed; no build warning/error matches.
USB confirms matching release. UFS read hashes match attempt15.
Cache enumerated as /dev/sdc55 this boot (previously sdb55); PARTNAME
lookup correctly handles enumeration order. Actual mount options:
ro,nosuid,nodev,noexec,relatime,norecovery. Kernel confirms mounted ro
without journal; UUID df37e030-a3a5-4d2d-bf53-e85cf43a7e4d.

df -k: total412104KiB, used1176KiB, available397664KiB (388.34375MiB).
Top-level contains backup, backup_stage, fota, lost+found, recovery,
USER-NAME, sui.log, sui.log.lck, twrplog.txt. No mainline directory yet.
A300MiB fully allocated file leaves about88MiB of current available
space, before additional directory/metadata overhead.
Unmount succeeded; explicit4MiB re-read matched pre-mount bytes with cmp.
This validates the sampled region only, not a whole-partition hash.
No cache writes/repair performed. Next step is a host-built rootfs image
and small initramfs loop/switch_root path with diagnostic fallback.

All28 live commands returned0.30s observation completed; final dmesg
had no I/O error, WARNING, BUG, kernel panic or EXT4-fs error matches.
USB disconnected32s after stop-feeding request. Awaiting fastboot
interception; no ACK restoration performed.
