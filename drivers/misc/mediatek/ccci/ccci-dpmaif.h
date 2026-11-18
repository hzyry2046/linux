/* SPDX-License-Identifier: GPL-2.0-only */
#ifndef __CCCI_DPMAIF_H
#define __CCCI_DPMAIF_H

#include <linux/bits.h>
#include <linux/types.h>

/*
 * Same-board register offsets, from the vendor dpmaif_reg.h. Each block is
 * mapped separately, so the vendor base macros all resolve to zero here.
 */
#define CCCI_DPMAIF_AO_UL_CHNL0_STA	0x00
#define CCCI_DPMAIF_AO_UL_CHNL0_STA0	0x60
#define CCCI_DPMAIF_AO_UL_AP_L2TIMR0	0x80
#define CCCI_DPMAIF_PD_UL_ADD_DESC	0x00
#define CCCI_DPMAIF_PD_UL_ADD_DESC_CH0	0xb0
#define CCCI_DPMAIF_PD_MD_IP_BUSY	0x00
#define CCCI_DPMAIF_PD_MD_IP_BUSY_MASK	0x40
/*
 * Infracfg busy control. The vendor ORs a two-bit field at 12 and then clears
 * bit 13, so a post-init read normally shows bit 12 set and bit 13 clear: bit
 * 13 is the MD to AP wakeup event and is not part of the mask that stays set.
 */
#define CCCI_DPMAIF_INFRA_CTRL		0xc00
#define CCCI_DPMAIF_IP_BUSY_MASK	(0x3 << 12)
#define CCCI_DPMAIF_IP_BUSY_SHIFT	12
#define CCCI_DPMAIF_WAKEUP_EVENT	BIT(13)

/* One read-only sample of the block; every field is a raw register value. */
struct ccci_dpmaif_sample {
	u32 ao_ul_chnl0_sta;
	u32 ao_ul_chnl0_sta0;
	u32 ao_ul_l2timr0;
	u32 pd_ul_add_desc;
	u32 pd_ul_add_desc_ch0;
	u32 pd_md_ip_busy;
	u32 pd_md_ip_busy_mask;
	u32 sram_word0;
	u32 sram_word1;
	u32 infra_ctrl;
	unsigned long rate_main;
	unsigned long rate_bus;
};

#if IS_ENABLED(CONFIG_OP6893_CCCI_DPMAIF)
/* Pure formatter, no I/O: one line per sampled register plus the masks. */
ssize_t ccci_dpmaif_format(const struct ccci_dpmaif_sample *sample, char *buf, size_t size);
#else
static inline ssize_t
ccci_dpmaif_format(const struct ccci_dpmaif_sample *sample, char *buf, size_t size)
{
	return -EOPNOTSUPP;
}
#endif
#endif
