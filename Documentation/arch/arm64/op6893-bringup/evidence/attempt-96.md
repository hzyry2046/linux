# Attempt96: phase-scoped budgets; TOP380/TOP390 write/readback/restore

2026-11-05. AI-assisted. Image `7551df9a01e1`, release
`7.3.0-op6893-d1-7551df9a01e1+`, boot SHA256
`dd03a28481b2e520c5a9a0c8256190e1971947b2f7cdc7f2ae9d1f41de95de5c`.

## Change

1. Data budgets are phase-scoped: prerequisite 2 s from the original start
   (unchanged), pad 2 s, cfg 3 s, cal 3 s, each measured from the phase start,
   plus a hard 8 s total cap that never resets. A stage begins only after the
   previous one succeeded. Status appends `data_phase` and `phase_elapsed_ns`;
   `data_elapsed_ns` remains total elapsed. This replaces the per-command caps
   of attempts 94/95.
2. New one-shot `adie-cal-cycle`: after the pad and cfg reads it requires the
   exact measured baselines TOP380=0xe0002, TOP384=0x8, TOP390=0xe0002,
   TOP394=0x8, otherwise refuses before any write. Then TOP380, then TOP390:
   write 0xe8002 (vendor CAL LDO value), verify with ID/target/ID/CTRL, write
   the measured baseline 0xe0002, verify. Dirty is set before each write and
   cleared only after that register's restore verify; first failure stops,
   retains parents, no retry. TOP384/394 are not written.
   Pad-cycle and cal-cycle share one write+verify helper (refactor; pad-cycle
   outcomes unchanged in tests).
Host: checkpatch 0/0; cal/cfg/pad/pad-cycle suites (37 PASS) in the full chain.

## Hardware result

Result 0, cleanup 0. cal_write_issued/applied/restored=0x3, cal_dirty=0,
cal_transfers=20, no busy pulse sampled, cfg baselines unchanged
(0xe0002/0x8/0xe0002/0x8), total data 2.87 s (phase 4: 0.50 s of 3 s).
All outer cleanup counters complete, no dirty/unsafe flags. Regression and
AP pin diff (only drive 0x0->0x8248) as in attempt95.

## Limits

Register write/readback/restore only; not shown: CAL LDO actually disabled,
analog effect, or that the baseline is the chip reset value. The registers are
restored, not retained for calibration. TOP384/394, TOPA18/A1C, GPIO180 return
and AFE calibration are still untested here. Wi-Fi remains unavailable.
