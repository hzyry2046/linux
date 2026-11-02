# Attempt35: CHIP_TEMP diagnostic voltage

Status: flashed and booted; diagnostic ADC reads and short regression passed.
Device left running d353a067577a. Temperature accuracy/liveness not validated.
Boot d353a067577a, SHA256
7e6b6aa57536560ac2d7f09efac3b730e38f76525ccbc1f2e4bfedeeef65c1b3.
Rollback: attempt34 b0e531f6c970; unchanged Debian9825862f46b0.

Board/build-gated ADC profile now selects exactly BATADC and CHIP_TEMP.
CHIP_TEMP is deliberately IIO_VOLTAGE, label chip_temp_voltage, channel2;
result0x1090, request0x1108 bit4,12data bits,ready bit15,8sample wait,
ratio1/1 and nominal1800/4096mV/count. Existing descriptor and mutex retained.
Normal request/clear writes only; no new analog setup, reset, calibration,
OTP engine, thermal zone, trip points, current or regulator control.

Calibration investigation found incompatible ACK paths. Generic pmic_temp.c
uses a10byte NVMEM cell at0x3e, calibration enable bit14 and degc bits13:8.
MT6893-specific mtk_pmic_efuse_mt6893.c instead reads0x11ce–0x11d8,
with calibration enable bit8 and degc bits5:0. The MT6359P register header
names0x11ce/0x11d0/0x11d2/0x11d4 as NAG8/9/10/11,0x11d6 as ELR_NUM,
and0x11d8 as ELR0. Do not assume the dedicated filename proves correctness.
Saved ACK attempt28 logs show calibration enable0,VTS0/34/8170/0;
older full ACK logs explicitly select fallback VTS1600,degc50,slope0.
This does not establish that the actual device lacks fused calibration.
The true calibration layout remains unresolved. No Celsius conversion used.
The ACK intercept and sample slope formulas also scale o_slope differently
(factor +/- slope*10 versus factor +/- slope); preserve as an audit question,
not an unverified correction. External search produced no usable corroboration.

ACK CHIP_TEMP uses the same request/output addresses and defaults8samples,
ratio1/1; MT6359P probe attaches no CHIP_TEMP convert callback. Mainline scale
returns fractional millivolts; an IIO_TEMP label alone would incorrectly imply
that applying this scale yields temperature. Diagnostic board array avoids it.

Build completed without compiler warnings; extracted-code FDT, PMIF guards
and ADC scale tests passed. Incremental checkpatch passes0errors/0warnings
with commit-description/signoff checks excluded for this uncommitted patch.
Initial unfiltered checkpatch result is retained separately. git diff --check
passes. No DTS/config changes, no new binding validation necessary this round.
Source hashes/address audit saved in attempt-35/audit.json; incremental patch,
pre-change source, build/capacity and baseline logs preserved.

Hardware plan: verify two voltage channels and no temperature interface;
sample CHIP_TEMP and BATADC alternately16times, stop on errors, check dmesg,
USB SSH,8CPUs,watchdog,readonly cache/root hash and seven PMIF registers.
No physical key test needed unless a regression appears. No GPT/rootfs changes.
ACK recovery remains original evidence/ack-boot.img. Code/analysis generated
with Codex assistance; no commits or Signed-off-by.

## Hardware results

Fastboot serial IF7HHUAUVSHIGMJR verified; boot image hash matched, flash and
reboot succeeded. First SSH attempt reached USB but sshd was not yet listening;
retry succeeded with the expected kernel release at uptime26.68s.
Exactly two voltage channels exposed, no temperature interface. CHIP_TEMP
label chip_temp_voltage and scale0.439453125mV/count; initial raw1565.
Sixteen alternating CHIP_TEMP/BATADC read pairs succeeded. CHIP_TEMP was1565
in every sample (687.744140625mV); battery ranged21029–21076, nominal
4043.051–4052.087mV, mean4048.543mV. All repeated CHIP_TEMP values being equal
is not proof that conversions track temperature; freshness/thermal response
needs a separate test. No Celsius conversion or calibration claim.

USB SSH,CPUs0–7,watchdog feeder,Debian hash and cache ro,norecovery verified.
PMIC/GPIO keys registered; no physical key event retest. Five PMIC IRQ rows
unchanged across15s (all zero), final recorded uptime68.40s. Seven audited
PMIF/clock registers unchanged from attempt34. Captured dmesg contains no ADC
stop/reset errors, PMIF transaction errors, CPU warning/oops/BUG/call trace.
Existing missing RTC/accdet nodes,UFS mphy reset,initial console and intentional
GPT diagnostics remain; this is not a claim of a warning-free boot.

Evidence: initial.txt (early sshd refusal), initial-ready.txt, samples.txt,
sample-analysis.json, regression.txt, snapshot.json, state-comparison.json,
dmesg-final.txt and flash.txt. Next work: establish real MT6359P calibration
mapping and validate CHIP_TEMP conversion freshness/response before adding
thermal reporting. Do not infer a no-calibration chip from legacy ACK fallback.
