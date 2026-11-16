<!-- SPDX-License-Identifier: GPL-2.0-only -->
# MT6893 bootstrap RPC / FS / NVRAM service audit

2026-11-16. Offline source audit at baseline `82dbc5aa7`; no firmware,
NVRAM contents, device identifiers or device I/O were read for this work.
This document establishes transport and ownership contracts, not modem boot
or radio readiness. The new bounded RPC codec is synthetic-peer tested;
there is no hardware RPC or FS service acceptance result.

## Sources and evidence limits

References below use these local roots:

- **A**: `/data/src/kernel_oddo_mt6893/drivers/misc/mediatek/eccci`, the
  same-board Android 4.19 driver. A spoofed uname does not change its origin.
- **V**: `/data/src/6.6-exp/android_kernel_modules_oneplus_mt6833/kernel/kernel_device_modules-6.6/drivers/misc/mediatek/eccci`,
  the working same-board 6.6 port.
- **U**: `/data/src/reverse-analysis/op6893-modem-userspace-analysis.md`.
- **L**: `/data/src/reverse-analysis/op6893-modem-mainline-checklist.md`.

A/V are primary local source evidence. U/L contain prior reverse engineering
and runtime observations, cited as such. The service audit does not independently
repeat their firmware analysis or access their original private traces.

## Exact normal-ring routing

| Service | MD to AP channel | AP to MD channel | Normal TX/RX queue | Exception TX/RX queue | Vendor endpoint |
|---|---:|---:|---:|---:|---|
| FS | 14 | 15 | 4 | 1 | `ccci_fs` |
| RPC userspace | 32 | 33 | 1 | 1 | `ccci_rpc` |
| RPC kernel | 32 | 33 | 1 | 1 | `ccci_rpc_k` |

A `inc/ccci_core.h:329-348` defines the channel numbers. A
`port/port_cfg.c:12-39` selects `DATA_FSD_Q=4` when `MD_GENERATION>6292`;
`DATA_FSD_Q=1` belongs to the older branch, not MT6297. Its FS entry at
130-132 and RPC entries at 178-182 bind these queues. V
`port/port_cfg.c:21,42-44,90-94` agrees; its later generation table also
has FS and RPC entries at 229-232 and 278-282. Exception queue values do
not authorize routing normal service packets through exception rings.

Both FS and userspace RPC retain the 16-byte CCCI header
(`PORT_F_USER_HEADER`). Kernel RPC has no character node and runs
`rpc_msg_handler` through a kernel worker. A `port/port_rpc.c:1364-1389`
and `port/port_char.c:106` describe this split. FS remains an opaque
character transport in the vendor kernel; file semantics live in userspace.

CCCI TX sequencing belongs to the transport. A
`hif/ccci_hif_internal.h:155-181` assigns an independent per-channel TX
sequence, sets assert, then clears assert for FS/RPC whenever MD state is
not `BOOT_WAITING_FOR_HS2`; V's corresponding helper at 125-151 has the
same rule. U §12.6.5 observed equal request/reply upper header bits at the
character boundary. That observation must not override transport assignment
on the wire. Matching a service response must use its leased request and
protocol transaction fields rather than requiring equal TX/RX sequence.

## RPC ownership and framing

A `port/port_rpc.c:1401-1464` routes only `0x400f` (AP property query)
and `0x4010` (SAR table index) to userspace outside the optional LGE
factory configuration. Every other operation is kernel-owned, including
unknown IDs. V `port/port_rpc.c:1684-1735` additionally routes `0x4014`
(AMMS DRDI) and `0x4015` (save MD CAPID) to userspace. This is a real
cross-version difference: it does not establish either operation as a
same-board 4.19 firmware requirement. U §4 explicitly says its vendor
rpcd contains an unreachable AMMS branch under the A routing policy.

The complete packet is a 16-byte CCCI header, then little-endian `u32
operation`, `u32 argc`, and `argc` instances of `{u32 length, byte value}`.
Each value occupies `ALIGN(length,4)` bytes. A
`port/port_rpc.h:185-200` defines six maximum arguments, packet cap 2048,
`RPC_REQ_BUFFER_NUM=2`, response mask `0xffff0000`, and RPC result codes.
The actual A handler at 1234-1348 (V at 1444-1556) limits the complete
skb to 2048 bytes. Its slot guard is `header.reserved > 2`, so the codec
preserves the actual accepted inclusive slot domain 0..2; the comment
"support 2 concurrently request" does not prove a stricter 0..1 wire rule.

Replies retain data0 and reserved slot, set channel 33, replace total
length, OR the operation with `0xffff0000`, and rebuild the aligned
argument vector. Unlike FS, RPC requests have no response-mask high bits.
The strict new codec validates complete packet length, direction, operation
phase, bounded argument spans and exact exhaustion; output padding is zero.
A codec rejecting an inconsistent packet does not assert that vendor code
was equivalently strict.

RPC result codes are separate from the filesystem result namespace:
`NO_OP=-1`, `PARAM_ERROR=-2`, `NO_FEATURE=-3`, `NO_MATCH=-4`,
`FUNC_FAIL=-5`, `ERROR_RESERVED=-6`, `MEM_OVERFLOW=-7`.

## Typed RPC policies: what can be implemented now

A `port/port_rpc.c:643-1228` implements different response schemas per
operation; one universal `(0,value)` reply is incorrect.

| Operation | Source behavior | Mainline policy until real backend exists |
|---|---|---|
| Unknown kernel op | Default case returns one 4-byte `NO_OP=-1` argument | This exact unsupported-operation reply is implementable; it does not mean a known mandatory service is satisfied |
| `0x4001/02/03`, EINT/GPIO/ADC name lookup | At least two arguments; two scalar result arguments, including duplicated result/error | Decode strings and use real named bindings; do not invent GPIO numbers |
| `0x4004`, EMI clock/type | Zero request arguments; three scalar response arguments; failure repeats `FUNC_FAIL` | Require actual DRAM provider; zero-success is not an unavailable indication |
| `0x4006/07`, GPIO/ADC value | One scalar request; two duplicated scalar result arguments | Validate exact scalar size and use real provider |
| `0x4008`, RF clock buffer | Packed 6-byte request; packed 18-byte result plus scalar status; conditional implementation | Do not fabricate PMIC/external-clock flags or perform AFC writes from unchecked input |
| `0x4009`, GPIO/ADC compound | Packed v1 or v2 request and fixed packed result | Validate exact known schema/version; no raw hardware-number passthrough |
| `0x400d`, LHIF mapping | One 8-byte `{net_if,lhif_q}` argument; invokes real queue remap, returns two scalar zeros | No success until packet data path and validated mapping exist |
| `0x400e`, DTSI query | One packed 66-byte request `{req,index,name[64]}`; scalar status and 68-byte `{value,string[64]}` reply | Typed allowlist of audited properties; no unrestricted DT disclosure |
| `0x400f`, property query | Userspace `property_get(key)` | Explicit userspace provider and approved property map; never Android property API in kernel |
| `0x4010`, SAR table | Userspace project/hardware/region lookup | Real board table/policy; never pretend zero is a calibrated result |
| `0x4011`, efuse | Conditional vendor programming hook | No bootstrap implementation or generic passthrough |
| `0x4013`, card type | A only logs and breaks without building a typed result | Treat as unresolved rather than claiming a verified response schema |

These are source schemas, not a proven list of RPCs issued during cold
bootstrap. U §11.3 reports a quiet userspace rpcd observation window, and
§11.6 observed kernel `0x400d` during flight-mode handling. Neither captures
a complete cold-boot kernel RPC request census. Thus the first implementation
can provide framing, ownership and explicit backend admission, while MD
release remains gated on actual services. Unknown-op behavior cannot replace
all unimplemented known operations.

The new `ccci-rpc-protocol.{c,h}` intentionally implements only framing,
A ownership classification, bounded reply encoding and request/reply identity.
It exposes no hardware callbacks, files, properties or automatically successful
RPC service. Argument slices borrow the immutable complete request buffer;
consumer lifetime must extend through dispatch. Encode inputs/output must not
overlap. The caller owns transport generation, queues, deadlines and TX sequencing.

## FS and NVRAM requirements

U §12.6.4-8 and L §5 establish the following previously observed contract:

- FS requests and replies both use `0xffff0000 | op`, with aligned
  length/value arguments after the CCCI header. This differs from RPC's
  request-versus-response operation phase.
- MD FS has five transaction buffers. Per-CCCI payload is at most `0xd80`;
  larger logical messages use fragmentation. U reports logical packet cap
  `0x40c8` and slot allocation `0x40dc`. A separate local static audit of
  `ccci_mdinit` (SHA256
  `0740831c74b699ee802a7e7c0ccb25266a29f4105a5dc233203ef9dc2ff71a4e`)
  established repeated opcode and 20-byte prefix: bit31 is MORE (`0x17ff8`),
  bit30 is accepted/cleared (`0x17ed4..0x17f18`), continuation appends after
  byte20 (`0x182c8`), and final header wins (`0x18310`). The actual C codec
  and synthetic regression implement these rules; no binary was copied into
  evidence. There is no wire fragment ordinal, so same-slot/same-opcode
  continuation loss/reordering is not detectable from this format alone.
- The observed boot workload needs Open `1001`, Seek `1002`, Read `1003`,
  Write `1004`, Close `1005`, CreateDir `1007`, GetFileSize `1009`, Move
  `100c`, FindFirst `1012`, GetDrive `101a`, SetDiskFlag `101c`, compound
  Read `1022`, and GetFileDetail `1025`. The broader vendor service has
  31 operations; the observed 13 are not proof other scenarios never use more.
- Paths are UTF-16LE, backslash becomes slash, drive-letter mapping is fixed,
  and `..` is refused. New userspace service should anchor each drive at an
  opened directory and prevent symlink traversal as well as lexical escape.
- Filesystem failures use `ENOENT→-9`, `EACCES→-16`, `EMFILE→-5`, invalid
  handle `-10`, other failures `-18`; these are not RPC's `FS_*` constants.
- `0x1022` takes a 40-byte control structure. The observed `0x1f` stage mask
  requests open, size, seek, read and close. Reply arguments are stage/error
  pair, total file size, read count and bytes; there is no extra scalar return
  code. Padding and returned byte counts must remain exact.
- Open writable/create/truncate semantics and close-time fsync matter.
  U/L report fsync on close when original flags contain any of `0x1000000`,
  `0x10000` or `0x20000`. Read-only dummy files cannot validate persistence.

`Z:` (nvdata MD tree) and `X:` (protect_f MD tree) are real persistent
inputs; optional missing certificate/config files returning `-9` were tolerated
in the previously observed Android boot. That observation does not justify
returning `-9` for every NVRAM file or synthesizing calibration contents.

U §12.6.14 / L §5.7 show AP libnvram and MD service share the tree with no
cross-process lock in the original implementation, gated by initialization
ordering (`Ready` or `Pre_Ready`). A mainline service must have a prepared,
private working copy and explicit ownership before MD release, rather than
mount/write Android's original NVRAM tree concurrently. Copy preparation is
separate authorized work; this audit did not copy any data. File contents,
identities and calibration bytes must not enter logs or evidence archives.

L §4.8 documents firmware consumers requiring runtime feature ID36 NVRAM
cache, and reports that population of that cache is still unknown. Valid
reserved memory and a functioning filesystem transport do not by themselves
prove cache initialization. Do not mark the runtime feature supported merely
because its region exists.

## Implementation follow-through

The codecs, normal service TX and generation/request-token router have now
been implemented and tested offline, together with a structured private-copy
FS prototype. They do not yet have a Linux live caller, backend wire adapter,
worker/timer or actual RPC providers. See [current implementation and remaining
milestone](MODEM-SERVICES.md); the following integration requirements remain.

## Combined next milestone

1. Connect normal FS q4 and RPC q1 to the implemented bounded service
   router, retaining generation/token ownership and exclusive providers. Close admission and drain
   consumers before MD power-off. Queue/resource exhaustion must fault or
   backpressure deterministically, not silently lose a mandatory request.
2. Preserve existing synthetic malformed-packet, fragment, stale/duplicate
   reply and sender/STOP coverage while adding Linux worker/backend lifetime
   integration tests. Add no empty hardware test for pure codecs.
3. Add real userspace FS provider over a private working tree, audited
   fragmentation, NVRAM preparation/cache policy, and typed RPC providers.
   Any unavailable capability keeps MD start disallowed; do not advertise
   unimplemented runtime support.
4. Only then combine MD CPU release, HS1/HS2, post-HS2 CCISM and real
   service traffic in one on-device milestone. HS2/CCISM completion alone
   does not establish SIM, network registration, AT or packet data support.
