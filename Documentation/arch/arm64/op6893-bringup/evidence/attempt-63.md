# Attempt63: clock-detector reset request and guarded digital ID

2026-11-03. Based on physically tested HOST_CSR-only attempt62. Physical
result: guarded ID read and cleanup succeeded. Image `0d19c805d6b6`, release
`7.3.0-op6893-d1-0d19c805d6b6+`, boot SHA256
`1974e9598f6a673f5813189126680597711ed3e496c72cad4a311a923a92b79d`. Source checkpoint f12c1a18c plus local experimental
changes; no external submissions or AI Signed-off-by.

Add explicit id-cycle under existing domain opt-in and the shared per-boot
one-shot. Existing domain-cycle and csr-cycle behavior is unchanged. Domain
start,6ms settle, protection sequence, shutdown, supply policy and uncertain
state retention are unchanged. No automatic experiment at boot/probe.

ACK reference: mt6893_consys_reg.c consys_check_reg_readable() checks primary
bit13, bank2 bit2 and host request, then RMW-sets HOST_CSR0x18060000 bit0,
waits and checks detector bits1/2, timeout0x180602d4 bit0, internal sleep
0x18060184 bit5. Attempt62 has physically read all three CSR words with
reverse-path bit14 set; no AP protection request is present in that state.

New path guards dual power ACK/control0xd/AP-to-CONN protection/host before
mapping HOST_CSR. It rechecks AP conditions for each CSR read and before the
single detector-reset RMW write, preserving other bits exactly as ACK. Wait1us,
then bounded20ms/50us polling of guarded clock reads. Unlike ACK retry loop,
request reset only once. clock_reset_requested records the issued write, not
an independent hardware acknowledgement that the reset occurred. Polling
cannot recover a stalled MMIO transaction; watchdog remains the recovery path.

Require both clock detector bits, timeout bit0 set and internal sleep bit5
clear before mapping the8-byte internal ID aperture. Repeat those checks and
the AP gate before EACH ID word. Record id_samples0--2 so partial reads are
not reported as complete. Expected HW/config IDs0x20010101/3. off_ready means
the last full readiness check passed, not ongoing ownership after shutdown.
Capture latest clock/timeout/sleep words and failure stage, then normal
shutdown/rail cleanup; on ambiguous shutdown keep supplies/pins as before.
No wakeup write, DEADFEED workaround, firmware, EMI, DMA or calibration.

Host tests execute extracted implementation and recursive rail integration.
Retain21-write old-path checks and existing fault cases. New cases exercise
reverse bit14 with reset-requested ID success; clock bits missing; timeout
bit absent; sleep ACK set; AP guard lost after reset; both mapping failures;
state changes after CSR/config mapping; clock/timeout/sleep/AP changes after
first ID read prevent second read; wrong HW/config IDs; six settling AP
changes prevent mapping; disabled opt-in and repeated trigger refuse.

Full image build and existing11 host suites pass. Extracted domain/rail/
preflight tests pass with undefined-behavior sanitizer. C/header checkpatch
zero errors/warnings. Schema document and filtered compiled-DTB validation
pass, boot payload and decompressed memory window capacity checks pass.

## Physical result

Queued serial-targeted flash boot and immediate reboot both succeed. Initial
SSH connection was briefly refused before service startup; retry succeeds.
Boot partition readback matches selected image SHA256. No automatic power
experiment at boot: attempted0, no rail parent votes, zero ID samples.

Explicit id-cycle succeeds with result0, cleanup0, domain cleanup0:

```
id_read=1 hw=0x20010101 cfg=0x3
id_requested=1 clock_reset_requested=1 off_ready=1 id_samples=2
fresh_clock=0x4006 fresh_timeout=0x1 fresh_sleep=0x100
```

Both expected digital words were read on mainline after the clock-reset
request and checks. AP gate snapshot: dual power ACK0x10580e03, control0xd,
primary protect0xe70c500e, bank2 protect0xe3 and host1. Reverse-path bit14 is
set in this state but is not a prerequisite for AP-to-CONN register reads;
request stays0 as previously observed. Its reassertion mechanism is still
unknown. Earlier combined guard was too strict for this register-access path.
No inference of Wi-Fi firmware, RF, DMA or calibration support follows.

After experiment, dual ACK0x10580e01, control0x12, host0, primary protection
0xe70c700e and bank2 protection0xe7. CONN/VCN off, zero leaf refs/dirty flags,
no uncertain flags; shared parent votes remain1/1. Repeat id-cycle refuses
with EALREADY and unchanged cached trace. off_ready1 records the last pre-ID
check; it does not mean domain remains on after cleanup.

USB configured/SSH, CPU0--7, sdc read-only, cache ro/norecovery and rootfs
hash unchanged. Battery ADC, PMIC temperature,17 LVTS channels and pin return
states remain available. No BUG/Oops/SError/kernel panic in collected dmesg.
Intentional GPT discrepancy and inherited image-alignment warning remain.
Device is left on this image, CONN off and successful experiment latched.

Next audit the post-ID D-die/SYSRAM initialization and EMI mapping separately,
including reserved memory bounds, ordering and rollback, before SPI/A-die
access. No factory efuse/calibration words are included in this evidence.
