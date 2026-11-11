# Attempt56: reverse-engineering review and offline NVRAM preparation

2026-11-03. User has restored ACK; device confirmed
6.6.30-4k-g6974e26f087e #66. Boot partition hash matches selected restore image.
No flash, reboot, module insertion, NVRAM delivery or calibration trigger.
Latest tested mainline remains attempt54 d873de3b8963; no kernel code changed.

Received /home/hzyry2046/src/conninfra-rev/REPORT.md. Original directory is
unchanged; report/manifest/readme archived outside Git under
/data/src/mainline/mt6893-direct/evidence/wifi-re/. No proprietary binaries or
raw factory data imported into kernel Git. Reviewed input hashes recorded.
All12 prior binary-manifest entries match mikuui inputs and RE source copies.

See [reviewed integration](../WIFI-INITIALIZATION.md), which supersedes the
report's framing and UART BT-container statements. Key corrections:
- WR-BUF:NVRAM is12 ASCII bytes with NO NUL; no extra zero padding.
- ACK BTIF strips48-byte EMI header, not UART's30-byte patch header.
- BTIF EMI address takes middle2bytes; BT low byte0x11 is not an offset.
-43us is log-entry to callback-registration difference, not write-return delay.

Fresh ACK record read into host memory matches RE hash; marker/checksum pass.
Prepared frame exactly6156bytes, handler bytes equal file[:-2], OPLUS version2
preserved. No raw record or frame saved. New host preparation tool has no
submission path.12 synthetic protocol/file-boundary tests pass. Original
parser's head16 exposes MAC despite redacted MAC field, so its device JSON
was not copied into Git. Curated evidence contains metadata only.

Evidence: ACK identity, input hashes, framing/BT object disassembly,
BTIF parsed offsets and bounds, live record metadata, host-test output.
An attempted lookup of /vendor/lib/modules/bt_drv_6893.ko failed; saved ACK
object confirms compiled path, but exact live module-file identity was not
established. Current dmesg had no selected BT download lines; old successful
calibration evidence is from RE report, not a newly executed test.

Remaining: real rail/voter/pinmux ownership and bounded CONN power/ID before
firmware/DMA/calibration. Keep genuine BT callbacks. No mainline Wi-Fi success
claimed. Device left in ACK; support inventory distinguishes current state
from the last tested mainline image.
