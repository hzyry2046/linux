# Attempt49: Wi-Fi source/resource audit (no hardware activation)

Baseline remains attempt48 / 06374ef46937. This round changes documentation
only; no new image, flash, MMIO accesses or device power transition.
Source hashes and selected historical ACK log lines are in attempt-49/.
Historical ACK evidence establishes that software path, not current mainline support.

## Confirmed identification

ACK DT: `mediatek,mt6893-consys`; WLAN `mediatek,wifi`, AXI aperture
0x18000000 + 0x700000. WLAN interrupts are GIC SPI375 and378, level high.
ACK log identifies analog die MT6635, while actual WLAN firmware/driver is
SOC3_0. These identifiers are not interchangeable. Successful firmware requests:

- soc3_0_ram_wmmcu_1a_1_hdr.bin
- soc3_0_ram_wifi_1a_1_hdr.bin
- soc3_0_patch_wmmcu_1a_1_hdr.bin
- WIFI_RAM_CODE_soc3_0_1a_1.bin

ACK DT reserves consys size0x450000/alignment0x100000, Wi-Fi DMA pool
size0xf20000/alignment0x1000000. These DT nodes describe dynamic allocations;
never turn their historical addresses into new hardcoded allocations without
checking current LK reservations and overlap with kernel/rootfs memory.

## Candidate implementation and missing prerequisites

Start from the local working ACK conninfra connv2/platform/mt6893 and gen4m
chips/soc3_0 + AXI host path. Treat this as a vendor-driver bring-up on a
mainline kernel, not an upstream-ready driver. Local mt76 identifier search
found no mt6893/mt6885/SOC3_0 implementation; enabling mt76 alone has not been
established as a solution.

The 6.6 reference build includes conninfra, connfem, wlan_page_pool,
connac2x adaptor and gen4m. Audit actual selected build macros and unresolved
symbols before copying any of these wholesale.

Critical dependencies found in ACK platform code:

1. CONN power: mt6893.c explicitly forces legacy clock-backed PG_CONN from
   clk-mt6893-pg. A successful runtime-PM call without an attached domain does
   not power hardware. Current mainline PMIF clocks are not a replacement.
2. PMIC: vcn13, vcn18, vcn33_1_bt, vcn33_1_wifi, vcn33_2_wifi; direct regmap
   programming also occurs, including VS2. Audit real rails and register masks;
   do not satisfy these with dummy regulators or blindly import VS2 writes.
3. XO/clock-buffer control, sleep protection, resets and analog-die SPI
   transactions must follow the actual MT6893 power sequence.
4. EMI remap/protection and DMA ownership must match reserved RAM. ACK already
   disables optional modem MCIF coexistence; this does not eliminate EMI MPU
   or WLAN DMA requirements. Historical mapping warnings need ownership review.
5. Firmware blobs, board calibration/NVRAM and MAC provenance need capture and
   hash verification; firmware names alone do not establish usable assets.
6. cfg80211/kernel API adaptation and module dependencies must build for this
   exact mainline release before any loading experiment.

The qqcandy reference contains vendor conninfra/wlan_drv_gen4m and useful
integration structure, but its DT uses different MT6895 power domains,
MT6363/MT6368 rails, interrupts and firmware flavor. Do not transplant these.

## Ordered experiments / acceptance gates

1. Finish offline source/build-symbol and power-sequence inventory; locate and
   hash matching firmware/calibration. Reconcile live LK reserved memory.
2. Implement minimal real CONN resource support with bounded failure paths.
   First hardware test only powers/identifies the connectivity block; no RF,
   firmware DMA or broad clock cleanup. Check USB/SSH, UFS/root, eight CPUs,
   watchdog and PMIC after each change.
3. Load verified firmware, initialize DMA/IRQ, register WLAN and test scan.
4. Associate using user-selected network, DHCP and SSH; add reconnect and
   boot autoconnect in external rootfs. Keep credentials out of evidence logs.
5. Verify Wi-Fi SSH with USB data physically disconnected and reconnect after
   link loss/reboot. Only then proceed with USB/Type-C ownership changes.

Wi-Fi is a second transport, not recovery from a kernel-wide deadlock.
No Wi-Fi support or successful build is claimed by this audit.

## ACK session/memory follow-up

See [history lessons](attempt-49/ack-history-lessons.md): pre-calibration callback
ordering, PMIC regmap lookup, early firmware availability, WMT userspace
activation, GKI packaging and historical sanitizer failures. The minimal
Wi-Fi-only module set remains conditional on calibration's BT dependencies.
