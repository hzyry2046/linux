# Attempt67: guarded SPI sleep-command baseline

2026-11-03. Image `fba0b6f25671`, release
`7.3.0-op6893-d1-fba0b6f25671+`, boot SHA256
`0b1a973d51c994a7e6340fb5113e50e2e97c4ab63fd972e4073ab0d381e130a2`.
Physical result: all39 words captured, normal shutdown/rail cleanup pass.
Device remains on this mainline image with CONN/VCN off.

## Starting environment and source provenance

User restored Android before this round and explicitly requested keeping the
existing recovery backup unchanged. ADB uname reports5.10.0, but the user
confirmed this is a spoofed uname on the actual4.19 kernel. That output is
not evidence of a5.10 implementation or the earlier6.6 ACK environment.
No new backup was taken; the previously selected ACK image remains
SHA256455ed6cea037d6d6bd9af328d589ab39b8692edd4db2c3924e1f8da7b4722c88.

Audited6.6 source:
`android_kernel_modules_oneplus_mt6833/vendor/mediatek/kernel_modules/connectivity/conninfra/conn_drv/connv2/platform/mt6893/mt6893_pos.c`,
`connsys_spi_master_cfg_mt6893()` plus `include/mt6893_consys_reg_offset.h`.
Cross-check with local4.19
`kernel_oddo_mt6893/drivers/misc/mediatek/connectivity/conninfra/platform/mt6893/`:
all36 non-BT configuration addresses, masks and targets agree. This is a
comparison of local source trees, not proof of the running Android module's
exact source identity. Function hashes and the full target list are archived
in spi-source-audit.json; comparison script is archived for reproducibility.

The function programs the WT sleep/wake command sequencer at0x18005000.
It is distinct from issuing RF SPI transfers through0x18004000. The actual
RF SPI read helper writes an address and then WDAT to trigger a transfer;
its status polling uses bits1..5 of SPI_STA. WB_STA bit26 is polled by the
A-die top-clock helper. Other status bits remain raw observations here.

## Implementation and host validation

New explicit `spi-baseline` uses the existing root-only rail_cycle interface,
domain/supply opt-in and per-boot one-shot. It requires successful refreshed
clock checks, AP-direction protection gates, internal timeout/sleep checks
and both expected digital IDs. No dependency on EMI allocation is added.

Capture exactly ADIE_CTL0x18001900, SPI_STA0x18004000, WB_STA0x18005008,
then all36 configuration words in ACK's programming order. For every word,
check readiness before mapping and after mapping, read exactly one word,
unmap, and preserve the count. Recheck readiness after the final word too:
a count of39 alone cannot prove successful completion. Timestamp the whole
sequential capture, including error exits. Cached root-only spi_baseline
shows requested/count/timestamps and only actually sampled words; reading
it does not access hardware. Normal shutdown follows even after partial
read-only failure, subject to the existing power-off verification.

No new register writes, RF SPI transfer, semaphore access, A-die reset
release, strap changes, SYSRAM access, remap/RGU changes, firmware, DMA or
RF operation. The existing HOST_CSR clock-detector reset request and common
power/pin sequencing still execute. An MMIO bus stall remains a watchdog
recovery case, not a software polling timeout.

Extracted actual-C integration tests with UBSan validate39-word success,
41 balanced mappings, exactly22 existing MMIO writes, no new-region writes,
cached display, retry refusal, both invalid digital IDs and both opt-outs.
All39 mapping failures and four readiness failures after each mapping and
each read (including the final read) stop at the proper sample count and
clean up. Partial captures still get end timestamps. Existing preflight,
recursive regulator, domain, ID, remap and RGU tests pass. Full image and11
existing host suites pass; C/header checkpatch zero errors/warnings, schema
and compiled-DTB checks pass, boot/decompression capacity checks pass.

## Physical result

Serial-targeted flash/reboot was queued before ADB reboot bootloader. This
round both commands succeeded, USB SSH returned, and running release plus
raw /dev/sdc48 SHA256 match the artifact. No recovery assistance was needed.
Initial attempted0 and cached SPI count0 were verified before triggering.

Trigger succeeds after HW0x20010101/config3, with39 samples over700615ns.
Sample window is sequential, not an atomic snapshot or duration of proven
idle state. The three status/control samples were:

| Register | Observed | Interpretation limited to audited fields |
|---|---|---|
| ADIE_CTL0x18001900 | 0x2 | Reset release bit0 clear; top-clock request bit1 set |
| SPI_STA0x18004000 | 0 | Known busy bits1..5 clear at this read |
| WB_STA0x18005008 | 0x80000 | Top-clock busy bit26 clear; bit19 not decoded |

Of36 configuration words,10 match the non-BT ACK targets under their masks;
26 differ. The matches are10 of the11 peripheral-address words. TOP_CK_ADDR
is0xa00 versus target0x02c. WB_SLP_CTL is0xf801 with command-length low5=1
versus target8; a future masked write would preserve upper bits as0xf808.
All eight BG addresses, eight BG_ON data words and eight BG_OFF data words
differ. See spi-comparison.json for every full original, mask and target.
The patterned values are observed initial contents; no assumption about
reset origin, retained programming or functional radio state is needed.

Final domain/rail cleanup0, dual power ACK off, control0x12, host0, no leaf
refs/dirty flags, parentvotes1/1 retained. Repeated trigger returns EALREADY
with SPI/protection snapshot hashes unchanged. USB configured/SSH, CPU0--7,
sdc RO, cache ro/norecovery/root hash, battery ADC, PMIC temperature,17 LVTS
samples and GPIO155/CONN idle pins pass. Collected dmesg has no BUG/Oops/
SError/kernel panic; inherited alignment warning and intentional GPT mismatch
remain. Raw logs stay in mt6893-direct; selected evidence is archived here.

## Next step

Implement an isolated36-word sleep-command configuration transaction using
these observed originals and audited non-BT masks/targets. Preserve unrelated
WB_SLP_CTL/address bits, check A-die reset and SPI/WB access state before
writes, verify targets, restore originals in a deliberate order, and retain
resources if restoration cannot be established. A single idle sample does
not authorize an unguarded later transaction. ADIE_CTL bit1 is already set,
so do not assume the entire A-die interface has no outstanding clock request.

Before A-die release, separately account for the full16KiB SYSRAM clear in
ACK's a_die_cfg (after d_die_cfg efuse/build mailbox copies), GPIO180's26MHz
strap output/pinmux sequence, and hardware semaphore ownership for RF SPI.
None is validated by reading the configuration table. Wi-Fi remains unavailable.

AI-assisted local implementation and host tests; no AI Signed-off-by or
external submission/message.
