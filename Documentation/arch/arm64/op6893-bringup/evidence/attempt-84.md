# Attempt84: three stable control observations, resources deliberately retained

2026-11-03. Image `e246cd7f80f4`, release `7.3.0-op6893-d1-e246cd7f80f4+`.
Boot SHA256 `3e4771d2bdac9f99085da754bc004d7d25eebc035a8dc9c9218b9366485c4f63`.
Queued serial-targeted flash/reboot succeeded; release/raw boot hash and
initial attempted0 matched. AI-assisted implementation, tests and docs.
No external submission or AI DCO.

## Observed result

One `adie-efuse-observe` issued a single address0/read-mode kick, followed by
three ID/CTRL pairs. All three nonstatus difference masks were **0x3b**.
Each full control response was equal to the others internally; each had
kick0/valid1, mode0/address0 and no changes above bit5 other than valid29.
The original and resulting low-six-bit values were not published. This is
three fresh, guarded observations in one boot, not three independent kicks.

Status: issued1, pending1, complete0, transfers7, polls3, confirmed0,
observe1, observed3, stable1. No engine or SPI busy pulse sampled; transport
freshness uses each ID-separated RDAT change. elapsed_ns170531000 is below
the250ms diagnostic deadline and includes guard overhead, not physical efuse
latency. Initial control baseline had kick/valid/mode/address zero.

As designed, the command returned EUCLEAN (-117), stage
`adie-efuse-observe-held`. Stable observation does not grant completion or
cleanup: all parents, FM, analog prefix, mailbox and semaphore11 stay held.
No private data registers, thermal trim, calibration or firmware startup.
The existing `adie-efuse-cycle` strict equality rule remains unchanged.

Retry refused; nine cached status hashes unchanged. USB SSH/configured,
CPUs0–7, read-only disk/cache and Debian image hash passed. No BUG/Oops/SError/
panic in captured log. ACK backup unchanged. Recovery to81 queued before
reset and confirmed: release/raw boot hash match, attempted0, all dirty/
uncertain states zero, CONN off at both samples, CPUs0–7 and USB configured.
Device remains on stable mainline81.

## Implementation and tests

Separate command observes at most three pairs within the existing deadline.
High-bit changes, busy/invalid response or low-bit drift stop immediately.
Delta0..2 and observed count include an inspected rejected sample; stable
requires all three accepted observations. Late third responses cannot set it.
Even three unchanged controls retain resources in this mode. Cached status
reads do not add MMIO. No additional control writes or kick retries.

Standalone actual-C/UBSan tests cover12 new dropped writes,192 write-time
faults,seven SPI timeouts,72 high-bit mutations across three samples,12
low-bit drifts,six kick/valid faults,late deadline,zero-change retention and
stale prerequisite refusal. Nested tests cover12 dropped writes,48 write
faults,the same response/deadline cases,masked status,one-shot and explicit
no-FM-restore/no-semaphore-release assertions. Earlier engine and parent
suites pass. A test-generator placeholder typo was corrected before final
validation; production acceptance/containment was not weakened to pass tests.

Full ARM64 build and11 built-in suites,checkpatch zero errors/warnings,
binding/DTB validation,pin model,capacity and diff checks passed.
Payload7,464,960 bytes leaves26,089,472 bytes in32MiB boot.

## Interpretation and next experiment

The low-six-bit delta agrees with83 and is stable across three responses.
This supports treating it as a candidate result field, consistent with the
other-chip AOUT definitions discussed in83, but does not establish MT6635
field semantics or fuse-data validity. Vendor MT6893 completion relies on
kick/valid rather than full control equality; our full equality gate is
stricter and rejects this observed behavior.

Next design a separate, explicit experimental completion rule: retain strict
comparison for all other nonstatus bits, require repeated kick0/valid1 and
stable low-six-bit state, then test the existing FM/analog/outer cleanup.
Document any low-six-bit exception as an empirical rule for this E3 device,
not a generic MT6635 specification. Do not restore the control word, replay a
kick, read private data or mix thermal trim into the cleanup experiment.
Wi-Fi and its independent SSH path are still unavailable.

Selected records: [attempt-84](attempt-84/). Full dmesg stays outside Git.
