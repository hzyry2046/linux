# Attempt70: complete volatile SYSRAM clear under held RGU policy

2026-11-03. Image `df82e6dfd58a`, release
`7.3.0-op6893-d1-df82e6dfd58a+`, boot SHA256
`7ffe211d3f879d842f7c496d21f4f3fffacac95b61cbe94154e7ba7d61aa2da3`.
Physical test passed. Running hardware baseline is mainline70.
Existing ACK recovery backup remains unchanged.

## Scope and sequencing

ACK connsys_a_die_cfg_mt6893() clears all16KiB at0x18050000 before26MHz
strap setup and A-die reset release. This occurs after d_die_cfg copied
D-die efuse/build mailboxes inside that same region; do not invent persistent
mailbox contents from the earlier copies. This round tests the complete
clear alone under the previously validated RGU memory policy. It does not
copy efuses, write build/radio/mailbox values, program SPI tables/remaps,
acquire semaphores, change GPIO180 or release A-die reset.

New root-only sysram-cycle shares the per-boot one-shot and supply/domain
opt-in. Fresh expected digital IDs are mandatory. It invokes existing RGU
save/baseline/apply, calls the SYSRAM experiment while all four verified RGU
targets are held (dirty0xf), then runs existing reverse RGU restore and
normal domain cleanup. Old rgu-cycle behavior remains unchanged.

Guard AP/clock/timeout/sleep, map ADIE_CTL0x18001900/4bytes, require full
word2 (reset release clear, inherited top-clock request set), then map
exactly0x18050000/0x4000bytes. Before every RAM write/read recheck internal
readiness, A-die control and readiness again. Write4096 zero words with
individual readback; then scan all4096 again after all writes. A final guard
must pass before marking complete. Counts identify completed writes and
verified reads; partial/zero fields are not success. An error reports only
the failing offset, never raw preexisting RAM contents. Cached sysram_status
has no live hardware access.

Old volatile contents are discarded and NEVER backed up, exported or
restored. SYSRAM completion means zero verification before RGU restoration,
not proof of retention through subsequent memory policy/domain shutdown.
RGU restoration only restores control words, not RAM data. There is no
firmware running through this bring-up path and no A-die release, but these
sequential guards are not atomic exclusion against arbitrary other masters.

A data readback mismatch returns EIO; with access/reset guards intact, RGU
restoration and normal shutdown proceed, and one-shot blocks retry until
reboot. A guard loss latches sysram_unsafe: skip further RAM accesses and
RGU restore writes, keep RGU dirty and retain domain/pins/rails. RGU restore
failure after successful RAM verification also retains resources. Original
failure stage/result remains separate from RGU/domain/rail cleanup errors.
An MMIO stall remains a watchdog recovery case.

## Host validation

Extracted actual C with UBSan checks4096 writes and8192 reads in exact
bounds, sentinel words outside the region unchanged, and correct RGU values
held on every RAM access. Success adds4096 zero writes to the existing30
RGU-cycle MMIO writes, with5 balanced mappings. Boundary/midpoint/mailbox
sample fault locations cover dropped writes, false readbacks and later scan
corruption. Five guard losses (clock,timeout,sleep,AP protection,A-die reset)
are injected after writes, both read passes and both mappings. Final-read
loss cannot mark complete; no RGU restore proceeds after unsafe state.
Tests also cover mapping failure, all RGU apply/restore drops, mixed RAM and
RGU cleanup errors, bad ID, both opt-outs, cached status and retry refusal.
Existing domain/rail/ID/remap/RGU/SPI/semaphore suites pass. Full image and11
existing suites pass; C/header checkpatch zero errors/warnings, schema/DTB
and boot/decompression capacity checks pass. AI-assisted implementation/tests;
no AI Signed-off-by or external message/submission.

Next validate GPIO18026MHz strap transition/restoration with explicit
pinctrl ownership and output/mux ordering, then compose the established
prerequisites for bounded A-die ID reading. SRAM clear alone is not evidence
of SPI transport, firmware or Wi-Fi support.

## Physical results

Queued serial-targeted fastboot flash and reboot both succeeded. USB SSH
returned with the expected release and full raw boot-partition SHA256.
Initial one-shot state was attempted=0. One sysram-cycle returned0:
written=4096, verified=4096, scanned=4096, complete=1, unsafe=0, ADIE_CTL=2.
All four RGU controls were saved/applied/restored, dirty=0 and cleanup=0.
Fresh HW/config IDs were0x20010101/3. Domain and rail cleanup returned0,
final control=0x12 and host=0; VCN13/18 off, parent votes retained1/1.

Runtime regression: CPUs0-7, USB configured and SSH usable, storage read-only,
cache ext4 ro/norecovery, Debian SquashFS hash unchanged
(4b831520cce5df878a6ddb1b428c235d1735f5eea9fe5148f0fa6d0783f90051).
Battery ADC raw20228, PMIC temperature38182, all17 LVTS capture entries
returned. GPIO155 retained and172-182 returned to idle GPIO modes.
Second sysram-cycle was refused with EALREADY; cached SYSRAM/RGU/protection
hashes unchanged. No BUG/Oops/SError/kernel panic observed in captured dmesg.
Known boot-image alignment warning remains. No new button event test performed.

Device remains mainline70 with CONN off. This proves the complete clear
before RGU restoration, not SRAM retention after power-down or Wi-Fi readiness.
Raw full dmesg remains outside Git; selected evidence is in attempt-70/.
