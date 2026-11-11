# Attempt89: both private trim candidates are no-ops at this baseline

2026-11-04 Asia/Shanghai. Image `9c7b04db21e4`, release
`7.3.0-op6893-d1-9c7b04db21e4+`. Boot SHA256
`9c807abca5a8bff161ac5bb39efd816780aa1814820ac0f8cbb158d4b071648d`.
Serial-targeted flash/reboot was queued before requesting mainline88 watchdog
reset. Fastboot capture, flash and boot succeeded. Release/raw boot hash and
attempted0 matched. Device remains on mainline89, recovery backup unchanged.
AI-assisted implementation/tests/docs; no external submission or AI DCO.

## Result

One `adie-thermal-plan` succeeded after repeated private efuse/thermal reads
and verified SYSRAM handoff erasure. The planner uses the second private efuse
word and two repeated thermal baselines to compare literal vendor size+1-bit
input extraction with a width-bounded interpretation. It executes the three
candidate operations in memory, preserving their ordering.

`plan_complete=1 plan_cleared=1 vendor_noop=1 bounded_noop=1 policies_equivalent=1`.
Each sequence preserves the value at every active step, and corresponding
steps agree. This is stronger than matching only the final register values:
a transient write undone by a later operation would fail the no-op test.
No active operations also counts as no-op; validity bits are not published,
so these flags do not distinguish invalid fields from matching programmed
fields. Neither interpretation requires changing TOP034/038 at this sampled
baseline. No trim writes were performed.

This observation permits designing an initialization path that proceeds only
after revalidating no-op conditions on each fresh startup. It does not justify
an unconditional skip, prove calibration is valid/accurate, resolve extra-bit
semantics, or prove a future write can be reversed. Baselines and private
inputs may differ on another boot. A non-no-op must still refuse that path.

Private candidate storage and read buffers were explicitly erased; no raw
values, validity distribution, coefficients or private hashes are exposed.
The final existing access/deadline guard passed before conclusions were made
visible. The total data budget remains2s; elapsed1343797846ns includes private
reads, handoff, thermal reads, planning and guards. Engine elapsed170537923ns,
one kick, three stable controls, delta3b, pending0/complete1. Thermal reads
remain four targets/16 transfers, issuedf/readf/matched3. No additional SPI
transaction was introduced by the in-memory planner.

Result0/cleanup_result0; all FM/analog/mailbox/reset/semaphore and outer
restoration succeeded. Remap/RGU4/4/4, SPI36/36/36, initial SYSRAM4096/4096/4096.
All dirty/unsafe/uncertain flags zero; CONN off at both preflight samples.
VS1/VS2 votes1/1 remain as before. Wi-Fi/independent SSH remain unavailable.

## Validation

Production planner extracted directly and compared with actual vendor code
for262144 relevant-input/baseline synthetic cases, plus a transient-only
counterexample. Tested per-step no-op/equivalence, explicit candidate erasure
and absence of hardware calls. The separate vendor audit also passes its
262144 cases. No device calibration data is used in host tests.

Independent private-read suite and nested parents through88 pass. Planner
integration repeats32 dropped writes,128 guard losses,16 SPI timeouts,two
repeat mismatches,four changed controls,four deadlines,stale/no-busy/zero
responses,15 cleanup faults and one-shot/redaction. Additional post-plan
access/deadline faults confirm retention and suppression of provisional
conclusions even though private candidate storage has already been erased.

The first planner integration fixture mistakenly expected divergent policies
when its synthetic baseline already had the disputed bits set. The fixture
was corrected to clear those bits; production code was unchanged. The final
suite was rerun using the saved same-source thermal parent C model; the final
image was rebuilt so its manifest contains the corrected fixture. Unflashed
intermediate image `84410ec26920` remains only a build artifact. Focused
runner/model and initial failure log stay outside Git.

Full ARM64 build/11 built-in suites, zero-error/zero-warning checkpatch,
binding/DTB validation, pin model and diff checks pass. Payload
7,469,056 bytes leaves26,085,376 bytes in32MiB boot.

USB SSH/configured, CPUs0–7, disk read-only/cache ro+norecovery, Debian hash,
battery ADC/PMIC temperature and17 LVTS samples pass. Pin-register change is
limited to established shared drive0→8248. Retry refused; all nine status
hashes unchanged. No BUG/Oops/SError/panic in captured log.
Selected records: [attempt-89](attempt-89/); full dmesg stays outside Git.

## Next boundary

Make the observed no-op condition an explicit, freshly evaluated prerequisite
for subsequent initialization; never substitute a constant based on this run.
Next audit the vendor steps following thermal calibration and their ownership,
while privately retaining only the software coefficients/lifetime needed by
later consumers. Existing diagnostic handoff erases SYSRAM before cleanup;
firmware-lifetime handoff still needs separate integration. Non-no-op trim
remains unsupported until write semantics and recovery are established.
