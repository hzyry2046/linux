# Attempt57: common-rail executable reference and staged CONN pinctrl

2026-11-03. Device remains on ACK6.6.30-4k-g6974e26f087e. No reboot, flash,
wireless command, NVRAM delivery or power transition requested. Mounted ACK
debugfs to collect fixed-address PMIC and selected pin readbacks; mounting
this filesystem was the only device-side setup change; it was unmounted
after collection to restore the prior state. No /dev/mem exists on
this ACK; attempts to use devmem did not read any register. No dark CONN
aperture accessed. Current SPM RC bit was therefore not directly sampled.

## Concrete DT change and verification

Board DTS now contains unreferenced conn-active-pins and conn-idle-pins.
No consumer or default state selects them, so boot does not apply them.
GPIO172--182 use CONN function1 on active, GPIO function0 on idle. Active
sets data GPIO173/177 pull-ups and4mA, reset GPIO174 to2mA, others4mA.
Idle switches data back to pull-down and retains drive fields as vendor off
code does. Neither state includes GPIO155 (volume-down).

Resolved attempt55 shared-drive issue: GPIO173,175,178--182 share bank5,
offset0,bit3. They must all request4mA. GPIO172 usesbit15; GPIO176bit6;
GPIO177bit9; GPIO174bit12 requests2mA. DRV_GRP4 translates4mA->code1,
2mA->code0. Result under mask0x3fff8 is0x8248, exactly vendor intent.
Do not configure PTA175 to2mA independently; it would overwrite the data
pin's shared field. No pinctrl driver bug fix was needed.

Built the actual embedded DTB using the op6893-dtb.o build target. Direct
*.dtb target invocation initially resolved through the normal DTS tree and
failed; building its object dependency succeeded. Filtered MT6893 pinctrl
schema validation emitted no diagnostics. Board patch checkpatch reports
0errors/0warnings. Host check uses compiled DT properties and actual MT6893
field tables, comparing four initial register fills against extracted vendor
first-on mask values and off-state effects; all pass. Unreferenced states
have no phandles and no boot consumer. This is final-field modeling, not a
runtime pinctrl lifecycle/electrical test. Full kernel/image not rebuilt;
no newly tested mainline boot claimed. Latest live mainline baseline stays
attempt54 d873de3b8963.

## Executed PMIC source reference

trace-vendor-conn-pmic.py extracts actual ACK common-power and VS2/VCN13
raise/restore functions, plus actual register definitions. Host fake APIs
compile with -Wall -Wextra -Werror and UBSan. No hardware APIs execute.

First-on legacy path: VCN18 OP_EN/OP_CFG bit0 set, SW_LP cleared,
set1.8V/enable; then same sequence for VCN13 at1.3V.
RC path: OP_EN bits7..4 set, writes zero to OP_CFG_SET for each,
SW_LP set, voltage/enable; VCN18 precedes VCN13. Writing zero to a SET
alias is NOT a guaranteed clear of an earlier CFG bit. Reboot preconditions
or explicit ownership/readback are needed; do not silently translate that
source into a base-register clear and call it an equivalent sequence.
Last-off disables VCN13 thenVCN18; other-active paths are no-ops.

Raise1.37 state writes VS2 requested selector0x35, voter SET bit4, sleep
selector0x2e, VCN13 VOCAL7, waits50us, then starts1ms timer. Restore clears
VOCAL, sleep selector0x2c, voter CLR bit4; it does not restore the requested
VS2 selector. Timer completion is immediate in the host model, so busy-wait
and real timing are not validated. Vendor comments labeling0x35 as1.4V or
VOCAL7 as1.32V do not match the actual selected sequence; use raw fields
and documented conversion, not those comments.

Fault injection into each of10legacy or22RC API calls always leaves the
extracted vendor function returning0 and proceeding. Thus copying this
wrapper's success return cannot validate supplies. This is characterization
of the external reference, not a tested mainline fix. Candidate transaction
must check every regulator/regmap operation and track partial progress.

## Fresh ACK observations

VCN13/VCN18 have SW_EN+SW_LP set, OP_EN=0x80f0, OP_CFG=0, consistent with
RC-path configuration (not an independent SPM RC-flag measurement).
VS2 requested/actual selectors both0x35 nominal1.4625V; sleep0x2e nominal
1.375V; voterbit4 set; VCN13 selector4/VOCAL7. VCN33 rails remain off.
Two snapshots differ only in VCN18 status0x3->0x7; do not describe them as
identical or assume ACK radio hardware is quiescent. These are sequential
observations during normal Android runtime, not commanded transitions or
multimeter readings. ACK framework summary has active CONN VCN13/18 users.

ACK raw pin debug format confirmed from mtk_pctrl_show_one_pin: GPIO172--182
are function1, drive code1 except reset174code0, data173/177 pull-up;
GPIO155 remains function0. Generic pinconf debug output labels raw codes as
mA and reports unrelated unsupported fields; do not interpret those labels
as electrical measurements. Selected raw readback archived.

## Remaining implementation gates

ACK omits parent supply hierarchy in its regulator summary; this does not
identify physical external VSYS wiring. Mainline still has dummy upstream
inputs, and VS1/VS2 are shared: no invented fixed voltage/source description
or blanket parent disable is justified. Separate inherited-parent observation
from managed supply ownership before the first rail-enable experiment.

Next implement a board-only preflight/explicit transaction with finite
polls, real handle/status checks, RC sampling from AP-side SPM, serialized
state and fault latch. Apply staged pinctrl only at the reviewed point after
rail readiness. Preserve exact vendor PG_CONN sequence (attempt53).
A successful poll must precede dark-domain access; first test excludes EMI,
firmware/DMA/RF and NVRAM registration. Even vendor polling_chipid has a
DEADFEED write after reading ID; do not reuse it as a read-only probe.
Per-stage cleanup needs proof before retry; a mixed power ACK or failed
shutdown must retain necessary supplies and fault-latch rather than tearing
down shared rails. No automatic test has been installed on the device.

Evidence and reusable host scripts are in attempt-57/. Maintainer lookup
saved locally; no external messages sent. Full build and physical activation
of the new pinctrl states remain untested.
