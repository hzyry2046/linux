// SPDX-License-Identifier: GPL-2.0-only
/*
 * Read-only DPMAIF reconnaissance for the op6893 CCMNI data path.
 *
 * The same-board ABI carries CCMNI over DPMAIF on MD generation 6297, not over
 * CCIF, so the data-path port has to start from a verified view of the block.
 * This driver only samples registers: it never writes one, never requests the
 * interrupt and never moves data. Clocks are enabled for the duration of one
 * read and released again, so probe itself performs no I/O.
 */
#include <linux/bits.h>
#include <linux/clk.h>
#include <linux/device.h>
#include <linux/dma-mapping.h>
#include <linux/interrupt.h>
#include <linux/io.h>
#include <linux/kernel.h>
#include <linux/mfd/syscon.h>
#include <linux/mm.h>
#include <linux/module.h>
#include <linux/mutex.h>
#include <linux/of.h>
#include <linux/of_irq.h>
#include <linux/platform_device.h>
#include <linux/regmap.h>
#include <linux/sysfs.h>

#include "ccci-dpmaif.h"

#define CCCI_DPMAIF_BLOCKS	4

struct ccci_dpmaif_ul {
	void *drb;
	dma_addr_t drb_dma;
	void *payload;
	dma_addr_t payload_dma;
	u32 entries;
	u32 payload_len;
	u32 queue;
	u32 wr;
	u32 rd;
	u32 sent;
	u32 done;
	u32 irqs;
	u32 err;
	u32 not_ready;
	u32 last_status;
	bool started;
};

struct ccci_dpmaif {
	struct device *dev;
	void __iomem *block[CCCI_DPMAIF_BLOCKS];
	resource_size_t base[CCCI_DPMAIF_BLOCKS];
	struct regmap *infra;
	struct clk *clk_main;
	struct clk *clk_bus;
	int irq;
	/* Serializes the clock-on/sample/clock-off window and the uplink. */
	struct mutex lock;
	struct ccci_dpmaif_ul ul;
};

static void dpmaif_ul_reset_counters(struct ccci_dpmaif *dpmaif)
{
	struct ccci_dpmaif_ul *ul = &dpmaif->ul;

	ul->wr = 0;
	ul->rd = 0;
	ul->sent = 0;
	ul->done = 0;
	ul->irqs = 0;
	ul->err = 0;
	ul->not_ready = 0;
	ul->last_status = 0;
}

/* Ring programming order is the same-board v2 driver's: size, base, rdy, arb. */
static void dpmaif_ul_program(struct ccci_dpmaif *dpmaif)
{
	struct ccci_dpmaif_ul *ul = &dpmaif->ul;
	u64 base = (u64)ul->drb_dma;
	u32 value;

	value = readl(dpmaif->block[0] + CCCI_DPMAIF_UL_DRBSIZE(ul->queue));
	value &= ~CCCI_DPMAIF_DRB_SIZE_MSK;
	value |= ((ul->entries * sizeof(struct ccci_dpmaif_drb_pd)) / 4) &
		 CCCI_DPMAIF_DRB_SIZE_MSK;
	writel(value, dpmaif->block[0] + CCCI_DPMAIF_UL_DRBSIZE(ul->queue));
	writel(lower_32_bits(base), dpmaif->block[0] + CCCI_DPMAIF_UL_QSAR(ul->queue));
	value = readl(dpmaif->block[0] + CCCI_DPMAIF_UL_DRBSIZE(ul->queue));
	value &= ~CCCI_DPMAIF_DRB_ADDRH_MSK;
	value |= (upper_32_bits(base) << 24) & CCCI_DPMAIF_DRB_ADDRH_MSK;
	writel(value, dpmaif->block[0] + CCCI_DPMAIF_UL_DRBSIZE(ul->queue));

	value = readl(dpmaif->block[0] + CCCI_DPMAIF_AO_UL_CHNL_ARB0);
	value |= BIT(ul->queue);
	value |= BIT(ul->queue + 8);
	writel(value, dpmaif->block[0] + CCCI_DPMAIF_AO_UL_CHNL_ARB0);
}

static void dpmaif_ul_unprogram(struct ccci_dpmaif *dpmaif)
{
	struct ccci_dpmaif_ul *ul = &dpmaif->ul;
	u32 value;

	value = readl(dpmaif->block[0] + CCCI_DPMAIF_AO_UL_CHNL_ARB0);
	value &= ~BIT(ul->queue);
	value &= ~BIT(ul->queue + 8);
	writel(value, dpmaif->block[0] + CCCI_DPMAIF_AO_UL_CHNL_ARB0);
	/* Mask every uplink event again; only this driver unmasked them. */
	writel(CCCI_DPMAIF_UL_INT_EN, dpmaif->block[0] + CCCI_DPMAIF_AO_UL_AP_L2TIMSR0);
	/*
	 * Drop the ring base and size before the memory is freed: the hardware
	 * would otherwise keep DMAing from a buffer that no longer belongs to us.
	 */
	writel(0, dpmaif->block[0] + CCCI_DPMAIF_UL_QSAR(ul->queue));
	value = readl(dpmaif->block[0] + CCCI_DPMAIF_UL_DRBSIZE(ul->queue));
	value &= ~CCCI_DPMAIF_DRB_SIZE_MSK;
	value &= ~CCCI_DPMAIF_DRB_ADDRH_MSK;
	writel(value, dpmaif->block[0] + CCCI_DPMAIF_UL_DRBSIZE(ul->queue));
	/* Leave no latched uplink event behind for the next owner. */
	writel(0xffffffff, dpmaif->block[1] + CCCI_DPMAIF_PD_MISC_BASE +
	       CCCI_DPMAIF_PD_AP_UL_L2TISAR0);
}

/*
 * Clear the uplink status latches, then enable the wanted events. A set bit in
 * the mask register means masked, so enabling is clearing the mask bits.
 */
static int dpmaif_ul_irq_enable(struct ccci_dpmaif *dpmaif)
{
	u32 count = 0;

	writel(0xffffffff, dpmaif->block[1] + CCCI_DPMAIF_PD_MISC_BASE +
	       CCCI_DPMAIF_PD_AP_UL_L2TISAR0);
	writel(CCCI_DPMAIF_UL_INT_EN, dpmaif->block[0] + CCCI_DPMAIF_AO_UL_AP_L2TIMCR0);
	writel(~CCCI_DPMAIF_UL_INT_EN, dpmaif->block[0] + CCCI_DPMAIF_AO_UL_AP_L2TIMSR0);
	while ((readl(dpmaif->block[0] + CCCI_DPMAIF_AO_UL_AP_L2TIMR0) &
		CCCI_DPMAIF_UL_INT_EN) == CCCI_DPMAIF_UL_INT_EN) {
		if (++count >= CCCI_DPMAIF_UL_POLL_LIMIT)
			return -ETIMEDOUT;
	}
	return 0;
}

static irqreturn_t dpmaif_irq(int irq, void *data)
{
	struct ccci_dpmaif *dpmaif = data;
	struct ccci_dpmaif_ul *ul = &dpmaif->ul;
	u32 status, masked;

	status = readl(dpmaif->block[1] + CCCI_DPMAIF_PD_MISC_BASE +
		       CCCI_DPMAIF_PD_AP_UL_L2TISAR0);
	masked = readl(dpmaif->block[0] + CCCI_DPMAIF_AO_UL_AP_L2TIMR0);
	status &= ~masked;
	/* Write back what is handled: the status bits are write-one-to-clear. */
	writel(status, dpmaif->block[1] + CCCI_DPMAIF_PD_MISC_BASE +
	       CCCI_DPMAIF_PD_AP_UL_L2TISAR0);
	ul->irqs++;
	ul->last_status = status;
	if (status & CCCI_DPMAIF_UL_INT_DONE(ul->queue))
		ul->done++;
	if (status & (CCCI_DPMAIF_UL_INT_ERR_MSK | CCCI_DPMAIF_UL_INT_MD_NOTREADY_MSK |
		      CCCI_DPMAIF_UL_INT_MD_PWR_NOTREADY_MSK))
		ul->err++;
	return IRQ_HANDLED;
}

/* One synthetic frame through the uplink ring; the caller holds the lock. */
static int dpmaif_ul_send(struct ccci_dpmaif *dpmaif, u32 channel_id)
{
	struct ccci_dpmaif_ul *ul = &dpmaif->ul;
	struct ccci_dpmaif_drb_msg *msg;
	struct ccci_dpmaif_drb_pd *pd;
	dma_addr_t dma;
	u32 count = 0;
	u32 size;

	if (!ul->started)
		return -ENOTCONN;
	size = ul->payload_len;
	dma = ul->payload_dma;
	msg = (struct ccci_dpmaif_drb_msg *)ul->drb + ul->wr;
	memset(msg, 0, sizeof(*msg));
	msg->dtyp = CCCI_DPMAIF_DES_MSG;
	msg->c_bit = 1;
	msg->packet_len = size;
	msg->channel_id = channel_id;
	ul->wr = (ul->wr + 1) % ul->entries;

	pd = (struct ccci_dpmaif_drb_pd *)ul->drb + ul->wr;
	memset(pd, 0, sizeof(*pd));
	pd->dtyp = CCCI_DPMAIF_DES_PD;
	/* The last descriptor of a packet clears c_bit. */
	pd->c_bit = 0;
	pd->data_len = size;
	pd->p_data_addr = lower_32_bits(dma);
	pd->data_addr_ext = upper_32_bits(dma) & 0xff;
	ul->wr = (ul->wr + 1) % ul->entries;

	/* Publish the descriptors before the doorbell. */
	wmb();
	while (readl(dpmaif->block[1] + CCCI_DPMAIF_UL_ADD_DESC(ul->queue)) &
	       CCCI_DPMAIF_UL_ADD_NOT_READY) {
		if (++count >= CCCI_DPMAIF_UL_POLL_LIMIT) {
			ul->not_ready++;
			return -EBUSY;
		}
	}
	writel((CCCI_DPMAIF_UL_DRB_WORDS * 2) | CCCI_DPMAIF_UL_ADD_UPDATE,
	       dpmaif->block[1] + CCCI_DPMAIF_UL_ADD_DESC(ul->queue));
	count = 0;
	while (readl(dpmaif->block[1] + CCCI_DPMAIF_UL_ADD_DESC(ul->queue)) &
	       CCCI_DPMAIF_UL_ADD_NOT_READY) {
		if (++count >= CCCI_DPMAIF_UL_POLL_LIMIT) {
			ul->not_ready++;
			return -EBUSY;
		}
	}
	ul->sent++;
	return 0;
}

static int dpmaif_ul_start(struct ccci_dpmaif *dpmaif, u32 queue)
{
	struct ccci_dpmaif_ul *ul = &dpmaif->ul;
	int ret;

	if (ul->started)
		return -EBUSY;
	if (queue > 4)
		return -EINVAL;
	ret = clk_prepare_enable(dpmaif->clk_main);
	if (ret)
		return ret;
	ret = clk_prepare_enable(dpmaif->clk_bus);
	if (ret)
		goto out_main;
	ul->drb = dma_alloc_coherent(dpmaif->dev, ul->entries * sizeof(struct ccci_dpmaif_drb_pd),
				     &ul->drb_dma, GFP_KERNEL);
	if (!ul->drb) {
		ret = -ENOMEM;
		goto out_bus;
	}
	ul->payload = dma_alloc_coherent(dpmaif->dev, CCCI_DPMAIF_UL_PAYLOAD_MAX,
					 &ul->payload_dma, GFP_KERNEL);
	if (!ul->payload) {
		ret = -ENOMEM;
		goto out_drb;
	}
	ul->queue = queue;
	dpmaif_ul_reset_counters(dpmaif);
	dpmaif_ul_program(dpmaif);
	ret = dpmaif_ul_irq_enable(dpmaif);
	if (ret)
		goto out_unprogram;
	ret = request_irq(dpmaif->irq, dpmaif_irq, 0, "op6893-dpmaif", dpmaif);
	if (ret)
		goto out_unprogram;
	ul->started = true;
	return 0;

out_unprogram:
	dpmaif_ul_unprogram(dpmaif);
	dma_free_coherent(dpmaif->dev, CCCI_DPMAIF_UL_PAYLOAD_MAX, ul->payload,
			  ul->payload_dma);
	ul->payload = NULL;
out_drb:
	dma_free_coherent(dpmaif->dev, ul->entries * sizeof(struct ccci_dpmaif_drb_pd),
			  ul->drb, ul->drb_dma);
	ul->drb = NULL;
out_bus:
	clk_disable_unprepare(dpmaif->clk_bus);
out_main:
	clk_disable_unprepare(dpmaif->clk_main);
	return ret;
}

static void dpmaif_ul_stop(struct ccci_dpmaif *dpmaif)
{
	struct ccci_dpmaif_ul *ul = &dpmaif->ul;

	if (!ul->started)
		return;
	ul->started = false;
	dpmaif_ul_unprogram(dpmaif);
	free_irq(dpmaif->irq, dpmaif);
	dma_free_coherent(dpmaif->dev, CCCI_DPMAIF_UL_PAYLOAD_MAX, ul->payload,
			  ul->payload_dma);
	ul->payload = NULL;
	dma_free_coherent(dpmaif->dev, ul->entries * sizeof(struct ccci_dpmaif_drb_pd),
			  ul->drb, ul->drb_dma);
	ul->drb = NULL;
	clk_disable_unprepare(dpmaif->clk_bus);
	clk_disable_unprepare(dpmaif->clk_main);
}

static int dpmaif_collect(struct ccci_dpmaif *dpmaif, struct ccci_dpmaif_sample *sample)
{
	u32 value = 0;
	int ret;

	memset(sample, 0, sizeof(*sample));
	ret = clk_prepare_enable(dpmaif->clk_main);
	if (ret)
		return ret;
	ret = clk_prepare_enable(dpmaif->clk_bus);
	if (ret)
		goto out_main;
	sample->rate_main = clk_get_rate(dpmaif->clk_main);
	sample->rate_bus = clk_get_rate(dpmaif->clk_bus);
	sample->ao_ul_chnl0_sta = readl(dpmaif->block[0] + CCCI_DPMAIF_AO_UL_CHNL0_STA);
	sample->ao_ul_chnl0_sta0 = readl(dpmaif->block[0] + CCCI_DPMAIF_AO_UL_CHNL0_STA0);
	sample->ao_ul_l2timr0 = readl(dpmaif->block[0] + CCCI_DPMAIF_AO_UL_AP_L2TIMR0);
	sample->pd_ul_add_desc = readl(dpmaif->block[1] + CCCI_DPMAIF_PD_UL_ADD_DESC);
	sample->pd_ul_add_desc_ch0 = readl(dpmaif->block[1] + CCCI_DPMAIF_PD_UL_ADD_DESC_CH0);
	sample->pd_md_ip_busy = readl(dpmaif->block[2] + CCCI_DPMAIF_PD_MD_IP_BUSY);
	sample->pd_md_ip_busy_mask = readl(dpmaif->block[2] + CCCI_DPMAIF_PD_MD_IP_BUSY_MASK);
	sample->sram_word0 = readl(dpmaif->block[3]);
	sample->sram_word1 = readl(dpmaif->block[3] + 4);
	/* Infracfg read goes through regmap: the block is shared with other owners. */
	if (!regmap_read(dpmaif->infra, CCCI_DPMAIF_INFRA_CTRL, &value))
		sample->infra_ctrl = value;
	clk_disable_unprepare(dpmaif->clk_bus);
out_main:
	clk_disable_unprepare(dpmaif->clk_main);
	return ret;
}

static ssize_t sample_show(struct device *dev, struct device_attribute *attr, char *buf)
{
	struct ccci_dpmaif *dpmaif = dev_get_drvdata(dev);
	struct ccci_dpmaif_sample sample;
	ssize_t ret;

	mutex_lock(&dpmaif->lock);
	ret = dpmaif_collect(dpmaif, &sample);
	if (!ret)
		ret = ccci_dpmaif_format(&sample, buf, PAGE_SIZE);
	mutex_unlock(&dpmaif->lock);
	return ret;
}
static DEVICE_ATTR_RO(sample);

static ssize_t layout_show(struct device *dev, struct device_attribute *attr, char *buf)
{
	struct ccci_dpmaif *dpmaif = dev_get_drvdata(dev);

	return sysfs_emit(buf,
			  "ao_ul=%pa pd_ul=%pa pd_md_misc=%pa sram=%pa irq=%d\n"
			  "clock_main=%s clock_bus=%s\n",
			  &dpmaif->base[0], &dpmaif->base[1], &dpmaif->base[2],
			  &dpmaif->base[3], dpmaif->irq,
			  dpmaif->clk_main ? "dpmaif-main" : "none",
			  dpmaif->clk_bus ? "dpmaif" : "none");
}
static DEVICE_ATTR_RO(layout);

static ssize_t ul_show(struct device *dev, struct device_attribute *attr, char *buf)
{
	struct ccci_dpmaif *dpmaif = dev_get_drvdata(dev);
	struct ccci_dpmaif_ul *ul = &dpmaif->ul;
	ssize_t ret;

	mutex_lock(&dpmaif->lock);
	ret = sysfs_emit(buf,
			 "started=%u queue=%u entries=%u payload=%u wr=%u sent=%u done=%u irqs=%u err=%u not_ready=%u last_status=0x%08x\n",
			 ul->started, ul->queue, ul->entries, ul->payload_len, ul->wr,
			 ul->sent, ul->done, ul->irqs, ul->err, ul->not_ready,
			 ul->last_status);
	mutex_unlock(&dpmaif->lock);
	return ret;
}
static DEVICE_ATTR_RO(ul);

/*
 * ul_start takes "<queue> <payload bytes>"; the payload is one synthetic frame
 * filled by tx_one, so the operator controls exactly how many bytes the modem
 * is offered. Nothing is sent until tx_one is written.
 */
static ssize_t ul_start_store(struct device *dev, struct device_attribute *attr,
			      const char *buf, size_t count)
{
	struct ccci_dpmaif *dpmaif = dev_get_drvdata(dev);
	struct ccci_dpmaif_ul *ul = &dpmaif->ul;
	unsigned int queue = 0, payload = 64;
	int ret;

	if (sscanf(buf, "%u %u", &queue, &payload) < 1)
		return -EINVAL;
	if (payload < 14 || payload > CCCI_DPMAIF_UL_PAYLOAD_MAX)
		return -EINVAL;
	mutex_lock(&dpmaif->lock);
	ul->entries = CCCI_DPMAIF_UL_DRB_ENTRIES;
	ul->payload_len = payload;
	ret = dpmaif_ul_start(dpmaif, queue);
	mutex_unlock(&dpmaif->lock);
	return ret ? ret : count;
}
static DEVICE_ATTR_WO(ul_start);

static ssize_t ul_stop_store(struct device *dev, struct device_attribute *attr,
			     const char *buf, size_t count)
{
	struct ccci_dpmaif *dpmaif = dev_get_drvdata(dev);

	mutex_lock(&dpmaif->lock);
	dpmaif_ul_stop(dpmaif);
	mutex_unlock(&dpmaif->lock);
	return count;
}
static DEVICE_ATTR_WO(ul_stop);

/* Fills the uplink payload with a fixed, recognisable frame and sends it once. */
static ssize_t tx_one_store(struct device *dev, struct device_attribute *attr,
			    const char *buf, size_t count)
{
	static const u8 dst[6] = { 0x02, 0x00, 0x00, 0x00, 0x00, 0x01 };
	static const u8 src[6] = { 0x02, 0x00, 0x00, 0x00, 0x00, 0x02 };
	struct ccci_dpmaif *dpmaif = dev_get_drvdata(dev);
	struct ccci_dpmaif_ul *ul = &dpmaif->ul;
	unsigned int channel = 0;
	u8 *frame;
	u32 i;
	int ret;

	ret = kstrtouint(buf, 10, &channel);
	if (ret)
		return ret;
	mutex_lock(&dpmaif->lock);
	if (!ul->started) {
		ret = -ENOTCONN;
		goto out;
	}
	frame = ul->payload;
	memset(frame, 0, ul->payload_len);
	memcpy(frame, dst, sizeof(dst));
	memcpy(frame + sizeof(dst), src, sizeof(src));
	/* Recognisable ethertype and a counting body; no protocol meaning. */
	frame[12] = 0x88;
	frame[13] = 0xb5;
	for (i = 14; i < ul->payload_len; i++)
		frame[i] = (u8)(i - 14);
	ret = dpmaif_ul_send(dpmaif, channel);
out:
	mutex_unlock(&dpmaif->lock);
	return ret ? ret : count;
}
static DEVICE_ATTR_WO(tx_one);

static struct attribute *dpmaif_attrs[] = {
	&dev_attr_sample.attr,
	&dev_attr_layout.attr,
	&dev_attr_ul.attr,
	&dev_attr_ul_start.attr,
	&dev_attr_ul_stop.attr,
	&dev_attr_tx_one.attr,
	NULL,
};
ATTRIBUTE_GROUPS(dpmaif);

static int dpmaif_probe(struct platform_device *pdev)
{
	static const char * const names[CCCI_DPMAIF_BLOCKS] = {
		"ao-ul", "pd-ul", "pd-md-misc", "sram",
	};
	struct ccci_dpmaif *dpmaif;
	struct device *dev = &pdev->dev;
	int i;

	dpmaif = devm_kzalloc(dev, sizeof(*dpmaif), GFP_KERNEL);
	if (!dpmaif)
		return -ENOMEM;
	dpmaif->dev = dev;
	mutex_init(&dpmaif->lock);
	for (i = 0; i < CCCI_DPMAIF_BLOCKS; i++) {
		struct resource *res;

		res = platform_get_resource_byname(pdev, IORESOURCE_MEM, names[i]);
		if (!res)
			return dev_err_probe(dev, -ENODEV, "no %s region\n", names[i]);
		dpmaif->base[i] = res->start;
		dpmaif->block[i] = devm_platform_ioremap_resource_byname(pdev, names[i]);
		if (IS_ERR(dpmaif->block[i]))
			return dev_err_probe(dev, PTR_ERR(dpmaif->block[i]),
					     "cannot map %s\n", names[i]);
	}
	dpmaif->irq = platform_get_irq(pdev, 0);
	if (dpmaif->irq < 0)
		return dev_err_probe(dev, dpmaif->irq, "no interrupt\n");
	dpmaif->infra = syscon_regmap_lookup_by_phandle(dev->of_node, "mediatek,infracfg");
	if (IS_ERR(dpmaif->infra))
		return dev_err_probe(dev, PTR_ERR(dpmaif->infra), "no infracfg regmap\n");
	dpmaif->clk_main = devm_clk_get(dev, "dpmaif-main");
	if (IS_ERR(dpmaif->clk_main))
		return dev_err_probe(dev, PTR_ERR(dpmaif->clk_main), "no dpmaif-main clock\n");
	dpmaif->clk_bus = devm_clk_get(dev, "dpmaif");
	if (IS_ERR(dpmaif->clk_bus))
		return dev_err_probe(dev, PTR_ERR(dpmaif->clk_bus), "no dpmaif clock\n");
	platform_set_drvdata(pdev, dpmaif);
	dev_info(dev, "dpmaif observed: irq=%d, %d blocks mapped, no register written\n",
		 dpmaif->irq, CCCI_DPMAIF_BLOCKS);
	return 0;
}

static void dpmaif_remove(struct platform_device *pdev)
{
	struct ccci_dpmaif *dpmaif = platform_get_drvdata(pdev);

	mutex_lock(&dpmaif->lock);
	dpmaif_ul_stop(dpmaif);
	mutex_unlock(&dpmaif->lock);
}

static const struct of_device_id dpmaif_of_ids[] = {
	{ .compatible = "mediatek,mt6893-dpmaif" },
	{ }
};
MODULE_DEVICE_TABLE(of, dpmaif_of_ids);

static struct platform_driver dpmaif_driver = {
	.probe = dpmaif_probe,
	.remove = dpmaif_remove,
	.driver = {
		.name = "op6893-dpmaif",
		.of_match_table = dpmaif_of_ids,
		.dev_groups = dpmaif_groups,
	},
};
module_platform_driver(dpmaif_driver);

MODULE_DESCRIPTION("Read-only op6893 DPMAIF reconnaissance");
MODULE_LICENSE("GPL");
