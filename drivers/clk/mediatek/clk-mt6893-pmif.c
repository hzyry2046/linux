// SPDX-License-Identifier: GPL-2.0-only
/* Experimental op6893 PMIF clock subset; register layout from MT6893 ACK. */

#include <linux/clk.h>
#include <linux/clk-provider.h>
#include <linux/mfd/syscon.h>
#include <linux/module.h>
#include <linux/regmap.h>
#include <linux/of.h>
#include <linux/platform_device.h>
#include <dt-bindings/clock/mt6893-clk.h>

#include "clk-gate.h"
#include "clk-mtk.h"
#include "clk-mux.h"

/*
 * Rate-only observer, deliberately outside the CCF parent tree. NOCACHE
 * refreshes a clock's subtree, not its ancestors or firmware mux changes.
 * Keeping this observer parentless lets it query live input rates without
 * recursively recalculating itself through the MAINPLL subtree.
 */
struct mt6893_axi_observer {
	struct clk_hw hw;
	struct regmap *map;
	struct clk *ref;
	struct clk *mainpll;
	struct clk *ulposc;
};

static unsigned long mt6893_axi_rate(struct clk_hw *hw,
				    unsigned long parent_rate)
{
	struct mt6893_axi_observer *axi = container_of(hw, struct mt6893_axi_observer, hw);
	static const unsigned int divisors[] = { 1, 16, 14, 8, 10, 12, 4 };
	unsigned int before, after, sel;
	unsigned long rate;

	if (regmap_read(axi->map, 0x10, &before))
		return 0;
	sel = before & 7;
	if (sel >= ARRAY_SIZE(divisors))
		return 0;
	if (!sel)
		rate = clk_get_rate(axi->ref);
	else if (sel == 6)
		rate = clk_get_rate(axi->ulposc);
	else
		rate = clk_get_rate(axi->mainpll);

	/* Reject a selector transition observed across the source-rate read. */
	if (regmap_read(axi->map, 0x10, &after) || ((before ^ after) & 7))
		return 0;

	return rate / divisors[sel];
}

static const struct clk_ops mt6893_axi_ops = {
	.recalc_rate = mt6893_axi_rate,
};

static struct clk_hw *mt6893_axi_register(struct device *dev)
{
	struct clk_init_data init = {
		.name = "mt6893_axi_observed",
		.ops = &mt6893_axi_ops,
		.flags = CLK_GET_RATE_NOCACHE,
	};
	struct mt6893_axi_observer *axi;
	int ret;

	axi = devm_kzalloc(dev, sizeof(*axi), GFP_KERNEL);
	if (!axi)
		return ERR_PTR(-ENOMEM);
	axi->map = syscon_node_to_regmap(dev->of_node);
	if (IS_ERR(axi->map))
		return ERR_CAST(axi->map);
	axi->ref = devm_clk_get(dev, "clk26m");
	if (IS_ERR(axi->ref))
		return ERR_CAST(axi->ref);
	axi->ulposc = devm_clk_get(dev, "ulposc");
	if (IS_ERR(axi->ulposc))
		return ERR_CAST(axi->ulposc);
	axi->mainpll = devm_clk_get(dev, "mainpll");
	if (IS_ERR(axi->mainpll))
		return ERR_CAST(axi->mainpll);
	if (!mt6893_axi_rate(&axi->hw, 0))
		return ERR_PTR(-EINVAL);
	axi->hw.init = &init;
	ret = devm_clk_hw_register(dev, &axi->hw);
	if (ret)
		return ERR_PTR(ret);

	return &axi->hw;
}

static DEFINE_SPINLOCK(mt6893_pmif_lock);

#ifdef CONFIG_COMMON_CLK_MT6893_SCP_BOOTSTRAP
struct mt6893_scp_bootstrap {
	struct clk_hw hw;
	struct regmap *map;
};

/* A constrained SCP output, not an implementation of the eight-parent mux. */
static int mt6893_scp_bootstrap_check(struct mt6893_scp_bootstrap *scp)
{
	unsigned int value;
	int ret;

	ret = regmap_read(scp->map, 0x10, &value);
	if (ret)
		return ret;
	return value & (GENMASK(18, 16) | BIT(23)) ? -EBUSY : 0;
}

static int mt6893_scp_bootstrap_enable(struct clk_hw *hw)
{
	struct mt6893_scp_bootstrap *scp =
		container_of(hw, struct mt6893_scp_bootstrap, hw);
	unsigned long flags;
	int ret;

	spin_lock_irqsave(&mt6893_pmif_lock, flags);
	ret = mt6893_scp_bootstrap_check(scp);
	if (!ret)
		ret = mt6893_scp_bootstrap_check(scp);
	/* Only reaffirm an inherited on gate; never switch a parent or update. */
	if (!ret)
		ret = regmap_write(scp->map, 0x18, BIT(23));
	if (!ret)
		ret = mt6893_scp_bootstrap_check(scp);
	spin_unlock_irqrestore(&mt6893_pmif_lock, flags);
	return ret;
}

static void mt6893_scp_bootstrap_disable(struct clk_hw *hw)
{
	/* No gate-off path until a shared SCP STOP/reset owner exists. */
}

static unsigned long mt6893_scp_bootstrap_rate(struct clk_hw *hw,
					       unsigned long parent_rate)
{
	struct mt6893_scp_bootstrap *scp =
		container_of(hw, struct mt6893_scp_bootstrap, hw);

	if (parent_rate != 26000000 || mt6893_scp_bootstrap_check(scp))
		return 0;
	return mt6893_scp_bootstrap_check(scp) ? 0 : parent_rate;
}

static const struct clk_ops mt6893_scp_bootstrap_ops = {
	.enable = mt6893_scp_bootstrap_enable,
	.disable = mt6893_scp_bootstrap_disable,
	.recalc_rate = mt6893_scp_bootstrap_rate,
};

static struct clk_hw *mt6893_scp_bootstrap_register(struct device *dev)
{
	const struct clk_parent_data parent = { .fw_name = "clk26m" };
	struct clk_init_data init = {
		.name = "mt6893_scp_bootstrap",
		.ops = &mt6893_scp_bootstrap_ops,
		.parent_data = &parent,
		.num_parents = 1,
		.flags = CLK_IS_CRITICAL | CLK_GET_RATE_NOCACHE,
	};
	struct mt6893_scp_bootstrap *scp;
	struct clk *ref;
	int ret;

	ref = devm_clk_get(dev, "clk26m");
	if (IS_ERR(ref))
		return ERR_CAST(ref);
	if (clk_get_rate(ref) != 26000000)
		return ERR_PTR(-EINVAL);
	scp = devm_kzalloc(dev, sizeof(*scp), GFP_KERNEL);
	if (!scp)
		return ERR_PTR(-ENOMEM);
	scp->map = syscon_node_to_regmap(dev->of_node);
	if (IS_ERR(scp->map))
		return ERR_CAST(scp->map);
	ret = mt6893_scp_bootstrap_check(scp);
	if (ret)
		return ERR_PTR(ret);
	scp->hw.init = &init;
	ret = devm_clk_hw_register(dev, &scp->hw);
	return ret ? ERR_PTR(ret) : &scp->hw;
}
#endif

static const struct mtk_fixed_factor top_factors[] = {
	FACTOR_FLAGS(CLK_TOP_OSC_D4, "mt6893_osc_d4", "mt6893_ulposc", 1, 4, 0),
	FACTOR_FLAGS(CLK_TOP_OSC_D8, "mt6893_osc_d8", "mt6893_ulposc", 1, 8, 0),
	FACTOR_FLAGS(CLK_TOP_OSC_D16, "mt6893_osc_d16", "mt6893_ulposc", 1, 16, 0),
	FACTOR_FLAGS(CLK_TOP_OSC_D10, "mt6893_osc_d10", "mt6893_ulposc", 1, 10, 0),
	FACTOR_FLAGS(CLK_TOP_FPWRAP_ULPOSC, "mt6893_fpwrap_ulposc",
		     "mt6893_pwrap_ulposc_sel", 1, 1, 0),
};

static const char * const pwrap_parents[] = {
	"mt6893_osc_d10",
	"clk26m",
	"mt6893_osc_d4",
	"mt6893_osc_d8",
	"mt6893_osc_d16",
};

/* Keep the supply transport alive even if a consumer fails to probe. */
static const struct mtk_mux top_muxes[] = {
	MUX_GATE_CLR_SET_UPD_FLAGS(CLK_TOP_PWRAP_ULPOSC_SEL,
				  "mt6893_pwrap_ulposc_sel", pwrap_parents,
				  0x90, 0x94, 0x98, 8, 3, 15, 0x8, 2,
				  CLK_IS_CRITICAL | CLK_SET_RATE_NO_REPARENT),
};

static const struct mtk_gate_regs infra_gate_regs = {
	.set_ofs = 0x80,
	.clr_ofs = 0x84,
	.sta_ofs = 0x90,
};

static const struct mtk_gate infra_gates[] = {
	GATE_MTK_FLAGS(CLK_IFRAO_PMIC_TMR, "mt6893_pmic_tmr",
		       "mt6893_fpwrap_ulposc", &infra_gate_regs, 0,
		       &mtk_clk_gate_ops_setclr, CLK_IS_CRITICAL),
	GATE_MTK_FLAGS(CLK_IFRAO_PMIC_AP, "mt6893_pmic_ap",
		       "mt6893_fpwrap_ulposc", &infra_gate_regs, 1,
		       &mtk_clk_gate_ops_setclr, CLK_IS_CRITICAL),
	/* Preserve the inherited on state until LVTS owns its lifecycle. */
	GATE_MTK_FLAGS(CLK_IFRAO_THERM, "mt6893_therm",
		       "mt6893_axi_observed", &infra_gate_regs, 10,
		       &mtk_clk_gate_ops_setclr, CLK_IS_CRITICAL),
};

#ifdef CONFIG_COMMON_CLK_MT6893_CCIF
static const struct mtk_gate_regs ccif_gate_regs = {
	.set_ofs = 0x88,
	.clr_ofs = 0x8c,
	.sta_ofs = 0x94,
};

/*
 * Only gates implemented with real set/clear operations in the ACK tree.
 * IGNORE_UNUSED preserves LK's state; registration must not enable MD paths.
 * The parent reports the inherited AXI rate, without managing its source.
 * CCIF2/4/5 used dummy operations in ACK and remain unsupported here.
 */
static const struct mtk_gate ccif_gates[] = {
	GATE_MTK_FLAGS(CLK_IFRAO_CCIF1_AP, "mt6893_ccif1_ap",
		       "mt6893_axi_observed", &ccif_gate_regs, 12,
		       &mtk_clk_gate_ops_setclr, CLK_IGNORE_UNUSED),
	GATE_MTK_FLAGS(CLK_IFRAO_CCIF1_MD, "mt6893_ccif1_md",
		       "mt6893_axi_observed", &ccif_gate_regs, 13,
		       &mtk_clk_gate_ops_setclr, CLK_IGNORE_UNUSED),
	GATE_MTK_FLAGS(CLK_IFRAO_CCIF_AP, "mt6893_ccif_ap",
		       "mt6893_axi_observed", &ccif_gate_regs, 23,
		       &mtk_clk_gate_ops_setclr, CLK_IGNORE_UNUSED),
	GATE_MTK_FLAGS(CLK_IFRAO_CCIF_MD, "mt6893_ccif_md",
		       "mt6893_axi_observed", &ccif_gate_regs, 26,
		       &mtk_clk_gate_ops_setclr, CLK_IGNORE_UNUSED),
};
#endif

static int mt6893_thermal_ready(struct regmap *map, struct clk *axi)
{
	unsigned int status;
	int ret;

	if (!clk_get_rate(axi))
		return -EINVAL;
	ret = regmap_read(map, infra_gate_regs.sta_ofs, &status);
	if (ret)
		return ret;
	/* Do not start an unexpectedly gated thermal block during bring-up. */
	return status & BIT(10) ? -EBUSY : 0;
}

static int mt6893_pmif_clk_probe(struct platform_device *pdev)
{
	struct device *dev = &pdev->dev;
	struct device_node *np = dev->of_node;
	struct clk_hw_onecell_data *data;
	struct regmap *map;
	struct clk *parent;
	struct clk_hw *axi = NULL;
	unsigned int num_clks;
	bool top;
	int ret;

	if (!of_machine_is_compatible("realme,op6893"))
		return -ENODEV;

	top = of_device_is_compatible(np, "mediatek,mt6893-topckgen");
	/* Resolve inputs before registering critical clocks; avoid orphans. */
	parent = devm_clk_get(dev, top ? "ulposc" : "pwrap");
	if (IS_ERR(parent))
		return dev_err_probe(dev, PTR_ERR(parent), "missing parent clock\n");
	if (!clk_get_rate(parent))
		return dev_err_probe(dev, -EINVAL, "parent clock has no rate\n");
	if (top) {
		parent = devm_clk_get(dev, "clk26m");
		if (IS_ERR(parent))
			return dev_err_probe(dev, PTR_ERR(parent), "missing clk26m\n");
	}

	if (top) {
		axi = mt6893_axi_register(dev);
		if (IS_ERR(axi))
			return dev_err_probe(dev, PTR_ERR(axi), "AXI observer unavailable\n");
	} else {
		parent = devm_clk_get(dev, "axi");
		if (IS_ERR(parent))
			return dev_err_probe(dev, PTR_ERR(parent), "missing AXI clock\n");
		map = syscon_node_to_regmap(np);
		if (IS_ERR(map))
			return PTR_ERR(map);
		ret = mt6893_thermal_ready(map, parent);
		if (ret)
			return dev_err_probe(dev, ret, "thermal clock is not inherited on\n");
	}

	/* Vendor IDs are sparse: the generic count-based probe is unsuitable. */
	num_clks = top ? CLK_TOP_PWRAP_ULPOSC_SEL + 1 : CLK_IFRAO_THERM + 1;
	if (!top && IS_ENABLED(CONFIG_COMMON_CLK_MT6893_CCIF))
		num_clks = CLK_IFRAO_CCIF_MD + 1;
	data = mtk_alloc_clk_data(num_clks);
	if (!data)
		return -ENOMEM;

	if (top) {
		/* AXI is a 1:1 alias of the selector output in the vendor tree. */
		data->hws[CLK_TOP_AXI] = axi;
		data->hws[CLK_TOP_AXI_SEL] = axi;
		ret = mtk_clk_register_factors(top_factors, ARRAY_SIZE(top_factors), data);
		if (ret)
			goto free_data;
		ret = mtk_clk_register_muxes(dev, top_muxes, ARRAY_SIZE(top_muxes),
					    np, &mt6893_pmif_lock, data);
		if (ret)
			goto unregister_factors;
#ifdef CONFIG_COMMON_CLK_MT6893_SCP_BOOTSTRAP
		/* An optional SCP experiment must not break the PMIC transport. */
		{
			struct clk_hw *scp = mt6893_scp_bootstrap_register(dev);

			if (IS_ERR(scp))
				dev_warn(dev, "SCP bootstrap clock unavailable: %ld\n",
					 PTR_ERR(scp));
			else
				data->hws[CLK_TOP_SCP] = scp;
		}
#endif
	} else {
		ret = mtk_clk_register_gates(dev, np, infra_gates,
					    ARRAY_SIZE(infra_gates), data);
		if (ret)
			goto free_data;
#ifdef CONFIG_COMMON_CLK_MT6893_CCIF
		ret = mtk_clk_register_gates(dev, np, ccif_gates,
					     ARRAY_SIZE(ccif_gates), data);
		if (ret)
			goto unregister_infra;
#endif
	}

	ret = of_clk_add_hw_provider(np, of_clk_hw_onecell_get, data);
	if (ret)
		goto unregister_clocks;

	platform_set_drvdata(pdev, data);
	dev_info(dev, "op6893 PMIF clock subset registered (%s)\n",
		 top ? "topckgen" : "infracfg");
	return 0;

unregister_clocks:
	if (top) {
		mtk_clk_unregister_muxes(top_muxes, ARRAY_SIZE(top_muxes), data);
	} else {
#ifdef CONFIG_COMMON_CLK_MT6893_CCIF
		mtk_clk_unregister_gates(ccif_gates, ARRAY_SIZE(ccif_gates), data);
unregister_infra:
#endif
		mtk_clk_unregister_gates(infra_gates, ARRAY_SIZE(infra_gates), data);
	}
unregister_factors:
	if (top)
		mtk_clk_unregister_factors(top_factors, ARRAY_SIZE(top_factors), data);
free_data:
	mtk_free_clk_data(data);
	return ret;
}

static const struct of_device_id mt6893_pmif_clk_of_match[] = {
	{ .compatible = "mediatek,mt6893-topckgen" },
	{ .compatible = "mediatek,mt6893-infracfg_ao" },
	{ }
};

/* Built-in only: unbinding a live supply-transport provider is unsupported. */
static struct platform_driver mt6893_pmif_clk_driver = {
	.probe = mt6893_pmif_clk_probe,
	.driver = {
		.name = "clk-mt6893-pmif",
		.of_match_table = mt6893_pmif_clk_of_match,
		.suppress_bind_attrs = true,
	},
};
builtin_platform_driver(mt6893_pmif_clk_driver);

MODULE_DESCRIPTION("Experimental MT6893 op6893 PMIF clocks");
MODULE_LICENSE("GPL");
