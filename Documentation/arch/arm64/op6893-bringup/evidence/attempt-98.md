# attempt-98 — vendor conninfra stack import (phase A, power-on path)

**Host-built only, not flashed.** Hypothesis markers noted inline.

Ported into drivers/misc/mediatek/connectivity/ (from qqcandy 6.18, retargeted
CONNAC2X2_SOC3_0/6893): connadp, connfem, conninfra (mt6893 platform), compat/.
7.3 API-drift fixes in compat/include/compat_shim.h (strncpy→strscpy,
get_random_int→get_random_u32, alarm_start_relative→alarm_start_timer,
rtc_time64_to_tm stub for log timestamps) + MTK_DISP_EVENT_BLANK define +
connfem_dt_parser of_gpio→fwnode_gpiod_get_index rewrite. Config:
CONFIG_MTK_COMBO=y, MTK_COMBO_CHIP_CONSYS_6893=y, dedicated log path=y.

Power path (hypothesis-verified against rail_cycle sequence):
consys_clk_get_from_dts → no-op; consys_platform_spm_conn_ctrl_mt6893(enable)
→ op6893_conn_mtcmos_on/off exported from arch/arm64/kernel/op6893-conn.c
(include/linux/soc/mediatek/op6893-conn.h), mutex+refcount under conn->lock;
vendor path refuses while preflight is attempted/unsafe; rail_cycle refuses
-EBUSY while vendor_hold. Extracted domain-only sequence:

on:  spm=(v&~0xffff0001)|0x0b160001; host(0x1020e504)|=BIT0; spm=0x0b160001;
     0x304|=BIT2; 0x304|=BIT3; wait 0x16c&BIT1 && 0x170&BIT1;
     0x304&=~BIT4; 0x304&=~BIT1; 0x304|=BIT0;
     infra+0x2a4=BIT14 wait 0x228 BIT14 clear; infra+0x718=BIT2 wait 0x724 BIT2
     clear; infra+0x2a4=BIT13 wait 0x228 BIT13 clear; usleep 6-7ms.
off: spm=0x0b160001; protect set 0x2a0 BIT13/14 (poll 0x228), 0x714 BIT2 (poll
     0x724); 0x304 set BIT1,BIT4 clr BIT0,BIT2,BIT3; wait both BIT1 clear;
     host&=~BIT0.

DT: consys@18000000 (mediatek,mt6893-consys), 16-entry reg in ACK DTB order,
memory-region→consys-reserve-memory@50000000 size 0x450000 no-map (ACK
alloc-range 0x50000000+0x40000000; no overlap with ramoops 0x48090000+0xe0000).
No clocks property (vendor clk path stubbed).

Trigger: /dev/conninfra_dev ioctl CONNINFRA_IOCTL_DO_MODULE_INIT(2) →
conninfra_dev_do_drv_init → connsys_hw_pwr_on; then GET_CHIP_ID(0),
GET_ADIE_CHIP_ID(3). Static helper: R/connport/conn-pwr (aarch64). Success
logs: 'Consys HW version id'/'A-die CHIP_ID' pr_info. Probe registers only
(hypothesis: no power-on at probe — to verify on hardware).

Superseded dists: 989fae851e31, cb3539cb7b9a, 2f65e934aa53 — superseded by final 7863049318ed.
Superseded: 7863049318ed (syscon regmap path — wrong; pwrap regmap has custom accessors). Final: 3b841c05214c.
Superseded: 3b841c05214c (booted, probe not reached — consys nested inside &pio; LK merge FDT_ERR_EXISTS).
Final: 48fd636e6955 (consys@18000000 at root via /{} block; merge reuses embed reserved-memory; retries 200->20).

Hardware 48fd636e6955: probed mtk_conninfra 18000000.consys (consys-mem 0x8db00000/0x450000, emi ok), then Oops -> panic in pmic_mng_init: pmic_mng_get_regmap read chip->regmap from pwrap drvdata (struct pmic_wrapper, not mt6397_chip) -> garbage regmap -> IABT at regmap_update_bits_base calling VS2 VOSEL write (addr 0x18b4 mask 0x7f val 0x35). Fixed in 595bbb907a96: dev_get_regmap(pwrap dev) + int return + fail-closed in pmic_mng_init; supersedes 48fd636e6955.

Hardware 595bbb907a96: probe completed cleanly (all stages ok, /dev/conninfra_dev + /proc/driver/conninfra_dbg present). Next: power-on via new conninfra_dbg cmds 0x30/0x31 -> conninfra_pwr_on/off(CONNDRV_TYPE_BT); bb061735c9a7 supersedes.

Hardware bb061735c9a7: probe OK; power-on hung in conninfra_core_pre_cal_blocking (no Wi-Fi pre-cal client; infinite NOT_INIT loop). 7d644cc025ce: dbg 0x30/0x31 call conninfra_core_power_on/off directly; blocking wait bounded to 2 s; supersedes.

Hardware 7d644cc025ce: 0x30 reached msg thread; thread Oopsed NULL+0xb8 in osal_wake_lock_count (wakeup_source_register is a NULL stub with CONFIG_SUSPEND=n -> pLock->wake_lock NULL; boot-time conn_drv_init powered BT at ~12 s, crashed before the manual 0x30). 66f7d22c6262: CONFIG_SUSPEND=y + NULL guards in osal_wake_lock_*; supersedes.

Hardware 66f7d22c6262: 0x30 completed FULL vendor power-on (Consys HW version id=0x20010101 cfg_id=0x3, A-die CHIP_ID=0x66358a11, SPI writes, raise_voltage, low_power_setting, pwr_on ret=0, no Oops). ~10-30 s after 0x31 power-off the SoC vanished from USB (fastboot intercept) — cause UNCONFIRMED; hypothesis: extracted mtcmos off sequence or CONN access after off. 6d0921598f8f: mtcmos_off now retains the domain (decrement only, no writes; hw sequence kept under CONFIG_OP6893_CONN_MTCMOS_OFF=n); vendor_domain_on makes later mtcmos_on a no-op; supersedes.

Bisection harness (3f8fcf1d41c2): crumb page 0x48180000 (free: mblock-17 ends 0x48170000+0x10000; next reserved 0x48c00000), ioremap nGnRE + dsb sy, 64-slot ring, sysfs crumbs_cur/crumbs_prev (root-only, seq-ns format). Steps enum: 0x200+step*2[+1 after]; skip mask via dbg 0x32, dump via 0x33. off steps bits 0-8: raise_voltage/spm_ctrl/pinmux/clkbuf/pmic/wakeup/subsys_status/spi_cfg/lowpower. R/attempt98-off-bisect.sh <mask>: on->mask->off; self-reboot recovery via crumbs_prev + R/crumb-decode.py.

Bisect result (hardware, 3f8fcf1d41c2): mask 0x1ff (skip all) -> no reset; 0x010 (skip pmic only) -> NO reset; 0x1ef (run only pmic) -> RESET; 0x000 -> RESET. Cause: PMIC power-off step (consys_plt_pmic_common_power_ctrl(0) -> regulator_disable vcn13/vcn18 / VS2-VCN13 changes) resets the SoC while the CONN domain is retained powered. Crumb page did not survive the reset (crumbs_prev empty) — hypothesis only. af4e2a7fdf24: op6893_off_skip_mask default=BIT(4), rails retained with pr_info; supersedes.

attempt99: pinned mode (op6893_conn_pin, default true, dbg 0x34) — pinned infra stays on, later on/off is bookkeeping-only (fixes cycle-2 reset); conninfra_core.c restored from connport (my sed had truncated it to 286 lines — the real link-drop cause, not bt); force_wakeup/sleep stubs -EOPNOTSUPP (no upstream def); bt/btif wired under CONFIG_MTK_COMBO_BT=y; scripts hci-reset + attempt99-run/fw-push. Build d929309fdc46.

a7e6bf0beec5: pinned scope fixed — normal off branch (0x31/BT) now also skips consys_hw_pwr_off + vcn off when pinned (force branch was covered; the per-subsys branch was the cycle-2 reset vector); vcn on skipped symmetrically; missing core_lock unlock on already-off force path fixed; crumb placed after decls.

958ff6e32eff: DT btif@1100c000 (reg 0x1100c000+0x11000d80/0x1100e000, irqs 0x9e/0x98/0x99, fixed-clock btif_clk 26MHz always-on) + bt@18000000 (3x 0x100000 regs, irqs 0x178/0x179, flavor_bin=a) extracted from live 6.6 DT via adb; LK merged dtb had no btif/bt collision. attempt99-fw-push pushes conninfra.cfg+BT_FW.cfg+soc3_0_ram_bt_*_hdr.bin to /lib/firmware.

attempt-100: gen4m + wlan_adaptor built-in (2ef75858d902); boot audit — only /dev/wmtWifi + probe registration at boot, no CONN MMIO before conn_pwr resolves; pre-cal trigger = echo 1 > /dev/wmtWifi (WLAN_OPID_FUNC_ON through conninfra pre-cal).

abb806980b75 (chunk3): op6893_wifi_go gates all Wi-Fi hw init on echo 1 > /dev/wmtWifi (no boot-time power-on, no NVRAM retry loop; defaults if blob absent). Wi-Fi blobs in initramfs.

62b76e366f2b (chunk4): wifi@18000000 gets memory-region=<&wifi_mem> + flavor_bin=a + emi-addr/size/alignment/max-addr props — root cause of probe -22: of_find_memory_region could not resolve -> "can NOT find memory-region" -> return false -> probe -EINVAL, leaving conninfra wifi callbacks (wf=) unregistered and wland thread g_data=0xDEADBEEF. Netdev is created by wlanProbe->glRegisterNetDev inside the deferred go-flag path.

2cb02d5fadbc (chunk5): wifi-mem gets compatible="shared-dma-pool" + no-map — root cause of probe -22 confirmed: of_reserved_mem_device_init(axi.c:453) returns -EINVAL unless the memory-region node is a shared-dma-pool no-map node (as vendor wifi-reserve-memory was). Probe should now pass; wf= callbacks register.


a91e936af2eb (chunk7): XAGA-WF breadcrumbs at wlanAdapterStart LP-OWN acquire + WAIT_FIRMWARE_READY (wlan_lib.c). reason:3 = ADAPTER_START_FAIL — wlanAdapterStart() failed after firmware download; same chain succeeded under pre-cal (wlanPreCalPwrOn). Hypothesis: WF MCU still running/LP-OWN held from pre-cal → driver-own handshake against live MCU fails, OR pinned subsys-only pwr_on skips a step the pre-cal full path did. Breadcrumbs pinpoint it next run.
