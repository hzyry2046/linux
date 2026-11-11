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
 *
 * A backlight device controls the panel through DCS: brightness is the
 * 11-bit Write Display Brightness (0x51, normal range only; the panel's
 * high-brightness mode above 2047 is not used), and bl_power/blanking sends
 * Display Off/On (0x28/0x29) and pauses frame transfers meanwhile. Frame
 * triggers and DCS writes share the DSI command queue, so both run under
 * one lock.
 */
#include <linux/backlight.h>
#include <linux/io.h>
#include <linux/iopoll.h>
#include <linux/jiffies.h>
#include <linux/module.h>
#include <linux/mutex.h>
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

#define DSI_CONFG_LONG_PACKET		0x02
#define DSI_DCS_SHORT_WRITE_0		0x05
#define DSI_DCS_SHORT_WRITE_1		0x15
#define DSI_DCS_LONG_WRITE		0x39
#define DCS_SET_DISPLAY_OFF		0x28
#define DCS_SET_DISPLAY_ON		0x29
#define DCS_SET_BRIGHTNESS		0x51
#define DCS_WRITE_CONTROL		0x53
#define DCS_CONTROL_NORMAL		0x20	/* dimming on, HBM off */

#define FBKICK_MAX_BRIGHTNESS		2047
#define FBKICK_DEFAULT_BRIGHTNESS	600
#define FBKICK_IDLE_TIMEOUT_US		100000

#define FBKICK_PERIOD_MS		33
#define FBKICK_STUCK_RESTART		30	/* ~1 s of a busy DSI */

struct fbkick {
	void __iomem *base;
	struct device *dev;
	struct mutex lock;		/* DSI command queue */
	bool display_off;
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

static int fbkick_wait_idle(struct fbkick *k)
{
	u32 sta;

	return readl_poll_timeout(k->base + DISP_DSI0 + DSI_INTSTA, sta,
				  !(sta & DSI_INTSTA_BUSY), 100,
				  FBKICK_IDLE_TIMEOUT_US);
}

/* Short or long DCS write through the DSI command queue, lock held. */
static int fbkick_dcs(struct fbkick *k, u8 cmd, const u8 *data, size_t len)
{
	void __iomem *dsi = k->base + DISP_DSI0;
	size_t i, j;
	u32 word;
	int ret;

	if (len > 8)
		return -EINVAL;

	ret = fbkick_wait_idle(k);
	if (ret)
		return ret;

	writel(0, dsi + DSI_INTSTA);
	if (len > 1) {
		writel(DSI_CONFG_LONG_PACKET | DSI_DCS_LONG_WRITE << 8 |
		       (len + 1) << 16, dsi + DSI_CMDQ0);
		for (i = 0; i < len + 1; i += 4) {
			word = 0;
			for (j = 0; j < 4 && i + j < len + 1; j++)
				word |= (u32)(i + j ? data[i + j - 1] : cmd) <<
					(8 * j);
			writel(word, dsi + DSI_CMDQ0 + 4 + i);
		}
		writel(2 + len / 4, dsi + DSI_CMDQ_SIZE);
	} else {
		writel((len ? DSI_DCS_SHORT_WRITE_1 : DSI_DCS_SHORT_WRITE_0) << 8 |
		       cmd << 16 | (len ? data[0] : 0) << 24, dsi + DSI_CMDQ0);
		writel(1, dsi + DSI_CMDQ_SIZE);
	}
	writel(0, dsi + DSI_START);
	writel(1, dsi + DSI_START);

	ret = fbkick_wait_idle(k);
	if (ret)
		dev_warn_ratelimited(k->dev, "DCS 0x%02x timed out\n", cmd);

	return ret;
}

static int fbkick_update_status(struct backlight_device *bl)
{
	struct fbkick *k = bl_get_data(bl);
	int level = backlight_get_brightness(bl);
	bool off = backlight_is_blank(bl);
	u8 v[2] = { level >> 8, level & 0xff };
	int ret = 0;

	guard(mutex)(&k->lock);

	if (off) {
		if (!k->display_off) {
			ret = fbkick_dcs(k, DCS_SET_DISPLAY_OFF, NULL, 0);
			k->display_off = !ret;
		}
		return ret;
	}

	ret = fbkick_dcs(k, DCS_SET_BRIGHTNESS, v, sizeof(v));
	if (!ret && k->display_off) {
		ret = fbkick_dcs(k, DCS_SET_DISPLAY_ON, NULL, 0);
		k->display_off = !!ret;
	}

	return ret;
}

static const struct backlight_ops fbkick_bl_ops = {
	.options = BL_CORE_SUSPENDRESUME,
	.update_status = fbkick_update_status,
};

static void fbkick_work(struct work_struct *work)
{
	struct fbkick *k = container_of(to_delayed_work(work), struct fbkick,
					work);

	mutex_lock(&k->lock);
	if (k->display_off) {
		/* Nothing to show; keep the DSI free while the panel is off. */
	} else if (readl(k->base + DISP_DSI0 + DSI_INTSTA) & DSI_INTSTA_BUSY) {
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
	mutex_unlock(&k->lock);

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
	struct backlight_properties props = {
		.type = BACKLIGHT_RAW,
		.max_brightness = FBKICK_MAX_BRIGHTNESS,
		.brightness = FBKICK_DEFAULT_BRIGHTNESS,
		.scale = BACKLIGHT_SCALE_NON_LINEAR,
	};
	struct backlight_device *bl;
	struct fbkick *k;
	u32 fb, l0, r0;
	u8 ctl = DCS_CONTROL_NORMAL;
	int ret;

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

	k->dev = dev;
	ret = devm_mutex_init(dev, &k->lock);
	if (ret)
		return ret;
	platform_set_drvdata(pdev, k);

	/* Normal (non-HBM) brightness range before the first level is set. */
	mutex_lock(&k->lock);
	fbkick_dcs(k, DCS_WRITE_CONTROL, &ctl, 1);
	mutex_unlock(&k->lock);

	bl = devm_backlight_device_register(dev, "panel", dev, k,
					    &fbkick_bl_ops, &props);
	if (IS_ERR(bl))
		return dev_err_probe(dev, PTR_ERR(bl), "backlight\n");
	backlight_update_status(bl);

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
