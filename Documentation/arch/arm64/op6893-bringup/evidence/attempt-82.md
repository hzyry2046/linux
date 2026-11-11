# Attempt82: efuse engine kick, unexpected control change contained

2026-11-03. Image `89780a5bbea6`, release `7.3.0-op6893-d1-89780a5bbea6+`.
Boot SHA256 `0ad58a5c9aa921730fe927ecf08fb4dd90ba8708e70a6ccdfa4cb0c535d6bfb9`.
Queued serial-targeted flash/reboot succeeded. Release, raw boot hash and
initial attempted=0 matched. AI-assisted implementation and documentation;
no external submission or AI DCO.

## Result: incomplete, not a successful engine/cleanup validation

One `adie-efuse-cycle` issued a single fixed address0/read-mode kick to
TOP108, after the stable control baseline and held FM/analog/mailbox setup.
The first ID-separated control read returned public flags `0x20000000`:
kick30=0, valid29=1, address25:16=0, mode7:6=0. However, comparison against
the saved full control word found a change outside bits30/29. The transaction
returned EIO at `adie-efuse-engine-state` before accepting any confirmation.
Neither which additional bits changed nor their meaning is established by
this masked evidence. Do not infer that they are harmless reserved bits.

Cached status: issued1, pending1, complete0, transfers3, polls1, confirmed0,
engine_busy_seen0, spi_busy_count0, elapsed_ns60345231. This elapsed time
includes extensive software guards and is not physical efuse latency.
It did not hit the250ms deadline. A valid bit alone is not accepted as proof
of a successful cycle; the required two confirmations were not reached.

Containment behaved as designed: FM, analog prefix, mailbox, A-die release,
semaphore11 and all outer resources were retained; cleanup_result=-117.
No speculative clear-kick, reset, semaphore release or power-down occurred.
No TOP130/134/138/13c private data reads, thermal trim, calibration or firmware
startup ran. Raw control contents remain internal, with only the existing
public mask exposed. Retry was refused and all nine cached hashes unchanged.
USB SSH remained available; no BUG/Oops/SError/panic appeared in captured log.
This is containment evidence, not a passed cleanup regression.

## Implementation and host validation

New one-shot command and cached root-only `efuse_status` implement a single
kick, ID-separated fresh reads, independent SPI timeout,250ms overall guard
and70-round cap. Completion requires two valid/kick-clear observations;
busy reassertion resets confirmation. Uncertainty retains parents until reboot.

Standalone actual-C/UBSan tests cover67 dropped writes,224 new write faults,
seven SPI timeouts, deadline boundaries (including late confirmation), poll
cap, fast completion, invalid results and30 nonstatus-bit mutations.
Nested tests cover65 dropped writes,56 new write faults,seven SPI timeouts,
masked diagnostics, outer failures and one-shot behavior. Older suites pass.
Full ARM64 build and11 built-in suites, checkpatch, schema/DTB, pin model,
capacity and diff checks passed. Payload7,464,960 bytes leaves26,089,472 bytes.
The hardware result demonstrates that the success model does not yet capture
all control-register behavior; host success does not override this observation.

## Recovery and next step

Recovery to previously verified image `b2d5ede80b81` was queued before asking
for watchdog reset. ACK backup remains unchanged. Recovery confirmed over USB SSH: release and raw boot SHA256 match81,
attempted=0, all dirty/uncertain states zero, CONN off at both preflight
samples, CPUs0–7 online and USB configured. Device remains on mainline81.

Before another kick, establish a minimal diagnostic for changed-bit positions
without publishing raw control/data contents, and compare register semantics
with the vendor implementation. The vendor polls kick then valid and does not
compare all other bits; that difference alone is insufficient to remove our
check. Also review its initial clear-kick write, omitted here because the
sampled baseline was already zero. Do not replay against the retained state.
Private data handling and thermal trim remain separate future steps. Wi-Fi
and independent network SSH remain unavailable and the development priority.

Selected records: [attempt-82](attempt-82/). Full dmesg stays outside Git in
`mt6893-direct/evidence/attempt-82`.
