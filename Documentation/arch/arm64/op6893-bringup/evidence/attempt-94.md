# Attempt94: TOP070 write/readback/restore/readback succeeded

2026-11-05. AI-assisted. Image `001e99b1fbd5`, release
`7.3.0-op6893-d1-001e99b1fbd5+`, boot SHA256
`23fa89fbbab6340b26654a0065c053ef173b05f3f1e68d741d7d77c22c5f3236`.

## Change

Only `adie-pad-cycle` uses a 3 s total data budget
(`OP6893_PAD_CYCLE_DATA_TIMEOUT_NS`); all read-only commands keep 2 s. The
timer start is unchanged and never resets. `adie_pad_cycle_requested` is set
only for that literal command, before the first guard. Host tests cover
2-3 s accepted, >=3 s timeout retaining dirty state, deadline between the two
writes, and the unchanged 2 s timeout for `adie-pad-read`; checkpatch 0/0,
18-suite chain pass.

## Hardware result

Baseline 0x0 (fresh boot after attempt93's unverified write). Result 0,
cleanup 0: pad_write_issued=0x3, applied=1, restored=1, dirty=0,
pad_transfers=18, data_elapsed_ns=2112000538, no busy pulse sampled. Spi/RGU/
remap/SYSRAM restore counters complete, no dirty/unsafe/cleanup flags.
Regression passed as in attempt92; AP pin diff only drive 0x0->0x8248.

## Limits

This proves register write/readback/restore through the SPI path for fixed
values only. It does not show the pad was electrically HighZ, that 0x0 is the
chip's reset value, or that the calibration sequence works. The restore
returns to the measured baseline, not the vendor's post-calibration 0x5.
Wi-Fi remains unavailable.
