# SPDX-License-Identifier: GPL-2.0
# Phase A: conninfra power-on only (no gen4m/wlan, no bt, no wlan_adaptor).
obj-y += connadp/
obj-y += conninfra/
obj-y += connfem/
obj-$(CONFIG_MTK_COMBO_WIFI) += wlan_adaptor/ wlan_drv_gen4m/
obj-$(CONFIG_MTK_COMBO_BT) += bt/

export MTK_COMBO_CHIP := CONNAC2X2_SOC3_0
export WLAN_CHIP_ID := 6893
export CONNAC_VER := 2_0
export MTK_WLAN_SERVICE_PATH := wlan_service/
export MTK_ANDROID_WMT := y
export MTK_ANDROID_EMI := y
export TARGET_BUILD_VARIANT := user
export CONFIG_MTK_CONNSYS_DEDICATED_LOG_PATH := y
export KBUILD_SUBDIR_CCFLAGS += MTK_WCN_REMOVE_KERNEL_MODULE
