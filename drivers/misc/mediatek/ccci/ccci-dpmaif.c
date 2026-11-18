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

struct ccci_dpmaif {
	struct device *dev;
	void __iomem *block[CCCI_DPMAIF_BLOCKS];
	resource_size_t base[CCCI_DPMAIF_BLOCKS];
	struct regmap *infra;
	struct clk *clk_main;
	struct clk *clk_bus;
	int irq;
	/* Serializes the clock-on/sample/clock-off window. */
	struct mutex lock;
};

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

static struct attribute *dpmaif_attrs[] = {
	&dev_attr_sample.attr,
	&dev_attr_layout.attr,
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

static const struct of_device_id dpmaif_of_ids[] = {
	{ .compatible = "mediatek,mt6893-dpmaif" },
	{ }
};
MODULE_DEVICE_TABLE(of, dpmaif_of_ids);

static struct platform_driver dpmaif_driver = {
	.probe = dpmaif_probe,
	.driver = {
		.name = "op6893-dpmaif",
		.of_match_table = dpmaif_of_ids,
		.dev_groups = dpmaif_groups,
	},
};
module_platform_driver(dpmaif_driver);

MODULE_DESCRIPTION("Read-only op6893 DPMAIF reconnaissance");
MODULE_LICENSE("GPL");
