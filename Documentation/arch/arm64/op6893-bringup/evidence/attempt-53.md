# Attempt53: executable ACK MTCMOS sequence reference

No device access, kernel change, build or flash in this round. Device baseline
remains attempt48. New host harness extracts spm_mtcmos_ctrl_conn verbatim
from ACK6.6 and original4.19 source, resolves referenced register macros and
executes both against fake MMIO. Compiles with -Wall -Wextra -Werror and UBSan.
Results and source SHA256 are in attempt-53/vendor-traces.json.

## Confirmed software sequence

Both vendor implementations produce identical successful on/off traces.
SPM key write is0x0b160001 to0x10006000. Starting from model control0x12,
power-on requests bit2 then bit3, waits for both status bits, clears clock
disable then isolation, releases reset, then clears bus protection:

1. infra0x2a4 mask0x4000;
2. infra0x718 mask0x4;
3. infra0x2a4 mask0x2000.

Power-off sets protection at0x2a0 mask0x2000, then0x2a0 mask0x4000, then
0x714 mask0x4, polling after each. It asserts isolation/clock-disable/reset,
clears both power requests and waits for both status bits clear.
These are software traces, not a demonstration of electrical correctness.

With acknowledgements suppressed, both actual vendor functions remain in
the polling loop after the two requests. The simulator aborts after9 debug
callbacks with exit77; that limit is in the harness, NOT in vendor code.
Do not copy the unbounded polling into a new mainline implementation.

## Resolve selected versus inactive source branches

Saved actual ACK .mt6893_pos.o.cmd under
`/data/src/6.6-exp/mt6893-gki66/out/android_kernel_modules_oneplus_mt6833/vendor/mediatek/kernel_modules/connectivity/conninfra/conn_drv/connv2/platform/mt6893/`
contains `-D MTK_CONNINFRA_CLOCK_BUFFER_API_AVAILABLE=1`.
Kbuild selects that when CONFIG_ARCH_MEDIATEK=y. mt6893.c separately forces
COMMON_KERNEL_CLK_SUPPORT=0 to use the legacy PG_CONN clock provider.

Thus conninfra's active wrapper does:
- masked SPM unlock write;
- set AP2CONN host clock bit0 at infracfg0x1020e504;
- call the PG_CONN path (which writes the SPM key again and runs above sequence);
- wait6ms for XO readiness.

The alternate POS branch with different polling, TOP_RGU writes and protection
literals is not the compiled reference. Do not combine pieces of both paths.
The macro name CLOCK_BUFFER_API_AVAILABLE does not by itself prove an actual
clock-buffer API is available; mt6893.c has a separate capability guard.

## Concrete scope for the first power experiment

Implement a board-gated, explicit-trigger transaction, not automatic boot or
probe power-on. Preflight captures/validates idle CONN state, rail readiness,
clock and reset prerequisites. Preserve USB, root storage and AP watchdog.
SPM/infra wrapper operations must use the verified active path and masks.

Use finite polls with stage/error/status recording. On missing power ACK,
do not release isolation, reset or bus protection and do not access CONN
registers. Latch the experiment faulted; do not blindly retry or assume that
cutting supplies after partial power-on is safe. A rollback policy must be
reviewed for each failure stage before the experiment can run.

After success, read a documented digital ID only. No firmware, DMA, RF or
pre-calibration in the first experiment. A successful digital-domain test
still does not establish Wi-Fi support. Resource ownership must be reconciled
before replacing this diagnostic transaction with general genpd/consumer PM.

Remaining prerequisites: real rail enable/voltage/voter handling; clock-buffer
and pinmux state; ACK identification register/access guard; bounded shutdown
and failure policy. No untested power-on script has been installed on device.
