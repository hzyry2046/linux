# op6893 SIM and radio access technology (RAT)

2026-11-19; same board, Android followed by mainline image `9bfc8e0f909c`.

## Channel map

Android reported `dsds`, two loaded SIMs and LTE on both. Both RIL channel
groups were present under `/dev/radio`. They are logical channels of the same
MD and the same CCCI UART2 byte stream. The board's `gsm0710muxd` binary
(SHA-256 `c69f99870a54d067e64550cf21944e5e303c510d1ea8351ea07094493400d4e9`)
has a table of little-endian u32 triples (channel, frame limit, PTY name
pointer) in `.data.rel.ro`. In the DSDS table:

| Android path suffix | DLCI | table entry virtual address |
| --- | ---: | ---: |
| pttycmd4 / pttynoti / pttycmd1 | 1 / 2 / 3 | 0x1205c / 0x12068 / 0x12074 |
| ptty2cmd4 / ptty2noti / ptty2cmd1 | 6 / 7 / 8 | 0x120e0 / 0x120ec / 0x120f8 |

The other multi-SIM tables agree on these entries' channel numbers.
`write_frame()` uses the channel shifted left by two in the wire address and
computes basic-mode FCS over the address, control and length. The existing
mainline AT client uses a different, already validated default-context
exchange. It is still used for PDP setup.

## Initial mainline result (superseded for slot attribution)

The modem reached HS2. After opening RF by the existing path, the default AT
context was EPS registered (CEREG stat 1). The following query results omit
all card, operator and cell identifiers:

| Query | Mainline result |
| --- | --- |
| ESLOTSINFO? | Reply starts with `2`; this does not establish per-slot registration |
| ERAT? | `7,0,6,4,0` |
| ERAT=? | `(0-8, 10-12, 14)`; not a mapping from values to RAT policy |
| E5GOPT? | `7` |
| C5GREG? | `0` |
| EDATASIM? | ERROR |
| CGACT? | CID 1 inactive |

The MD acknowledged SABM on DLCI 0, 3 and 8. On both 3 and 8 it returned
an AT echo and unframed CPIN replies. Alternating COPS queries four times
also returned the same operator on the unframed stream. There is no reverse
DLCI on these replies and no evidence that the queries addressed separate
radio contexts. Do not treat either result as per-slot proof. Manually
sending a CMUX set command from the mainline AT session (also tried as raw
text on a fresh boot) did not produce a usable framed session afterward.
A reboot into the same image restored normal AT and EPS registration.
These experiments do not reproduce the full Android MUX startup sequence.

[modem_slot_probe.py](tools/modem_slot_probe.py) sends a small, read-only AT
query set and only credits replies carried on the requested DLCI. It is a
diagnostic for getting the full MUX session working. Run it after HS2 with
exclusive use of the AT endpoint and no active data session:

```sh
python3 modem_slot_probe.py --device /dev/ccci-at-10209000.modem-platform
```

## Framed MUX and dual LTE registration

The original slot probe incorrectly reused the legacy client's CRC table.
The MD returned the transmitted control header with a different FCS: e.g.
`f9 03 3f 01 1c f9` for DLCI 0 SABM. The vendor table and these wire bytes
agree on reflected CRC-8 (polynomial 0xe0 in the right-shift loop), with
initial state 0xff and final XOR 0xff. The slot probe now uses this FCS for
basic MUX headers. The legacy default-context data-session codec is unchanged.

On the existing `9bfc8e0f909c` kernel, after HS2, raw startup chat
`AT`, `ATZ`, `ATE0`, `AT+CMUX=0,0,5,512` followed by correctly framed
SABM/UA opened DLCI 0, 3 and 8. With only DLCI 3 enabled by `AT+CFUN=1`,
DLCI 3 read CFUN 1 and CPIN READY; DLCI 8 still read CFUN 0 and CPIN ERROR.
After RF enable on DLCI 8, both reported CFUN 1, CPIN READY, CEREG state 1
and COPS access technology 7, with different operators at the same time.
Both reported packet attach (`CGATT: 1`) but no active CID 1. Both read
`ERAT: 7,0,6,4,0`, `E5GOPT: 7` and `C5GREG: 0`.

From a fresh HS2, with no active data session:

```sh
python3 modem_slot_probe.py --device /dev/ccci-at-10209000.modem-platform \
    --enter-basic --radio-on
python3 modem_slot_probe.py --device /dev/ccci-at-10209000.modem-platform
```

Run the startup chat only once per MD boot. The first RF enable shortly after
HS2 can lack a terminal response; the probe uses CFUN readback. CPIN and
registration can lag RF enable; use the read-only second command to poll
them. The isolated CFUN test was with both cards inserted; physical single
card configurations still need separate tests.

## Sequential data selection

From DLCI 3 the firmware acknowledged `AT+EDATASIM=1`, then `=2`, then
`=1`; both subscriptions stayed registered. `EDATASIM?` returned ERROR
on both DLCIs. A test harness reused the existing session code with the
appropriate framed AT context and the shared `ccmnidp0` data interface:

| Selected slot | PDP and data result |
| --- | --- |
| 1 (DLCI 3) | Dual-stack CID 1; interface-bound IPv4 and IPv6 DNS both passed |
| 2 (DLCI 8) | Dual-stack activation supplied addresses but no usable IPv6 RA was received in the test window |
| 2 (DLCI 8), IPv4-only PDP | CID 1 inactive on slot 1 and active on slot 2; interface-bound IPv4 DNS passed |

The IPv4-only run reused the DPMAIF rings initialized on the first slot.
Only the dedicated interface-bound route was installed; the USB management
path stayed up. The last test deactivated CID 1 on both slots, checked that
the interface, policy routes and rules were cleaned up, and sent
`EDATASIM=1` to restore the initial selection. This was a sequential smoke
test with both cards inserted. Concurrent traffic and live migration of an
active PDP were not tested.

## Session tool

On a modem already in basic MUX mode, with RF and the downlink ring up:

```sh
python3 modem_data_session.py --slot 2 --apn YOUR_APN --policy-routing --probe --seconds 45
python3 modem_data_session.py --slot 2 --apn YOUR_APN --policy-routing --ipv4-only --probe --seconds 15
```

Install `modem_slot_probe.py` alongside the existing AT and IPv6 helpers.
Before changing the data SIM, the tool checks both SIMs for active PDP
contexts and refuses to switch if one is active. On exit, it removes its
addresses and routes and deactivates CID 1. The selected data SIM stays set
unless an explicit `--restore-slot` is supplied. The firmware rejects
`EDATASIM?`, so this option sends the requested selection at exit rather
than discovering the original setting. The no-slot invocation continues
to use the legacy AT context.

IPv4 and its routes are installed immediately. If the PDP provides no IPv6
interface ID or a solicitation returns no usable RA, the tool retries IPv6
on the same PDP. A DNS miss is also diagnostic and does not tear down either
family. Confirm the printed probe result when using the CLI for traffic
validation. The regression test injects a missing RA and then a valid RA
and verifies that IPv4 stays configured across both without PDP reactivation.

On image `9bfc8e0f909c`, the SIM2 dual-stack PDP supplied IPv4, but bound
IPv4 DNS did not reply and no IPv6 RA arrived even with retries. The IPv4
policy route remained installed and no PDP reconnect occurred during the
45-second run. A separate SIM2 IPv4-only PDP passed bound UDP DNS. SIM1
passed both IPv4 and IPv6 DNS on a repeat dual-stack run; an earlier SIM1
attempt immediately after SIM2 also had no DNS or RA. This is not enough
to attribute the misses to an operator or a driver mechanism.

## LTE and NR policy

The same-device Android `libmtk-ril.so` (SHA-256
`2a816e0b1aaa7049c30abb0ffe8004bfc85f7a942a38312b4434beb314f3058e`) maps
Android LTE-only mode 11 and NR+LTE mode 24 through the jump table at
`0x15e66b` in `requestSetPreferredNetworkType()`. Its normal non-test-SIM
path formats the arguments at `0x30fb58` as `AT+ERAT=%d,%d`.

| Android mode | ERAT write | SIM2 mainline observation |
| --- | --- | --- |
| LTE-only | `3,0` | ERAT configured fields `3,0`, COPS AcT 7, IPv4 DNS passed on repeat |
| NR+LTE | `19,128` | ERAT configured fields `19,128`, COPS AcT 11, IPv4 DNS passed once and did not reply on another run |

The two modes reached packet attach. SIM1 remained at AcT 7 throughout.
With extended `C5GREG` reporting enabled for the comparison, SIM2 reported
5GS home registration in both modes. Accordingly, use the COPS access
technology to distinguish these two observations; the C5GREG registration
flag alone does not distinguish the radio link.

ERAT readback begins with two runtime fields. Save and restore the third
and fourth fields, which track the configured pair (here `6,4`). Setting
the first two fields back as though they were policy initially caused a
temporary loss of registration; restoring `6,4` brought LTE back. The
final test confirmed both slots back at `7,0,6,4,0` and EPS registered,
the reporting mode restored, data selection reset to slot 1, and both
CID 1 contexts inactive.

The session tool accepts `--rat lte-only` and `--rat nr-lte` together
with `--slot`. It checks the policy readback, waits for packet attach,
and restores the saved policy on normal exit, SIGINT/SIGTERM or a handled
failure. NR+LTE permits LTE fallback: use `--radio-status` to print the
COPS AcT and physical channel rows at the start and end of the active
session. Use an IPv4-only PDP for SIM2 until its dual-stack issue is
understood.

### Physical channel and data checks

The same-device Android RIL's `getPhyChlCfgInfoV2ByQuery` (0x325860) sends
`AT+EPHYCONFIG=2`. Its parser (0x337800) maps row type 4 to LTE and
128 to NR; the sixth field carries the band. The session tool reports
these rows without cell identifiers and skips the zero placeholder.
The rows alone do not establish the serving RAT or dual connectivity;
read COPS alongside them.

On image `9bfc8e0f909c`, SIM1 reported AcT 7 and LTE B3. SIM2 under
NR+LTE reported AcT 11 and NR n41, with DL/UL channel numbers
504990/503172. This is consistent with NR SA registration; NSA and
band-mask writes have not been validated. `ENRCABAND?` returned ERROR
on both SIMs and is not a supported-band inventory.

In one 105-second SIM2 IPv4-only PDP session, the start and end both
reported AcT 11 and n41 and CID 1 remained active. At ten-second
intervals, none of ten interface-bound IPv4 UDP DNS probes and none
of ten TCP connections to the same resolver's port 53 succeeded. An
earlier session on n41 did return a matching DNS reply. Registration
and PDP activation are repeatable; usable NR data is not yet repeatable.

A 65-second-per-mode comparison kept SIM2, the IPv4-only PDP setup, the
DPMAIF rings, the interface-bound routing and the resolver the same:

| Policy | AcT at start/end | UDP DNS | TCP connect | Interface TX/RX delta |
| --- | --- | --- | --- | --- |
| LTE-only | 7/7 | 6/6 | 6/6 | +29/+18 |
| NR+LTE | 11/11 | 0/6 | 0/6 | +30/+0 |

The LTE-only session reported LTE B3 at start and B40 at end, with an
additional n41 row in both snapshots. As the LTE-only run still had
AcT 7, an n41 row by itself is insufficient evidence that the data
bearer is on NR. Neither comparison session reported a CID loss.
After each run both SIMs read back their original ERAT policy, both had
no active PDP, the modem acknowledged explicit data selection of SIM1,
and the cellular interface and dedicated rules/routes were clean.

A shorter repeat sampled DPMAIF counters during three identical probe
pairs per mode. LTE passed all three pairs; NR failed all three:

| Policy | UL submitted / done IRQ delta | UL power-not-ready IRQ delta | DL IRQ / packet delta |
| --- | --- | --- | --- |
| LTE-only | +14/+12 | 0 | +8/+8 |
| NR+LTE | +15/+15 | +12 | 0/0 |

The v2 ACK register header agrees with the mainline UL power-not-ready
mask (bits 19:15). UL done counts IRQ events; neither those events nor
interface TX counters prove that a particular packet reached the radio.
The counter by itself does not identify a failing rail or wake handshake.

### Same-device Android comparison

With `boot-review6.img` (`6.6.30-4k-g061b7bdafc86`), Android selected
SIM2 for mobile data. A temporary kprobe recorded the v2 ISR's four
register values after its reads and before it acknowledged either
direction. The loaded `ccci_dpmaif` module build ID
`e695f488e64f783e834131e8cb176792ff84724b` matched the disassembled
module: at `drv2_isr+0xa4`, x21/x22 hold UL status/mask and x19/x20
hold DL status/mask. Counts below use status with the masked bits
removed. The vendor ISR acknowledges UL power-not-ready along with the
other enabled bits; it has no special retry for that event.

| Android SIM2 data RAT | Interface with IPv4 | Ping replies | UL power-not-ready ISR samples (5 s idle / ping window) | DL done ISR samples (idle / ping) |
| --- | --- | --- | --- | --- |
| LTE | ccmni0 | 5/6 | 3/5 (queues 0 and 1) | 18/12 |
| NR_SA | ccmni2 | 3/6 | 0/4 (queue 0) | 6/12 |

The read-only AO snapshots showed PIT write and read indices advance in
both runs (LTE +78; NR +46). The IRQ and ring counts include Android
background traffic; they cannot be attributed to individual pings. The
Android run used ICMP, not the mainline UDP/TCP probe, and Android chose
the PDP itself. The user's Android network policy was restored to the
original LTE-capable mask, and the trace instance and module were removed.

This establishes that power-not-ready can coexist with working NR
downlink on this board. It also exposes a bearer-selection difference:
Android used ccmni2 for the observed NR session, while mainline's
single-interface test sends and receives DPMAIF channel 0. The ACK
driver uses the CCMNI index as the UL descriptor channel. Compare
the modem's CID-to-interface and LHIF mapping during activation before
changing the mainline channel; Android's interface number alone does
not establish which channel the modem assigned to mainline CID 1.

Android's radio log reported active calls on both ccmni0 and ccmni2 in
both configurations. Across the switch, the framework call IDs changed
from 100/302 to 400/502 for ccmni0/ccmni2, respectively. These are Android
call IDs, not the modem's raw AT CIDs. Select the interface with the
tested IPv4 bearer rather than assuming ccmni2 is reserved for NR.
Earlier mainline work also recorded a CID 1 activation associated with
an LHIF remap for net_if=1, queue 0 (see the UL bring-up section of
[MODEM-BOOT-RELEASE.md](MODEM-BOOT-RELEASE.md)). The next mainline run
should capture LHIF requests across activation, including repeated
requests for an existing entry. A final remap table alone cannot
attribute an entry to that specific activation.
