# Attempt38: MT6893 LVTS resource and calibration audit

Status: source/saved-device calibration audit complete. No kernel edits, flash,
reset or LVTS MMIO access. Current image74e7947a974f remains running.
Live /chosen contains bootargs/name only; atag,devinfo read fails ENOENT
(devinfo.bin is empty, stderr retained). op6893-fdt.c merges memory ownership,
not this bootloader calibration property. Saved ACK DTB remains the source
for this round; do not describe the result as current live fuse verification.

## Calibration provenance

ACK mtk-devinfo.c copies native-endian count+words from /chosen/atag,devinfo
into a read-only NVMEM provider. It does not map efuse@11c10000's MMIO reg.
Therefore NVMEM byte offsets0x1d0/0x2f8 refer to devinfo words116–119 and
190–207, not proof that physical registers11c101d0/11c102f8 contain this data.
Do not follow stale physical-address comments in tscpu_lvts_config.h.

Saved ack-live.dtb property has220 little-endian words. Extracted22 LVTS
words exactly match preserved ACK dmesg; raw golden60 means30C because the
conversion uses golden*500mC. ACK prose/log interpretation of60C is misleading.
17 sensor count_r values34774–35575;7 controller count_rc values2739–2766.
Full limited calibration result in calibration.json, not a whole-devinfo dump.
Host lvts-calibration.py validates count,length,endian and calibration presence,
with no fake fallback. Test extracts actual ACK C decode and checks all17+7
counts and golden field against Python, compares22 words to ACK log, and
rejects malformed/truncated/wrong-endian blobs. UBSan passes. Saved-device
agreement establishes provenance/decoder correctness, not hardware operation.

## Controller/resources

Seven controllers and17 sensors: MCU groups2,2,4 at11278000/11278100/11278200;
AP groups2,2,2,3 at1100b000/1100b100/1100b200/1100b300. ACK describes one
large base1100b000 range26e200; MCU offsets26d000–26d200. Prefer explicit
domain resources for a mainline adaptation instead of claiming the intervening
address space. IRQs SPI169/170 require verified domain mapping before binding.
ACK thermal gate is infracfg bank0 bit10, parent axi_ck; current clock provider
only implements the PMIF subset, not this parent/gate. ACK reset descriptions:
AP SET120/CLR124 bit0; MCU SET730/CLR734 bit10 (relative infracfg10001000).
No reset, gate or LVTS register touched in this audit.

## Why a data-table-only port is insufficient

ACK config LVTS_DEVICE_AUTO_RCK=0. Each sensor requires manual RC measurement;
normalization EDATA=(count_rc_now*count_r)>>14, with vendor drift handling
against controller count_rc. Current mainline generic calibration writes its
stored per-sensor calibration directly; manual MT6893 RCK integration and
command/timing/error lifecycle remain to be implemented. MT6893 conversion
coefficients are-252500/+252500, differing from MT8195-250460/+250460.
Shared register names do not establish identical device initialization.
Mainline initialization may reset domains/program protection and ACK already
records reset problems with bogus calibration. Do not enable a guessed
compatible or fake calibration on this unit.

## Concrete next stages

1. Preserve validated LK calibration through the early FDT handoff, with bounded
   little-endian count/length checks and malformed-input tests. Import only the
   required property/data, not arbitrary Android chosen state. Then verify its
   live bytes against boot evidence before publishing an NVMEM consumer.
2. Implement/audit thermal AXI parent/gate and two reset resources; document
   actual domain IRQ mapping and inherited controller/protection ownership.
3. Add MT6893-specific manual RCK/normalization with bounded waits and explicit
   failures, plus extracted-code tests; first hardware profile should avoid
   unvalidated protection-threshold or AP-reset changes.
4. Validate calibrated sensor readings before thermal trips/cooling/DVFS.
   PMIC die temperature is not CPU/GPU thermal coverage.

No claim of SoC thermal support yet. No ACK code modifications, commits or
Signed-off-by. Source audit/tooling generated with Codex assistance.
