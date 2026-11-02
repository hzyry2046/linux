# Attempt34: battery ADC diagnostic subset

Status: build/static validation and hardware sampling/regression complete.
Device left running mainline b0e531f6c970.
Boot b0e531f6c970 SHA256
56e32a3d398b1c6568798a73e643f278cbc68264cae414c271c85f65d861ffbe.
Baseline b83ff1cd5a1f; Debian9825862f46b0 unchanged.

Audit: nine MT6359 ADC register offsets match ACK MT6359P definitions.
All12 normal channel output addresses also match: ACK symbolic ADC38/39/40
are contiguous at0x10c4/0x10c6/0x10c8, corresponding to mainline arithmetic
indices30/31/32. Different names are not a register-address mismatch.
BATADC uses RQST0=0x1108 bit0,ADC0=0x1088,ready bit15,15data bits,
128sample wait,reference1800mV,divider7/2; all match ACK.

Reset audit: both use key0x6359 at0xfb4,assert/deassert mask0x9 at0xf90,
then relock. ACK debug reset adds TSX/MDRT request bits; ACK MT6359P probe
also writes MDRT2/CON10. This experiment copies none of those init writes:
board/build-gated mutable chip info exposes only the first BATADC channel,
no_reset=true and no impedance callback. Startup and timeout resets skipped;
misleading reset log also suppressed for no_reset models. Analog/averaging
setup inherited from LK. Sampling writes0x1108=1 and clears it to0 using
existing normal ADC code, waits and polls result; it is not read-only.
No dummy load,current/impedance sampling,thermal conversion or regulator
control enabled. No IIO buffers or triggers,only direct access.

Found and fixed existing raw scale bug: denominator omitted2^realbits.
Scale now numerator*vref/(denominator*2^realbits), returned as fractional.
MT6359 BATADC channel type corrected from resistance to voltage. Battery
scale=12600/65536mV/count (0.1922607421875); raw16384 represents3150mV.
Host test extracts actual scale branch: old source fails transfer-law check,
new passes12/15bit and integer/fractional divider cases with UBSan. This
normalizes digital scale; other channels' physical units/calibration remain
outside this board test. Test is hashed/run/preserved by build.py.

Calibration: ACK MT6359P probe does not attach the MT6358 BATADC software
calibration function; no new efuse/calibration handling enabled here. Values
are nominal ADC estimates, not independent meter validation, battery charge
percentage or a working power_supply driver.

Build no compiler warnings; all three incremental checkpatch runs pass0/0.
Host FDT,PMIF guard and ADC scale tests/packing pass. Actual ADC DT node
validates against existing ADC schema; no full board schema claim.
Audit source hashes and maintainer discovery saved, no messages sent.

Hardware results: flash/reboot succeeded; exactly one IIO voltage channel
(MT6359, bat_adc) exposed. First raw sample20987; subsequent16 samples at
0.5s intervals range20990–21029, nominal4035.553–4043.051mV, mean4039.278mV.
All reads succeeded. No ADC reset/timeout, PMIF transaction error, warning,
oops or call trace found in captured final dmesg. No independent calibration.

USB SSH, eight online CPUs, watchdog feeder and unchanged Debian root hash
verified; cache remains ro,norecovery. Seven audited PMIF/clock registers
match attempt33. Five PMIC IRQ rows remain unchanged (all zero) across15s
idle observation; final recorded uptime134.68s. PMIC and GPIO key devices
registered; physical key events not retested (latest test attempt32).
Evidence: attempt-34/sample-analysis.json, regression.txt, idle.txt,
state-comparison.json and dmesg-final.txt. This is a short smoke test, not
long-duration stability or power-management validation.

No GPT/root image changes; ACK recovery stays original evidence/ack-boot.img.
Code/analysis generated with Codex assistance; no commits or Signed-off-by.
