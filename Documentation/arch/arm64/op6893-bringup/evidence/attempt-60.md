# Attempt60: bounded CONN domain cycle and guarded digital ID

2026-11-03. Image `f69280004fb4`, release
`7.3.0-op6893-d1-f69280004fb4+`, boot SHA256
`f7aa586cd96fc537524143e105af6b554986e38da9975fc4a534b36d3b1f3b58`.
Rollback mainline image `d46fc22c1b0c`; ACK recovery unchanged.
First image physically tested, then snapshot-only follow-up image
`6346689c1150`, release `7.3.0-op6893-d1-6346689c1150+`, boot SHA256
`0bfda93ecdf7cf1fb5f5a78ceaf15cf0e457df4f4cad3a87edd6c146139518db`.
Device remains on the follow-up image after successful shutdown/rail cleanup.
Digital identification is NOT yet successful.

## Explicit transaction

Existing root-only `rail_cycle` accepts `domain-cycle` as an alternative to
`rc-cycle`; both share a single per-boot attempt and mutex. A second board
opt-in enables the domain experiment. Boot/probe only acquires resources;
it does not enable supplies, select pins or map CONN MMIO. Custom pinctrl
names `conn-active` and `conn-idle` avoid driver-core automatic selection
of default/init/sleep states. GPIO155 is excluded from both states.

Keep the tested common-rail setup, baseline predicates and lifetime shared
parent votes. Once both VCN references and enable acknowledgements exist,
require inherited protection bit14/bank2 bit2 before selecting active pins.
Then perform the compiled ACK wrapper and legacy PG_CONN sequence: masked
SPM unlock, host-clock request bit0, PG unlock, primary and secondary power
requests, dual ACK, clock-disable clear, isolation clear, reset release,
protection release bit14, bank2 bit2, bit13. Preserve unrelated register bits.
Protection SET/CLR uses exact writes. Unlike ACK, each release is polled.
Every poll has a20ms deadline; dual power ACK shares one deadline and rejects
mixed states. Preserve the ACK6ms XO settling interval, without claiming a
physical clock measurement.

## Digital access and shutdown

Require both power ACKs, control low bits0x0d, all three protection bits clear,
and host request enabled before mapping the host CSR word0x18060184. Poll
sleep-protection bit5 clear, recheck AP prerequisites, then map just8bytes
at0x18001000 and read HW version/configuration ID. Expected0x20010101/3.
These addresses/offsets come from actual ACK DT, enum and polling source.
Do not call vendor polling_chipid wholesale: its later DEADFEED write is
intentionally absent. No CONN writes, firmware, DMA, EMI or calibration.
Finite software polls do not make a stalled MMIO transaction recoverable;
AP watchdog remains the recovery path if a hardware access hangs.

After the ID attempt, run exact legacy shutdown protection set order13,14,
bank2 bit2, polling each, then isolation/clock-disable/reset/power-request
order and dual off ACK. Clear host-clock request only after verified off.
Select idle pins next, then run tested reverse rail cleanup and final baseline
check. Shutdown leaves all legacy protection bits set; cold-boot bit13 was
clear. This deliberate difference is the completed vendor shutdown state,
not byte-for-byte restoration of inherited protection registers. Active
drive fields remain after idle selection, matching the vendor off routine.

If requests/control writes or power-on ACK fail, leave isolation/reset as
far as completed and retain supplies and pins without speculative rollback.
After a confirmed on state, a protection-release or ID error attempts bounded
normal shutdown. Any shutdown error retains supplies/pins, captures AP words
and latches failure. An idle-pin failure also retains supplies. Track original
failure stage, domain cleanup result, rail cleanup result, retained state and
ID values separately. A failed poll is not grounds for removing a supply.

`preflight` stays read-only. Its dark_conn_access field records whether the
two ID words have been attempted; a failed earlier CSR-only poll can leave
id_read false even though a guarded CSR read occurred. Use failure stage and
transaction result to distinguish that case.

## Host/build verification

Extract actual domain implementation and full rail integration. Verify exact
21-write success trace against ACK wrapper/PG reference, then simulate every
single dropped MMIO write, four dual-ACK timeout modes (neither/mixed on,
both/mixed off), partial active/idle pin failures, mapping failures, stuck
CSR sleep ACK, bad HW/config IDs and disabled opt-in. Fake MMIO rejects dark
reads unless AP prerequisites pass and any write to the ID/CSR aperture.
Assertions check map/unmap balance, finite polls and retained supplies on
uncertain state. Existing158 API fault-point rail tests and read-only snapshot
tests still pass. Host models do not prove electrical timing or recoverability
of an actual interconnect fault.

Updated compiled-DTB pinctrl model now verifies the two explicitly referenced
custom states, with no automatic state name. Final active/idle field values
still match ACK across four register fills. C/header checkpatch zero errors/
warnings; new schema document and filtered DT validation pass. Full image
build, its existing11host suites and boot capacity check pass. No external
messages or AI Signed-off-by added.

Full build logs and image are retained in `/data/src/mainline/mt6893-direct`.
Selected evidence will be archived under attempt-60/. Coding assistance was
used for implementation, verification and documentation.

## Physical result and bounded refusal

Both serial-targeted boot flashes and immediate reboots succeeded; current
boot hash was read back and matches the follow-up image. Initial status had
attempted=0, all VCN rails off and pins172--182 mode0, confirming no automatic
probe transition. Both explicit attempts returned EBUSY at id-access-guard,
before mapping either CONN aperture. Both completed normal legacy shutdown,
idle pin selection and rail cleanup successfully; domain/rail cleanup result0,
no uncertain flags, no dirty state, no leaf references remain. Shared parent
votes remain held. One-shot failure latch prevents retry within this boot.

The first image only retained post-shutdown state. Follow-up adds a six-word
AP snapshot inside the unchanged guard, preserving the sample before cleanup.
No sequencing, poll deadline or access predicate was relaxed. That capture:

```
status=0x10580e03 status2=0x10580e03 control=0xd
protect=0xe70c500e protect2=0xe3 host=0x1
```

Both power ACKs are on, control/reset/isolation matches intended on state,
host request is on and bank2 bit2 is clear. But primary protection bit14
is set again after6ms settling, despite its release poll having seen zero.
This is the immediate reason the guard rejects access. It does NOT establish
whether a firmware agent reasserted the request, ACK has different semantics,
or another missing clock/reset condition causes it. The source and timing
remain unresolved. Do not remove this prerequisite merely to get an ID.
Host tests additionally inject six AP prerequisite changes during settling;
each is captured and prevents all dark-domain mapping/reading.

Post-shutdown control0x12, both ACKs off, host0; protect0xe70c700e and
bank2 status0xe7 now include the full legacy shutdown protection bits.
VCN13/18 configuration and selected PMIC state restore. Pins172--182 return
to GPIO mode, retaining active drive settings as vendor off does; GPIO155
readback is unchanged. USB SSH, eight CPUs, disk/cache read-only status and
Debian hash, watchdog, battery/temperature reads and LVTS capture remain
available. No selected WARNING/BUG/Oops/Call trace in regression log.

Next add protection request-vs-ACK observations around release and XO settling
and compare the active ACK clocks/reset prerequisites. Keep guarded refusal,
normal shutdown and retained-parent policy. No firmware, DMA, EMI or
calibration is justified until digital-domain access prerequisites are stable.
