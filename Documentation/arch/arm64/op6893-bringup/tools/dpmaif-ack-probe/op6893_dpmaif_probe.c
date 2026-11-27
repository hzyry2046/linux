// SPDX-License-Identifier: GPL-2.0-only
/* Read-only DPMAIF v2 AO register snapshots for the op6893 ACK comparison. */
#include <linux/io.h>
#include <linux/ktime.h>
#include <linux/module.h>
#include <linux/of.h>
#include <linux/of_address.h>
#include <linux/sysfs.h>

#define DPMAIF_AO_BASE	0x10014000
#define DPMAIF_AO_SIZE	0x1000

static void __iomem *ao;

static const struct {
	const char *name;
	u16 offset;
} registers[] = {
	{ "ul_arb",		0x01c },
	{ "ul_q0_sta0",		0x060 },
	{ "ul_q1_sta0",		0x064 },
	{ "ul_q2_sta0",		0x068 },
	{ "ul_q3_sta0",		0x06c },
	{ "ul_q4_sta0",		0x0dc },
	{ "ul_widx01",		0x0c0 },
	{ "ul_widx23",		0x0c4 },
	{ "ul_widx4",		0x0e4 },
	{ "dl_irq_mask",	0x090 },
	{ "pktinfo0",		0x400 },
	{ "pktinfo1",		0x404 },
	{ "pktinfo2",		0x408 },
	{ "thres",		0x40c },
	{ "bat_sta1",		0x414 },
	{ "bat_sta2",		0x418 },
	{ "pit_sta1",		0x424 },
	{ "pit_sta2",		0x428 },
	{ "pit_sta3",		0x42c },
	{ "frg_thres",		0x430 },
	{ "frgbat_sta1",	0x444 },
	{ "frgbat_sta2",	0x448 },
	{ "bat_sta3",		0x450 },
	{ "pit_sta4",		0x454 },
	{ "frgbat_sta3",	0x458 },
};

static int snapshot_get(char *buf, const struct kernel_param *param)
{
	int len;
	unsigned int i;

	if (!ao)
		return -ENODEV;

	len = scnprintf(buf, PAGE_SIZE, "start_ns=%llu\n", ktime_get_boottime_ns());
	for (i = 0; i < ARRAY_SIZE(registers); i++)
		len += scnprintf(buf + len, PAGE_SIZE - len, "%s=0x%08x\n",
				 registers[i].name, readl(ao + registers[i].offset));
	len += scnprintf(buf + len, PAGE_SIZE - len, "end_ns=%llu\n",
			 ktime_get_boottime_ns());

	return len;
}

static const struct kernel_param_ops snapshot_ops = {
	.get = snapshot_get,
};
module_param_cb(snapshot, &snapshot_ops, NULL, 0400);
MODULE_PARM_DESC(snapshot, "Read one timestamped DPMAIF v2 AO register snapshot");

static int __init op6893_dpmaif_probe_init(void)
{
	struct device_node *node;
	struct resource res;
	u32 version;
	int ret;

	node = of_find_compatible_node(NULL, NULL, "mediatek,dpmaif");
	if (!node)
		return -ENODEV;

	ret = of_address_to_resource(node, 0, &res);
	if (ret)
		goto put_node;

	if (!of_device_is_available(node) || res.start != DPMAIF_AO_BASE ||
	    resource_size(&res) != DPMAIF_AO_SIZE) {
		ret = -ENODEV;
		goto put_node;
	}

	/* The preserved op6893 DT has the v2 resource layout, with no ver cell. */
	if (of_find_property(node, "mediatek,dpmaif-ver", NULL) &&
	    (of_property_read_u32(node, "mediatek,dpmaif-ver", &version) || version != 2)) {
		ret = -ENODEV;
		goto put_node;
	}

	ao = ioremap(res.start, resource_size(&res));
	ret = ao ? 0 : -ENOMEM;

put_node:
	of_node_put(node);
	return ret;
}

static void __exit op6893_dpmaif_probe_exit(void)
{
	/* The module parameter is removed by the kernel after the exit hook. */
	kernel_param_lock(THIS_MODULE);
	iounmap(ao);
	ao = NULL;
	kernel_param_unlock(THIS_MODULE);
}

module_init(op6893_dpmaif_probe_init);
module_exit(op6893_dpmaif_probe_exit);

MODULE_DESCRIPTION("Read-only op6893 DPMAIF v2 AO comparison probe");
MODULE_LICENSE("GPL");
