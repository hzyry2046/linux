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
#define CCCI_DPMAIF_AO_UL_AP_L2TIMCR0	0x84
#define CCCI_DPMAIF_AO_UL_AP_L2TIMSR0	0x88
#define CCCI_DPMAIF_PD_UL_ADD_DESC	0x00
#define CCCI_DPMAIF_PD_UL_ADD_DESC_CH0	0xb0
/* The vendor derives this from pd_ul_base + 0x400 rather than mapping it. */
#define CCCI_DPMAIF_PD_MISC_BASE	0x400
#define CCCI_DPMAIF_PD_AP_UL_L2TISAR0	0x00
#define CCCI_DPMAIF_PD_MD_IP_BUSY	0x00
#define CCCI_DPMAIF_PD_MD_IP_BUSY_MASK	0x40

/* Uplink ring programming, from the same-board v2 driver. */
#define CCCI_DPMAIF_AO_UL_CHNL_ARB0	0x1c
#define CCCI_DPMAIF_AO_UL_CHNL0_CON0	0x20
#define CCCI_DPMAIF_AO_UL_CHNL0_CON1	0x24
#define CCCI_DPMAIF_UL_QSAR(q)		(CCCI_DPMAIF_AO_UL_CHNL0_CON0 + 0x10 * (q))
#define CCCI_DPMAIF_UL_DRBSIZE(q)	(CCCI_DPMAIF_AO_UL_CHNL0_CON1 + 0x10 * (q))
#define CCCI_DPMAIF_UL_ADD_DESC(q)	(CCCI_DPMAIF_PD_UL_ADD_DESC_CH0 + 0x04 * (q))
#define CCCI_DPMAIF_DRB_SIZE_MSK	0x0000ffff
#define CCCI_DPMAIF_DRB_ADDRH_MSK	0xff000000
#define CCCI_DPMAIF_UL_ADD_UPDATE	BIT(31)
#define CCCI_DPMAIF_UL_ADD_NOT_READY	BIT(31)
#define CCCI_DPMAIF_UL_INT_DONE(q)	BIT(q)
#define CCCI_DPMAIF_UL_INT_QDONE_MSK	(0x1f << 0)
#define CCCI_DPMAIF_UL_INT_ERR_MSK	(0x1f << 20)
#define CCCI_DPMAIF_UL_INT_MD_NOTREADY_MSK	(0x1f << 10)
#define CCCI_DPMAIF_UL_INT_MD_PWR_NOTREADY_MSK	(0x1f << 15)
#define CCCI_DPMAIF_UL_INT_EN		(CCCI_DPMAIF_UL_INT_QDONE_MSK | \
					 CCCI_DPMAIF_UL_INT_ERR_MSK | \
					 CCCI_DPMAIF_UL_INT_MD_NOTREADY_MSK | \
					 CCCI_DPMAIF_UL_INT_MD_PWR_NOTREADY_MSK)
#define CCCI_DPMAIF_UL_DRB_ENTRIES	2048
#define CCCI_DPMAIF_UL_DRB_WORDS	2
#define CCCI_DPMAIF_UL_PAYLOAD_MAX	1600
#define CCCI_DPMAIF_UL_POLL_LIMIT	1600000

#define CCCI_DPMAIF_DES_PD		0x0
#define CCCI_DPMAIF_DES_MSG		0x1

/* Two-word uplink descriptors; the layout is the vendor's, bit for bit. */
struct ccci_dpmaif_drb_pd {
	u32 dtyp:2;
	u32 c_bit:1;
	u32 reserved:5;
	u32 data_addr_ext:8;
	u32 data_len:16;
	u32 p_data_addr;
};

struct ccci_dpmaif_drb_msg {
	u32 dtyp:2;
	u32 c_bit:1;
	u32 reserved:13;
	u32 packet_len:16;
	u32 count_l:16;
	u32 channel_id:8;
	u32 network_type:3;
	u32 r:1;
	u32 ipv4:1;
	u32 l4:1;
	u32 rsv:2;
};

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
