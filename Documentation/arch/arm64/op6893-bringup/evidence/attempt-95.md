# Attempt95: TOP380/384/390/394 baselines (read-only)

2026-11-05. AI-assisted. Image `183cfc1cfb87`, release
`7.3.0-op6893-d1-183cfc1cfb87+`, boot SHA256
`3a25720134c005e1d23b4bac6c09f1136190c4cc22efbaf086b050c79bbb6f1d`.

## Change

New one-shot `adie-cfg-read`, after the full chain through the TOP070 read.
It reads TOP380/384/390/394 (read addresses 0xb380/0xb384/0xb390/0xb394, the
same 0xb000 read framing and 0xa000 write framing as TOP070; vendor
`mt6893_pos.c` L1231/1239 write 0xe8002 to TOP380/390 "Disable CAL LDO",
L1268/1275 write 0x2008 to TOP384/394 "WF THADC initial IR") twice each with
ID/target/ID/CTRL, compares rounds, runs the guard once and only then publishes
values. No writes. These are vendor whole-word configuration constants, not
efuse/NVRAM/calibration data. Budget for this command: 4 s (read-only commands
2 s, pad-cycle 3 s), same non-resetting timer. Host: checkpatch 0/0, new cfg
suite plus 18-suite chain pass.

## Hardware result

Result 0, cleanup 0, cfg_transfers=32, cfg_matched=0xf, no busy pulse, no
dirty/unsafe flags, data elapsed 2.364 s of the 4 s cap.

| register | board baseline | vendor target | difference |
|---|---|---|---|
| TOP380 | 0x000e0002 | 0x000e8002 | bit15 |
| TOP384 | 0x00000008 | 0x00002008 | bit13 |
| TOP390 | 0x000e0002 | 0x000e8002 | bit15 |
| TOP394 | 0x00000008 | 0x00002008 | bit13 |

Each register differs from the vendor write by exactly one bit, so the vendor
writes look like set-one-bit updates of a whole-word write; their baselines
are 0 elsewhere. This is an inference; no bit definition was found. Regression
passed as in attempt94; AP pin diff only drive 0x0->0x8248.

## Next

A fixed write/readback/restore of TOP380 and TOP390 (restore the measured
baselines 0xe0002) as separate experiments, TOP384/394 afterwards. The budget
(2.4 s of 4 s here) will need a phase-scoped design before more stages are
chained. Wi-Fi remains unavailable.
