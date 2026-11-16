<!-- SPDX-License-Identifier: GPL-2.0-only -->
# AP filesystem service: recovered operation semantics

2026-11-16, offline static analysis. This resolves missing semantics in
`MODEM-SERVICES-AUDIT.md` against the actual AP userspace implementation.
No modem firmware, NVRAM contents, identities or hardware were accessed.
These are static AP implementation results; there is no new runtime evidence
that every recovered branch is used or accepted by MD.

## Reproducible source identity

Input:
`/data/src/reverse-analysis/conninfra-rev/modem/sources/bin/ccci_mdinit`

- SHA256: `0740831c74b699ee802a7e7c0ccb25266a29f4105a5dc233203ef9dc2ff71a4e`
- ELF64 AArch64 Android 31 PIE, stripped.
- ELF BuildID: `7219d404e3539fa62e3d5987b13b4539`.
- Ghidra default image base: `0x100000`; addresses below use that base.
  For the cited code and rodata, subtract `0x100000` for the ELF virtual
  address and file offset. Example `FS_CCCI_Move` at `0x11e420` is ELF/file
  `0x1e420`. This relationship was checked against ELF section headers.

Analysis: Ghidra headless autoanalysis/decompiler with relevant control paths
checked using `llvm-objdump -d --start-address=... --stop-address=...`.
Decompiler output is transient under `/tmp/op6893-fs-semantics`; the document
records stable binary identity and offsets rather than relying on that output
remaining available. No proprietary binary or decompilation dump is added to
this repository.

Prior reports used, without recapturing original private traces:

- `/data/src/reverse-analysis/op6893-modem-userspace-analysis.md`, SHA256
  `967e5629d27e31fec295cfd9b0e9c77c2ffed1123e8552b7ba52d50d65c56631`.
- `/data/src/reverse-analysis/op6893-modem-mainline-checklist.md`, SHA256
  `154a5afd13f21fe72753dbbee240898a9860c32684aead0b2a46347dfd8929fd`.

The prior runtime observations of successful Move and failed FindFirst/detail
remain observations. Their previous suggestion that Move is an atomic rename
was explicitly an inference. The AP binary implements copying instead.

## Move `0x100c`: flags and real side effects

`fsd_main` at `0x116ea4`, case `0x100c`, passes argument pointers 0 and 1
as source/destination wide paths and the first little-endian u32 of argument 2
as flags. It emits exactly one 4-byte signed status argument.
`FS_CCCI_Move` occupies `0x11e420..0x11f1b4` (exclusive next function boundary); its main flag checks are at `0x11e938..0x11e94c`,
source permission gate at `0x11ec14`, and copy decision at `0x11ed2c`.

Flags must satisfy both `(flags & 3) != 0` and
`(flags & 0xfffefffc) == 0`. Thus only bits 0, 1 and 16 are allowed,
and at least one low bit must be present. Invalid flags return `-2`.
Identical **mapped path strings** also return `-2`; the code uses `strcmp`,
not an inode identity check.

| Flag | Proven behavior |
|---|---|
| bit 0 (`0x1`) | Copy source contents into destination: open source read-only, seek end/start for size, allocate whole-file buffer, read, `creat(destination,0777)`, write, close. It does not rename or unlink the source. |
| bit 1 (`0x2`) | Refuse a read-only source with `-45`; later log `kill ..., NULL`. There is no source deletion call. With no bit 0, the copy path is skipped. |
| bit 16 (`0x10000`) | Before the copy decision, refuse read-only destination with `-45`, delete an existing regular destination with `FS_CCCI_Delete`, or delete a directory with `FS_CCCI_XDelete(path,0x1c)`. If neither file nor directory exists, retain provisional result `-18`. |

Without bit 16, the provisional result is `-18`, but a bit-0 copy proceeds
and can succeed. The later `creat` truncates an existing destination even
without bit 16; therefore bit 16 is not a simple exclusive-overwrite switch.
With bit 1 alone, writable source, and no bit 16, the function logs and
returns `-18`, changing nothing. With bits 1 and 16 but no bit 0, it can
return the destination deletion's success while preserving the source.
Do not interpret bit 1's name or logging as proof of deletion semantics.

Copy errors: actual failing source open/read, destination create/write use
`FS_ErrorConv` at `0x115a08`: `ENOENT→-9`, `EACCES→-16`, `EMFILE→-5`,
other errno `→-18`. Short reads/writes and allocation/negative-size failures
return `-1`. Source/destination close results are not propagated. There is
no fsync in this Move copy path; do not claim atomic replace or durable rename.
A safe new backend may use bounded streaming instead of whole-file malloc,
but must preserve the proven source-retention and flags/error semantics and
state any durability improvements separately.

The vendor read-only predicate is `FS_IsReadOnly` at `0x123b50`:
`(mode & 0xdb) == 0 && (mode & 0x124) != 0`, using stat mode bits.
It is not `access(W_OK)`, nor simply “all write bits clear”: low-byte execute
bits participate. Stat failures return the mapped negative error. Move tests
only for positive results, so a negative stat error is not itself a positive
read-only condition.

Invalid drive mapping returns `-19`; overlong mapped paths return `-49`.
Do not reproduce vendor lexical-check weaknesses: new private-root path
confinement remains mandatory before any filesystem operation.

## GetFileDetail `0x1025`: success layout resolved

`FS_CCCI_GetFileDetail` at `0x122a98`, success stores at
`0x122d98..0x122dc0`, calls `stat` on the mapped path and emits:

1. a 4-byte signed status (0 on success);
2. a **24-byte** value containing three little-endian u64 second counts:
   `mtime`, `atime`, `ctime`, in that order.

The source stat offsets are `0x58`, `0x48`, `0x68` respectively. These
are seconds, not nanoseconds, FAT fields or file size. The `fsd_main` case
always declares a second argument of length `0x18`, including on failure.
The mapped stat errno conversion is the same as above. Unknown drive is
`-19`, overlong path `-49`.

On failure the vendor helper leaves the output storage untouched; its
caller supplies a stack local. A new implementation must zero those 24
bytes rather than disclosing stack memory. This safe initialization is an
intentional difference from unspecified vendor bytes, not a newly observed
MD requirement.

## FindFirst `0x1012`: request and response shape

`FS_CCCI_FindFirst` at `0x1203d4` takes:

1. wide path including basename wildcard;
2. required attribute byte;
3. excluded attribute byte (called `AttrMask` in logs);
4. u32 output filename capacity, measured in wide characters.

The `fsd_main` switch takes only the first byte of arguments 1/2 and first
u32 of argument 3. A strict codec should enforce typed sizes rather than
emulating out-of-bounds access on malformed arguments.

It splits mapped directory/basename, opens the directory, skips `.`/`..`,
and applies case-sensitive `PatMatch` at `0x115548`: `*` and `?` are the
only special symbols. In particular `*.*` is not silently rewritten into
`*`; the recursive matcher treats the dot literally. A filename attribute
has read-only bit `0x1` and directory bit `0x10`. The match is admitted only
if `(required & ~actual) == 0 && (actual & excluded) == 0`.

On success it allocates a shared file/search handle (positive 1..128 from
`FS_GetFreeHandle` at `0x12330c`), retains the directory stream, stores
pattern and attributes for FindNext, and replies with exactly three values:

1. 4-byte signed handle/status;
2. **52-byte** entry produced by `FS_EntryLinuxToDos` at `0x12407c`;
3. byte-widened basename with trailing NUL, size `2 * returned_chars + 2`
   when the returned character count is nonzero, otherwise zero bytes.

The byte-to-wide converter `0x12430c` copies low-byte characters and
replaces slash with backslash. It returns original length if it fits,
otherwise `capacity-1`, and terminates at that point. This is not proof of
full Unicode conversion. The backend widens filesystem bytes directly;
it does not decode them as UTF-8. Zero capacity needs explicit rejection in a new
backend: the vendor subtraction would underflow. Long-name fit flag at
entry offset `0x0c` is `strlen(basename) < capacity`.

For opendir failure, errno maps as above (`ENOENT=-9`). If directory opens
but no matching entry exists, it closes it and returns `-6`. Free-handle
exhaustion returns `-5`; allocation failure returns `-1`. Entry-name output
length is explicitly reset to zero before path/open/search, so failures still
have three response arguments, with third argument length zero. The 52-byte
entry can contain untouched caller storage on failures: zero it explicitly
in a new service. Directory iteration retains native enumeration order,
without sorting or snapshotting. File and search handles share 128 slots;
index zero is reserved, not an additional usable handle.

`FS_CCCI_FindNext` at `0x1211f8` takes a u32 handle and positive u32
wide-character capacity. It resumes the stored pattern and attribute filters,
with the same three reply arguments. Success status is **zero**, not the
handle; exhausted search is `-6` and keeps the stream allocated until close.
Invalid handles and file handles used as search handles return `-10`.
`FS_CCCI_FindClose` at `0x1219c4` takes one handle and replies with one
signed status. It can also close file handles, without Close's conditional
fsync. Ordinary Close can close a search handle. Shutdown closes both kinds.

### The entry is not a generic FAT dirent

The helper zeroes all 52 bytes, then sets these offsets (all integers LE):

| Offset | Size | Proven field |
|---:|---:|---|
| `0x0b` | 1 | attributes: read-only `0x1`, directory `0x10` |
| `0x0c` | 1 | filename fit indicator set by FindFirst/Next |
| `0x0e` | 4 | packed time/date derived from `localtime(atime)` pointer |
| `0x12` | 4 | zero |
| `0x16` | 4 | packed time/date derived from `localtime(mtime)` pointer |
| `0x1a` | 2 | zero |
| `0x1c` | 4 | low 32 bits of stat file size |

Disassembly `0x12425c..0x124284` and `0x124290..0x1242b8` proves the
packed word uses the following nonstandard formula (u32 arithmetic):

```
u = (tm_sec & 31) | ((tm_min & 63) << 5) | ((tm_hour & 31) << 11);
u = (u | 0x60000000) + (tm_year << 25);
u = (u & ~(15U << 21)) | ((tm_mday & 15) << 21);
u = (u & ~(31U << 16)) | ((tm_mday & 31) << 16);
```

Seconds are not divided by two, and bits commonly used for FAT month are
filled from **day**, not month. Do not “correct” this into standard FAT
encoding while claiming a byte-identical replica.

The helper calls `localtime(atime)`, then `localtime(mtime)`, before reading
either returned pointer. Local Android Bionic source
`/data/src/mikuui/bionic/libc/tzcode/localtime.c:1691` returns shared static
`struct tm` storage (including the alternate C89 configuration). Source
SHA256: `94734ca974ae7205dccef40dfcface2c3520ae67c932fb3af7aec1fd47e35b92`.
The prototype explicitly chooses this Bionic aliasing policy: both packed
words use mtime. It uses the provider process's timezone; it does not read
Android's `persist.sys.timezone` property. This source evidence is not runtime
verification of the installed libc or of MD acceptance. A synthetic golden
test fixes the unusual layout: local 2024-07-29 23:58:59 packs to `0x59bdbf5b`.

## XDelete `0x1018` and recursive Move destination deletion

`FS_CCCI_XDelete` at `0x121ea4` takes wide directory path and u32 flags,
and emits one signed result. Flags must be a nonzero subset of `0x1c`;
invalid flags or a regular-file target return `-2`. `FS_RecursiveDelete`
at `0x124388` walks children and applies these bits:

| Bit | Effect |
|---|---|
| `0x04` | Unlink regular-file children. |
| `0x08` | Remove child directories after any recursive walk. |
| `0x10` | Recurse into child directories. |

When both `0x08` and `0x10` are set, XDelete also removes the requested
directory itself. Success is the **count of removed files and directories**,
not a fixed zero status. A negative child error aborts recursion. Move with
bit 16 uses flags `0x1c` and preserves this count when bit 0 does not request
a subsequent copy. A successful copy returns zero.

The vendor follows `stat` links, treats recursive opendir failure as zero,
continues after some child stat errors, and may attempt root rmdir after a
recursive error. The private-copy backend deliberately fails closed instead:
it preflights the entire tree, accepts only directories and single-link
regular files on the working root's filesystem, and rejects symlinks,
special files, drive-root deletion and trees reaching depth 64 before any
deletion. Directory opens use O_NOFOLLOW and verify inode/device identity.
Mutation repeats entry checks and stops on the first error; it is not atomic
and does not promise rollback after an I/O error. The caller must exclude
concurrent filesystem mutation, including by other local processes.
Move also refuses a source contained within the destination tree it would
delete, before deletion begins. These confinement and bounded-resource rules
are prototype policy, not claims about vendor behavior.

## CMPT_Read `0x1022`: errors and completion masks

`FS_CCCI_CMPT_Read` at `0x1199fc`, callers in `fsd_main`, are sufficient
to resolve all-five-stage (`0x1f`) failures without inventing a generic
scalar error response. The 40-byte wire control structure is expanded into
an AP-local structure; AP pointers are never copied from the MD wire.
The helper initializes returned read count to zero.

The caller **always emits four arguments**, independent of helper return:

1. 8 bytes `{u32 completed_mask, s32 actual_FS_error}`;
2. 4-byte file size;
3. 4-byte actual read count;
4. that many data bytes.

The helper's own return `-1..-7` is only a local diagnostic value and is
not serialized as an additional return code.

| Failed operation, request mask `0x1f` | Completed mask | Wire error | Local helper return |
|---|---:|---|---:|
| Open | `0x00` | actual negative Open result | `-1` |
| GetFileSize | `0x01` | actual negative GetFileSize result | `-2` |
| Seek | `0x03` | actual negative Seek result | `-3` |
| Read | `0x07` | actual negative Read result | `-4` |
| Close after successful read | `0x0f` | actual negative Close result | `-5` |
| All succeed | `0x1f` | `0` | `0` |

After size/seek/read failure the helper attempts close, but keeps the original
completion mask/error. If the read succeeded and close failed, read count and
data remain available. On Open failure, file size is not initialized by the
vendor helper; a new backend must reply zero size and zero read count rather
than uninitialized AP storage. After a successful size but later error,
retain the obtained size. Read failure begins with count zero, though a real
provider should explicitly specify whether it can report a partial count.

Bit 0 is mandatory in the vendor helper despite a misleading log text
"miss read flag". If absent, the constant at `0x10ba60` encodes
`{completed=0,error=-18}`, and helper returns `-7`.
Missing bit 4 causes a close followed by local `-6` **without initializing
completion/error**. Therefore accepting arbitrary masks is not equivalent
to having recovered safe semantics: the first backend should admit the
observed exact `0x1f` and continue to reject unsupported masks before I/O.

## Implementation implications

Resolved now: Move's source-retaining copy and flag subset, GetFileDetail's
24-byte time layout, the FindFirst/Next/Close family and 52-byte entry shape,
XDelete's recursive flags/counts, and CMPT all-five-stage failure layout. These enable
useful filesystem provider work without another resource-only flash.

Still unproved: actual runtime Move flag census (previous traces only
summarized paths/results), successful FindFirst response acceptance on MD,
installed libc `localtime` pointer behavior, full Unicode names, and MD requirements
for otherwise-uninitialized failure fields. Synthetic filesystem tests can
validate new provider choices; do not label them captured MD behavior.

## Live MD wire results (2026-11-17, image a6025a735b61)

These are real hardware observations from the op6893 with the gated release
owner and the private FS runner; no vendor NVRAM, identity or firmware data
was read. They correct two earlier static assumptions.

### Replies must carry the 0xffff0000 operation prefix

The MD sends requests with a **bare** operation (`0x1001`, `0x1009`, `0x100e`,
`0x1010`, `0x1021`, `0x1022`), but its FS client asserts unless every reply
carries `0xffff0000 | op`. The first release attempt answered `0x1001` and the
MCU asserted 3 s later:

```
ex_type=0x50 (ASSERT) offender=MCU
path=mcu/service/hif/ncccisrv/ccci_fs/src/ccci_fs.c line=1302
para=0xffff1001,0x1001,0x0        (expected, actual, unused)
```

After the reply prefix was added, the same request sequence completed without
an assert. The kernel endpoint now accepts only
`reply_op == (request_op | 0xffff0000)`; the fragment router still compares the
low 16 bits. This is a wire requirement, not a cosmetic difference.

### Observed boot sequence before NVRAM initialisation

```
Open    X://md_nv_config.txt   flags 0x700   (double separator, trailing NUL)
GetFileSize handle 1
Close   handle 1
GetDiskInfo Z:\                argc 2, reply status + 84-byte record
GetAttributes Z:\FAT6F5923D6.log            -> -9 when absent
Open    Z:\NVRAM               flags 0x900   (read-only directory open)
GetAttributes Z:\NVRAM\{NVD_DATA,NVD_CORE,CALIBRAT,NVD_IMEI,BACKUP}
GetAttributes / CreateDir on X:\ and Y:\ drive roots
CMPT_Read (mask 0x13, flags 0x100) of ~350 Z:\NVRAM\... files
CMPT_Read Z:\NVRAM\NVD_CORE\MTCR_000
Restore Z:\NVRAM\NVD_IMEI\NV0S_000 (argc 3)
```

`GetDiskInfo` returns two arguments: a 4-byte status and an 84-byte record.
The same-board helper writes sector size 512 at 0x30, `statfs.f_blocks >> 9`
at 0x34, `statfs.f_bfree` at 0x38 and 512 at 0x40; every other byte stays
zero. `GetAttributes` returns `(read-only ? 0x1 : 0) | (dir ? 0x10 : 0)`.
`Restore` returns the `NVM_RestoreFromBinRegion_OneFile` status and maps a
failed restore to `-18`; a provider without a bin-region backup must return
`-18`, not a fabricated success.

### CMPT_Read masks

The MD has been observed sending both `0x1f` (open,size,seek,read,close) and
`0x13` (open,size,close) with flags `0x700` and `0x100`. The stage bits are
independent: `completed` accumulates the performed stages and a missing bit 0
serializes the vendor constant `{completed=0, error=-18}`. The adapter now
admits any subset of `0x1f` and rejects unknown bits; the seek origin and read
length are validated only when their bits are set.

### NVRAM data is the current hard boundary

With an empty private NVRAM tree every `CMPT_Read` returns `{0, -9}` and the
MD continues the scan, but it asserts in `mcu/service/nvram/src/nvram_io.c`
line 2394 (`para=0x1,0x4,0xf008`) once `NV0S_000` cannot be read or restored.
A diagnostic run that reported `Restore` success without creating the file
produced the same assert, so the MD needs real NVRAM content or a real
bin-region backup. Importing either is outside this project's constraints.
