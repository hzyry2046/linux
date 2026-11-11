# Attempt85: empirical stable control completion and full cleanup

2026-11-03. Image `68e4d632a8bb`, release `7.3.0-op6893-d1-68e4d632a8bb+`.
Boot SHA256 `fafe2a6e462d9399cfda2dfc8ee8ef45bcdf055b9c6c34a2a4295ceb1bac9dd1`.
Queued serial-targeted flash/reboot succeeded; release/raw boot hash and
initial attempted0 matched. Device remains on this mainline85 image, CONN off.
ACK backup unchanged. AI-assisted implementation/tests/docs; no external
submission or AI DCO.

## Result

One `adie-efuse-stable-cycle` succeeded, including reverse cleanup. After the
stable zero-status/address0/read-mode baseline, a single kick was followed by
three fresh ID-separated control reads. Each had kick0/valid1 and the same
nonstatus difference mask0x3b; no other nonstatus changes occurred.

The separate experimental command uses an empirical exception for stable
bits5:0 on this E3 device, supported by83/84 and the vendor kick/valid handshake.
It does not claim a generic MT6635 AOUT specification. The original strict
cycle and hold-only observer commands retain their behavior.

Final engine: requested1/issued1, pending0/complete1, transfers7, polls3,
confirmed3, flags20000000, stable1 and delta0/delta1/delta2 all3b.
No engine/SPI busy pulse was sampled. elapsed_ns171040615 is below250ms and
includes software guards; it is not physical efuse latency. Freshness comes
from each transfer's changed RDAT, with ID separators and matching IDs.

FM restored801f before reverse analog restoration (TOP0bc=1,TOP064=0), mailbox
clear, A-die reset/address restore, semaphore release and outer cleanup.
Remap4/4/4, RGU4/4/4, SPI36/36/36 and SYSRAM4096/4096/4096 passed.
Result0/cleanup_result0; all dirty/unsafe/uncertain states zero. CONN off at
both subsequent preflight samples. Established VS1/VS2 votes1/1 remain.

No TOP130/134/138/13c private data reads, control-word restoration, second
kick, thermal trim, calibration or firmware startup. Completion means this
explicit handshake policy passed; it does not prove data validity or Wi-Fi.
Control values remain masked in status, including the inherited RDAT slot
at the first analog-restore ID sample.

## Tests and regression

Actual-C/UBSan standalone and nested tests pass:72 high-bit changes,12 low-bit
instability cases,six kick/valid faults,seven SPI timeouts,deadline boundary,
new transfer dropped writes/guard faults and unchanged controls. Completion
is refused before all three valid samples. Standalone16/nested15 cleanup
write drops are exercised after accepted completion. Nested FM restoration
and outer SPI restoration failures retain the appropriate parent state;
one-shot and masked output pass. Earlier engine/parent suites pass, and the
hold-only standalone observer still returns EUCLEAN and retains resources.

Full ARM64 build and11 built-in suites,checkpatch zero errors/warnings,
binding/DTB validation,pin model,capacity and diff checks pass. Aligned payload
7,464,960 bytes leaves26,089,472 bytes in32MiB boot.

USB SSH/configured,CPUs0–7,disk read-only,cache ext4 ro/norecovery,Debian image
hash,battery ADC/PMIC temperature and17 LVTS samples pass. AP pin differences
are limited to the established shared drive0→8248 transition. Retry refused;
nine cached status hashes unchanged. No BUG/Oops/SError/panic in captured log.
Selected records: [attempt-85](attempt-85/). Full dmesg stays outside Git.

## Next boundary: private data handling, then thermal trim separately

Design guarded TOP130/134/138/13c reads only after accepted completion, with
ID/control separators, per-transfer freshness and no additional kick. Raw
words stay in temporary kernel storage, never sysfs, printk or Git evidence.
Before adding any such read, audit inherited RDAT paths and error diagnostics:
masking CTRL alone is insufficient once RDAT can contain private data.

First validate transport and repeatability without applying calibration or
publishing raw values, then explicitly erase temporary data. SYSRAM handoff
and thermal trim are separate changes: require destination bounds, readback,
cleanup/zeroization and fault tests. Do not copy vendor raw-word logging,
continue-after-transfer-error behavior or thermal writes into the read-only
experiment. Wi-Fi and independent network SSH remain the development priority.
