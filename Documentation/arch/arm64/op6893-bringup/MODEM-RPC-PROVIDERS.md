<!-- SPDX-License-Identifier: GPL-2.0-only -->
# RPC providers: bounded facts and explicit availability

2026-11-16. Offline implementation of typed RPC replies from immutable,
explicitly supplied board facts. No live GPIO, ADC, OTP, property service,
DT traversal, file operation or modem CPU operation is performed. No board
fact table is populated automatically. The experimental endpoint now routes
kernel-owned RPC requests through these providers; its default provider is
`NULL`. Passing synthetic tables in tests does not establish real device RPC
availability or modem boot success.

## Audited sources

A root: `/data/src/kernel_oddo_mt6893/drivers/misc/mediatek/eccci`.
V root: `/data/src/6.6-exp/android_kernel_modules_oneplus_mt6833/kernel/kernel_device_modules-6.6/drivers/misc/mediatek/eccci`.
Both refer to the same-board implementations; A is Android 4.19 and V is
the working 6.6 port. Exact inputs:

| Root-relative file | SHA256 |
|---|---|
| A `port/port_rpc.c` | `4319787e8a0523a0021ae653569af886f94263bf8cede3f55282f7e073fa11d5` |
| A `port/port_rpc.h` | `4279770775f06b9de763a5037fd728114c77416c07576015edad2eb3b4c93e30` |
| V `port/port_rpc.c` | `c715e01fbb7537fdcc12f6889d1be04e5fd86590c9a04aa6818f157932486ca2` |
| V `port/port_rpc.h` | `7bf91ff23571dde7e242d69bf8370c48904e5d5beda5cf9c0d69d1f2bb567574` |

`MODEM-SERVICES-AUDIT.md` describes framing, ownership and evidence limits.
This document adds a known-ID census and the first source-backed pure providers.

## Known operations are not unknown-operation fallbacks

`ccci_rpc_provider_known()` covers the union of declared A/V operations,
the optional LGE range, and the explicitly reserved ID `0x400c`. These IDs
remain known even when a vendor build excludes their case using a Kconfig
or feature macro. That conservative classification prevents a missing known
service from silently receiving an unknown-op response.

| ID | A/V meaning | This provider |
|---|---|---|
| `0x2001` | secure algorithm | unavailable |
| `0x2002` | secure RO region | unavailable |
| `0x3001..0x3012` | conditional LGE factory/SIM-lock/identity operations | unavailable; no identity or factory handler |
| `0x4001` | TDD EINT name lookup | unavailable |
| `0x4002` | GPIO name to MD-view number | complete audited GPIO snapshot required |
| `0x4003` | ADC name to channel number | complete audited ADC snapshot required |
| `0x4004` | DRAM type/clock | unavailable |
| `0x4005` | SIM EINT attribute lookup | complete audited, MD-converted EINT snapshot required |
| `0x4006` | live GPIO value | unavailable |
| `0x4007` | live ADC value | unavailable |
| `0x4008` | RF clock buffer configuration/AFC | unavailable |
| `0x4009` | combined GPIO/ADC lookup/sample | unavailable |
| `0x400a` | USIM-to-NFC notification | unavailable |
| `0x400b` | declared DSP EMI MPU operation | unavailable |
| `0x400c` | reserved | unavailable |
| `0x400d` | live LHIF queue remapping | unavailable |
| `0x400e` | MD DT u32 property query | complete audited MD property snapshot required |
| `0x400f` | AP Android property query | unavailable, user-owned under A routing |
| `0x4010` | board/region SAR table index | unavailable, user-owned under A routing |
| `0x4011` | conditional efuse programming | excluded |
| `0x4012` | TRNG, added in V | unavailable |
| `0x4013` | card-type query | unavailable; A only logs without typed result construction |
| `0x4014` | AMMS DRDI control, added in V | unavailable; V user-owned, not A |
| `0x4015` | save MD CAPID, added in V | unavailable; V user-owned, not A |
| `0x4016` | RF ECID information, added in V | unavailable |
| `0x4017` | conditional AFC/UFS I/O block operation, added in V | unavailable |
| `0x4321` | diagnostic integration-test operation | unavailable |

Sources: enums in A `port_rpc.h:12-56`, V `port_rpc.h:12-61`, A helper
switch at `port_rpc.c:643-1228`, V switch at `789-1440`; A routing at
`1401-1464` versus V `1684-1735`.

A genuinely unknown low-16-bit operation receives exactly the A default-case
response: one little-endian signed `-1` argument, operation ORed with
`0xffff0000`, original data0 and request slot retained. The provider does
not apply this response to known unavailable IDs. A high-bit response passed
as a request is rejected by the existing RPC codec.

## Snapshot contract and API

`ccci-rpc-provider.{c,h}` exposes:

- `ccci_rpc_provider_known(operation)` for the census above;
- `ccci_rpc_provider_available(provider, operation)` returning 1/0, or a
  negative snapshot validation error;
- `ccci_rpc_provider_reply(provider, request, length, reply, capacity)`
  returning complete packet bytes or a negative host error.

Each namespace has an explicit `*_present` flag, a pointer and a count.
The flag asserts an audited **complete namespace**, including absent names;
absence of a backend cannot be represented by enabling an empty table and
calling every lookup a failure. Each table admits at most 32 entries, with
nonempty NUL-terminated names up to 63 bytes, no duplicates. GPIO and ADC
numbers must fit nonnegative signed 32-bit results. EINT attributes may hold
negative provider error values; they are processed according to vendor lookup
rules. DT u32 values use the full unsigned range.

Storage is owned externally and immutable. When installed in the endpoint,
the provider and its table storage must survive stopped cleanup and worker
joins; a call-scoped snapshot is insufficient. Fact storage, packet and output
must not overlap. No values are read from DT or
hardware by the provider. A future owner must populate snapshots from
verified resources and provenance before it advertises them as available.

A `NULL` provider has no available known services. Known unavailable IDs
return host `-EOPNOTSUPP` with output unchanged. Malformed records return a
host protocol error; invalid table configurations return `-EINVAL`. Buffer
capacity failure returns `-ENOSPC`. Every negative return preserves the
entire caller output; the existing two-pass reply codec writes only after
successful sizing. These host errors are not serialized as arbitrary MD
error codes. The endpoint propagates a provider failure to the service
session, which contains the generation instead of delivering that request
to userspace or fabricating an MD reply.

## Endpoint integration and ownership

`ccci_service_endpoint_set_rpc()` validates an explicitly supplied snapshot
and installs its immutable pointer while the endpoint is dormant. It rejects
changes after removal, backend reservation or arming. This setter does not
populate board facts, grant general RPC readiness or start MD. Leaving the
provider `NULL` keeps every known kernel service unavailable; it is the
default, not a placeholder board implementation.

The serialized service worker decodes RPC ownership before adding an endpoint
request to the userspace queue. Kernel-owned requests call
`ccci_rpc_provider_reply()` directly, and successful typed packets re-enter
the same session reply validation and CCIF TX path. A known unavailable ID
fails with host `-EOPNOTSUPP` and causes containment, with no userspace fallback.
Genuinely unknown IDs use the audited one-argument vendor `NO_OP` response
through this kernel path, including when the provider is `NULL`.

A routing still assigns only `0x400f` and `0x4010` to userspace. Those requests
remain endpoint records for a real AP property/SAR implementation; they are
not handled by the immutable kernel providers. The explicit
`tools/modem_service_backend.py` runner currently implements only FS and
rejects any RPC record, then closes the endpoint. Therefore its presence
does not satisfy either userspace RPC service. V-only user routing for
`0x4014`/`0x4015` is not inherited.

## Implemented typed replies

### GPIO and ADC names: `0x4002` / `0x4003`

A `port_rpc.c:643-727`, V `789-873`: request has 2..6 arguments; argument
0 is the name. The remaining arguments are not interpreted by these helpers.
A successful number is returned twice as two 4-byte result arguments;
provider lookup failure becomes `FUNC_FAIL=-5`, also duplicated. Invalid
argument count produces duplicated `PARAM_ERROR=-2`.

A `get_md_gpio_info` at `port_rpc.c:174-213` looks up an AP GPIO to validate
it exists, but the reply returns the **MD-view number**, read from the second
property cell, rather than the AP global GPIO number. The new GPIO snapshot
must therefore contain MD IDs whose AP relationship has already been checked.
ADC snapshots similarly contain audited channel numbers, not sample values.

Names match exactly, optionally including one final NUL. Empty, oversized or
interior-NUL names are rejected before encoding. Vendor prefix matching and
unbounded string assumptions are not reproduced: a partial prefix does not
select the first GPIO mapping. Snapshots must contain every explicitly allowed
MD-facing alias; callers must not label a partial alias table complete.

### SIM EINT attributes: `0x4005`

A `get_eint_attr_DTSVal` at `port_rpc.c:365-396` and helper case
`775-846`; V corresponding lookup `411-439`, case `921-997`:
request needs 3..6 arguments, name at argument 0, attribute type as an exact
4-byte argument 2. Success gives `(status=0, value)`, both 4 bytes. Invalid
argument count gives duplicated `-2`; type outside 0..6 gives duplicated
`-12`; missing name or a negative stored attribute gives duplicated `-11`.
These follow A `port_rpc.h:221-225` and V `port_rpc.h:242-246`: the enum
starts at `NULL_POINTER=-13`, then implicitly **increments** to
`QUERY_TYPE=-12` and `QUERY_STRING=-11`. The source-derived enum regression
fixture guards against incorrectly decrementing those negative constants.

Attribute indices: number, debounce, polarity, sensitivity, socket type,
dedicated enable, source pin. Snapshots contain **MD-domain results**.
A `get_eint_attr_val` at `port_rpc.c:278-329` converts AP debounce us to
MD ms by division by 1000; it derives polarity and edge/level sensitivity
from the IRQ flags. Raw AP GIC interrupt IDs or unconverted microseconds
cannot be inserted as if they were final MD values. This provider deliberately
does not perform DT parsing or invent those conversions from unavailable data.

### MD DT property query: `0x400e`

A helper `port_rpc.c:1152-1182`, getter `405-433`; V corresponding getter
`451-479`, helper `1304-1334`. Exactly one 66-byte packed request:
`{u8 request, u8 index, char name[64]}`. The name must be nonempty and NUL
terminated within its fixed field. `request==1` queries an immutable u32
property; source ignores index. Unsupported request kinds do not query a table.

The response has two arguments: scalar status 0 and a 68-byte packed
`{u32 retValue, char retString[64]}`. Vendor code initializes the entire
68-byte result with **byte `0x0f`**, then replaces only the first u32 when
request kind 1 finds a property. Thus an audited absent property or other
request kind produces `retValue=0x0f0f0f0f` with string bytes all `0x0f`.
This is a source-proven wire indication, not invented zero-valued metadata.
The returned string is not NUL-terminated and must not be printed with `%s`.
Invalid argument count produces two scalar `-2` results; wrong packed
argument size is rejected as malformed before any reply.

## Why other apparently simple handlers remain unavailable

- A `get_td_eint_info` at `port_rpc.c:116-119` and
  `get_dram_type_clk` at `234-237` are hardcoded `-1`. Although their
  helpers produce typed failure replies, this does not prove working TDD
  or DRAM providers. There is no reason to advertise measured DRAM facts
  without a source defining both their values and units.
- A LHIF mapper `port_rpc.c:596-625` changes a real network port's TX queue:
  AP_UL_Q0 maps queue 0, AP_UL_Q1 maps queue 3. The helper case at 1120-1150
  ignores the remap result and emits two zeros. Returning those zeros without
  the data path would hide a missing required side effect.
- AP property and SAR replies require exact userspace schemas and an actual
  board/region policy. Knowledge that rpcd calls `property_get()` is not enough
  to invent a length, termination or fallback contract.
- RF clock-buffer and NFC handlers have side effects, while GPIO/ADC value
  operations are live reads. Immutable name mappings do not establish those
  capabilities. Efuse/OTP programming is intentionally outside bootstrap work.
- V adds TRNG/ECID/UFS operations and additional userspace routing. Their mere
  presence in the working port does not prove the MD issued them under A or
  authorize treating every V feature as supported in mainline.

## Validation and remaining work

`tools/test_modem_rpc_provider.py` compiles the actual provider and packet
codec under ASan/UBSan. Synthetic facts exercise both names with/without NUL,
exact-name matching, GPIO MD-ID/ADC results, all EINT result forms, DT packed
schema/default bytes, known/unknown classification, disabled services, invalid
snapshots/duplicates/counts, malformed packets and unchanged output on error.
No hardware-dependent values are embedded in those fixtures.
`tools/test_modem_service_endpoint.py` also exercises the actual endpoint
branch: unknown kernel `NO_OP`, known unavailable containment without a user
record, snapshot installation and lifecycle rejection, and typed provider
replies through the session TX path.

Remaining: obtain and validate the actual board snapshot contents, determine
cold-bootstrap RPC demand, add live providers only with their required owners
and resource lifetimes, and establish complete capability/admission checks
before MD release. Implement the user-owned property/SAR schemas and policy
separately. Kernel dispatch is wired, but no new radio or real modem RPC
support acceptance is claimed.
