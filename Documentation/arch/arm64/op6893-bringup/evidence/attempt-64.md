# Attempt64: post-ID setup baseline and dynamic EMI allocation

2026-11-03. Physical result: dynamic allocation lookup and13 post-ID reads succeed. Image `acbc438563c6`, release
`7.3.0-op6893-d1-acbc438563c6+`, boot SHA256
`dbf9679a8b41482f7e5a5a85969b224f253598198b2d1949197715394cc0dd65`. Builds on successful digital ID
attempt63. No D-die/SYSRAM/remap initialization or firmware support claimed.

Audit compiled ACK ordering in platform/consys_hw.c: successful chip-ID,
then EMI remap, D-die setup, SPI master, A-die and calibration. D-die setup
copies efuse to SYSRAM+0x2820, optionally writes build mode+0x2838 and writes
RGU0x38/0x3c/0x50/0x54 as0/0xff/0/1. Those writes affect memory power/sleep
policy; do not assume their inverse is safe without actual reset-state data.
This round obtains the baseline before choosing a bounded write transaction.

ACK DT's CONN reservation has size0x450000, alignment1MiB, no-map and
alloc-ranges0x50000000..0x90000000, but no fixed reg. The local FDT importer
copies size/alignment/range/no-map without compatible or original phandle.
Use the board-specific imported path /reserved-memory/consys-reserve-memory
and of_reserved_mem_lookup() to obtain Linux's CURRENT allocated base/size.
Do not parse a missing reg, hardcode an earlier ACK/mainline base, or invent
a phandle. Probe only records metadata; it does not map or touch reserved RAM.

Validate exact size,1MiB alignment and allocation bounds with overflow-safe
subtraction. Absence/invalid allocation does not remove the existing preflight
or ID diagnostics, but rejects post-id-cycle before consuming its one-shot or
powering anything. The reservation is observed, not claimed as a DMA pool;
no allocation, MPU programming, reserved-RAM read/write or remap write occurs.

Explicit post-id-cycle shares existing domain opt-in and one-shot latch. It
runs the tested reset-requested ID path and requires BOTH expected ID words
before reading13 audited4-byte locations: RGU0x18000038/3c/50/54,
SYSRAM0x18052830/34/38 (top-clock control, radio status, build mode), and
HOST_CSR0x180601c4/1cc/1d0/1d4/1d8/1dc (MCU EMI, MD share, GPS EMI,
WF/BT/GPS peripheral remaps). Bases cross-checked with actual ACK DT and enum.
No efuse/calibration source or SYSRAM efuse mailbox is read or printed.

Check AP, clock, timeout and sleep prerequisites before each mapping and
again before each read. Balance every map/unmap, retain partial sample count,
then use unchanged bounded shutdown/rail cleanup. post_id0400 only shows
cached metadata/observations; it never triggers work. No new hardware writes
beyond the already tested clock reset request and21 power/protection writes.
No arbitrary-address interface, wakeup, DEADFEED, firmware, DMA or RF activity.

Host tests retain previous coverage. New success case checks13 ordered words,
15 balanced mappings and unchanged22 writes. Inject each13 mapping failures
and each of four clock/timeout/sleep/AP failures after every mapping; no
subsequent sampled read occurs. Bad ID prevents all post-ID reads, invalid
memory refuses before attempt, repeated trigger refuses, and eight memory
boundary/alignment/size/overflow cases verify the allocation predicate.

Full image build and existing11 host suites pass. Extracted domain/rail/
preflight tests pass with undefined-behavior sanitizer. C/header checkpatch
zero errors/warnings; schema document and filtered DTB checks pass. Boot
payload and known decompression-memory-window capacity checks pass.
No AI Signed-off-by or external messages.

## Physical result

Queued flash/reboot succeeds; selected boot hash matches readback. Initial
probe reports actual Linux allocation base0x8fb00000,size0x450000,emi_valid1,
no attempts, zero samples/votes. No imported fixed reg or historical base
was used. Explicit post-id-cycle returns success with all13 reads, both ID
words correct and normal domain/rail cleanup0. Post-ID snapshot:

| Register group | Observed | ACK setup target |
|---|---|---|
| RGU0x38/3c/50/54 | 0xff / 0 / 1 / 0 | 0 / 0xff / 0 / 1 |
| MCU EMI remap low20 | 0x4000 | 0x8fb0 from THIS Linux allocation |
| MD share / GPS EMI low20 | 0x4000 / 0x4000 | leave untouched in next isolated MCU test |
| WF / BT / GPS peripheral low20 | 0x1100 each | 0x1000 each |

The MCU remap encodes an AP base0x40000000, not current reserved0x8fb00000.
This must be corrected before placing/executing firmware, without assuming
that LK defaults already match the Linux allocation. Peripheral differences
also need an explicit transaction; no remap write occurred here.

SYSRAM three software words contain nonzero uninitialized/retained values.
They must NOT be decoded as active-radio or clock-vote state. Actual ACK
connsys_a_die_cfg_mt6893() at1132 clears the first16KiB with memset_io before
writing its software state; those offsets are inside that region. Preserve
ordering context: its earlier D-die efuse/build-mode stores are also within
that clear range. Do not blindly treat those earlier stores as persistent
mailboxes or initialize just the radio-status word in isolation.

After experiment, CONN/VCN off, no dirty or uncertain flags, zero leaf refs;
shared parent votes1/1 retained. Repeat refuses EALREADY, BOTH cached post-ID
and protection-trace hashes unchanged. USB configured/SSH,8 CPUs, sdc RO,
cache ro/norecovery/root hash, ADC/PMIC temperature and17 LVTS channels pass.
No BUG/Oops/SError/kernel panic in collected log. Device remains on64 with
successful one-shot latched. Raw factory calibration/efuse was not acquired.

## Next bounded write transaction

Implement a separate remap-cycle after verified fresh ID. Save full originals
of MCU EMI and three peripheral remaps before any write. Compute MCU low20
from current validated reserved base>>16, preserving high12; set peripheral
low20 to0x1000 with the same preservation. Leave MD/GPS EMI untouched.
Check readiness around each access, read back every expected full word, then
restore originals in reverse order and verify BEFORE domain shutdown.
Track acquired/dirty state per word, original error versus cleanup error,
and retain supplies/pins if safe restoration cannot be established. Cover
write/readback failures and readiness loss in host fault tests. No reserved
RAM access, MPU change, SYSRAM policy/clear, SPI, A-die, firmware or DMA in
that remap-only experiment. RGU/SYSRAM initialization remains a later step.
