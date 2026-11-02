// SPDX-License-Identifier: GPL-2.0-only
/* One-shot op6893 LVTS calibration experiment, not a thermal driver. */

#include <linux/clk.h>
#include <linux/clk-provider.h>
#include <linux/delay.h>
#include <linux/init.h>
#include <linux/io.h>
#include <linux/iopoll.h>
#include <linux/ktime.h>
#include <linux/math64.h>
#include <linux/mutex.h>
#include <linux/mfd/syscon.h>
#include <linux/of.h>
#include <linux/platform_device.h>
#include <linux/regmap.h>
#include <linux/unaligned.h>
#include <linux/slab.h>
#include <linux/sysfs.h>
#include <dt-bindings/clock/mt6893-clk.h>

#define LVTS_MONCTL	0x00
#define LVTS_MONINT	0x0c
#define LVTS_ID		0x4c
#define LVTS_CONFIG	0x50
#define LVTS_PROTCTL	0xc0
#define LVTS_PROTTC	0xcc
#define LVTS_CLKEN	0xe4
#define LVTS_ACCESS	BIT(24)

static int op6893_lvts_idle(void __iomem *base)
{
	/* Require the exact inactive state observed before this experiment. */
	if (readl(base + LVTS_MONCTL) || readl(base + LVTS_MONINT) ||
	    readl(base + LVTS_PROTCTL) || readl(base + LVTS_PROTTC) ||
	    readl(base + LVTS_CLKEN) || (readl(base + LVTS_CONFIG) & LVTS_ACCESS))
		return -EBUSY;

	return 0;
}

static int op6893_lvts_command(void __iomem *base, u32 command)
{
	u32 value;

	if (readl(base + LVTS_CONFIG) & LVTS_ACCESS)
		return -EBUSY;
	writel(command, base + LVTS_CONFIG);
	/* ACK requires at least 3 us before checking the serial interface. */
	udelay(3);
	return readl_poll_timeout(base + LVTS_CONFIG, value,
				 !(value & LVTS_ACCESS), 2, 200);
}

static int op6893_lvts_identify(void __iomem *base, u32 expected, u32 *id)
{
	int ret;

	writel(1, base + LVTS_CLKEN);
	ret = op6893_lvts_command(base, 0x8103ffff); /* Reset sensor devices. */
	if (ret)
		goto stop_clock;
	ret = op6893_lvts_command(base, 0x8502fc55); /* Update the ID latch. */
	if (ret)
		goto stop_clock;
	*id = readl(base + LVTS_ID) & 0xff;
	if (*id != expected)
		ret = -ENODEV;
stop_clock:
	/* Never enable sensing, IRQs or protection in this experiment. */
	writel(0, base + LVTS_CLKEN);
	readl(base + LVTS_CLKEN);
	return ret;
}

static int op6893_lvts_reset(struct regmap *map, u32 set, u32 clear, u32 mask)
{
	int ret;

	/* SET/CLR aliases need exact writes, never read-modify-write. */
	ret = regmap_write(map, set, mask);
	if (ret)
		return ret;
	udelay(2);
	ret = regmap_write(map, clear, mask);
	if (ret)
		regmap_write(map, clear, mask);
	return ret;
}

struct op6893_lvts_calibration {
	u32 count_r[17];
	u32 count_rc[7];
	u32 golden;
};

struct op6893_lvts_result {
	u32 raw[4];
	u32 used[4];
	u32 edata[4];
};

static const unsigned int op6893_lvts_sensor_counts[] = { 2, 2, 4, 2, 2, 2, 3 };

static int op6893_lvts_decode(const void *blob, int len,
			      struct op6893_lvts_calibration *cal)
{
	const u8 *bytes = blob;
	u32 words[22], count;
	int i;

	if (!blob || len < 4)
		return -EINVAL;
	count = get_unaligned_le32(bytes);
	if (count < 208 || count > 400 || len != 4 + count * 4)
		return -EINVAL;
	for (i = 0; i < ARRAY_SIZE(words); i++)
		words[i] = get_unaligned_le32(bytes + 4 + 4 * (i < 4 ? 116 + i : 186 + i));
	cal->golden = words[0] >> 24;
	if (!cal->golden || cal->golden > 62)
		return -EINVAL;
	for (i = 0; i < ARRAY_SIZE(cal->count_r); i++) {
		cal->count_r[i] = words[i + 1] & GENMASK(23, 0);
		if (!cal->count_r[i])
			return -EINVAL;
	}
	cal->count_rc[0] = words[21] & GENMASK(23, 0);
	for (i = 1; i < ARRAY_SIZE(cal->count_rc); i++)
		cal->count_rc[i] = ((words[i * 3 - 2] >> 24) << 16) |
				  ((words[i * 3 - 1] >> 24) << 8) |
				  (words[i * 3] >> 24);
	for (i = 0; i < ARRAY_SIZE(cal->count_rc); i++)
		if (!cal->count_rc[i])
			return -EINVAL;
	return 0;
}

static int op6893_lvts_normalize(u32 raw, u32 factory, u32 count_r,
				 u32 *used, u32 *edata)
{
	u64 value, ratio;

	if (!factory || !count_r || factory > GENMASK(23, 0) ||
	    count_r > GENMASK(23, 0) || raw > GENMASK(23, 0))
		return -EINVAL;
	/* Match ACK's integer ratio and strict >1061 refinement threshold. */
	ratio = raw ? div_u64((u64)max(raw, factory) * 1000, min(raw, factory)) : 0;
	*used = !raw || ratio > 1061 ? factory : raw;
	value = ((u64)*used * count_r) >> 14;
	if (!value || value > U32_MAX)
		return -ERANGE;
	*edata = value;
	return 0;
}

static int op6893_lvts_rck(void __iomem *base, unsigned int num,
			   const u32 *count_r, u32 factory,
			   struct op6893_lvts_result *result)
{
	static const u32 init[] = {
		0x81030300, 0x81030420, 0x81030500, 0x81030ac4, 0x81030c7c,
		0x8103098d, 0x810308f5, 0x810308fc, 0x810308f5, 0x810307a6,
		0x81030e00,
	};
	static const u32 single[] = {
		0x81030678, 0x810307a6, 0x810308f5, 0x810308fc, 0x810308f5,
	};
	u32 status;
	unsigned int i, j;
	int ret, cleanup;

	if (!num || num > 4)
		return -EINVAL;
	writel(1, base + LVTS_CLKEN);
	for (i = 0; i < ARRAY_SIZE(init); i++) {
		ret = op6893_lvts_command(base, init[i]);
		if (ret)
			goto stop;
	}
	for (i = 0; i < num; i++) {
		ret = op6893_lvts_command(base, 0x81030d00 | i);
		if (ret)
			goto stop;
		for (j = 0; j < ARRAY_SIZE(single); j++) {
			ret = op6893_lvts_command(base, single[j]);
			if (ret)
				goto stop;
		}
		udelay(10);
		ret = op6893_lvts_command(base, 0x81030302);
		if (ret)
			goto stop;
		udelay(30);
		ret = readl_poll_timeout(base + LVTS_CONFIG, status,
					 !(status & BIT(25)), 2, 200);
		if (ret)
			goto stop;
		ret = op6893_lvts_command(base, 0x81020000);
		if (ret)
			goto stop;
		udelay(2); /* Read commands need at least 5 us in total. */
		result->raw[i] = readl(base + 0xb0) & GENMASK(23, 0);
		ret = op6893_lvts_command(base, 0x810308f1);
		if (ret)
			goto stop;
		ret = op6893_lvts_normalize(result->raw[i], factory, count_r[i],
					  &result->used[i], &result->edata[i]);
		if (ret)
			goto stop;
	}
	ret = op6893_lvts_command(base, 0x81030d10);
stop:
	/* Best-effort TS_EN shutdown even after initialization/counting failure. */
	cleanup = op6893_lvts_command(base, 0x810308f1);
	if (cleanup)
		pr_err("op6893-lvts: TS_EN cleanup failed: %d\n", cleanup);
	if (!ret)
		ret = cleanup;
	writel(0, base + LVTS_CLKEN);
	readl(base + LVTS_CLKEN);
	return ret;
}

static int op6893_lvts_program(void __iomem *base, unsigned int num,
			       const struct op6893_lvts_result *result)
{
	unsigned int i;
	int ret = 0;

	if (!num || num > 4)
		return -EINVAL;
	writel(1, base + LVTS_CLKEN);
	for (i = 0; i < num; i++) {
		writel(result->edata[i], base + 0x54 + i * 4);
		if (readl(base + 0x54 + i * 4) != result->edata[i]) {
			ret = -EIO;
			break;
		}
	}
	writel(0, base + LVTS_CLKEN);
	readl(base + LVTS_CLKEN);
	return ret;
}

static int op6893_lvts_temperature(u32 msr, u32 golden, int *temperature)
{
	u32 raw = msr & 0xffff;

	if (!(msr & BIT(16)) || !raw)
		return -ENODATA;
	if (!golden || golden > 62)
		return -EINVAL;
	/* Explicit signed arithmetic matches ACK's negative coefficient. */
	*temperature = ((-(s64)252500 * raw) >> 14) + golden * 500 + 252500;
	return 0;
}

static int op6893_lvts_sample(void __iomem *base, unsigned int num,
			      u32 golden, u32 *samples, int *temperatures)
{
	u32 value;
	unsigned int i;
	int ret, cleanup;

	if (!num || num > 4)
		return -EINVAL;
	writel(1, base + LVTS_CLKEN);
	/* Never sample with an inherited interrupt or protection configuration. */
	if (readl(base + LVTS_MONCTL) || readl(base + LVTS_MONINT) ||
	    readl(base + LVTS_PROTCTL) || readl(base + LVTS_PROTTC)) {
		ret = -EBUSY;
		goto clock_off;
	}
	/* Reject stale valid data before starting this first acquisition. */
	for (i = 0; i < num; i++) {
		if (readl(base + 0x90 + i * 4) & BIT(16)) {
			ret = -ESTALE;
			goto clock_off;
		}
	}
	writel(0x13121110, base + 0x40);
	writel(0x300, base + 0x48);
	writel(0x10000c, base + 0x04);
	writel(0x10001, base + 0x08);
	writel(0x492, base + 0x38);
	ret = op6893_lvts_command(base, 0x81030d10);
	if (ret)
		goto stop;
	ret = op6893_lvts_command(base, 0x810306b8);
	if (ret)
		goto stop;
	ret = op6893_lvts_command(base, 0x810308f5);
	if (ret)
		goto stop;
	udelay(10);
	writel(BIT(9) | (BIT(num) - 1), base + LVTS_MONCTL);
	for (i = 0; i < num; i++) {
		ret = readl_poll_timeout(base + 0x90 + i * 4, value,
					 value & BIT(16), 50, 20000);
		if (ret)
			goto stop;
		samples[i] = value;
		ret = op6893_lvts_temperature(value, golden, &temperatures[i]);
		if (ret)
			goto stop;
	}
stop:
	/* Pause, stop requests, then wait for the controller to become idle. */
	writel(readl(base + 0x3c) | 0x10e, base + 0x3c);
	writel(0, base + LVTS_MONCTL);
	cleanup = readl_poll_timeout(base + 0x3c, value, !(value & 0x481), 2, 1000);
	if (cleanup)
		pr_err("op6893-lvts: sample controller did not become idle: %d\n", cleanup);
	if (!ret)
		ret = cleanup;
	cleanup = op6893_lvts_command(base, 0x810308f1);
	if (cleanup)
		pr_err("op6893-lvts: sample TS_EN shutdown failed: %d\n", cleanup);
	if (!ret)
		ret = cleanup;
clock_off:
	writel(0, base + LVTS_CLKEN);
	readl(base + LVTS_CLKEN);
	return ret;
}

static int op6893_lvts_load_calibration(struct op6893_lvts_calibration *cal)
{
	struct device_node *chosen;
	const void *blob;
	int len, ret;

	chosen = of_find_node_by_path("/chosen");
	if (!chosen)
		return -ENODATA;
	blob = of_get_property(chosen, "atag,devinfo", &len);
	ret = op6893_lvts_decode(blob, blob ? len : 0, cal);
	of_node_put(chosen);
	return ret;
}

struct op6893_lvts_capture {
	u64 start_ns;
	u64 end_ns;
	u32 raw[17];
	int temperature[17];
};

struct op6893_lvts_session {
	struct mutex lock;
	u64 sequence;
	bool faulted;
};

static int op6893_lvts_acquire(struct platform_device *pdev,
			       struct op6893_lvts_capture *capture)
{
	struct device_node *np;
	struct op6893_lvts_calibration cal;
	struct op6893_lvts_result results[7] = {};
	struct of_phandle_args spec = { .args_count = 1,
				       .args = { CLK_IFRAO_THERM } };
	void __iomem *ap, *mcu, *controllers[7];
	struct regmap *infra;
	struct clk *clk;
	u32 id = 0, samples[4];
	int temperatures[4];
	int i, j, sensor, ret;

	capture->start_ns = ktime_get_boottime_ns();
	if (!of_machine_is_compatible("realme,op6893"))
		return -ENODEV;
	ret = op6893_lvts_load_calibration(&cal);
	if (ret)
		return dev_err_probe(&pdev->dev, ret, "invalid LVTS calibration\n");
	np = of_find_compatible_node(NULL, NULL, "mediatek,mt6893-infracfg_ao");
	if (!np)
		return -ENODEV;
	infra = syscon_node_to_regmap(np);
	spec.np = np;
	clk = of_clk_get_from_provider(&spec);
	of_node_put(np);
	if (IS_ERR(clk))
		return dev_err_probe(&pdev->dev, PTR_ERR(clk), "thermal clock unavailable\n");
	if (IS_ERR(infra)) {
		ret = PTR_ERR(infra);
		goto put_clock;
	}
	if (!clk_get_rate(clk)) {
		ret = -EINVAL;
		goto put_clock;
	}
	ret = clk_prepare_enable(clk);
	if (ret)
		goto put_clock;

	/* Board-only audited ranges; replace with DT resources in a real driver. */
	ap = ioremap(0x1100b000, 0x400);
	mcu = ioremap(0x11278000, 0x300);
	if (!ap || !mcu) {
		ret = -ENOMEM;
		goto unmap;
	}
	for (i = 0; i < ARRAY_SIZE(controllers); i++) {
		controllers[i] = i < 3 ? mcu + i * 0x100 : ap + (i - 3) * 0x100;
		ret = op6893_lvts_idle(controllers[i]);
		if (ret) {
			pr_err("op6893-lvts: controller %d is not idle\n", i);
			goto unmap;
		}
	}
	ret = op6893_lvts_reset(infra, 0x120, 0x124, BIT(0));
	if (ret)
		goto unmap;
	ret = op6893_lvts_reset(infra, 0x730, 0x734, BIT(10));
	if (ret)
		goto unmap;

	for (i = 0; i < ARRAY_SIZE(controllers); i++) {
		id = 0;
		ret = op6893_lvts_identify(controllers[i], 0x81 + i, &id);
		if (ret) {
			pr_err("op6893-lvts: controller %d identification failed: %d, id %#x\n",
			       i, ret, id);
			goto unmap;
		}
		pr_debug("op6893-lvts: controller %d ID %#x verified; local clock stopped\n",
			i, id);
	}
	for (i = 0, sensor = 0; i < ARRAY_SIZE(controllers); i++) {
		ret = op6893_lvts_rck(controllers[i], op6893_lvts_sensor_counts[i],
				     &cal.count_r[sensor], cal.count_rc[i], &results[i]);
		if (ret) {
			pr_err("op6893-lvts: controller %d RCK failed: %d\n", i, ret);
			goto unmap;
		}
		for (j = 0; j < op6893_lvts_sensor_counts[i]; j++, sensor++)
			pr_debug("op6893-lvts: sensor %d RC raw=%u used=%u factory=%u R=%u EDATA=%u\n",
				sensor, results[i].raw[j], results[i].used[j],
				cal.count_rc[i], cal.count_r[sensor], results[i].edata[j]);
	}
	/* Publish calibration only after all seventeen measurements succeed. */
	for (i = 0; i < ARRAY_SIZE(controllers); i++) {
		ret = op6893_lvts_program(controllers[i], op6893_lvts_sensor_counts[i],
					  &results[i]);
		if (ret) {
			pr_err("op6893-lvts: controller %d EDATA readback failed\n", i);
			goto unmap;
		}
	}
	for (i = 0, sensor = 0; i < ARRAY_SIZE(controllers); i++) {
		ret = op6893_lvts_sample(controllers[i], op6893_lvts_sensor_counts[i],
					 cal.golden, samples, temperatures);
		if (ret) {
			pr_err("op6893-lvts: controller %d sample failed: %d\n", i, ret);
			goto unmap;
		}
		for (j = 0; j < op6893_lvts_sensor_counts[i]; j++, sensor++) {
			capture->raw[sensor] = samples[j];
			capture->temperature[sensor] = temperatures[j];
		}
	}
	capture->end_ns = ktime_get_boottime_ns();
unmap:
	if (mcu)
		iounmap(mcu);
	if (ap)
		iounmap(ap);
	clk_disable_unprepare(clk);
put_clock:
	clk_put(clk);
	return ret;
}
/* Read initiates a destructive diagnostic acquisition, not cached telemetry. */
static ssize_t capture_show(struct device *dev, struct device_attribute *attr, char *buf)
{
	struct op6893_lvts_session *session = dev_get_drvdata(dev);
	struct op6893_lvts_capture capture = {};
	ssize_t length;
	int i, ret;

	ret = mutex_lock_interruptible(&session->lock);
	if (ret)
		return ret;
	if (session->faulted) {
		ret = -EIO;
		goto unlock;
	}
	ret = op6893_lvts_acquire(to_platform_device(dev), &capture);
	if (ret) {
		/* Do not automatically retry partially completed hardware operations. */
		session->faulted = true;
		goto unlock;
	}
	session->sequence++;
	length = sysfs_emit(buf, "sequence=%llu start_ns=%llu end_ns=%llu\n",
			    session->sequence, capture.start_ns, capture.end_ns);
	for (i = 0; i < ARRAY_SIZE(capture.raw); i++)
		length += sysfs_emit_at(buf, length, "%d %#x %d\n", i,
				       capture.raw[i], capture.temperature[i]);
	mutex_unlock(&session->lock);
	return length;
unlock:
	mutex_unlock(&session->lock);
	return ret;
}
static DEVICE_ATTR(capture, 0400, capture_show, NULL);

static struct attribute *op6893_lvts_attrs[] = {
	&dev_attr_capture.attr,
	NULL,
};
ATTRIBUTE_GROUPS(op6893_lvts);

static int op6893_lvts_probe(struct platform_device *pdev)
{
	struct op6893_lvts_capture capture = {};
	struct op6893_lvts_session *session;
	int ret;

	session = devm_kzalloc(&pdev->dev, sizeof(*session), GFP_KERNEL);
	if (!session)
		return -ENOMEM;
	mutex_init(&session->lock);
	ret = op6893_lvts_acquire(pdev, &capture);
	if (ret)
		return ret;
	platform_set_drvdata(pdev, session);
	pr_info("op6893-lvts: diagnostic capture ready; reads reset and recalibrate all sensors\n");
	return 0;
}

static struct platform_driver op6893_lvts_driver = {
	.probe = op6893_lvts_probe,
	.driver = {
		.name = "op6893-lvts-identify",
		.dev_groups = op6893_lvts_groups,
		.suppress_bind_attrs = true,
	},
};

static int __init op6893_lvts_init(void)
{
	struct platform_device *pdev;
	int ret;

	if (!of_machine_is_compatible("realme,op6893"))
		return -ENODEV;
	ret = platform_driver_register(&op6893_lvts_driver);
	if (ret)
		return ret;
	pdev = platform_device_register_simple("op6893-lvts-identify", -1, NULL, 0);
	if (IS_ERR(pdev)) {
		platform_driver_unregister(&op6893_lvts_driver);
		return PTR_ERR(pdev);
	}
	return 0;
}
late_initcall(op6893_lvts_init);
