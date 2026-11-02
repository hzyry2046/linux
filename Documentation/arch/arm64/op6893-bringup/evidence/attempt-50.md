# Attempt50: vendor calibration and Debian activation contract

Source audit only. Device baseline remains attempt48, boot06374ef46937.
No build, module insertion, NVRAM write, firmware activation or flash performed.
Numbered source excerpts and SHA256 manifest are in attempt-50/.

## Decision: preserve real BT calibration participation initially

The current ACK conninfra implementation is explicitly a two-participant
BT+WLAN protocol. This is a dependency of the selected software implementation,
not proof that every possible MT6893 driver must expose Bluetooth to users.

- conninfra_core_subsys_ops_reg schedules preparation once BOTH do_cal callbacks
  exist. opfunc_pre_cal_prepare refuses to schedule if either is missing.
- opfunc_pre_cal powers both subsystems, waits for both power callbacks, runs
  BT calibration then WLAN calibration, and backs up WLAN calibration in EMI.
- BT callback calls btmtk_set_power_on(hdev, TRUE); calibration sends a real
  firmware command and processes the response. A success-returning stub would
  not be equivalent. Retain actual bt_drv_6893/BTIF/firmware dependencies for
  initial bring-up; Bluetooth pairing/UI is not an acceptance requirement.
- Loading the final callback participant can schedule hardware activity.
  Do not insert the combined stack merely to test symbol resolution until
  power, memory and firmware prerequisites have been established.

## Two different completion states

conninfra cal_info->status and gen4m g_fgEverCal are different state variables.
PRE_CAL_ALL_DISABLED may set conninfra PRE_CAL_DONE in pre_cal_start, but it
cannot make gen4m's is_cal_flow_finished return true: on this path that function
returns g_fgEverCal. wlan_func_on_by_chrdev waits100 times100ms, then EBUSY.

Moreover, wlan_precal_docal_v1 sets g_fgEverCal even on its error exit. Thus
"flow finished" is NOT calibration success. Acceptance must include callback
return codes, successful firmware initialization and observed network behavior.
The callback wait loop in opfunc_pre_cal repeats after down_timeout diagnostics;
it does not impose an overall deadline there. Userspace timeout cannot cancel
arbitrary blocked kernel work. Review cancellation/cleanup before deployment;
no kernel hang or newly reproduced bug is claimed by this static audit.

## NVRAM delivery is part of initialization

- gen4m gl_init.c registers wlanNvramBufHandler with the adaptor.
- wmt_cdev_wifi.c accepts a single write containing the12-byte prefix
  `WR-BUF:NVRAM` followed by the binary payload. It can wait up to2000*100ms
  for a missing handler. Confirm driver readiness before attempting it.
- wlanNvramBufHandler copies bounded data, marks NVRAM_STATE_READY and registers
  platform callbacks if they were not already registered. This can unlock the
  automatic BT+WLAN calibration sequence.
- There is also a module parameter `nvram` using request_firmware in
  glLoadNvram, called from wlanOnPreAdapterStart. Its existence alone does not
  establish that it bootstraps the prior calibration/func-on gate. Trace the
  selected build's entry path before choosing this instead of the adaptor ABI.
- Later writing `1` to wmtWifi requests normal WLAN func-on. Success requires
  a full-count write and subsequent driver/firmware milestones, not just the
  existence of a device node or wiphy.

Do not use another device's NVRAM, synthesize RF calibration, or treat a MAC
address alone as the complete payload. Exact on-device calibration format,
source and integrity remain to be collected. No payload was sent this round.

## Candidate component closure and next implementation work

Real CONN power/PMIC/EMI resources -> conninfra (+ required support exports),
BTIF + bt_drv_6893, cfg80211 + wlan_page_pool + connac2 adaptor + gen4m SOC3_0.
connfem/connadp and ancillary exports still require build-level dependency
closure. This is a candidate set, not a successful mainline build.

Next: locate/hash this device's firmware/config/NVRAM assets; inventory actual
exported-symbol dependencies and isolate required CONN power/EMI interfaces.
Initial userspace ordering: external rootfs ready -> firmware/assets verified ->
resource providers ready -> real participant drivers registered -> deliberate
NVRAM handoff/calibration -> normal func-on -> scan -> association/DHCP/SSH.
No Android HAL, screen-on notification, or ConnectivityService is assumed.
Preserve the USB recovery baseline throughout.
