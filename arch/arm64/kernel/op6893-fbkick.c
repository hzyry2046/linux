// SPDX-License-Identifier: GPL-2.0-only
/*
 * op6893 early console: keep the LK-initialised command-mode panel fed.
 *
 * LK leaves the whole display pipeline (OVL -> ... -> DSC -> DSI0) running,
 * with Layer 0 of both OVL_2L pipes scanning out its buffer 2. The panel is a
 * MIPI DSI command-mode panel, so new framebuffer content only reaches it
 * when a frame is explicitly sent. This periodically repeats LK's direct-link
 * trigger (mutex 0 enable, DSI CMDQ "write memory start", DSI start), which
 * lets a simple-framebuffer over that buffer act as a console before any real
 * display driver exists. The sequence follows Mu-Silicium's DisplayTriggerLib
 * for this board.
 *
 * Nothing is reconfigured: clocks, power and the pipeline stay as LK left
 * them, which relies on clk_ignore_unused/regulator_ignore_unused. This is a
 * bring-up aid, not a display driver.
 */
#include <linux/io.h>
#include <linux/jiffies.h>
#include <linux/module.h>
#include <linux/of.h>
#include <linux/platform_device.h>
#include <linux/workqueue.h>

#define DISP_OVL0_2L			0x001000
#define DISP_DSI0			0x00e000
#define DISP_OVL1_2L			0x101000
#define DISP_MUTEX			0x117000
#define DISP_SIZE			0x130000

#define OVL_EN				0x00c
#define OVL_L0_ADDR			0xf40
#define DSI_START			0x000
#define DSI_INTSTA			0x00c
#define DSI_INTSTA_BUSY			BIT(31)
#define DSI_MODE_CTRL			0x014
#define DSI_CMDQ_SIZE			0x060
#define DSI_CMDQ0			0x200
#define DSI_CMDQ_WRITE_MEMORY_START	0x002c3909
#define MUTEX0_EN			0x020

#define FBKICK_PERIOD_MS		33
#define FBKICK_STUCK_RESTART		30	/* ~1 s of a busy DSI */

struct fbkick {
	void __iomem *base;
	struct delayed_work work;
	unsigned int stuck;
	unsigned long frames;
	unsigned long restarts;
};

static void fbkick_send(struct fbkick *k, bool restart)
{
	void __iomem *dsi = k->base + DISP_DSI0;

	if (restart)
		writel(0, dsi + DSI_START);
	writel(0, dsi + DSI_INTSTA);
	writel(1, k->base + DISP_MUTEX + MUTEX0_EN);
	writel(DSI_CMDQ_WRITE_MEMORY_START, dsi + DSI_CMDQ0);
	writel(1, dsi + DSI_CMDQ_SIZE);
	if (!restart)
		writel(0, dsi + DSI_START);
	writel(1, dsi + DSI_START);
}

static void fbkick_work(struct work_struct *work)
{
	struct fbkick *k = container_of(to_delayed_work(work), struct fbkick,
					work);

	if (readl(k->base + DISP_DSI0 + DSI_INTSTA) & DSI_INTSTA_BUSY) {
		/* A frame that never finishes freezes the panel; drop it. */
		if (++k->stuck % FBKICK_STUCK_RESTART == 0) {
			fbkick_send(k, true);
			k->restarts++;
		}
	} else {
		k->stuck = 0;
		fbkick_send(k, false);
		k->frames++;
	}

	schedule_delayed_work(&k->work, msecs_to_jiffies(FBKICK_PERIOD_MS));
}

static ssize_t stats_show(struct device *dev, struct device_attribute *attr,
			  char *buf)
{
	struct fbkick *k = dev_get_drvdata(dev);

	return sysfs_emit(buf, "frames %lu restarts %lu stuck %u\n",
			  k->frames, k->restarts, k->stuck);
}
static DEVICE_ATTR_RO(stats);

static int fbkick_probe(struct platform_device *pdev)
{
	struct device *dev = &pdev->dev;
	struct fbkick *k;
	u32 fb, l0, r0;

	if (of_property_read_u32(dev->of_node, "op6893,framebuffer", &fb))
		return dev_err_probe(dev, -EINVAL, "missing op6893,framebuffer\n");

	k = devm_kzalloc(dev, sizeof(*k), GFP_KERNEL);
	if (!k)
		return -ENOMEM;

	/*
	 * Not devm_platform_ioremap_resource(): the blocks belong to the
	 * future display driver, so do not claim the region exclusively.
	 */
	k->base = devm_ioremap(dev, 0x14000000, DISP_SIZE);
	if (!k->base)
		return -ENOMEM;

	/* Only touch a pipeline LK actually left running in command mode. */
	if (!(readl(k->base + DISP_DSI0 + DSI_START) & 1) ||
	    readl(k->base + DISP_DSI0 + DSI_MODE_CTRL) != 0 ||
	    !(readl(k->base + DISP_OVL0_2L + OVL_EN) & 1) ||
	    !(readl(k->base + DISP_OVL1_2L + OVL_EN) & 1))
		return dev_err_probe(dev, -ENODEV,
				     "LK display pipeline not running\n");

	/* Scan out the buffer simple-framebuffer draws into. */
	l0 = readl(k->base + DISP_OVL0_2L + OVL_L0_ADDR);
	r0 = readl(k->base + DISP_OVL1_2L + OVL_L0_ADDR);
	if (r0 < l0 || r0 - l0 >= SZ_16K)
		return dev_err_probe(dev, -ENODEV,
				     "unexpected OVL layout %08x/%08x\n", l0, r0);
	writel(fb, k->base + DISP_OVL0_2L + OVL_L0_ADDR);
	writel(fb + (r0 - l0), k->base + DISP_OVL1_2L + OVL_L0_ADDR);

	platform_set_drvdata(pdev, k);
	INIT_DELAYED_WORK(&k->work, fbkick_work);
	schedule_delayed_work(&k->work, 0);

	dev_info(dev, "refreshing panel from %08x (LK had %08x)\n", fb, l0);

	return device_create_file(dev, &dev_attr_stats);
}

static const struct of_device_id fbkick_of_match[] = {
	{ .compatible = "op6893,fbkick" },
	{ }
};

static struct platform_driver fbkick_driver = {
	.probe = fbkick_probe,
	.driver = {
		.name = "op6893-fbkick",
		.of_match_table = fbkick_of_match,
		.suppress_bind_attrs = true,
	},
};
builtin_platform_driver(fbkick_driver);
