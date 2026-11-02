# Wi-Fi: ACK history lessons and mainline applicability

Reviewed 2026-11-02. Historical assistant notes are leads, not proof of current
hardware behavior. No device operation or kernel change in this review.

## Sources

- `/home/hzyry2046/.claude/projects/-home-hzyry2046/memory/op6893-connsys-bt-map.md`
- `/home/hzyry2046/.claude/projects/-home-hzyry2046/memory/op6893-droidspaces-fw-fallback.md`
- Session records under `.claude/projects/-data-src-6-6-exp/`:
  `6d554c37-d156-4cdc-9f78-0a422276a0ff.jsonl` lines100,151;
  `62dd8892-e9fb-4af2-a75c-4ba3027c87ce.jsonl` line81;
  `fae17369-f632-4c4b-830b-6f5a95893ad5.jsonl` line2468;
  `e342cfd0-34c8-4347-88aa-9ff89ed8a281.jsonl` line117.
  These contain echoed historical source/notes, not independent new test results.
- Cross-check: current ACK connectivity sources under
  `/data/src/6.6-exp/android_kernel_modules_oneplus_mt6833/vendor/mediatek/kernel_modules/connectivity/`.

## Lessons verified against current ACK source

| Issue | Evidence | Mainline action |
|---|---|---|
| False success of runtime PM without a domain | conninfra connv2/platform/mt6893/mt6893.c forces clock-backed PG_CONN for legacy DT | Implement real CONN power ownership; do not infer powered state from successful PM API return. Legacy macro override is tied to ACK DT, not universally required. |
| NULL PMIC regmap on DT lacking pmic phandle | platform/pmic_mng.c has mt6359-pmic fallback; mt6893_pmic.c guards VS2 write | Explicitly resolve real PMIC provider and defer/fail if absent. A skipped write is not proof of correct power sequence. |
| Pre-cal disable workaround later blocks WLAN | core/conninfra_core.c:2454–2486 explains removed unconditional override; gen4m chips/common/cmm_asic_common.c:430–452 waits up to100 iterations of100ms | Audit BT/WLAN callbacks and support mask as a state machine. Do not disable calibration to make a Wi-Fi-only port appear ready. Determine whether BT participation is required before choosing minimal modules. |
| Config missing at early probe | conf/conninfra_conf.c:621–636 retries config after historical /vendor mount delay | Put verified firmware/config in external rootfs; load connectivity after rootfs is ready. Test missing-file failure explicitly. |
| Wrong gen4m platform/build selection | gen4m/Kbuild.6893 selects CONNAC2X2_SOC3_0, HIF axi, CONNAC_VER2_0 and Android EMI/WMT flags | Use as hardware identification/build reference. Audit Android-specific flags rather than accepting them wholesale. |

## Historical observations requiring separate validation

- Firmware helper fallback once added roughly three minutes to first-stage ACK
  boot because ueventd was absent. Debian bring-up should use direct firmware
  files after rootfs mount; no blanket USER_HELPER_FALLBACK workaround.
- Vendor `/dev/wmtWifi` func-on and callback registration were needed before
  usable WLAN. Mainline Debian has no Android HAL to invoke that interface.
  Plan an explicit, bounded startup step if retaining this vendor ABI, then
  cfg80211/nl80211 association through wpa_supplicant or equivalent. Verify
  NVRAM delivery path as well; do not assume Android supplied no configuration.
- ACK selected `CONFIG_MTK_WIFI_CCCI_SUPPORT=n` and
  `CONFIG_MTK_WIFI_MDDP_SUPPORT=n` to avoid modem dependencies. Verify current
  source/build selection and symbol closure; never silence unresolved symbols
  with KBUILD_MODPOST_WARN for a deployable module.
- ACK notes report scan-time cfg80211 counted-array traps and connect-time
  BPF LPM trie traps triggered by Android ConnectivityService. They called
  these false positives and disabled UBSAN. That diagnosis is not reproduced
  here. Do not disable mainline UBSAN globally based on this history; inspect
  any actual report with the current compiler/source/config. Debian startup
  does not imply the same ConnectivityService BPF path.
- GKI protected exports/signing and Android first-stage module lists are ACK
  packaging constraints, not hardware prerequisites. Build mainline modules
  against the exact new config and generated symbol versions; no reuse of
  ACK binaries, stale /tmp symvers, version stripping, or guessed CRCs.
- Historical EMI MPU failures were described as cosmetic because networking
  worked. This does not establish DMA isolation or correct memory ownership;
  retain explicit EMI/DMA validation as an acceptance gate.
- MT6359P rail observations in notes include BT-only states; do not assume
  those rail states or voltages are sufficient for Wi-Fi RF activity.

## Revised startup design

Keep emergency USB and root storage built in. Mount external rootfs, verify
firmware/config availability, then load audited power/resource providers and
connectivity modules. Register all required calibration participants before
requesting radio power. Use bounded startup with recorded calibration,
firmware, DMA and IRQ milestones. Add association/DHCP/reconnect only after
scan works. Test USB-free SSH before changing USB resource ownership.
