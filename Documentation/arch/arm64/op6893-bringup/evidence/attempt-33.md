# Attempt33: dedicated MT6885 register/type description

Status: flashed and booted successfully; hardware regression passed.
Device left running mainline; no further reset requested. Final boot b83ff1cd5a1f, SHA256
394e053a159467b97d605b12ef29306ab06d129d8c018fdc78ab3c8733981a2b.
Rollback ea6328ee080d; Debian9825862f46b0 unchanged. Initial artifact
 afe2c2cf4567 had an enum-switch compiler warning, was not flashed; fixed by
explicit unsupported MT6885 cipher case and early legacy-init rejection.

New MT6885 enum/type/table replaces the MT6873 data alias. Ten offsets
match ACK, including group3 enable/flags/clear. No inferred WDT source
register or generic init callback/mask is populated. Probe dispatches by
type to the board/build-gated LK handoff; pwrap_init rejects MT6885 before
reset/programming. Other SoC data remain unchanged.

Low-level read/write helpers check sparse holes and out-of-range indices
for MT6885 only. INIT_DONE remains valid at zero; unsupported access warns
and avoids MMIO (read returns all-ones; write does nothing). This is a
programming-error guard, not a full errno-bearing register-access API.
Runtime regmap failures retain original errno and emit rate-limited register,
status and IRQ flag diagnostics; the diagnostic code reads status only, adds
no retries/clears and does not claim error recovery. Existing transport
VLDCLR recovery behavior is unchanged. Wrapper error IRQ still unclaimed,
no source unmasking, no arbitrary PMIC writes or live error injection.

New host test extracts actual table/accessor/regmap callback code, compiles
with ASan+UBSan and fake MMIO/transaction/log backends. Verifies all ten ACK
offsets, holes/negative/beyond-table indices, invalid WDT writes preserving
INIT_DONE, successful callback behavior, timeout errno preservation and
read-only diagnostic accesses, plus MT6873 valid-access/error behavior.
Simulated logs do not test kernel rate limiting, timing or physical recovery.
Build.py now hashes/runs this test and preserves pwrap-tests.log in dist.

Binding adds MT6885 two-bank/four-clock layout with compatible-specific
constraints retaining legacy names for other variants. Driver and binding
incremental checkpatch each0errors/0warnings; final compiler no warnings;
host FDT/packing/PMIF tests pass. pwrap dt_binding_check including existing
example and YAML lint pass; actual board DTB pwrap-node validation passes.
This is scoped schema validation, not complete board validation.

Hardware checks passed: PMIF16read pairs (0x5920/0x5aa5),four26MHz clock
references,8CPUs,USB SSH,UFS root checksum,readonly cache,PMIC key device
registration. Parent and four nested PMIC IRQ counts remain0 across15s idle;
seven clock/PMIF registers unchanged from attempt32. No register-guard WARN,
BUG/Oops/Call trace observed; devices_deferred empty. Feeder alive and uptime
73s at final observation. Existing console/UFS reset/GPT/unbound MFD child
messages remain unchanged. No physical key test repeated
this attempt; attempt32 contains the latest physical press/release evidence.
No GPT or root image modifications; ACK recovery remains original
 evidence/ack-boot.img. Generated with Codex assistance; no commits/signoffs.
