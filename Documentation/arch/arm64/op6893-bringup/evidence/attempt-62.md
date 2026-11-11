# Attempt62: isolate on-domain HOST_CSR observations

2026-11-03. Based on attempt61 request/ACK captures and ACK register-access
source audit. Image `7c249e95b089`, release
`7.3.0-op6893-d1-7c249e95b089+`, boot SHA256
`d3e457c2395064b29a919bc7e9a9134f1096a71506cd25f1ceaf8c4f4386f3a2`.
Physically tested: three HOST_CSR reads and cleanup succeeded. No ID success claimed.

Add explicit root-only `csr-cycle` to the same per-boot one-shot rail/domain
transaction and existing domain opt-in. Boot/probe behavior and legacy21-write
power/protection sequence remain unchanged. After the unchanged6ms settling,
check dual power ACK, control0xd, host request and AP-to-CONN protection bit13
and bank2 bit2 clear. Reverse CONN-to-AP bit14 remains recorded but does not
reject this on-domain-only diagnostic, matching ACK's AP-side readability gate.

Map/read/unmap exactly one word each at0x18060000 (raw clock detector),
0x18060184 (internal sleep protection) and0x180602d4 (timeout status), in that
order. Recheck AP-side prerequisites before each mapping and again before
its hardware read. Save partial sample count and raw words, including when
later reads refuse. No HOST_CSR writes, detector reset, wakeup, internal ID
mapping, firmware, DMA or calibration. Existing `domain-cycle` retains its
stricter combined guard and ID behavior. Normal shutdown, idle pins, reverse
rail cleanup and uncertainty retention remain unchanged.

A successful csr-cycle means three guarded reads completed and cleanup passed;
it does not establish off-domain access, fresh clock detection, electrical
clock rates, or Wi-Fi support. The raw clock detector is not reset and may
contain inherited/stale state. Partial reads are indicated by samples0--2;
zero unfilled words are not observations. preflight reports guarded-csr-only
when at least one new sample exists. MMIO may stall despite bounded software
polls; AP watchdog remains the recovery mechanism.

Host tests retain normal exact21-write trace and existing failure coverage.
New cases: reverse bit14 reappears while CSR reads succeed without any ID
mapping/read; all three mapping failures; AP bit13 asserted after each map
prevents that read with balanced unmap; six AP prerequisite changes during
settling prevent all CSR access; one-shot retry and disabled opt-in refuse.
All tests use extracted actual implementation and recursive regulator model.

Full image build and existing11 host suites pass. Extracted domain/rail/
preflight tests pass, C/header checkpatch zero errors/warnings, schema document
and filtered compiled-DTB validation pass. Payload7,448,576bytes fits32MiB
boot with26,105,856bytes free. No external messages or AI Signed-off-by.

## Physical result

Initial resend failed at SendBuffer, before Writing boot; no reboot executed.
Second send/write/reboot succeeded. Boot partition SHA256 matches this image.
Explicit csr-cycle succeeds with result0, cleanup0, domain cleanup0:

```
csr_requested=1 samples=3 clock_raw=0x4006 sleep_raw=0x100 timeout_raw=0x1
access_status=0x10580e03 status2=0x10580e03 control=0xd
protect=0xe70c500e protect2=0xe3 host=0x1
```

HOST_CSR internal sleep ACK bit5 is clear and timeout bit0 is set. Raw clock
bits1/2 are set but were not refreshed by detector reset, so this is not a
fresh clock test. Primary request remains0 while reverse-path bit14 returns
in STA1 after settling, matching61. Three guarded on-domain reads completed
in this state without ID access. This narrows the earlier refusal to the
combined predicate; it does not yet establish off-domain ID access or the
cause of reverse-path ACK behavior.

Final domain off/control0x12/host0, VCN18/13 off, zero leaf refs/dirty flags,
parent votes held1/1. One-shot repeat returns EALREADY, cached trace unchanged.
USB configured/SSH, CPU0--7, block sdc read-only, cache ro/norecovery and rootfs
hash unchanged. ADC/PMIC temperature and17 LVTS channels remain available.
Device remains running this image, experiment complete and latched.

Next use an explicit fresh HOST_CSR clock-detector check and audited internal
sleep/timeout prerequisites before a separately guarded ID experiment.
No wakeup, DEADFEED workaround, firmware, DMA or calibration was performed.
