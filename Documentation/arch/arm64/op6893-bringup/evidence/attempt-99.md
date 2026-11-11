# Attempt 99: vendor BT (BlueZ mode) on mainline 7.3

Final image: `f0ce935b727b` (boot.img sha256 `154fa2d28e83fbe48ce8db5c9a77e274a26f6a50879cbbae00e566e1d546f98f`).
Earlier images of this attempt (`958ff6e32eff`, `3cbcd77083ac`, `52786282ba2b`, `f466d5342464`,
`d64f5bfe5810`, `736fbd8d73b9`) are superseded; see per-image notes below.

## Hardware-verified facts

- Vendor conninfra (attempt 98) powers CONN on, repeated on/off cycles pass in pinned mode.
- `btif@1100c000` and `bt@18000000` probe; `hci0` registers (BlueZ mode, `CFG_SUPPORT_BLUEZ=1`).
- Opening `hci0` (`HCIDEVUP`) drives: conninfra BT power-on, `soc3_0_ram_mcu_1a_1_hdr.bin` and
  `soc3_0_ram_bt_1a_1_hdr.bin` download, BT MCU start, WMT power command, `bt_open` complete.
- With firmware embedded in the initramfs (copied to `usr/lib/firmware` of the overlay upper), `hci0` comes up
  automatically at ~2.4 s of boot. HCI Reset and Read Local Version complete with status 0.

## Fixes needed on the way (all source-verified, root causes observed)

- `CONFIG_FW_LOADER` was off: `request_firmware()` returned -EINVAL.
- `CONFIG_BT=y` is required (driver uses hci_core).
- btif/bt DT nodes must match the vendor DTB (clock-names `btifc`/`apdmac`, reg sizes); an earlier copy was wrong.
- btif init waited forever if probe never ran; bounded to 2 s.
- Firmware returns "unknown command" for opcodes 0x0c77/0x0c78 (sync train); `bt_send_frame` completes them
  locally so hci_core init proceeds (workaround, not a fix).
- Initramfs init must not create a real `/lib` in the overlay upper: Debian's `/lib` is a symlink to `usr/lib`;
  image `736fbd8d73b9` did that and booted without sshd/bash (dynamic loader hidden).

## Not verified / negative result

- LE scan (8 s) and BR/EDR inquiry (about 9 s) return zero advertising reports/inquiry responses although every
  control command succeeds. RF path is therefore NOT verified. Candidates (unproven): connfem/antenna
  configuration absent (driver logs `No ConnFem context`, `CONNFEM BTvid/pid == 0`), calibration state, or no
  advertisers in range.
- The BT sync-train workaround, retained rails and pinned CONN power are experimental policies.
