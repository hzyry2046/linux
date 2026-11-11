# Attempt59: explicit RC common-rail cycle

2026-11-03. Test image `d46fc22c1b0c`, release
`7.3.0-op6893-d1-d46fc22c1b0c+`, boot SHA256
`107fb3ff278dbfe0de91e4aaff620e5d24b8df5e318ff979ec63eb5e66529424`.
Rollback mainline image `d79c36ef9d28`; selected ACK recovery unchanged.
Built, flashed and physically tested successfully. Device remains on this
mainline image; no further reset scheduled.

## Scope and parent policy

Add root-only 0600 `rail_cycle` beside existing root-only `preflight`.
Reading either attribute does not initiate a cycle. Probe does not enable
rails. The board explicitly opts in using
`realme,allow-inherited-parent-rail-cycle`. Only writing `rc-cycle` triggers
the experiment, once per boot; subsequent attempts return EALREADY even
after success. All accesses share the preflight mutex.

CONN remains off, reset asserted and isolated. No SPM/infra/host writes,
pin state selection, dark CONN mapping, voltage change, VS2 boost/voter,
EMI, firmware or calibration. This tests the common-rail stage in isolation;
it is not the full attempt53 PG_CONN transaction or Wi-Fi activation.

Regulator core recursively enables/disables parent supplies. Merely avoiding
explicit parent-disable calls does not preserve shared inherited VS1/VS2:
leaf shutdown or failed leaf-enable unwind can drop the parent's last use.
The diagnostic therefore verifies the observed already-on parents and takes
one lifetime enable vote on each before touching a leaf. These votes are
intentionally retained until reboot, including on partial failure. With the
current uncoupled providers, zero load and no voltage/mode request, an
already-on parent should only acquire framework references. No always-on DT
constraint is added, so probe does not power an unexpectedly disabled parent.
This refines attempt58's proposed policy: reference ownership is necessary
to protect the inherited parent, while hardware configuration stays inherited.

The external VSYS graph is still unresolved and includes dummy inputs.
This bounded diagnostic does not claim full managed upstream ownership.
No other driver is being allowed to manage these rails concurrently; the
current board configuration has no WLAN/BT consumers. This policy must be
replaced before introducing general connectivity PM or suspend.

## Preconditions and transaction

Reject unexpected dual CONN ACK/control, host clock request or RC mode.
Verify 26 fixed PMIC predicates, including parent enable/monitor/selectors,
VS2 sleep/voter, VCN13 selector/VOCAL, VCN13/18 enable/OP_EN/OP_CFG and
both VCN33 software/monitor/Wi-Fi enables. Verify six framework enable and
nominal voltage readbacks. VS2 actual selector0x2c and requested0x30 are
deliberately distinct. These are enable/selector observations, not electrical
power-good or physical voltage measurements.

After parent votes and a repeated baseline check, enable VCN18 then VCN13.
Per rail: exact OP_EN_SET writes for bits7..4; set SW_LP; verify OP_EN0x80f0
and OP_CFG0; enable using the real regulator handle; poll enable monitor
with a 20 ms deadline and verify software enable. The cold-boot selectors
already encode nominal1.8/1.3V and remain unchanged. ACK's zero writes to
OP_CFG_SET are omitted because the baseline requires zero and those writes
do not clear anything. This is a deliberate simplification of the reference,
not a claim to reproduce every vendor API call.

Save on-state CON/MON/OP_EN/OP_CFG for both rails, then disable VCN13 before
VCN18. Poll each off with the same deadline. Clear only acquired OP_EN bits
using exact CLR writes and restore SW_LP. Recheck the complete baseline.
Parent votes remain held, even after successful cleanup.

## Failure policy

Every regulator/regmap call is checked. Track successful leaf references,
partially configured rails, uncertain enables, failure stage and cleanup
result. A failed enable can have changed hardware despite its return value;
do not issue an unbalanced framework disable or blindly remove its supplies.
Instead retain state and parent votes, report EUCLEAN cleanup and fault-latch.

With known successful references and CONN still off, ordinary read/config
failures attempt bounded reverse cleanup. A failed disable or off poll stops
cleanup before removing the other supply. Any observed live/mixed CONN ACK
refuses cleanup. Diagnostic fields distinguish the original failure from
cleanup failure and retained references. Reboot is the retry boundary.

## Host verification

Compile extracted actual transaction code with warnings as errors and UBSan.
Fake APIs model shared-parent reference propagation and reject any explicit
parent-disable operation. All 158 successful-path API failure points are
injected individually, including ambiguous enable side effects. Also cover
26 PMIC predicate mismatches, 12 framework status/voltage mismatches,
on/off poll timeouts, domain becoming active after either rail enable,
disabled opt-in, invalid commands, interrupted locking and repeated trigger.
Read-only preflight tests continue to pass. This is an API-boundary model;
it does not model every internal regmap operation of the regulator core,
physical timings or electrical behavior.

New C source checkpatch: zero errors/warnings. DT schema document and
filtered compiled-DTB checks pass. Unreferenced CONN pinctrl still passes
the existing four-fill model. Full image build and its 11 existing host
suites pass; capacity check passes. No AI Signed-off-by or external messages.

## Device result

Queued serial-targeted flash/reboot before watchdog reset; both succeeded.
Boot partition readback hash matches the immutable image. Before triggering,
the interface reported attempted=0, no votes, idle; selected PMIC/CONN
registers matched attempt58, confirming probe did not run the rail cycle.

The single trigger completed with result=0 and cleanup_result=0. Both rails
returned on-state CON/MON/OP_EN/OP_CFG `0x3/0x7/0x80f0/0x0`, then their
successful consumer references returned to zero. Dirty and uncertain-enable
flags are clear. Both shared parents retain one diagnostic vote; their
framework use counts are one, while regulator-dummy use count changes from
one to three due to those two parent references. This count change is
expected and does not turn dummy upstream inputs into managed real supplies.

All 20 PMIC words in preflight and the sampled SPM/infra/host words match
before/after; the full final 26-predicate baseline check also passed. CONN
stays off. Actual-enable readbacks do not prove analog voltage quality.
The repeat trigger returned EALREADY and left the successful result intact.
Attribute mode is 0600 root. Post-cycle preflight passes another16 serial
and four concurrent captures with nonoverlapping capture intervals.

USB SSH, eight CPUs, disk/cache read-only policy, rootfs hash, watchdog,
ADC reads and CCF observations remain available. Both key devices remain
registered; no physical key presses retested. LVTS returns17 valid samples,
35.625--42.005 C; independent host conversion agrees, and all seven
controllers end with monitor/local clock/interrupt/protection words zero.
No selected WARNING/BUG/Oops/Call trace in collected kernel log.

Next extend the separately triggered experiment to reviewed pinctrl timing
and exact legacy PG_CONN sequence with finite dual-ACK/protection polling,
then guarded first digital-ID access. Keep the tested common-rail stage and
shared-parent votes; an uncertain CONN shutdown must not remove supplies.
The current one-shot has completed, so the next experiment requires a new
boot. No Wi-Fi, firmware, DMA, RF or calibration support claimed.

Selected evidence is archived under attempt-59/. Full build and test
artifacts remain in `/data/src/mainline/mt6893-direct`. Coding assistance
was used for implementation, tests and documentation.
