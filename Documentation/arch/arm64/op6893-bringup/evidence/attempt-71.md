# Attempt71: GPIO180 strap transition and restoration

2026-11-03. Image `d8f40ea749e6`, release
`7.3.0-op6893-d1-d8f40ea749e6+`, boot SHA256
`b6e72757814e3bbcdbff2dbab0aa185fdc2bea888dae6a6759f903e2a8725d62`.
Full image build and eleven existing build-time suites passed; boot capacity
and decompression window passed. Physical test passed.
Device now runs attempt71. ACK recovery backup unchanged.
AI-assisted implementation and tests, no AI Signed-off-by or external submission.

## Scope

Add Paris pinconf OUTPUT_ENABLE for independent direction changes. The
board strap-cycle uses existing fresh digital-ID/domain prerequisites and
five explicit pinctrl states: preload high behind peripheral mux, GPIO mux,
restore peripheral mux, restore low latch, restore input direction, then
ordinary active state. All states retain all eleven CONN pins. Shared SMT,
IES, pull and drive fields are not intentionally changed by the strap path.
Existing common active-pin settings are reapplied identically at each stage.

Require ADIE_CTL=2 and CSR/AP access checks around state transitions. Read
seven snapshots of DIR5/DOUT5/MODE22 and five IOCFG words. Compare full
unrelated fields and exact GPIO180 targets; require observed baseline
DIR0/DO0/mode1, 4mA drive, IES1, PD1, PU0 and shared SMT0. Baseline refusal
performs no strap state selection. Partial state failure or readback mismatch
latches dirty/unsafe; no further pin writes and no domain/supply shutdown.
Core automatic rollback is not trusted as proof of hardware restoration.
Even final guard loss after restored pins retains resources.

No A-die reset release, SPI transfer, SYSRAM/RGU/remap transaction, firmware
or calibration writes in this experiment. This does not prove oscillator
frequency, strap sampling by MT6635, or Wi-Fi support. Per-access guards are
sequential, not exclusion against other masters. Boot/probe does not select
any pin state or run the cycle.

## Host validation

Actual Paris get/set:32 argument/direction/latch/Schmitt combinations,
all unrelated fields/pins preserved, getter/setter provider errors and bad
pin rejection, existing LEVEL interoperability. Actual strap C: seven
snapshots, all mapping/guard/read-loss points,24 partial state failures,
48 adjacent/shared-field corruptions, dropped changes and final restore loss.
Actual one-shot/domain/rail glue uses injected strap outcomes to check
fresh-ID prerequisites, both opt-outs, cached status, independent dirty and
unsafe retention, normal cleanup and retry refusal. This is separate from
the actual strap-function tests, not a claim to emulate the entire pinctrl
core or analogue pad behaviour.

Compiled DTB model checks all eleven pins remain present in each state,
active/idle vendor equivalence across four seeds, all six transitions and
exact field restoration. Driver and embedded DTB compile; binding schema
and board-specific DTB validation pass; C/header checkpatch has no errors
or warnings. Existing domain/SYSRAM/SPI/semaphore host regressions pass.

## Required physical checks

Verify running release and raw boot hash, initial attempted0, and AP idle
baseline. Trigger strap-cycle once; require selected6/samples7/complete1,
dirty0/unsafe0, ADIE2, normal cleanup, fresh HW/config20010101/3. Compare
post-shutdown AP fields and ownership with the initial idle snapshot.
Then USB SSH,8CPU,read-only cache/root hash,ADC/LVTS and EALREADY regressions.
See [design and baseline](../GPIO180-STRAP.md).


## Physical results

Serial-targeted fastboot flash and reboot succeeded. USB SSH returned with
matching release and raw boot-partition SHA256; initial attempted0 and no
pinmux ownership confirm no automatic board cycle. One strap-cycle returned0:
selected6, samples7, complete1, dirty0, unsafe0, ADIE_CTL2. All seven expected
mode/direction/latch tuples matched, including restored active baseline:
(1,0,0) -> (1,1,1) -> (0,1,1) -> (1,1,1) -> (1,1,0) -> (1,0,0) -> (1,0,0).
Shared drive/IES/pulls/Schmitt words stayed identical throughout these seven
samples. Fresh digital ID20010101/config3, normal domain/rail cleanup0,
final control12/host0, VCN13/18 off and parent votes1/1.

Post-shutdown GPIO180 is input, latch0, mux0 and owned by conn-preflight's
idle state. All nine AP snapshot words match the pre-cycle snapshot except
DRIVE:0 -> 0x8248, the existing common active-pin policy retained by idle,
not a new strap-specific drive change. Do not claim restoration of the whole
cold-boot electrical configuration. Shared SMT remains0x1c01, including
GPIO178–182 bit7clear. DIR5/DOUT5 and neighbouring mux bits restored.

Runtime regression passes: CPUs0-7, USB configured/SSH, sdc read-only,
cache ext4 ro/norecovery and unchanged Debian hash. Battery ADC20260,
PMIC temperature39372, all17 LVTS entries returned. GPIO155 retained and
all11 CONN pins idle/owned. Retry refused with EALREADY; cached strap and
protection hashes unchanged. No BUG/Oops/SError/kernel panic in captured
dmesg; known image-alignment warning remains. No new button event test.

Device remains mainline71, CONN off. Next compose validated RGU/SYSRAM,
SPI configuration, remaps, strap and semaphore prerequisites with explicit
lifetimes and reverse cleanup for a bounded A-die reset-release/ID read.
No actual RF SPI transaction, A-die response or Wi-Fi readiness proven yet.
