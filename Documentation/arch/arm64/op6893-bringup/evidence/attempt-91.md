# Attempt91: fixed TOP070 apply/readback/restore experiment prepared

2026-11-04 Asia/Shanghai. AI-assisted audit, implementation and tests.
Image `8b6652fe2067`, release `7.3.0-op6893-d1-8b6652fe2067+`.
Boot SHA256 `cb4606b92114987e5da67d6376431879f8f052afd4cca2ab3cb9dc056a5c68b0`.

## Current state

**Superseded:** hardware ran as image b3b211622901 (same code); the cycle refused because the baseline was not 0x5. See attempts 92-94.

**(Original text follows.) Hardware validation pending.** Before reset, native SSH confirmed attempt90
release and its cached successful read-only pad result. A serial-targeted
flash-boot then reboot worker was queued for IF7HHUAUVSHIGMJR, followed by
an expected-release-checked watchdog reset request. USB disappeared; the
worker is still waiting for fastboot. No flash or new-kernel execution is
claimed here. No ACK restore or backup replacement was performed.

The first local build `e65ae4f35006` was superseded by `8b6652fe2067` after
correcting a stale source comment; neither image has yet been flashed.
The ACK backup remains SHA256
`455ed6cea037d6d6bd9af328d589ab39b8692edd4db2c3924e1f8da7b4722c88`.

## Change and boundary

See [pad audit](../PAD-CYCLE-AUDIT.md) for source provenance and limitations.
MT6983's ADIE_6635 branch supplies additional evidence for the public pair
80000000/5, describing the second as initial-value restoration; it is not a
bit specification or proof that the current board baseline is5.

`adie-pad-cycle` requires the fresh trim no-op gate and repeated TOP070
baseline equal to5. It then writes80000000, verifies with ID/target/ID/CTRL,
writes5 and verifies again before clearing dirty. Ten extra SPI transfers,
18 pad-stage transfers total, unchanged2s shared data budget. Unsupported
baseline refuses before any pad write. Any failure retains parents without
speculative analog recovery. The original `adie-pad-read` remains read-only.

There is no firmware startup, retained pad configuration, AFE calibration,
Wi-Fi connectivity or electrical HighZ measurement in this change.

## Host validation

- Full ARM64 build and11 built-in build suites pass. Checkpatch reports zero
  errors/warnings. DTB binding validation, pin model, capacity and diff checks
  pass. Payload7,469,056 bytes, free26,085,376 bytes in32MiB boot.
- All predecessor suites through attempt90 execute and pass in
  `integration.log`. The initial full-chain invocation then fails in the new
  test's total-transfer assertion:90 omitted six parent-cleanup transfers.
  It was already running with its old in-memory test when the source was
  corrected. This invocation is **not** recorded as a full-chain pass.
- Corrected new suite executes separately with actual extracted C and UBSan:
  fixed-baseline and fresh-no-op refusal,20 dropped writes,80 guard faults,
  ten SPI timeouts,two read mismatches,two deadlines,two changed controls,
  15 cleanup faults,no-busy success,one-shot refusal and erasure all pass.
  Its inherited model generation suppresses ancestor executions; those
  skipped calls are not counted as passes. Ancestors were executed above.
- Initial focused bring-up also caught the missing new command in the
  dispatch allowlist; this was fixed before the full-chain run and builds.
  The final artifact archives the corrected command and96-transfer test.

Full records and prepared runtime collector/verifier are under
`/data/src/mainline/mt6893-direct/evidence/attempt-91` and adjacent scripts.
Selected source audit and host logs are in [attempt-91](attempt-91/).

## Resume

Allow the already queued single flash/reboot worker to finish; do not start
a competing fastboot client. Verify the new release, raw boot SHA and
attempted0, capture AP pins, invoke one `adie-pad-cycle`, capture cleanup and
regression, then run the prepared verifier only if the cycle succeeded.
A baseline refusal or timeout must be documented separately, not forced
through the success verifier or retried in the same boot.
