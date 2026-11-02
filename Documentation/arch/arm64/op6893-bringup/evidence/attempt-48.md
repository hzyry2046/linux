# Attempt48: serialized on-demand LVTS diagnostic captures

Status: implementation,host tests and repeated/concurrent hardware reads passed.
Current mainline image06374ef46937.
Rollback:3e5080c359e5. ACK recovery is the updated455ed6ce... image documented
in ACK-RESTORE-CURRENT.md; previous976b5d... is historical only.

## Interface and freshness

Root-only sysfs attribute:
/sys/bus/platform/devices/op6893-lvts-identify/capture

Read initiates a complete capture,not cached telemetry. Each capture checks
idle state and calibration,obtains the thermal clock,resets AP/MCU domains,
identifies all devices,measures RCK,programs/verifies EDATA,checks that MSR
valid bits are clear,then collects all17samples and stops sensing/local clocks.
This repeats the validated boot procedure; no unverified clear-valid-bit write
is added. It is intentionally expensive and resets LVTS on every read. Do not
connect automatic high-frequency monitoring or use while another firmware or
kernel driver owns LVTS. No suspend/runtime-PM/ownership coordination claimed.

Output first line:sequence,start_ns,end_ns (CLOCK_BOOTTIME nanoseconds).
Subsequent17lines:sensor index,raw MSR including valid bit,temperature mC.
Times bound the whole acquisition,not per-sensor simultaneous sample times.
The interval also includes calibration/setup. Sysfs buffers one show result;
partial reads of that result do not create extra samples,while reopening or
seeking/restarting a read can trigger another acquisition.

A mutex serializes readers across the entire hardware sequence and output.
Sequence advances only on success. No output is emitted until all sensors
succeed and cleanup completes. First acquisition error returns its errno and
latches the session faulted; further reads returnEIO without hardware accesses
until reboot. Interrupted mutex acquisition returns interruption without faulting.
No userspace reset/unlock knob. dev_groups publishes the attribute only after
probe successfully initializes driver state. No unbind attributes, builtin only.
Mapping/clock references are acquired/released for each capture,not retained
past a failed operation. Existing cleanup limits still apply to unresponsive HW.

Host test compiles actual capture_show with fake acquisition and validates
sequence/timestamps,full publication,interruptible locking,sticky timeout/busy/
stale errors,no partial output and no retry after fault. Existing calibration,
RCK and sampling fault injection remain required. Checkpatch flags0400 as an
unusual DEVICE_ATTR permission; intentional root restriction retained rather
than exposing reset-on-read to all users. No other style finding expected.

AI-assisted implementation/tests/docs with Codex. No commits or Signed-off-by.
No thermal zone,IRQ/protection or CPU stress. Hardware validation will check
repeated and concurrent reads,shutdown state,base-function regressions.

Built06374ef46937 SHA256
e445fb73bbf243be73e417049d851c2a715c468513034816e90e08ef7d964792.
All integrated host tests passed; kernel build has no warning/error markers.


## Hardware validation

Initial fastboot transfer stalled during Sending; user re-entered fastboot.
Confirmed no remaining fastboot client,then reflashed the identical verified
image. reflash.log records successful send/write/reboot; first partial log is
retained. This was a transport interruption,not evidence of kernel failure.

First capture(sequence1) returned17valid samples. Six serial captures at about
one-second intervals plus four concurrent requests returned sequences2..11.
All17samples per request pass valid/nonzero checks and independent temperature
conversion. Acquisition intervals do not overlap,showing serialization under
concurrent userspace requests. Duration12.636..13.060ms; temperature range
36.349..43.839C across these captures. This is diagnostic repeatability,not
external absolute calibration or a controlled thermal response experiment.

Device lacks Python,so capture-test.py runs on the host via pinned USB SSH.
The initial attempted on-device Python command did not execute any capture.
Attribute permissions confirmed0400. No injected hardware fault; sticky-error
behavior remains host-test coverage. Avoid artificial HW errors on this unit.

Post-test snapshot:all7MONCTL/local clocks/IRQ enables/protection control and
threshold words0. PLL/AXI/infra and seven PMIF registers match attempt47.
Eight CPUs,USB SSH,watchdog feeder,PMIC ADC,cache ro,norecovery,read-only disk
and Debian hash remain normal. No selected WARN/BUG/Oops/Call trace or sampling
cleanup errors. Existing GPT warning expected. No physical key retest.

Next: reduce diagnostic reset overhead only after proving a reliable fresh-data
mechanism; establish controlled temperature response and ownership/lifecycle
before any permanent hwmon/thermal zone or protection support.
