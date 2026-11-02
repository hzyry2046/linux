# Attempt 2: flash boot, 4377cca94e7d

The user explicitly authorized writing boot and manually intercepted the
subsequent boot into fastboot. The test image was
`dist/4377cca94e7d/boot.img`, SHA256
`66d0c09bde50c175a75dd9b3a8b448adaf04aa95a97445d3eabc2b93f82211c7`.
The flash/reboot transcript is `flash-4377cca94e7d.txt`.

Before another kernel booted, fastboot `oem peek` read the entire pstore
reservation 0x48090000..0x4816ffff in checked contiguous 4096-byte requests.
The raw capture, full command replies, header metadata and decoded console
are under `peek-4377cca94e7d/`. 917504 bytes were read; the console contained
69198 bytes with a valid DBGC header at offset 0x8f000 (PA 0x4811f000).

## Positive evidence

- Unique mainline release: `7.3.0-op6893-d1-4377cca94e7d+`.
- The synthesized board FDT was accepted; the machine model is the new
  minimal Realme GT Neo direct-LK board.
- The FIX_FDT mapping BUG from attempt 1 did not recur; the kernel reached
  paging, memory setup, interrupts, timer, initcalls, and userspace.
- PSCIv1.1/SMCCCv1.1, GICv3, and a 13 MHz physical architectural timer were
  reported. The boot CPU entered at EL2. Only one CPU was enabled deliberately.
- ramoops registered and replayed kernel logs using the expected reservation.
- At kernel timestamp 0.160050, PID 1 wrote:

  `OP6893-DIRECT: INITRAMFS_REACHED release=7.3.0-op6893-d1-4377cca94e7d+`

This establishes a working **minimal userspace boot** via LK -> boot partition
-> mainline Image -> built-in initramfs. It does not establish peripheral
support or sustained uptime. No 30-second heartbeat was captured; no cause is
assigned to that absence without another observation.

## Limits / remaining diagnostics

- Kernel reports the LK load address is misaligned (0x40080000 is inherited
  from ACK). The kernel handled it and reached PID 1; do not suppress the
  warning or assume a different load address is accepted without testing.
- No real tty console exists in this minimal configuration, so
  `Warning: unable to open an initial console` is expected. PID 1 writes
  directly to /dev/kmsg after mounting devtmpfs.
- `regulator_ignore_unused` is not recognized with this minimal regulator
  configuration and is passed as an init argument. It had no demonstrated
  effect on reaching PID 1; remove it in a future revision if still unused.
- USB, display, storage, secondary CPU bring-up, and long-run stability were
  not tested. The watchdog state and absence of a later heartbeat remain
  follow-up items.

## Restoration

After raw collection, the original ACK backup was flashed back and rebooted.
See `restore-after-4377cca94e7d.txt`; final ACK identity and partition checksum
are saved in `restored-ack.txt`. No other partition was flashed in this session.
