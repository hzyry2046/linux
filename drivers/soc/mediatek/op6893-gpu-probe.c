// SPDX-License-Identifier: GPL-2.0-only
/*
 * op6893 bring-up: power the MT6893 GPU domains on request and read the
 * Mali ID registers. Nothing happens at probe; writing 1 to
 * /sys/kernel/debug/op6893-gpu/power runs the sequence, 0 powers off.
 */
#include <linux/bits.h>
#include <linux/debugfs.h>
#include <linux/delay.h>
#include <linux/io.h>
#include <linux/module.h>
#include <linux/of.h>
#include <linux/platform_device.h>
#include <linux/pm_domain.h>
#include <linux/pm_runtime.h>

#define MFG_CG_CON		0x000
#define MFG_CG_CLR		0x008
#define MFG_ASYNC_CON		0x020
#define MFG_ASYNC_CON_1		0x024
#define MFG_ASYNC_CON_3		0x02c
#define MFG_GLOBAL_CON		0x0b0
#define MFG_QCHANNEL_CON	0x0b4

#define GPU_ID			0x000
#define L2_FEATURES		0x004
#define SHADER_PRESENT_LO	0x100
#define SHADER_PRESENT_HI	0x104
#define L2_PRESENT_LO		0x120

static const char * const op6893_gpu_pds[] = {
	"mfg1", "mfg2", "mfg3", "mfg4", "mfg5", "mfg6",
};

struct op6893_gpu {
	struct device *dev;
	void __iomem *gpu;
	void __iomem *mfg;
	struct dev_pm_domain_list *pds;
	struct dentry *dir;
	bool on;
};

static void op6893_gpu_rmw(void __iomem *reg, u32 clr, u32 set)
{
	writel((readl(reg) & ~clr) | set, reg);
}

/* Vendor mt_gpufreq_external_cg_control(), after the BG3D gate opens. */
static void op6893_gpu_mfg_setup(struct op6893_gpu *g)
{
	op6893_gpu_rmw(g->mfg + MFG_ASYNC_CON, 0, GENMASK(25, 22));
	op6893_gpu_rmw(g->mfg + MFG_ASYNC_CON_3, 0, GENMASK(15, 12));
	op6893_gpu_rmw(g->mfg + MFG_GLOBAL_CON, BIT(10) | BIT(9), 0);
	op6893_gpu_rmw(g->mfg + MFG_QCHANNEL_CON, 0, BIT(4));
	op6893_gpu_rmw(g->mfg + MFG_GLOBAL_CON, BIT(19) | BIT(8), 0);
	op6893_gpu_rmw(g->mfg + MFG_ASYNC_CON_1, 0, BIT(0));
}

static int op6893_gpu_power_on(struct op6893_gpu *g)
{
	int i, ret;

	for (i = 0; i < g->pds->num_pds; i++) {
		ret = pm_runtime_resume_and_get(g->pds->pd_devs[i]);
		if (ret) {
			dev_err(g->dev, "%s on failed: %d\n", op6893_gpu_pds[i], ret);
			goto err;
		}
		dev_info(g->dev, "%s on\n", op6893_gpu_pds[i]);
	}

	dev_info(g->dev, "MFG_CG_CON %08x\n", readl(g->mfg + MFG_CG_CON));
	writel(BIT(0), g->mfg + MFG_CG_CLR);
	op6893_gpu_mfg_setup(g);
	udelay(10);
	dev_info(g->dev, "MFG_CG_CON %08x ASYNC %08x GLOBAL %08x\n",
		 readl(g->mfg + MFG_CG_CON), readl(g->mfg + MFG_ASYNC_CON),
		 readl(g->mfg + MFG_GLOBAL_CON));

	dev_info(g->dev, "GPU_ID %08x L2_FEATURES %08x\n",
		 readl(g->gpu + GPU_ID), readl(g->gpu + L2_FEATURES));
	dev_info(g->dev, "SHADER_PRESENT %08x%08x L2_PRESENT %08x\n",
		 readl(g->gpu + SHADER_PRESENT_HI),
		 readl(g->gpu + SHADER_PRESENT_LO),
		 readl(g->gpu + L2_PRESENT_LO));
	g->on = true;
	return 0;

err:
	while (--i >= 0)
		pm_runtime_put_sync(g->pds->pd_devs[i]);
	return ret;
}

static void op6893_gpu_power_off(struct op6893_gpu *g)
{
	int i;

	for (i = g->pds->num_pds - 1; i >= 0; i--)
		pm_runtime_put_sync(g->pds->pd_devs[i]);
	g->on = false;
	dev_info(g->dev, "domains released\n");
}

static int op6893_gpu_power_set(void *data, u64 val)
{
	struct op6893_gpu *g = data;

	if (val && !g->on)
		return op6893_gpu_power_on(g);
	if (!val && g->on)
		op6893_gpu_power_off(g);
	return 0;
}

static int op6893_gpu_power_get(void *data, u64 *val)
{
	*val = ((struct op6893_gpu *)data)->on;
	return 0;
}

DEFINE_DEBUGFS_ATTRIBUTE(op6893_gpu_power_fops, op6893_gpu_power_get,
			 op6893_gpu_power_set, "%llu\n");

static int op6893_gpu_probe(struct platform_device *pdev)
{
	struct dev_pm_domain_attach_data pd_data = {
		.pd_names = op6893_gpu_pds,
		.num_pd_names = ARRAY_SIZE(op6893_gpu_pds),
	};
	struct device *dev = &pdev->dev;
	struct op6893_gpu *g;
	int ret;

	g = devm_kzalloc(dev, sizeof(*g), GFP_KERNEL);
	if (!g)
		return -ENOMEM;
	g->dev = dev;

	g->gpu = devm_platform_ioremap_resource_byname(pdev, "gpu");
	if (IS_ERR(g->gpu))
		return PTR_ERR(g->gpu);
	g->mfg = devm_platform_ioremap_resource_byname(pdev, "mfgcfg");
	if (IS_ERR(g->mfg))
		return PTR_ERR(g->mfg);

	ret = devm_pm_domain_attach_list(dev, &pd_data, &g->pds);
	if (ret < 0)
		return dev_err_probe(dev, ret, "attach power domains\n");
	if (ret != ARRAY_SIZE(op6893_gpu_pds))
		return dev_err_probe(dev, -ENODEV, "got %d power domains\n", ret);

	g->dir = debugfs_create_dir("op6893-gpu", NULL);
	debugfs_create_file("power", 0600, g->dir, g, &op6893_gpu_power_fops);
	platform_set_drvdata(pdev, g);
	dev_info(dev, "ready; nothing powered\n");
	return 0;
}

static void op6893_gpu_remove(struct platform_device *pdev)
{
	struct op6893_gpu *g = platform_get_drvdata(pdev);

	debugfs_remove_recursive(g->dir);
	if (g->on)
		op6893_gpu_power_off(g);
}

static const struct of_device_id op6893_gpu_of_match[] = {
	{ .compatible = "realme,op6893-gpu-probe" },
	{ }
};
MODULE_DEVICE_TABLE(of, op6893_gpu_of_match);

static struct platform_driver op6893_gpu_driver = {
	.probe = op6893_gpu_probe,
	.remove = op6893_gpu_remove,
	.driver = {
		.name = "op6893-gpu-probe",
		.of_match_table = op6893_gpu_of_match,
	},
};
module_platform_driver(op6893_gpu_driver);

MODULE_DESCRIPTION("op6893 GPU power bring-up probe");
MODULE_LICENSE("GPL");
