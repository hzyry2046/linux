// SPDX-License-Identifier: GPL-2.0-only
/* Experimental op6893 readback of MAINPLL/MFGPLL inherited from the bootloader. */

#include <linux/bitfield.h>
#include <linux/clk.h>
#include <linux/clk-provider.h>
#include <linux/delay.h>
#include <linux/io.h>
#include <linux/module.h>
#include <linux/of.h>
#include <linux/platform_device.h>
#include <dt-bindings/clock/mt6893-clk.h>

#define MAINPLL_CON0	0x340
#define MAINPLL_CON1	0x344
#define MAINPLL_CON3	0x34c
#define MFGPLL_CON0	0x268
#define MFGPLL_CON1	0x26c
#define MFGPLL_CON3	0x274
#define PLL_PCW		GENMASK(21, 0)
#define PLL_POSTDIV	GENMASK(26, 24)

/* 4.19 POSDIV_8_MIN..POSDIV_4_MAX for the MFGPLL programming range. */
#define MFGPLL_MIN_RATE	187500000UL
#define MFGPLL_MAX_RATE	950000000UL
#define MFGPLL_POSDIV4_RATE	375000000UL

struct mt6893_pll_desc {
	unsigned int id;
	const char *name;
	const struct clk_ops *ops;
	u16 con0;
	u16 con1;
	u16 con3;
};

struct mt6893_pll {
	struct clk_hw hw;
	void __iomem *base;
	const struct mt6893_pll_desc *desc;
};

static unsigned long mt6893_pll_rate(struct clk_hw *hw,
				     unsigned long parent_rate)
{
	struct mt6893_pll *pll = container_of(hw, struct mt6893_pll, hw);
	u32 con0, con1, con3, pcw, postdiv;
	u64 rate;

	con0 = readl(pll->base + pll->desc->con0);
	con1 = readl(pll->base + pll->desc->con1);
	con3 = readl(pll->base + pll->desc->con3);
	if (!(con0 & BIT(0)) || !(con3 & BIT(0)) || (con3 & BIT(1)))
		return 0;

	pcw = FIELD_GET(PLL_PCW, con1);
	postdiv = 1U << FIELD_GET(PLL_POSTDIV, con1);
	/* MT6893 has 22 PCW bits, of which 8 are integer bits. */
	rate = DIV_ROUND_UP_ULL((u64)parent_rate * pcw, BIT(14));
	return DIV_ROUND_UP_ULL(rate, postdiv);
}

/* Firmware ownership is unresolved: never prepare, gate or program this PLL. */
static const struct clk_ops mt6893_pll_ops = {
	.recalc_rate = mt6893_pll_rate,
};

static u32 mt6893_mfgpll_posdiv_field(unsigned long rate)
{
	return rate >= MFGPLL_POSDIV4_RATE ? 2 : 3;
}

static u32 mt6893_mfgpll_pcw(unsigned long rate, unsigned long parent_rate,
			     bool nearest)
{
	u64 pcw;

	pcw = (u64)rate << mt6893_mfgpll_posdiv_field(rate) << 14;
	pcw = nearest ? DIV_ROUND_CLOSEST_ULL(pcw, parent_rate) :
			 DIV_ROUND_DOWN_ULL(pcw, parent_rate);
	return pcw > PLL_PCW ? PLL_PCW : pcw;
}

static int mt6893_mfgpll_determine_rate(struct clk_hw *hw,
				      struct clk_rate_request *req)
{
	unsigned long rate = clamp(req->rate, MFGPLL_MIN_RATE, MFGPLL_MAX_RATE);
	u32 postdiv = 1U << mt6893_mfgpll_posdiv_field(rate);
	u64 pcw;

	/*
	 * Round the divider and the produced rate down so the reported rate
	 * never exceeds the request: dev_pm_opp_set_rate() looks it up with
	 * _find_freq_ceil() and fails outright above the top OPP.
	 */
	pcw = mt6893_mfgpll_pcw(rate, req->best_parent_rate, false);
	rate = DIV_ROUND_DOWN_ULL((u64)req->best_parent_rate * pcw, BIT(14));
	req->rate = DIV_ROUND_DOWN_ULL(rate, postdiv);
	return 0;
}

/*
 * MFGPLL is only ever reprogrammed through its CON1 PCW/postdiv word; it stays
 * powered and enabled throughout (there are no prepare/enable ops), and
 * consumers are parked on a stable parent by the mfg_sel mux notifier.
 */
static int mt6893_mfgpll_set_rate(struct clk_hw *hw, unsigned long rate,
				  unsigned long parent_rate)
{
	struct mt6893_pll *pll = container_of(hw, struct mt6893_pll, hw);
	u32 field = mt6893_mfgpll_posdiv_field(rate);
	u32 pcw = mt6893_mfgpll_pcw(rate, parent_rate, true);

	writel(BIT(31) | FIELD_PREP(PLL_POSTDIV, field) | FIELD_PREP(PLL_PCW, pcw),
	       pll->base + pll->desc->con1);
	udelay(20); /* PLL spec: wait for the reprogrammed output to settle */

	return 0;
}

static const struct clk_ops mt6893_mfgpll_ops = {
	.recalc_rate = mt6893_pll_rate,
	.determine_rate = mt6893_mfgpll_determine_rate,
	.set_rate = mt6893_mfgpll_set_rate,
};

static const struct mt6893_pll_desc mt6893_plls[] = {
	{ CLK_APMIXED_MAINPLL, "mt6893_mainpll", &mt6893_pll_ops,
	  MAINPLL_CON0, MAINPLL_CON1, MAINPLL_CON3 },
	{ CLK_APMIXED_MFGPLL, "mt6893_mfgpll", &mt6893_mfgpll_ops,
	  MFGPLL_CON0, MFGPLL_CON1, MFGPLL_CON3 },
};

static struct clk_hw *mt6893_pll_get(struct of_phandle_args *clkspec,
				     void *data)
{
	struct mt6893_pll *plls = data;
	unsigned int i;

	if (clkspec->args_count != 1)
		return ERR_PTR(-EINVAL);

	for (i = 0; i < ARRAY_SIZE(mt6893_plls); i++)
		if (clkspec->args[0] == mt6893_plls[i].id)
			return &plls[i].hw;

	return ERR_PTR(-EINVAL);
}

static int mt6893_mainpll_probe(struct platform_device *pdev)
{
	struct device *dev = &pdev->dev;
	struct clk_parent_data parent_data = { .index = 0 };
	void __iomem *base;
	struct clk *parent;
	struct mt6893_pll *plls;
	unsigned int i;
	int ret;

	if (!of_machine_is_compatible("realme,op6893"))
		return -ENODEV;

	parent = devm_clk_get(dev, "clk26m");
	if (IS_ERR(parent))
		return dev_err_probe(dev, PTR_ERR(parent), "missing reference clock\n");
	if (clk_get_rate(parent) != 26000000)
		return dev_err_probe(dev, -EINVAL, "expected 26 MHz reference\n");

	base = devm_platform_ioremap_resource(pdev, 0);
	if (IS_ERR(base))
		return PTR_ERR(base);

	plls = devm_kcalloc(dev, ARRAY_SIZE(mt6893_plls), sizeof(*plls),
			    GFP_KERNEL);
	if (!plls)
		return -ENOMEM;

	for (i = 0; i < ARRAY_SIZE(mt6893_plls); i++) {
		const struct mt6893_pll_desc *desc = &mt6893_plls[i];
		struct clk_init_data init = {
			.name = desc->name,
			.ops = desc->ops,
			.parent_data = &parent_data,
			.num_parents = 1,
			.flags = CLK_GET_RATE_NOCACHE,
		};
		unsigned long rate;

		plls[i].base = base;
		plls[i].desc = desc;
		plls[i].hw.init = &init;

		rate = mt6893_pll_rate(&plls[i].hw, clk_get_rate(parent));
		if (!rate) {
			if (desc->id == CLK_APMIXED_MAINPLL)
				return dev_err_probe(dev, -EINVAL,
						     "MAINPLL has no active rate\n");
			dev_warn(dev, "%s has no active rate\n", desc->name);
		}

		ret = devm_clk_hw_register(dev, &plls[i].hw);
		if (ret)
			return ret;

		dev_info(dev, "%s%s registered: %lu Hz (register-derived)\n",
			 desc->id == CLK_APMIXED_MAINPLL ? "read-only " : "",
			 desc->name, rate);
	}

	ret = devm_of_clk_add_hw_provider(dev, mt6893_pll_get, plls);
	if (ret)
		return ret;

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

MODULE_DESCRIPTION("Experimental MT6893 op6893 read-only MAINPLL/MFGPLL");
MODULE_LICENSE("GPL");
