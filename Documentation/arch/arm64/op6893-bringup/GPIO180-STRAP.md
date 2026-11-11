# GPIO180 / MT6635 26 MHz strap: baseline and implementation plan

2026-11-03, AI-assisted source audit and read-only hardware capture.
Source checkpoint f12c1a18c418f799d4964b0f3477afdddf95eccf plus local changes.
Device remains attempt70 (`df82e6dfd58a`), CONN off. No strap transition,
A-die reset release, new image flash or ACK backup update in this audit.

## Observed baseline

[Raw AP register snapshot](evidence/gpio180-audit/idle.json) and
[pin ownership / domain state](evidence/gpio180-audit/ownership.txt) were
captured after attempt70's successful shutdown, not before its first cycle.
GPIO180 is owned by conn-preflight's idle pinctrl state; no GPIO consumer.

| Field | Address / bits | Observed GPIO180 value |
| --- | --- | --- |
| Mux | 0x10005460 [19:16] | 0, GPIO |
| Direction | 0x10005050 [20] | 0, input |
| Output latch | 0x10005150 [20] | 0 |
| Input sample | 0x10005250 [20] | 0 |
| Input buffer | 0x11ea0030 [18] | 1 |
| Pull-down / pull-up | 0x11ea0050 / 0x11ea0070 [18] | 1 / 0 |
| Shared Schmitt | 0x11ea00c0 [7] | 0; shared by GPIO178–182 |
| Shared drive | 0x11ea0000 [5:3] | 1, 4 mA encoding |

Fields follow `drivers/pinctrl/mediatek/pinctrl-mt6893.c`; drive is shared
with GPIO173/175/178–182. Full mux field is four bits in this driver; ACK's
strap mask covers only three. Baseline validation should check all four.
These sequential observations do not measure oscillator frequency or prove
the A-die has latched a strap. The same fields must be checked again before
and after active pin selection in the eventual one-shot transaction.

## Why a single output-high state is insufficient

`drivers/pinctrl/core.c:pinctrl_commit_state()` applies every mux setting
before any pin configuration. Putting GPIO mux and output-high in one
state therefore does not preload the output while peripheral mux is held.
Re-selecting an already-current state returns without touching hardware.
An out-of-band GPIO/raw mux write followed by selecting conn-active cannot
be assumed to restore the mux. State selection failure attempts restoration
of the old state, but does not provide transactional register rollback.

`drivers/pinctrl/mediatek/pinctrl-paris.c:mtk_pinconf_set()` implements:

- LEVEL: write DO, then DIR=output.
- INPUT_ENABLE: change IES only, leaving DIR unchanged.
- INPUT_SCHMITT_ENABLE: change DIR and SMT together.
- No OUTPUT_ENABLE case at present.

Consequently, existing conn-idle leaves a previously asserted output latch
and direction intact. INPUT_ENABLE cannot fix that. Using Schmitt-enable
to restore input would change a shared field from its observed zero to one,
affecting neighbouring pins. This is a prerequisite for a new strap path,
not evidence of a regression in attempt70: that test never changed DIR/DO.

## Intended implementation

First add generic PIN_CONFIG_OUTPUT_ENABLE get/set support to Paris pinctrl,
using only PINCTRL_PIN_REG_DIR and propagating provider errors. Generic DT
already maps output-enable/output-disable to arguments 1/0. Test actual
provider code for both arguments, unchanged DO/SMT/IES/pulls, and errors;
compile the provider before integrating the board transaction. This is a
new pinconf capability; no existing state should start using it implicitly.

Then add distinct, explicitly named board states owned by the same consumer.
Every state must retain ownership of all eleven CONN pins, with the existing
non-GPIO180 fields unchanged. Do not create a competing GPIO consumer or
write GPIO registers directly. No default/init state or probe-time selection.

The candidate sequence, while A-die reset remains asserted, is:

1. Capture AP baseline, select existing active pins, verify GPIO180 mode1
   and inherited DIR=0/DO=0. Require fresh digital IDs and ADIE_CTL=2.
2. Prepare: keep mode1, output-high preloads DO=1 then sets DIR=1.
3. Strap: change only GPIO180 mux to mode0, verify DIR=1/DO=1.
4. Restore peripheral mux first, keeping DIR=1/DO=1.
5. Behind mode1, restore DO=0 with output-low, then use a separate state
   with output-disable to restore DIR=0 without changing SMT.
6. Verify complete restoration, select ordinary active state, then perform
   normal domain shutdown and idle selection; verify idle GPIO180 baseline.

Use separate states for low and input restoration; do not depend on DT
property ordering within a state. Hold no undocumented minimum strap delay
claim: this isolated test does not release reset or test strap sampling.
For the first experiment, require the audited input/low baseline rather than
inventing arbitrary restoration sequences for unknown inherited states.

Before and after each transition, recheck AP accessibility, fresh CSR
clock/timeout/sleep, and full ADIE_CTL=2. Read back direction, latch and mux,
and check untouched shared fields. Mark dirty before each potentially partial
state change. Failure paths must account for core rollback attempts and
read actual hardware: an error return alone says nothing about final mux.
Guard loss or unverifiable restoration must retain domain/pins/rails and
refuse another attempt until reboot. Cache status; status reads do no MMIO.
Do not report success merely because pinctrl_select_state() returned zero.

Host fault coverage must include partial DO/DIR writes, failed mux switches,
failed automatic old-state restoration, each guard loss, final restore loss,
and shared-field corruption. Successful runtime validation requires baseline,
high GPIO state, restored active state, restored idle state, normal cleanup,
one-shot refusal, and USB/root/CPU/ADC/LVTS regressions. No A-die release or
SPI transfer is part of this first strap transaction.

## Reproduce the read-only capture

Run `tools/conn-strap-snapshot.py` with `--ssh-helper` pointing to the local
`mt6893-direct/ssh-native.sh` and `--expected-release` set explicitly.
The tool checks release and board compatibility before reading nine fixed
AP registers. It performs no SET/CLR alias access and no CONN aperture access.


## Implementation prepared for attempt71

Paris OUTPUT_ENABLE now sets only DIR (boolean argument), and its getter
reports enabled output or EINVAL for input, preserving provider errors.
Actual complete get/set functions pass the host field-isolation/error tests;
ARM64 object compilation and patch checkpatch pass.

The board now has five distinct strap states and a separate normal GPIO180
active node. Each state references the same ten-pin active group plus exactly
one GPIO180 node, retaining ownership of all eleven pins. The one-shot
strap-cycle selects prepare/high/mux/low/input/ordinary-active, with seven
AP snapshots including the starting active baseline. DIR/DO/mux targets and
all other sampled bits must match. ADIE_CTL remains2 throughout. Full GPIO
and IOCFG sampled words are retained in cached root-only strap_status.

Any state-selection error or post-write mismatch latches unsafe/dirty;
there is deliberately no further recovery write, including after core
rollback. Domain and rail cleanup retain resources. Final guard failure
retains resources even after apparent successful pin restoration. A bad
starting electrical baseline refuses all strap writes and permits ordinary
shutdown. This version validates restored active fields inside the kernel;
post-shutdown idle fields must also be checked from the AP-only snapshot
on the host. Physical strap testing passed in attempt71; see its archived evidence.


Attempt71 hardware result: all six state selections and seven snapshots
pass, with complete active-field restoration and clean domain shutdown.
Post-shutdown DIR/DO/mux match boot idle; common drive changed0->0x8248 as
in the established active/idle policy. The strap phase itself preserved
shared fields. See [attempt71](evidence/attempt-71.md). No A-die response yet.
