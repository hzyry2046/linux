# Attempt36: live MT6359P thermal calibration audit

Status: calibration decoding, vendor arithmetic comparison, passive captures
and hand-contact observation complete. Qualitative variation observed; no
absolute accuracy or controlled thermal-response validation. No kernel changes,
flash, reset, partition change or ACK restore. Still running d353a067577a.

Local4.19 kernel_oddo_mt6893 header resolves PMIC_AUXADC_EFUSE fields to
MT6359_AUXADC_DIG_3_ELR8–12 at0x11e8/0x11ea/0x11ec/0x11ee/0x11f0.
Despite the MT6359 symbolic prefix, this is its MT6359P header; addresses also
match the6.6 MT6359P header's ELR8–12 addresses. Header field definitions:
enable bit14,degc bits13:8,slope sign7,slope bits6:1,id bit0; VTS bits12:0.
This agrees with the generic ACK temperature driver's bit layout, unlike the
hardcoded6.6 MT6893 legacy temperature calibration path. Prior ACK log fallback
therefore cannot establish absence of factory calibration. ACK code unchanged.

Mounted debugfs, verified pwrap range0-fffe. Audited regmap-debugfs.c and
pwrap_regmap_config16: stride2,maxffff,16-bit values,no cache/filter =>11byte
text records. dd bs=11 skip=2292 count=5 seeks directly to0x11e8 and reads
exactly five registers through locked regmap transactions. No full register
dump, direct PMIF command manipulation,OTP clock/control or shadow writes.
The exposed current firmware is allowlisted in pmic-temperature.py.

Two initial reads and before/after capture agree:
11e8=7100,11ea=064d,11ec=0611,11ee=060c,11f0=0616.
Decoded enable1,degc49 (24.5C),id0,slope0,sign0;
VTS chip1613,buck1553/1548/1558. Chip has enabled calibration shadow data.
No claim of independent physical calibration accuracy or fuse reload proof.

Host pmic-temperature.py reads only these shadows and existing CHIP_TEMP
IIO samples; sampling still performs ordinary request/clear writes. It computes
vendor integer-mV conversion only for enabled,plausible zero-effective-slope
calibration. Unsupported/invalid calibration yields no Celsius estimate;
there is no synthesized default. Nonzero effective slope remains deferred
because vendor intercept/sample formulas scale slope differently.

tests/test_pmic_temperature.py extracts actual4.19 C calibration and conversion
functions, compiles with UBSan and compares all4096 raw values to Python using
captured calibration. All pass; raw1613 =>24500mC,raw1565 =>36992mC.
Missing/malformed/disabled/out-of-range calibration and unsupported slope
cases tested. No tests on hardware with fabricated calibration.

Before capture a manual read changed from attempt35 raw1565 to1564, then1565.
32 passive samples were1564; a separate16-sample tool capture was1564,
estimated36992mC throughout (vendor integer-mV quantization maps both1564 and
1565 to687mV). This weak variation alone is not proof of per-request freshness
or thermal response. Hand-contact observation captured120 samples, one per second; results below.
No CPU stress load.

USB SSH,8CPUs,watchdog,readonly cache,unchanged seven-register PMIF snapshot
and no new ADC/PMIF fault diagnostics verified after passive capture. No
physical key retest. No thermal zone,trips,cooling,DVFS or suspend enabled.
Code/analysis generated with Codex assistance; no commits or Signed-off-by.

## Contact-response observation completed

User confirmed holding the device and putting it back. Exact physical contact
start/end times were not independently logged. Capture uptime473.95–593.56s,
120 successful samples: raw1564x50,1565x11,1563x15,1562x44. First20 mean1564,
last20 mean1562. Vendor estimate ranges36992–37587mC (roughly37.0–37.6C).
This supports changing output rather than a permanently frozen ADC result,
and is consistent with gradual warming. It does not isolate contact as the
cause, prove every conversion fresh, or validate absolute temperature accuracy.
The estimate is quantized by vendor integer-millivolt arithmetic.

After user completion,32 further samples at uptime683.1–714.26s
range raw1560–1560, first1560,last1560; vendor estimates
38182–38182mC. This short follow-up does not establish a full
return to the initial thermal state.

Calibration shadows unchanged throughout. Post-contact PMIF seven-register
snapshot unchanged;8CPUs,USB SSH,watchdog,readonly cache and zero PMIC IRQ
counts verified; no new ADC/PMIF fault or kernel BUG/oops diagnostics in
captured log. Device remains running d353a067577a without reflashing.
Evidence: contact-response.json,after-contact.json,response-analysis.json,
after-contact-regression.txt and after-contact-snapshot.json.

Next implementation scope: calibrated diagnostic temperature reporting using
verified shadow fields, preserving raw voltage and rejecting invalid calibration;
resolve nonzero-slope formula before generic support. PMIC die temperature is
not SoC CPU/GPU thermal coverage and does not justify enabling DVFS/suspend.
