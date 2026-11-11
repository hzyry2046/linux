# Attempt58: CONN read-only preflight implemented and tested

2026-11-03. Image `d79c36ef9d28`, release
`7.3.0-op6893-d1-d79c36ef9d28+`. Boot SHA256:
`435fc65f144584cd0f40236a4a8da1e8b5c1253d012f765c9a64bbe3affafc1c`.
Previous tested mainline image: `d873de3b8963`. Device started on ACK;
its boot hash matched selected recovery backup `455ed6ce...722c88` before
testing. Queued serial-targeted flash boot followed immediately by reboot,
then entered bootloader using ADB. Both commands succeeded. Device now runs
the new mainline image; no further restart scheduled. GPT remains unchanged.

## Implementation

`arch/arm64/kernel/op6893-conn.c`, gated by
`CONFIG_ARM64_OP6893_CONN_PREFLIGHT`, exposes root-only 0400:

```
/sys/devices/platform/conn-preflight/preflight
```

Each read takes a mutex and samples audited always-on AP SPM/infra/host
registers, 20 fixed PMIC registers, and six explicitly described regulator
handles. The SPM status/control words are sampled again at the end. The
capture is sequential, not atomic; matching endpoints cannot exclude a
transition between samples. No CONN aperture is mapped. Probe and reads do
not request pin states, clocks, resets, power transitions or voltage changes.
The staged active/idle pinctrl states remain unreferenced.

DT supplies are required explicitly and optional regulator lookup rejects
absent leaf providers rather than substituting a dummy leaf. The wrapper
regmap has a supplier device link. Upstream VSYS inputs still use inherited
dummy providers; the diagnostic unconditionally reports `activation_ready=0`
and `upstream_policy=unresolved`. It does not claim full supply ownership.
Regulator readback is a nominal selector interpretation, not a voltage
measurement. No machine-specific factory record or firmware added to Git.

Reads fail immediately on PMIC/regulator API errors or an unexpected HWCID;
there are no partial snapshot results. Unlike a power transaction, a failed
read has no hardware cleanup state and can be retried. Off-state detection
and legacy shutdown protection completeness are separate output fields.
This is a local bring-up observer with an experimental DT schema, not an
upstream connectivity binding or WLAN driver.

## Host and build checks

Extracted actual snapshot code compiled with warnings as errors and UBSan.
Tests cover 128 status/control combinations, adjacent unrelated status bits,
a transition between endpoint samples, inherited incomplete protection,
all 20 PMIC read failures, incorrect identity, 12 regulator read failures,
interrupted mutex acquisition and retry. Static checks reject known write
APIs and confirm only the three AP ranges are mapped. These fake APIs do
not prove electrical behavior or kernel supplier lifecycle behavior.

New C source checkpatch: zero errors/warnings. New schema document validation
and filtered compiled-DTB validation: no diagnostics. Existing pinctrl field
model passes all four fills and still finds no active boot consumer. Full
image build and its existing 11 host suites passed. Capacity: payload
7,442,432 bytes, 26,112,000 bytes free in boot; padded image is 32 MiB.
Maintainer lookup saved locally; no messages sent.

## Live observations

First direct RC read: SPM `0x10006504=0x401425`, bit0=1. Both CONN power
status bit1 values are zero; power control `0x12`, host request zero.
Protection status is unchanged from previous mainline snapshots:
`0xe70c500e`, `0x519c0000`, `0xe7`. ACK legacy shutdown step1 bit13 is
absent, while bit14 and bank2 bit2 are set. Hence
`off_at_both_samples=1`, `legacy_protection_complete=0`. This does not prove
the entire shutdown sequence ran or justify dark-domain access.

PMIC HWCID `0x5930`. All four VCN rails are off; VS1/VS2 remain enabled.
VCN13/18 OP_EN `0x8000`, OP_CFG zero; VCN13 VOCAL zero. VS2 voter zero,
sleep selector `0x2c`, requested selector `0x30`, actual low selector `0x2c`.
Framework VS2 nominal readback is 1.4 V (requested selector), whereas the
actual/sleep selector encodes nominal 1.35 V; neither is a multimeter reading.
These differ from active ACK attempt57 and are not an ACK off-state sample.

16 serial and four concurrent captures pass assertions. Their intervals
serialize and all 20 selected PMIC words match across these captures.
Six named real leaf consumer handles appear in regulator_summary, each with
use count zero; dummy upstream handles remain. GPIO172--182 stay mode0;
GPIO155 remains the volume-down input. No wireless activation performed.

Regression: USB SSH, CPU0--7, disk read-only policy, cache mount and Debian
SquashFS hash, watchdog processes, battery/PMIC temperature reads and three
CCF rate readouts remain available. Key devices registered; physical presses
not retested. LVTS capture returns 17 valid samples, 35.933--40.603 C;
independent host arithmetic agrees. All seven controllers afterwards have
monitor, local clock, interrupt and protection controls/thresholds zero.
No selected WARNING/BUG/Oops/Call trace in the collected kernel log. Initial
CONN probe deferrals resolve after the PMIC provider binds.

## Next transaction boundary

First define an explicit inherited-parent policy: verify shared VS1/VS2
enable/status without changing their voltage, modes or use ownership, refuse
unexpected inherited states, and never disable either shared parent during
rollback. Keep unresolved external inputs visible rather than inventing a
fixed source voltage. This policy needs review before rail enablement.

Then add a separately triggered serialized experiment with checked per-rail
progress, RC-specific PMIC handling, exact SET/CLR writes, reviewed pinctrl
timing and finite ACK polling. An incomplete shutdown or mixed power ACK
must retain required supplies and latch failure. Use the attempt53 legacy
PG_CONN sequence, not the generic genpd table. Only after power, isolation,
reset and protection prerequisites pass may the first digital-ID reads run.
Do not reuse vendor polling_chipid wholesale: it also writes DEADFEED state.
EMI, firmware, DMA, RF and NVRAM/callback registration remain later steps.

Selected results are in attempt-58/; full logs, raw captures and immutable
image remain in `/data/src/mainline/mt6893-direct`. Coding assistance was used
for implementation, host tests and documentation; no AI Signed-off-by added.
