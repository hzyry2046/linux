# Attempt65: reversible MCU/peripheral remap transaction

2026-11-03. Physical result: four masked writes/readbacks and all four restorations succeed. Image `e2a490e43787`, release
`7.3.0-op6893-d1-e2a490e43787+`, boot SHA256
`6d0ec7831e6c4888f7238b86b5eb8c7fdd98d028f089f10fa5cff5067fd08ba1`. Based on attempt64 observed
MCU remap0x4000 versus current Linux reservation target0x8fb0, plus three
peripheral remaps0x1100 versus ACK0x1000. No firmware or DMA support claimed.

New explicit remap-cycle under existing domain opt-in and per-boot one-shot
requires validated current reserved memory before consuming attempt/powering
anything. Reuse reset-requested clock checks, dual power ACK/control/host,
AP-to-CONN gate and BOTH expected digital IDs. Old commands are unchanged.

Reuse guarded HOST_CSR mapping. Save all four full original words at offsets
0x1c4/1d4/1d8/1dc before any remap write. MCU target low20 is current
validated EMI base>>16, peripheral target low20 is0x1000. Preserve high12
bits. Do not touch MD share0x1cc or GPS EMI0x1d0. This follows compiled ACK
consys_emi_set_remapping_reg_mt6893() field encoding; no saved physical base.

Check AP/clock/timeout/sleep conditions before every save, write and readback.
Mark each word dirty BEFORE issuing the target write. Verify exact full-word
readback; count only verified targets as applied. Regardless of apply error,
restore dirty words in reverse order with readiness checks and exact readback.
Clear dirty bits only after verified restoration. Count restored words and
preserve original failure_stage separately from remap_cleanup_result.

If any dirty remap remains, skip legacy power-off and idle-pin selection,
retain on-domain resources and both supplies, mark domain cleanup EUCLEAN.
The independent rail cleanup also rejects dirty remaps. A subsequent trigger
is refused until reboot. If targets fail but originals restore successfully,
normal shutdown/rail cleanup proceeds while returning the original error.

Root-only remap_status shows cached saved/applied/restored counts, dirty mask,
cleanup error and four before/target/on/after records. Counts indicate which
words were actually observed; zero/unfilled on/after fields are not evidence.
No hardware access from show. No additional mapping or arbitrary address API.
No reserved-RAM access, MPU change, SYSRAM/RGU/SPI/A-die writes, firmware,
DMA, RF, DEADFEED or wakeup write. MMIO stalls still require watchdog recovery.

Host tests verify30-write success (old22 plus four targets/four restores),
exact target order/reverse restoration, unrelated high-bit preservation,
all four dropped apply writes/readback mismatches, all four dropped restore
writes/readback mismatches, original plus restore errors together, and each
of four readiness failures after each of eight remap writes. Unsafe cleanup
retains domain/pins/rails, maps balance, retries refuse. Invalid memory and
bad ID prevent remap writes. Existing domain/rail/preflight cases still pass.

Full image build and existing11 host suites pass. Extracted integration tests
pass with undefined-behavior sanitizer. C/header checkpatch zero errors/
warnings, schema document and filtered compiled-DTB validation pass. Boot
partition payload and decompression memory-window checks pass. No external
messages or AI Signed-off-by.

## Physical result

Queued serial-targeted boot flash/reboot succeed. SHA256 readback matches
selected image. Initial state attempted0, saved/applied/restored0, dirty0,
actual Linux EMI allocation0x8fb00000/0x450000 valid. Explicit remap-cycle
succeeds after expected HW0x20010101/config3 with:

```
saved=4 applied=4 restored=4 dirty=0 cleanup_result=0
```

| HOST_CSR offset | Before | Target / observed on | After verified restore |
|---|---|---|---|
| 0x1c4 MCU EMI | 0x4000 | 0x8fb0 | 0x4000 |
| 0x1d4 WF peripheral | 0x1100 | 0x1000 | 0x1100 |
| 0x1d8 BT peripheral | 0x1100 | 0x1000 | 0x1100 |
| 0x1dc GPS peripheral | 0x1100 | 0x1000 | 0x1100 |

All full-word target and original readbacks match. No partial/uncertain
remap remains; normal legacy shutdown, idle pin selection and rail cleanup
succeed. Final dual ACK off, control0x12, host0, zero leaf refs/dirty flags,
parent votes1/1 retained. Repeated request refuses EALREADY; cached remap
and protection-trace hashes both unchanged. Device remains on65, CONN off.
The target map was temporary and has been restored; no active firmware map
is left installed. This verifies register programming/restoration only,
not EMI payload access, MPU permission, DMA or firmware execution.

USB configured/SSH, CPU0--7, sdc RO, cache ro/norecovery/root hash, ADC/PMIC
temperature,17 LVTS channels and pin return state pass. No BUG/Oops/SError/
kernel panic in collected dmesg; inherited alignment warning and intentional
GPT discrepancy remain. Selected evidence is archived alongside this report.

Next isolate RGU SYSRAM/coexistence-memory hardware power/sleep policy setup
with saved originals, exact readback and safe restoration. Keep SYSRAM
mailbox/16KiB clearing, D-die efuse copy, SPI/A-die and firmware as separate
ordered stages. Do not advance to loading firmware on remap readback alone.
