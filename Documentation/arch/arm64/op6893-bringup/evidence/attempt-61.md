# Attempt61: protection request/ACK timeline

2026-11-03. Image `764614420260`, release
`7.3.0-op6893-d1-764614420260+`, boot SHA256
`e0b83ec5203e2a77126d84dee4b1c297d17263ff331ed2b3d5b9099973274f80`.
Previous tested image `6346689c1150`. Full build, existing11host suites,
extracted domain/rail tests and boot capacity checks pass. Physically tested:
the unchanged access guard refuses, and domain/rail cleanup succeeds.
No AI Signed-off-by or external messages.

Add root-only0400 `protection_trace`, reading cached AP-side captures only.
Seven points: before pins, before release, after bit14 release, after bank2
release, after bit13 release, after6ms settling, after domain shutdown.
Each capture includes timestamp, primary request/STA0/STA1, bank2 request/
STA0/STA1, dual power ACK, control and host request. Fixed eight-entry buffer
bounds capture count; the separate attribute stays within a sysfs page.
No new hardware writes or changes to access predicates/settling delay.
Captures are sequential observations and alter timing through additional
reads; they are not an atomic hardware trace or firmware-write attribution.

Addresses cross-checked with compiled ACK PG source: primary request0x220,
STA0=0x224, STA1=0x228; bank2 request0x710, STA0=0x720, STA1=0x724.
Previous image's post-shutdown snapshot: request0x6000, STA0=0xde006000,
STA1=0xe70c700e; bank2 request4, STA0=0, STA1=0xe7. These distinct full
word values warn against treating all three register types as interchangeable.
Only the audited CONN bits participate in the transaction.

Host tests verify seven ordered timestamps and sysfs trace formatting while
retaining exact21-write sequence, dropped-write, mixed ACK, pin/mapping,
settling-state-change and rail cleanup cases. Existing preflight and158-point
API failure tests pass. C/header checkpatch zero errors/warnings. No DT change
since the last validated compiled board. Shared-parent policy, per-boot
one-shot and dark-access guard remain unchanged.

## Physical result

Boot partition readback matches the image hash. The explicit one-shot returns
EBUSY at `id-access-guard`, with no CONN aperture mapped and no ID read.
The important primary request/STA1 observations are:

| Capture | Request0x220 | STA1 CONN bits13/14 | Bank2 request/ACK bit2 |
|---|---|---|---|
| Before pins | 0 | bit14 set | request clear / ACK set |
| Before release | 0 | both clear | both clear |
| After each explicit release | 0 | both clear | both clear |
| After settling | 0 | bit14 set | both clear |
| After shutdown | 0x6000 | both set | both set |

Between after-release13 and after-settle samples, 6,706,770ns elapsed.
Primary STA0 stays0xde006000 in all seven captures. The two power ACKs stay
on, control0xd and host1 through settling. Request0x220 remains zero when
bit14 reappears in STA1; the observations do not establish a new AP request,
firmware writer, or automatic sleep as the cause. In particular, some ACKs
already clear before the explicit CLR writes. Do not attribute those changes
to writes which have not yet happened.

Normal shutdown and rail cleanup both return0. Final dual power ACKs are off,
control0x12, host0; leaf refs0/0, dirty flags0/0, uncertainty flags clear.
Both shared parent votes remain held. A repeated trigger returns EALREADY,
and the cached trace hash is unchanged. USB stays configured and SSH works;
CPU0--7 online, sdc read-only, cache ro/norecovery, rootfs hash unchanged.
Battery ADC, PMIC temperature and all17 LVTS sample channels remain available.
GPIO155 is unchanged; CONN pins return to GPIO mode with the documented
retained drive fields. Device remains on this image with the experiment latched.

## Reference audit and next experiment

Compiled ACK `mt6893_consys_reg.c:533`, `consys_check_reg_readable()`, checks
AP-to-CONN primary bit13 and bank2 bit2 clear, then host0x1020e504 bit0.
It does not use CONN-to-AP bit14 in that AP-side gate. It subsequently resets
the HOST_CSR clock detector at0x18060000, checks clock bits1/2, timeout status
0x180602d4 bit0, and internal sleep ACK0x18060184 bit5. ACK POS comments
identify primary bit14 as CONN-to-AP RX protection; these are distinct paths.
The current diagnostic uses a stricter combined predicate and therefore
cannot distinguish HOST_CSR accessibility from internal off-domain readiness.

ACK first-power-on `platform/consys_hw.c:310` invokes power control then
chip-ID polling without an explicit wakeup call. The separate wakeup function
writes0x180601a0 before polling the internal sleep ACK. Thus adding a wakeup
write here is not yet justified solely by the first-power-on call sequence.

Next isolate a HOST_CSR-only diagnostic using the audited AP-to-CONN gate,
while retaining dual power/control/host checks and recording bit14 separately.
Audit HOST_CSR clock/sleep/timeout checks before permitting the internal ID
aperture. Do not merely delete bit14 and proceed straight to ID or speculate
with repeated protection clears. No guard relaxation or CONN write was made
in attempt61. Full raw logs remain in the external evidence directory;
selected snapshots and a result verifier are archived alongside this document.
