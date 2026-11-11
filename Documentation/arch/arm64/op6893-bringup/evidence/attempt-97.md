# Attempt97: TOPA18, TOP384, TOP394 write/readback/restore

2026-11-05. AI-assisted. Image `7b4f9d238ef2`, release
`7.3.0-op6893-d1-7b4f9d238ef2+`, boot SHA256
`b8ba1b40da9d86f14922b7fe36c72976cb828f65e130226653c252ba0c38891a`.

## Change

- `adie-cfg-read` now reads six registers (TOP380/384/390/394, TOPA18, TOPA1C;
  48 transfers, cfg phase budget 4 s) and reports `topa18`/`topa1c`.
- New one-shot `adie-ir-cycle` gated on all six baselines being exactly
  0xe0002, 0x8, 0xe0002, 0x8, 0xf668fff5 (from attempt74) and 0x55555fff.
  In vendor order: TOPA18 <- 0xf6e8fff5 (XOBUF supply; vendor
  `mt6893_pos.c` ~L1241), TOP384 <- 0x2008, TOP394 <- 0x2008 (~L1264-1273),
  each verified with ID/target/ID/CTRL, then restored to the measured
  baseline (0xf668fff5/0x8/0x8) and verified. TOPA1C is not written: its
  baseline equals the vendor E3 value 0x55555fff (the vendor write is a no-op
  on this board). First failure stops and retains parents, no retry.
- Register-cycle logic is now a table-driven helper shared by cal-cycle and
  ir-cycle (pure refactor, cal-cycle tests unchanged). Phase 5 budget 3 s;
  global 8 s cap unchanged.
Host: checkpatch 0/0, new ir suite + full chain pass.

## Hardware result

Result 0, cleanup 0. ir_write_issued/applied/restored=0x7, ir_dirty=0,
ir_transfers=30, no busy pulse sampled, phase-5 time 0.90 s of 3 s, total
4.20 s of the 8 s cap. cfg baselines matched the gate, cfg_target_match=0x20
(only TOPA1C already equals its vendor target). No dirty/unsafe flags; regression
and AP pin diff (only drive 0x0->0x8248) as before.

## Limits

Register write/readback/restore only. The target values are not retained, the
analog effect of XOBUF/IR settings was not measured, and no bit definitions
were found. With attempts 96-97, all fixed-value config writes of the vendor
sequence up to the GPIO180 return have been exercised individually; the
sequence has not been executed as one retained configuration, AFE calibration
has not been attempted, and Wi-Fi remains unavailable.
