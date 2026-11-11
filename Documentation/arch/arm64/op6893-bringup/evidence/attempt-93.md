# Attempt93: restore the measured baseline; deadline refused the cycle

2026-11-05. AI-assisted. Image `451b0bd2e165`, boot SHA256
`a164fc38df81f3aff68a34d19ea424c75bb8d67e741953913a52ec4bcc4e1760`.

## Change

`adie-pad-cycle` gate and restore value changed from 0x5 to the measured
baseline 0x0 (step0 writes/verifies 0x80000000, step1 writes/verifies 0x0).
Freshness of a legitimate zero readback was audited: it is accepted only if
RDAT changed relative to the preceding ID read or the engine busy was
observed; a stale readback is rejected (new tests). Host: checkpatch 0/0,
18-suite chain pass.

## Hardware result: refused by the shared 2 s data deadline

Baseline gate passed (0x0), first write issued, then `-ETIMEDOUT` at
`adie-efuse-data-deadline`: data_elapsed_ns=2003770077, pad_transfers=13,
pad_write_issued=0x1, applied=0, restored=0, dirty=1. Parents retained
(`cleanup_result=-117`) as designed; no retry. About 48 ms/transfer: the
earlier stages take ~1.6-1.9 s and the cycle adds ten transfers. TOP070's
state after this attempt was unverified; the next boot re-read it as 0x0.
