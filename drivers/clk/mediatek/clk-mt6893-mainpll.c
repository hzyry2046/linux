// SPDX-License-Identifier: GPL-2.0-only
/* Experimental op6893 readback of MAINPLL inherited from the bootloader. */

#include <linux/bitfield.h>
#include <linux/clk.h>
#include <linux/clk-provider.h>
#include <linux/io.h>
#include <linux/module.h>
#include <linux/of.h>
#include <linux/platform_device.h>
#include <dt-bindings/clock/mt6893-clk.h>

#define MAINPLL_CON0	0x340
#define MAINPLL_CON1	0x344
#define MAINPLL_CON3	0x34c
#define MAINPLL_PCW	GENMASK(21, 0)
#define MAINPLL_POSTDIV	GENMASK(26, 24)

struct mt6893_mainpll {
	struct clk_hw hw;
	void __iomem *base;
};

static unsigned long mt6893_mainpll_rate(struct clk_hw *hw,
					unsigned long parent_rate)
{
	struct mt6893_mainpll *pll = container_of(hw, struct mt6893_mainpll, hw);
	u32 con0, con1, con3, pcw, postdiv;
	u64 rate;

	con0 = readl(pll->base + MAINPLL_CON0);
	con1 = readl(pll->base + MAINPLL_CON1);
	con3 = readl(pll->base + MAINPLL_CON3);
	if (!(con0 & BIT(0)) || !(con3 & BIT(0)) || (con3 & BIT(1)))
		return 0;

	pcw = FIELD_GET(MAINPLL_PCW, con1);
	postdiv = 1U << FIELD_GET(MAINPLL_POSTDIV, con1);
	/* MT6893 has 22 PCW bits, of which 8 are integer bits. */
	rate = DIV_ROUND_UP_ULL((u64)parent_rate * pcw, BIT(14));
	return DIV_ROUND_UP_ULL(rate, postdiv);
}

/* Firmware ownership is unresolved: never prepare, gate or program this PLL. */
static const struct clk_ops mt6893_mainpll_ops = {
	.recalc_rate = mt6893_mainpll_rate,
};

static struct clk_hw *mt6893_mainpll_get(struct of_phandle_args *clkspec,
				       void *data)
{
	if (clkspec->args_count != 1 || clkspec->args[0] != CLK_APMIXED_MAINPLL)
		return ERR_PTR(-EINVAL);

	return data;
}

static int mt6893_mainpll_probe(struct platform_device *pdev)
{
	struct device *dev = &pdev->dev;
	struct clk_parent_data parent_data = { .index = 0 };
	struct clk_init_data init = {
		.name = "mt6893_mainpll",
		.ops = &mt6893_mainpll_ops,
		.parent_data = &parent_data,
		.num_parents = 1,
		.flags = CLK_GET_RATE_NOCACHE,
	};
	struct mt6893_mainpll *pll;
	struct clk *parent;
	unsigned long rate;
	int ret;

	if (!of_machine_is_compatible("realme,op6893"))
		return -ENODEV;

	parent = devm_clk_get(dev, "clk26m");
	if (IS_ERR(parent))
		return dev_err_probe(dev, PTR_ERR(parent), "missing reference clock\n");
	if (clk_get_rate(parent) != 26000000)
		return dev_err_probe(dev, -EINVAL, "expected 26 MHz reference\n");

	pll = devm_kzalloc(dev, sizeof(*pll), GFP_KERNEL);
	if (!pll)
		return -ENOMEM;
	pll->base = devm_platform_ioremap_resource(pdev, 0);
	if (IS_ERR(pll->base))
		return PTR_ERR(pll->base);

	rate = mt6893_mainpll_rate(&pll->hw, clk_get_rate(parent));
	if (!rate)
		return dev_err_probe(dev, -EINVAL, "MAINPLL has no active rate\n");

	pll->hw.init = &init;
	ret = devm_clk_hw_register(dev, &pll->hw);
	if (ret)
		return ret;
	ret = devm_of_clk_add_hw_provider(dev, mt6893_mainpll_get, &pll->hw);
	if (ret)
		return ret;

	dev_info(dev, "read-only MAINPLL registered: %lu Hz (register-derived)\n", rate);
	return 0;
}

static const struct of_device_id mt6893_mainpll_of_match[] = {
	{ .compatible = "mediatek,mt6893-apmixedsys" },
	{ }
};

static struct platform_driver mt6893_mainpll_driver = {
	.probe = mt6893_mainpll_probe,
	.driver = {
		.name = "clk-mt6893-mainpll",
		.of_match_table = mt6893_mainpll_of_match,
		.suppress_bind_attrs = true,
	},
};
builtin_platform_driver(mt6893_mainpll_driver);

MODULE_DESCRIPTION("Experimental MT6893 op6893 read-only MAINPLL");
MODULE_LICENSE("GPL");
