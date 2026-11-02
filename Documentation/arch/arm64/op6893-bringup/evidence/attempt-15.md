# Attempt 15: UFS enumeration and repeated cache reads

Image: dist/7508d9e5a04c/boot.img
Release: 7.3.0-op6893-d1-7508d9e5a04c+
SHA256: 69e33be79bc895da44682653a7c4043b77a0a4343385a2c2d9ee4b74d470e2d0
Only kernel-source change from attempt14: mediatek,ufs-disable-mcq
applies existing UFSHCD_QUIRK_BROKEN_LSDBS_CAP. No UFS core edits.
Flash and reboot succeeded; transcript attempt-15-flash.txt.

Live USB usb-attempt-15/ confirms exact release, eight online CPUs and
successful UFS probe. SAMSUNG KLUEG8UHDB-C2D1 revision1903 enumerated,
three normal LUNs: two4MiB and one256GB (62480384 x4096 bytes).
This boot maps main LUN to sdb; names must never be hardcoded.
GPT identifies cache as sdb55, PARTUUID c09b7bd1-5e46-450c-97d5-adf4072a8d6b,
452984832 bytes (432MiB). All enumerated sd block devices and partitions
were set read-only and their ro flags verified before explicit reads.

Three 4MiB cache-head reads, dropping page cache between reads, each
returned the exact requested length and SHA256:
3dc7a511b4e62023e3cd3dbbf9249667f060fb97fe40db5ed9d52746ba9f3263
Superblock bytes show ext magic0xef53 and last-mounted path /cache.
No filesystem mounted; no filesystem/data writes, discard or fsck issued.
This is a short read test, not full-storage integrity or sustained stress.

GPT reports partition_entry_array_crc32 mismatch:
0xf53247a2 != 0xf502c1ec. EXACT same warning/values already appear in
pre-mainline evidence/ack-dmesg.txt and evidence/before-test/dmesg.txt.
Thus not a newly observed partition-table change from this experiment.
No GPT repair attempted, respecting user's partition-table constraint.

Remaining milestone: enable ext4, mount cache read-only without journal
replay, inspect directory/free space, then plan external rootfs file.
LK-inherited clocks/rails/PHY still experimental; no PM support claim.

All25 live commands succeeded.45s observation passed with eight CPUs
online and USB configured. Final dmesg has no I/O error, WARNING, BUG,
panic or abort matches. Stop-feeding request succeeded; USB disconnected
31s later. Awaiting user fastboot interception; ACK not restored.
