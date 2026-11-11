# Attempt92: TOP070 baseline exposed (read-only)

2026-11-05. AI-assisted source change, tests and hardware run. Image
`9cf34867094a`, release `7.3.0-op6893-d1-9cf34867094a+`, boot SHA256
`fb486a59725618a83b3d7fd429d8ff767249266bc879386cc257b6231b6971e8`.

## Why

Attempt91's image (`b3b211622901`, a rebuild of the same code as
`8b6652fe2067`; only docs differed) was flashed and `adie-pad-cycle` refused
at `adie-pad-baseline-prerequisite` (`pad_baseline_supported=0`, no pad write,
`cleanup_result=-117`, parents retained until reset). The kernel did not print
the actual baseline, so the cause was unknown.

## Change

`adie_pad_value`/`adie_pad_value_valid` are set only after both TOP070 reads
matched and the final guard passed, and are reported as
`pad_value_valid=%u pad_value=%#x`. TOP070 is a pad-control word, not efuse,
NVRAM or calibration data. No new writes, transfers or control-flow change.

## Result

`adie-pad-read`: two matching reads, `pad_value_valid=1 pad_value=0x0`,
`pad_target_match=0`, complete, cleanup_result 0, no dirty/unsafe flags. The
public pair 0x80000000/0x5 assumed by attempt91 does not describe this board's
baseline (0x0 here). Regression passed (CONN off, CPU0-7, ro storage, Debian
hash, USB configured, 17 LVTS, retry refused, nine status hashes unchanged,
no BUG/Oops); only AP pin difference was drive 0x0->0x8248.
Host: checkpatch 0/0, focused and full 18-suite chain pass.
