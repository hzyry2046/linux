<!-- SPDX-License-Identifier: GPL-2.0-only -->
# User RPC: property and SAR contracts

2026-11-16. `tools/modem_rpc_backend.py` provides a pure packet codec and
immutable caller-supplied providers for `0x400f` and `0x4010`. It reads no
Android properties, device state, identity, firmware or partitions. No actual
board policy or property values are supplied by this implementation. This
establishes a source-backed wire contract, not successful modem operation.

## Inputs and reproducible static evidence

The AP executable is
`/data/src/reverse-analysis/conninfra-rev/modem/sources/bin/ccci_rpcd`:

- SHA256 `edfa5a37567631c589953f1cbca51eb2f52872500c62779707229c487accee75`;
- 42,944 bytes, AArch64 PIE, Build ID `f0204ec1b779766dfaa4017307ad7176`;
- executable addresses below are ELF virtual addresses, also file offsets
  within its text segment (`0x6000..0x800f`). Ghidra's default image base is
  `0x100000`, which must be subtracted from its displayed addresses.

The existing `/data/src/reverse-analysis/op6893-modem-userspace-analysis.md`
section 4 identifies these handlers; this work checks their argument and
reply construction against both decompilation and `llvm-objdump` instructions.
Only contract summaries are retained here; no executable, property dump or
complete decompiler output is committed.

The property library contract is cross-checked against local source, not
claimed to be a byte-for-byte match for the original device library:

| Input | SHA256 | Evidence |
|---|---|---|
| `/data/src/mikuui/system/core/libcutils/properties.cpp` | `abd6c0bfae09980320b331352654fead972d1003229923268d0fffdc21719de0` | `property_get()` at lines 85–92 returns underlying length; uses fallback only when a non-NULL default is supplied |
| `/data/src/mikuui/bionic/libc/system_properties/system_properties.cpp` | `533637ad454b733c220657639db5c3119957ff34affd1c02339aea1c085c781d` | `SystemProperties::Get()` at lines 259–267 returns 0 and writes a terminating NUL when the property is absent |

A `port_rpc.c:1401..1464` assigns these two operations to userspace. V adds
other user operations; they are deliberately outside this provider.

## Framing and ownership

The complete packet uses the existing six-argument RPC envelope: 16-byte CCCI
header, little-endian operation and argc, then `{u32 size, bytes}` arguments
rounded up to four bytes. The decoder checks exact total length, every span
and padding extent, at most six arguments, maximum 2048 bytes, RX channel 32,
request operation without high response bits, and slot 0..2. It accepts
arbitrary padding contents but emits initialized zero padding.

Replies preserve data0 and request slot, set channel 33, OR the operation
with `0xffff0000`, and set exact total size. The upper channel word is retained
as opaque metadata; actual TX sequence/assert assignment belongs to HIF, as
with the existing kernel codec. No lease, generation, timeout, duplicate or
transport ownership is implemented by this module.

Malformed packets raise `MalformedRequest`; missing services/facts or any
other operation raise `Unavailable`. Neither is serialized as an invented
MD error. The caller must contain the transaction on either exception.

## Property query `0x400f`

The executable branch at `0x74a0..0x7528`:

1. Takes the first request argument's pointer and length, then writes a NUL
   after that length (`0x74a0..0x74a8`).
2. Calls `mtk_property_get(key, value, NULL)` at `0x74ac..0x74b8`. Its wrapper
   at `0x79e8` transfers to `property_get`.
3. Saves the returned length as a four-byte scalar and computes
   `strlen(value)+1`, with a 92-byte checked buffer (`0x74bc..0x74f4`).
4. Returns two arguments: signed length, then value bytes **including NUL**
   (`0x74f8..0x7524`). For `abc`, these are `{4, 3}` and `{4, "abc\0"}`;
   a proven absent/empty property returns `{4, 0}` and `{1, "\0"}`.

The vendor branch does not check a per-operation argc. The adapter requires
at least one argument and ignores later arguments up to the codec limit,
matching the branch's actual accesses. It accepts a key with or without one
final NUL. It rejects an empty key and interior/repeated NULs instead of
reproducing truncation or the vendor's unchecked write. Values are bounded
to 91 bytes plus their terminator; no truncation, encoding conversion or
host environment fallback occurs.

`PropertySnapshot(facts)` takes an immutable tuple of `(key_bytes, value)`:

- byte values mean an explicitly audited MD-visible property value;
- `None` means an explicitly audited absent/inaccessible property and produces
  the proven empty result;
- an unlisted key raises `Unavailable`, even when the fact tuple is empty.

A partial approved map is safe because it never treats an unreviewed key as
absent. Duplicate keys, mutable containers, NULs, oversized values and invalid
fact types are rejected. Snapshot and request reprs hide their payloads.
Returning an empty response for every unknown key would conflate missing
policy with Android's actual property absence and is deliberately forbidden.

## SAR query `0x4010`

`mtk_sar_table_id_get` is at `0x79ec..0x7bd4`. It initializes the result
index to `0xffff` (`0x7a38..0x7a40`) before reading two properties:

- `ro.product.hw`, default empty string, pointer `0x1830`;
- `ro.vendor.oplus.radio.sar_regionmark`, default `CE`, pointer `0x155d`.

The helper compares the hardware string against a 62-entry project table
(`0x7aac..0x7b00`). The table begins at `0x9470`, with 24-byte records:
region-table pointer, u32 count plus padding, project-name pointer. For a
matched project it scans 16-byte region records: name pointer, u32 index plus
padding (`0x7b28..0x7b78`). Matching uses case-sensitive `strcmp`; a match
copies that exact u32 index (`0x7b9c..0x7ba0`). Missing project or region
retains `0xffff`. There is no zero-index fallback.

The helper returns **zero unconditionally** on its normal path
(`0x7bb4`), even though its caller logs a confusing "fail" when return is zero.
The caller at `0x7780..0x77f8` returns two four-byte arguments: status 0 and
the selected index. No request payload is read by this operation; the adapter
therefore accepts any codec-valid argc 0..6 and ignores its arguments.

`SarSnapshot(product_hw, regionmark, projects)` reproduces only this pure
selection algorithm. Both strings are already resolved, explicit bytes from
the caller. The module never fetches them or silently inserts defaults.
`projects` must be an immutable **complete audited** policy, shaped as:

```python
((b'hardware', ((b'region', 7), (b'other_region', 9))), ...)
```

The names and indices in this example are synthetic. Construction is the
caller's assertion that the policy is complete for this firmware/board;
passing a tiny invented table to obtain a no-match sentinel violates that
contract. The implementation bounds projects and regions at 128 each,
rejects duplicate names and non-u32 indices, and requires nonempty region
lists. This includes the source's 62-project shape without baking in any real
board choices. A disabled provider remains `None` and raises `Unavailable`.

Actual deployment remains blocked on supplying and reviewing the complete
applicable policy and resolved hardware/region facts. Although the executable
contains the policy, this change does not export its entire table, select a
real-device region, infer calibration suitability, or claim that the MD has
requested SAR. No raw caller-selected default index is substituted for that
review.

## API and validation

The stable pure API is:

```python
reply = respond(request_packet, properties=property_snapshot, sar=sar_snapshot)
```

Either provider may be `None`. The snapshots are frozen, nested storage is
validated as immutable, and reprs do not expose their contents. The explicit runner now accepts a caller-supplied private `--rpc-policy` JSON;
see [integration and policy schema](MODEM-BOOTSTRAP-PROFILE.md). It retains the endpoint's generation/token/slot checks and
must not infer complete service readiness from merely opening a provider.

`tools/test_modem_rpc_backend.py` runs seven synthetic test groups covering
exact reply bytes, terminators, explicit absence versus unknown facts,
91-byte bounds, ignored extra arguments, SAR selection and sentinel, disabled
providers, malformed frames, immutable facts, and packet identity. It also
compiles the actual `ccci-rpc-protocol.c` under ASan/UBSan and validates five
Python-produced request/reply pairs against the kernel decoder and reply
validator. No device, identity or real property values are used.

## Observed queries and audited facts

The runner can print the request operation and a bounded printable request
name with the explicit `--trace-rpc-names` flag. It prints no value, writes no
reply, and is off by default; it exists so a policy can be authored from the
MD's real queries instead of guesses. `--trace-fs` does the same for the file
service and reduces every write payload to a byte count.

On this unit the MD asked `0x400f` for `ro.build.version.svn.c`,
`ro.build.version.svn` and `ro.build.version.ota`. All three are absent from the
device's own `getprop` output, so the Android `property_get()` answer is a
zero-length value, which the policy expresses as an explicit `null` fact rather
than an unknown key. The export used to establish that is kept outside any git
tree with identity keys removed; only the keys the MD actually asks for are
copied into the policy.

Answering those queries moved the same release sequence from `tx=88` (endpoint
closed on the first query) to `tx=964 tx_error=0`, with the exception point
unchanged. See
[the release log](MODEM-BOOT-RELEASE.md) and
`evidence/modem-rpc-policy-live-boot.json`.
