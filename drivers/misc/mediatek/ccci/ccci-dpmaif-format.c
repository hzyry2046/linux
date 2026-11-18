// SPDX-License-Identifier: GPL-2.0-only
/*
 * Pure text formatter for one DPMAIF sample. Split out so the exact rendering
 * can be exercised on the host without any driver, clock or MMIO shim.
 */
#include <linux/errno.h>
#include <linux/kernel.h>
#include <linux/types.h>

#include "ccci-dpmaif.h"

ssize_t ccci_dpmaif_format(const struct ccci_dpmaif_sample *sample, char *buf, size_t size)
{
	int ret;

	if (!sample || !buf || !size)
		return -EINVAL;
	/*
	 * snprintf reports the length it would have written, so a buffer that is
	 * too small is an explicit -ENOSPC rather than a silently cut dump.
	 */
	ret = snprintf(buf, size,
		       "ao_ul_chnl0_sta=0x%08x ao_ul_chnl0_sta0=0x%08x ao_ul_l2timr0=0x%08x\n"
		       "pd_ul_add_desc=0x%08x pd_ul_add_desc_ch0=0x%08x\n"
		       "pd_md_ip_busy=0x%08x pd_md_ip_busy_mask=0x%08x\n"
		       "sram_raw0=0x%08x sram_raw1=0x%08x infra_ctrl=0x%08x\n"
		       "busy_mask_field=%u wakeup_event_bit=%u md_busy_mask_field=%u\n"
		       "clk_main=%lu clk_bus=%lu\n",
		       sample->ao_ul_chnl0_sta, sample->ao_ul_chnl0_sta0,
		       sample->ao_ul_l2timr0, sample->pd_ul_add_desc,
		       sample->pd_ul_add_desc_ch0, sample->pd_md_ip_busy,
		       sample->pd_md_ip_busy_mask, sample->sram_word0,
		       sample->sram_word1, sample->infra_ctrl,
		       (sample->infra_ctrl & CCCI_DPMAIF_IP_BUSY_MASK) >>
			       CCCI_DPMAIF_IP_BUSY_SHIFT,
		       !!(sample->infra_ctrl & CCCI_DPMAIF_WAKEUP_EVENT),
		       (sample->pd_md_ip_busy_mask & CCCI_DPMAIF_IP_BUSY_MASK) >>
			       CCCI_DPMAIF_IP_BUSY_SHIFT,
		       sample->rate_main, sample->rate_bus);
	if (ret < 0)
		return ret;
	if ((size_t)ret >= size)
		return -ENOSPC;
	return ret;
}
