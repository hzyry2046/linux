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

## Mainline result

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

The physical slot test should use different carrier subscriptions or a
one-card-at-a-time matrix. Capture Android's UART2 startup and per-DLCI AT
framing, then reproduce the earliest initialization step that makes the
two slot responses distinct. Only then use the Android settings trace to
map LTE-only and NR-allowed policy values and data-SIM selection; verify
actual registration and data after each change. Android boot traffic includes
ERAT and EDATASIM writes, but it does not isolate the mapping from a settings
toggle. Neither NR SA/NSA attachment nor LTE/NR band locking was exercised
on mainline in this run.
