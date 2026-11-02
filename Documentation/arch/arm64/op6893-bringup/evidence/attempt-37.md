# Attempt37: calibrated PMIC die-temperature diagnostic interface

Status: flashed and hardware smoke test passed; device left running74e7947a974f.
Boot74e7947a974f SHA256
f6d6755fdd0b8bff808f68b64f713ad3df1810fe806fcb871731d5a7ffdedff0.
Baseline/rollback d353a067577a; unchanged Debian9825862f46b0.

Board/build-gated ADC array gains IIO_TEMP channel2 with PROCESSED only,
label chip_temp. Standard in_temp2_input unit is milli-degrees Celsius per
Documentation/ABI/testing/sysfs-bus-iio. Existing battery and CHIP_TEMP voltage
raw/scale interfaces retained. Physical CHIP_TEMP descriptor/address reused;
direct-only mode skips buffered scan-index uniqueness (verified in IIO core).
No buffers,thermal zone,trips,cooling or DT temperature consumer added.
The same DT channel number still resolves to the earlier voltage descriptor;
this diagnostic alias is not yet a generic thermal-provider binding design.

Processed reads take the ADC mutex, read only MT6359P ELR8/9 shadows
0x11e8/0x11ea, validate enable,degc38–60,VTS1–4095 and zero effective slope,
then request the existing12-bit CHIP_TEMP ADC conversion. No OTP engine,
reset,averaging,calibration or regulator writes added. ID0 ignores slope bits
as vendor code does; ID1 with nonzero slope returns EOPNOTSUPP. Invalid
calibration returns ENODATA. PMIF/ADC errors propagate without fallback values.
Retain vendor integer-millivolt truncation and zero-slope1681 transfer factor.
Every read refreshes calibration instead of trusting a boot-time cache.

New extracted-C host test checks all4096 ADC codes against64-bit reference
arithmetic, calibration absence/invalid ranges/nonzero slope, both calibration
read failures and ADC timeout/I/O errors. Invalid calibration never requests
ADC sampling. UBSan passes. Prior attempt36 test establishes equivalence with
actual vendor C for this unit's captured calibration. Test now hashed/run and
preserved by build.py. Host test is error injection only; no device faults
or fake calibration writes performed.

Build no compiler warnings. Incremental checkpatch0errors/0warnings with
commit-message/signoff checks excluded; git diff --check passes. Existing
FDT,PMIF guard and ADC scale tests pass. No DTS/config change. Maintainer
list saved, no messages sent. No commits or Signed-off-by. Code/analysis
generated with Codex assistance.

Hardware plan: check voltage and temperature interfaces/labels, sample
raw-before/processed/raw-after and compare quantized vendor conversion allowing
for changing sequential ADC samples. Verify calibration remains stable,
8CPUs,USB SSH,watchdog,readonly root/cache,PMIF state and dmesg. No physical
key test required unless a regression appears. No GPT/rootfs changes.

## Hardware verification

Serial IF7HHUAUVSHIGMJR and boot SHA verified; fastboot flash boot and reboot
succeeded. Expected release reached USB SSH by uptime10.21s. Sysfs exposes
in_temp2_input/label plus both prior voltage raw/scale/label interfaces.
Initial processed value37587mC. Sixteen sequential raw-before/temperature/
raw-after/battery groups all succeeded: temperature37587mC in every group,
CHIP_TEMP before/after1562, exactly matching the captured-calibration vendor
formula. These are independent conversions, not an atomic same-sample proof.
Battery raw21104–21145, nominal4057.471–4065.353mV.

Five calibration shadows unchanged before/after sampling and match attempt36.
Seven audited PMIF/clock registers also unchanged.8CPUs,USB SSH,watchdog feeder,
Debian root hash and cache ro,norecovery verified. Both key devices registered;
physical key events not retested. Five PMIC IRQ rows remain zero/unchanged over
15s; final regression uptime65.86s. Captured dmesg has no ADC stop/reset errors,
PMIF transaction errors,CPU warning/BUG/oops/call trace. Existing boot resource
and intentional GPT diagnostics are not resolved by this test.

Evidence: flash.txt,initial.txt,samples.txt,sample-analysis.json,regression.txt,
snapshot.json,state-comparison.json. Host capture tool now also permits this
validated image; previous tool source preserved in this evidence directory.

Temperature remains a board-specific diagnostic estimate without external
accuracy validation,thermal zones,trips or cooling actions. PMIC die reporting
does not cover CPU/GPU temperatures. Next useful scope: audit the SoC LVTS
controller/calibration and missing resources before planning thermal control;
retain disabled DVFS/idle/suspend and existing clock/regulator policy.
