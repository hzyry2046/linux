<!-- SPDX-License-Identifier: GPL-2.0-only -->
# Feature 36 NVRAM cache: ownership and initialization audit

2026-11-16. Offline source comparison and review of existing analysis only.
No device, original NVRAM files, partition contents or modem firmware contents
were accessed. Source line numbers below refer to the hashed snapshots listed
at the end; the reverse-analysis reports were read as reports, not independently
reproduced firmware analysis.

The current evidence does **not** justify an "AP must prefill a cache image"
blocker. The same-board 4.19 kernel explicitly zeroes this region on its first
MD start, publishes its MD address and size, and contains no NVRAM-cache image
loader. The available 6.6 implementation retains the same zero/retain policy,
with an important call-chain caveat below. Use a correctly sized, zero-initialized
region and working FS service as the initial contract; do not copy qqcandy's
raw-partition fill or invent a cache header.

This corrects a presumed AP-prefill requirement, not every cache readiness
requirement. Valid mapping, feature payload and lifecycle remain necessary.
Whether an unexamined AP userspace path writes the cache after the first clear,
and the exact MD cache-control/header layout, are not proved here.

## Source aliases and identifiers

- **A**: `/data/src/kernel_oddo_mt6893`, same-board Android 4.19 source.
- **V**: `/data/src/6.6-exp/android_kernel_modules_oneplus_mt6833/kernel/kernel_device_modules-6.6`,
  the user's working 6.6 ACK port. The repository's mt6833 name is not proof of
  which CCCI memory path executes; generation checks and callers matter.
- **Q**: `/data/src/mainline/linux-qqcandy-6.18`, different-board MT6895 port.
- **R**: `/data/src/reverse-analysis`, existing analysis reports.

Unless qualified, CCCI paths below are relative to
`drivers/misc/mediatek/`. Runtime feature **36** is not shared-memory user
ID **32**: the former negotiates `NVRAM_CACHE_SHARE_MEMORY`, the latter selects
`SMEM_USER_MD_NVRAM_CACHE` in kernel layout tables.

## A: concrete first-start and reset contract

| Source | Evidence |
|---|---|
| `eccci/ccci_modem.c:93-110` | `md1_6297_cacheable` gives NVRAM cache flags **zero**. In contrast, CONSYS and USIP carry `SMF_NCLR_FIRST`. |
| `eccci/ccci_modem.c:673-690` | Region offset/size come from `get_md_cache_region_info`; the kernel sets layout metadata, not cache data or a cache header. |
| `ccci_util/ccci_util_lib_fo.c:470-493,1336-1355` | Parse LK `md1_bank4_cache_info` and `md1_bank4_cache_layout`; lookup returns the selected entry's offset and size. These are layout descriptors, not serialized NVRAM records. |
| `eccci/ccci_modem.c:465-495` | First start clears every mapped nonempty region lacking `SMF_NCLR_FIRST`. Later starts clear only `SMF_CLR_RESET` regions. |
| `eccci/ccci_modem.c:1390-1429` | Both noncacheable and cacheable lists go through that clearing function. Extra later-start clears name CCB DHL/RAW DHL, not NVRAM cache. |
| `eccci/modem_sys1.c:349-378` | `md_cd_start` directly calls `ccci_md_clear_smem(index,1)` on `MD_SETTING_FIRST_BOOT`, then clears that setting after successful platform start; subsequent starts pass zero. |
| `eccci/ccci_modem.c:1876-1882,1988-2006,2453-2460` | Generation 6297 advertises feature 36 as MUST, then emits the ordinary shared-memory descriptor `{MD address, size}`. There is no cache-content preparation in that helper/case. |

For this flags-zero entry the actual clearing predicates give:

| Lifecycle | AP action on NVRAM-cache contents |
|---|---|
| First MD start of this driver instance | Clear **all `region->size` bytes** to zero before platform start. |
| Later MD restart in the same instance | Do not clear this region in the generic shared-memory clearing code. |
| Kernel/module reinitialization | The first-start setting is initialized again; do not assume retained RAM is a valid cache. |

"First" here means the driver's first-start lifecycle, not proof of a physical
power-off/power-on distinction. `ccci_md_alloc` sets `MD_SETTING_FIRST_BOOT`
at `eccci/ccci_modem.c:512`; an early failed platform start can leave that
setting asserted for a retry. The comment at line 1399 says MD clears shared
memory itself after the first boot. That comment is vendor intent, not direct
proof of which cache bytes MD resets or retains.

Thus a bootloader-prepared cache payload cannot be a mandatory preserved input
to this A path: the kernel destroys it before MD start. This does not logically
exclude a later userspace writer. However, a search of the A MediaTek C/H sources
for both cache identifiers finds layout/name/feature entries, not a writer that
loads partition/file bytes into this region. The char shared-memory ports are
enumerated at `eccci/port/port_cfg.c:285-321`; none selects this user ID.
`eccci/port/port_smem.c:707` maps the selected port's region, while the CCB
selection ioctl at lines 537-548 restricts selection to CCB IDs. Those inspected
interfaces do not establish an NVRAM-cache userspace refill mechanism. This is
a bounded source finding, not a proof that arbitrary privileged AP software
could never access the physical memory through another interface.

## V: same policy in code, unconnected clearing callback

V has split the old `ccci_modem.c` responsibilities:

- `ccci_util/ccci_util_md_mem.c:121,479-497` obtains NVRAM-cache layout metadata
  from the cache-region information; it does not copy a cache image.
- `eccci/fsm/ap_md_mem.c:83` gives the cache region flags zero.
  `ap_md_mem_init:614-650` binds cacheable memory/layout information.
- `eccci/fsm/ap_md_mem.c:212-235,707-736` retains A's first-clear/later-selective
  clear implementation, including the MD-self-clear comment.
- `eccci/fsm/ccci_fsm.c:695-705,819-837,1346-1354` advertises feature 36 for
  `md_gen >= 6297` and publishes only its address/size.

Crucially, do **not** treat the clearing function's presence as evidence that
the working 6.6 kernel executes it. Its only direct caller in the inspected V
tree is `smem_md_state_notification` at `ap_md_mem.c:739-749`, where a static
`init=1` switches first/later behavior on `BOOT_WAITING_FOR_HS1`. Searching that
whole device-modules tree for `smem_md_state_notification` finds only its
definition and the declaration at `ap_md_mem.h:56`: no invocation or registration.
The FSM broadcasts HS1-wait before `ccci_md_start` at `ccci_fsm.c:1488-1495`,
but that alone does not connect this callback. V therefore corroborates the
intended **policy** and absence of a typed cache-fill implementation, not an
executed cold-clear call chain. The user's report that V works does not resolve
its actual initial RAM contents or cache producer.

## What existing MD/AP analysis establishes

`R/op6893-modem-userspace-analysis.md` explicitly leaves cache population
unknown at line 322. Its firmware analysis is useful but narrower than an
AP-prefill claim:

- Lines 803,809-812 (§12.6.11), and checklist line 84 (§4.8), say
  `nvram_cache_init` requires feature 36 and a valid payload. The documented
  assertion is about availability of the negotiated memory descriptor, not a
  proved requirement for an AP-created cache image.
- Lines 717-734 (§12.6.8) describe **file** headers produced by MD
  `nvram_prepare_*_header` and `nvram_write_data_header`. They do not specify
  an AP-produced shared-region control header. Do not conflate the two formats.
- Lines 825-833 (§12.6.12) identify attribute `0x8000` as bypassing the cache
  in MD file-section/header write paths. Lines 838-842 (§12.6.13) identify
  MD `nvram_drv_fat_write_cache_section` and cache-related reset/write paths.
  These support MD managing cached records and flushing them through FS.
- Checklist line 19 and §5 describe MD requesting NVRAM files through FS;
  userspace-analysis lines 881-887 describe one later airplane-mode scenario
  with MD writing through FS and no AP NVRAM-service file writes observed.
  Neither is a snapshot of the feature-36 region or a full producer trace.

The best current model is **MD-owned cache contents, AP-owned reservation,
initial zeroing and FS transport**: MD can populate cached records from FS and
generate its own file/header data. The specific sequence "MD initializes every
cache-control word, then fills every record after a successful FS read" remains
an inference. No exact cache-global header, validity magic, rebuild algorithm,
or warm-reset retention protocol is established by these reports. No such
structure should be fabricated in AP code to make readiness look complete.

AP NVRAM initialization also has a different meaning: the analysis's
`vendor.service.nvram_init=Ready`/`Pre_Ready` gate prepares/restores filesystem
data before MD use. It does not by itself prove a write to feature-36 memory.
Likewise a working private-copy FS provider is not evidence that all required
real device-specific files have been provisioned or that MD accepted the cache.

## Q is an experimental workaround, not a vendor ownership reference

Q `eccci/ccci_modem.c:589-612` fills missing layout information with that
board's observed LK offset/size. This corrects a missing descriptor, a distinct
problem from cache-data initialization; its numerical values must not be
transferred to MT6893.

Q `eccci/port/port_rpc.c:803-923` separately adds an AP raw-partition loader:
it reads up to 2 MiB from a configurable `nvram` block path and blindly copies
the bounded prefix into this shared region. It runs from AMMS INIT at line
1029. Its comment says Android userspace normally refills the cache and links
zero calibration to an audio assertion. Neither a same-board vendor writer,
a cache-format conversion, nor a controlled causal experiment is provided by
this code. Raw storage bytes and an MD cache representation are not established
as interchangeable. The loader's raw prefix logging is also outside this
project's handling policy; no part of that loader was executed here.

Q's reported assertion can be relevant to its board but cannot establish that
MT6893 requires the same fill. In particular, descriptor absence, USIP layout,
FS failures and an actual invalid cache payload must not be collapsed into a
single "zero cache" diagnosis. Do not adopt Q's prefill as a bootstrap blocker.

## Result for mainline work

Correct the blocker from "AP cache population is unknown, therefore AP must
implement a fill before feature 36" to **"provide the valid vendor-sized
feature-36 region with the proven first-start zeroing policy; cache producer
details remain an observation target, not an invented AP input"**.

For a first MD boot, the next useful work is descriptor/layout correctness and
the FS/RPC service path, using authorized private working copies. No new cache
blob import, raw partition read, AP header synthesis or content dump is needed
on the strength of the evidence above. Keep first-start and MD-restart policies
separate: do not re-zero an active cache during arbitrary service reconnects,
and do not claim that reset retention or MD-side reconstruction is verified.
This audit supplies no new hardware result and does not by itself certify MD
service readiness.

## Implemented owner (2026-11-16)

`CONFIG_OP6893_CCCI_NVRAM_CACHE` adds `ccci-nvram-cache.c`: the single owner of
the cached user-32 window. Construction validates the already-parsed geometry
without mapping. `prepare` maps the AP view write-combined, clears every byte
once, and reads back the first and last word; a mapping or read-back failure
latches FAULT. Retries, reconnects and `stop` never clear the region again.
The owner is stopped only after the parent proves MD1 OFF, and it exports no
region content. See [release gate](MODEM-BOOT-RELEASE.md). No cache image,
raw partition read or synthesized header is introduced.

## Reproduction and source hashes

For a source-only cross-reference census, run `rg -n` for
`SMEM_USER_MD_NVRAM_CACHE|NVRAM_CACHE_SHARE_MEMORY` in each tree's MediaTek
C/H sources; separately search V's entire device-modules root for
`smem_md_state_notification`. Read the full clearing functions and their callers,
not only identifier hits. All hashes below are SHA256 of the entire source/report
file, with paths relative to the aliases above.

| Source file | SHA256 |
|---|---|
| A `drivers/misc/mediatek/eccci/ccci_modem.c` | `850e6d9fad97525c163f5a28d8464c1867f79cf16e995a5684b7ff1ea58e4c1b` |
| A `drivers/misc/mediatek/eccci/modem_sys1.c` | `17d8291d852914ad0513ae10e341e600a62c98f89ccb459f295613e91969fad2` |
| A `drivers/misc/mediatek/eccci/port/port_cfg.c` | `74cd62d2a69bad6283e5ca4aab7705636a405390f60e7f259c29b483773323da` |
| A `drivers/misc/mediatek/eccci/port/port_smem.c` | `2ccf14d445976ebe101d273870c5b1cd500de055ca5770ae2002b5c7a266154c` |
| A `drivers/misc/mediatek/ccci_util/ccci_util_lib_fo.c` | `420e21279c890b4d797ba7797fc2816a7ff4b8844d4cc70c12e8de0a7ece57c6` |
| V `drivers/misc/mediatek/eccci/fsm/ap_md_mem.c` | `5d5317caaa6c934a46eac6e65974a29e95f6d65bf5d589a70dcc83735b15f2e3` |
| V `drivers/misc/mediatek/eccci/fsm/ap_md_mem.h` | `f6f7f78862a9139da78e8257e59e6ff8331b49d7edd60e52b22c0becf903e9c2` |
| V `drivers/misc/mediatek/eccci/fsm/ccci_fsm.c` | `de08368078b6739023902fb2071edca862bcd7d8f2843c34d03e2cca79b39270` |
| V `drivers/misc/mediatek/ccci_util/ccci_util_md_mem.c` | `2d39cbdd6e7b263b01a04598cfa47ec927fae519fe1f6e9729af3c2fc269e518` |
| Q `drivers/misc/mediatek/eccci/ccci_modem.c` | `f22a0f39a790add5adc39291a2e165be30cd750856f4a40eae7f4f3b764f6674` |
| Q `drivers/misc/mediatek/eccci/port/port_rpc.c` | `5c868a6297215fb46b7bb3acee51ccf5a3a30e1b09bdee719ab70dc3f6d540f9` |
| R `op6893-modem-userspace-analysis.md` | `967e5629d27e31fec295cfd9b0e9c77c2ffed1123e8552b7ba52d50d65c56631` |
| R `op6893-modem-mainline-checklist.md` | `154a5afd13f21fe72753dbbee240898a9860c32684aead0b2a46347dfd8929fd` |
