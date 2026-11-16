// SPDX-License-Identifier: GPL-2.0-only
/* Same-board cold MD platform cycle. Never issue the MD CPU boot SMC. */
#include <linux/arm-smccc.h>
#include <linux/bitops.h>
#include <linux/clk.h>
#include <linux/delay.h>
#include <linux/mfd/syscon.h>
#include <linux/mutex.h>
#include <linux/of.h>
#include <linux/platform_device.h>
#include <linux/pm_domain.h>
#include <linux/pm_runtime.h>
#include <linux/regmap.h>
#include <linux/regulator/consumer.h>
#include <linux/slab.h>
#include <linux/soc/mediatek/mtk_sip_svc.h>
#include <linux/soc/mediatek/mt6893-md.h>

#include "ccci-md-platform.h"
#include "ccci-ccif.h"
#include "ccci-ccism-bridge.h"
#include "ccci-md-boot.h"
#include "ccci-nvram-cache.h"
#include "ccci-rtc32k.h"
#include "ccci-service-endpoint.h"
#include "ccci-port-dispatch.h"
#include "ccci-rpc-op6893.h"
#include "ccci-md-power.h"
#include "ccci-smem.h"

#define MD_FLIGHT_MODE	7
#define MD_POWER_CONFIG	6
#define MD_CHECK_DONE	3
#define MD_PROTECT2	(BIT(10) | BIT(21) | BIT(29))
#define SPM_PCM_REG13	0x110

struct ccci_md_platform {
	/* Serializes commands, state reporting and shutdown. */
	struct mutex lock;
	struct ccci_md_power power;
	struct ccci_smem_layout smem;
	struct regmap *spm;
	struct regmap *infra;
	struct regulator *rails[4];
	int voltage[4];
	struct clk_bulk_data clocks[4];
	struct device *lookup;
	struct device *domain;
	struct ccci_ccif *ccif;
	struct ccci_ccism_bridge *bridge;
	struct ccci_service_endpoint *services;
	struct ccci_port_dispatch *dispatch;
	struct ccci_nvram_cache *cache;
	struct ccci_md_boot *boot;
};

/* Independent hardware check also catches a genpd power-off veto/failure. */
static int md_domain_check(struct ccci_md_platform *md, bool on)
{
	u32 status, control, iso, protect1, protect2, protect3;
	int ret;

	ret = regmap_read(md->spm, 0x16c, &status);
	if (ret)
		return ret;
	ret = regmap_read(md->spm, 0x300, &control);
	if (ret)
		return ret;
	ret = regmap_read(md->spm, 0x398, &iso);
	if (ret)
		return ret;
	ret = regmap_read(md->infra, 0x228, &protect1);
	if (ret)
		return ret;
	ret = regmap_read(md->infra, 0xb90, &protect2);
	if (ret)
		return ret;
	ret = regmap_read(md->infra, 0xbc4, &protect3);
	if (ret)
		return ret;
	if ((status & BIT(0)) != (on ? BIT(0) : 0) ||
	    (control & (BIT(0) | BIT(2))) != (on ? BIT(0) | BIT(2) : 0) ||
	    (iso & GENMASK(1, 0)) != (on ? 0 : GENMASK(1, 0)) ||
	    (protect1 & BIT(7)) != (on ? 0 : BIT(7)) ||
	    (protect2 & MD_PROTECT2) != (on ? 0 : MD_PROTECT2) ||
	    (protect3 & GENMASK(7, 6)) != (on ? 0 : GENMASK(7, 6)))
		return -EBUSY;
	return 0;
}

static int md_off_check(void *context)
{
	return md_domain_check(context, false);
}

static int md_read_rails(struct ccci_md_platform *md, int voltage[4])
{
	int ret;

	for (unsigned int i = 0; i < ARRAY_SIZE(md->rails); i++) {
		ret = regulator_is_enabled(md->rails[i]);
		if (ret <= 0)
			return ret ?: -ENODATA;
		ret = regulator_get_voltage(md->rails[i]);
		if (ret <= 0)
			return ret ?: -ENODATA;
		voltage[i] = ret;
	}
	return 0;
}

static int md_rails_check(void *context)
{
	struct ccci_md_platform *md = context;
	int voltage[4], ret;

	ret = md_read_rails(md, voltage);
	if (ret)
		return ret;
	if (memcmp(voltage, md->voltage, sizeof(voltage)))
		return -ESTALE;
	return md_domain_check(md, md->power.state == CCCI_MD_INHERITED);
}

static int md_clocks(void *context, bool on)
{
	struct ccci_md_platform *md = context;

	if (on)
		return clk_bulk_prepare_enable(ARRAY_SIZE(md->clocks), md->clocks);
	clk_bulk_disable_unprepare(ARRAY_SIZE(md->clocks), md->clocks);
	return 0;
}

static int md_srcclk(void *context, bool on)
{
	struct ccci_md_platform *md = context;
	u32 value;
	int ret;

	ret = regmap_update_bits(md->infra, 0xf0c, 0xff, on ? 0x21 : 0);
	if (ret)
		return ret;
	ret = regmap_read(md->infra, 0xf0c, &value);
	if (ret)
		return ret;
	return (value & 0xff) == (on ? 0x21 : 0) ? 0 : -EIO;
}

static int md_srclken_o1(void *context)
{
	struct ccci_md_platform *md = context;
	u32 value;
	int ret;

	ret = regmap_write(md->spm, 0, 0xb160001);
	if (ret)
		return ret;
	ret = regmap_set_bits(md->spm, 8, BIT(21));
	if (ret)
		return ret;
	ret = regmap_read(md->spm, 8, &value);
	if (ret)
		return ret;
	/* Same-board vendor OFF does not clear this shared SPM bit. */
	return value & BIT(21) ? 0 : -EIO;
}

static int md_flight(void *context, bool flight)
{
	struct arm_smccc_res res;

	arm_smccc_smc(MTK_SIP_KERNEL_CCCI_CONTROL, MD_FLIGHT_MODE, flight, 0, 0, 0, 0, 0, &res);
	if (res.a0 == (unsigned long)SMCCC_RET_NOT_SUPPORTED)
		return -EOPNOTSUPP;
	/* No fallback function IDs or interpretation of diagnostic a1..a3. */
	return res.a0 ? -EIO : 0;
}

static int md_domain(void *context, bool on)
{
	struct ccci_md_platform *md = context;
	int ret;

	if (on)
		ret = pm_runtime_resume_and_get(md->domain);
	else
		ret = pm_runtime_put_sync_suspend(md->domain);
	if (ret < 0)
		return ret;
	return md_domain_check(md, on);
}

static int md_handoff_check(void *context)
{
	struct ccci_md_platform *md = context;
	struct arm_smccc_res res;
	int ret;

	ret = md_domain_check(md, true);
	if (ret)
		return ret;
	/* Same-board md_start_platform(): up to 100 CHECK_DONE requests at 20 ms. */
	for (unsigned int i = 0; i < 100; i++) {
		arm_smccc_smc(MTK_SIP_KERNEL_CCCI_CONTROL, MD_POWER_CONFIG, MD_CHECK_DONE,
			      0, 0, 0, 0, 0, &res);
		if (!res.a0)
			return md_domain_check(md, true);
		if (res.a0 == (unsigned long)SMCCC_RET_NOT_SUPPORTED)
			return -EOPNOTSUPP;
		msleep(20);
	}
	return -ETIMEDOUT;
}

static int md_handoff_acquire(void *context)
{
	struct ccci_md_platform *md = context;
	int ret;

	ret = md_domain_check(md, true);
	if (ret)
		return ret;
	ret = pm_runtime_resume_and_get(md->domain);
	if (ret < 0)
		return ret;
	/* Hold the runtime reference before lifting the inherited-domain OFF veto. */
	return mt6893_md_domain_allow_off(md->domain);
}

static const struct ccci_md_power_ops md_power_ops = {
	.off_check = md_off_check,
	.rails_check = md_rails_check,
	.clocks = md_clocks,
	.srcclk = md_srcclk,
	.srclken_o1 = md_srclken_o1,
	.flight = md_flight,
	.domain = md_domain,
	.handoff_check = md_handoff_check,
	.handoff_acquire = md_handoff_acquire,
};

static ssize_t md_power_show(struct device *dev, struct device_attribute *attr, char *buf)
{
	static const char * const states[] = { "cold", "powered", "stopped", "lk-on", "fault" };
	struct ccci_md_platform *md = dev_get_drvdata(dev);
	ssize_t ret;

	mutex_lock(&md->lock);
	ret = sysfs_emit(buf,
			 "state=%s step=%s error=%d attempted=%u clocks=%u domain=%u cpu_release_issued=0 rails_uv=%d,%d,%d,%d smem_users=%u\n",
			 states[md->power.state], md->power.step, md->power.error,
			 md->power.attempted, md->power.clocks, md->power.domain,
			 md->voltage[0], md->voltage[1], md->voltage[2], md->voltage[3],
			 md->smem.count);
	mutex_unlock(&md->lock);
	return ret;
}

/*
 * Active boot: reset/join CCIF while clocks are held, prove MD1 OFF, then stop
 * services and SCP. The CCIF stop inside the dispatcher then returns early.
 */
static int md_platform_off(struct ccci_md_platform *md)
{
	u32 r13 = 0;
	int ret;

	if (ccci_md_boot_active(md->boot)) {
		if (!regmap_read(md->spm, SPM_PCM_REG13, &r13))
			ccci_md_boot_note_pcm(md->boot, r13);
		ret = ccci_ccif_stop(md->ccif);
		if (!ret)
			ret = ccci_md_power_off(&md->power);
		if (!ret)
			ret = ccci_md_boot_stop(md->boot, true);
		return ret;
	}
	ret = ccci_md_boot_offline(md->boot);
	if (!ret)
		ret = ccci_nvram_cache_offline(md->cache);
	if (!ret)
		ret = ccci_port_dispatch_offline(md->dispatch);
	if (!ret)
		ret = ccci_service_endpoint_offline(md->services);
	if (!ret)
		ret = ccci_ccism_bridge_offline(md->bridge);
	if (!ret && md->ccif && md->power.state == CCCI_MD_POWERED)
		ret = ccci_ccif_stop(md->ccif);
	if (!ret && md->power.state != CCCI_MD_INHERITED)
		ret = ccci_md_power_off(&md->power);
	if (!ret)
		ret = ccci_nvram_cache_stop(md->cache);
	return ret;
}

static ssize_t md_power_store(struct device *dev, struct device_attribute *attr,
			      const char *buf, size_t count)
{
	struct ccci_md_platform *md = dev_get_drvdata(dev);
	int ret;

	mutex_lock(&md->lock);
	if (sysfs_streq(buf, "on")) {
		ret = ccci_md_power_on(&md->power);
	} else if (sysfs_streq(buf, "takeover")) {
		ret = ccci_md_power_takeover(&md->power);
	} else if (sysfs_streq(buf, "off")) {
		ret = md_platform_off(md);
	} else {
		ret = -EINVAL;
	}
	if (ret)
		dev_err(dev, "MD platform request failed at %s: %d\n", md->power.step, ret);
	mutex_unlock(&md->lock);
	return ret ?: count;
}
static DEVICE_ATTR_RW(md_power);

static ssize_t md_boot_show(struct device *dev, struct device_attribute *attr, char *buf)
{
	struct ccci_md_platform *md = dev_get_drvdata(dev);
	ssize_t ret;

	mutex_lock(&md->lock);
	ret = ccci_md_boot_status(md->boot, buf);
	mutex_unlock(&md->lock);
	return ret;
}

static ssize_t md_boot_store(struct device *dev, struct device_attribute *attr,
			     const char *buf, size_t count)
{
	struct ccci_md_platform *md = dev_get_drvdata(dev);
	enum ccci_runtime_crystal crystal;
	enum ccci_rtc32k_source source;
	u64 generation;
	int ret;

	if (!md->boot)
		return -EOPNOTSUPP;
	mutex_lock(&md->lock);
	if (sscanf(buf, "prepare %llu", &generation) == 1) {
		if (md->power.state != CCCI_MD_POWERED || !md->power.clocks ||
		    !md->power.domain) {
			ret = -EHOSTDOWN;
			goto out;
		}
		ret = ccci_rtc32k_read(dev, &crystal, &source);
		if (!ret)
			dev_info(dev, "MD boot prepare: generation=%llu crystal=%u source=%u\n",
				 generation, crystal, source);
		if (!ret)
			ret = ccci_md_boot_prepare(md->boot, &md->smem, generation, crystal);
	} else if (sysfs_streq(buf, "release")) {
		ret = ccci_md_boot_release(md->boot);
	} else if (sysfs_streq(buf, "stop")) {
		/* Parent must have independently read MD1 OFF. */
		ret = ccci_md_boot_stop(md->boot, md->power.state == CCCI_MD_STOPPED);
	} else {
		ret = -EINVAL;
	}
out:
	mutex_unlock(&md->lock);
	return ret ?: count;
}
static DEVICE_ATTR_RW(md_boot);

static ssize_t ccif_show(struct device *dev, struct device_attribute *attr, char *buf)
{
	struct ccci_md_platform *md = dev_get_drvdata(dev);
	ssize_t ret;

	if (!md->ccif)
		return -EOPNOTSUPP;
	mutex_lock(&md->lock);
	ret = ccci_ccif_status(md->ccif, buf);
	mutex_unlock(&md->lock);
	return ret;
}

static ssize_t ccif_store(struct device *dev, struct device_attribute *attr,
			  const char *buf, size_t count)
{
	struct ccci_md_platform *md = dev_get_drvdata(dev);
	int ret;

	if (!md->ccif)
		return -EOPNOTSUPP;
	if (!sysfs_streq(buf, "prepare"))
		return -EINVAL;
	mutex_lock(&md->lock);
	if (md->power.state != CCCI_MD_POWERED || !md->power.clocks || !md->power.domain) {
		ret = -EHOSTDOWN;
	} else {
		/* The boot owner owns the rings once its one preparation starts. */
		ret = ccci_md_boot_offline(md->boot);
		if (!ret)
			ret = ccci_port_dispatch_offline(md->dispatch);
		if (!ret)
			ret = ccci_service_endpoint_offline(md->services);
		if (!ret)
			ret = ccci_ccism_bridge_offline(md->bridge);
		if (!ret)
			ret = md_domain_check(md, true);
		if (!ret)
			ret = ccci_ccif_prepare(md->ccif);
	}
	mutex_unlock(&md->lock);
	return ret ?: count;
}
static DEVICE_ATTR_RW(ccif);

static ssize_t handshake_show(struct device *dev, struct device_attribute *attr, char *buf)
{
	struct ccci_md_platform *md = dev_get_drvdata(dev);
	ssize_t ret;

	if (!md->ccif)
		return -EOPNOTSUPP;
	mutex_lock(&md->lock);
	ret = ccci_ccif_handshake_status(md->ccif, buf);
	mutex_unlock(&md->lock);
	return ret;
}
static DEVICE_ATTR_RO(handshake);

static ssize_t ccism_show(struct device *dev, struct device_attribute *attr, char *buf)
{
	struct ccci_md_platform *md = dev_get_drvdata(dev);

	if (!md->bridge)
		return -EOPNOTSUPP;
	return ccci_ccism_bridge_status(md->bridge, buf);
}
static DEVICE_ATTR_RO(ccism);

static ssize_t services_show(struct device *dev, struct device_attribute *attr, char *buf)
{
	struct ccci_md_platform *md = dev_get_drvdata(dev);
	ssize_t ret;

	mutex_lock(&md->lock);
	ret = ccci_service_endpoint_status(md->services, buf);
	mutex_unlock(&md->lock);
	return ret;
}
static DEVICE_ATTR_RO(services);

static ssize_t dispatch_show(struct device *dev, struct device_attribute *attr, char *buf)
{
	struct ccci_md_platform *md = dev_get_drvdata(dev);
	ssize_t ret;

	mutex_lock(&md->lock);
	ret = ccci_port_dispatch_status(md->dispatch, buf);
	mutex_unlock(&md->lock);
	return ret;
}
static DEVICE_ATTR_RO(dispatch);

static struct attribute *md_attrs[] = {
	&dev_attr_md_power.attr, &dev_attr_md_boot.attr, &dev_attr_ccif.attr,
	&dev_attr_handshake.attr, &dev_attr_ccism.attr, &dev_attr_services.attr,
	&dev_attr_dispatch.attr, NULL,
};

static const struct attribute_group md_group = { .attrs = md_attrs };

static void md_lookup_release(struct device *dev)
{
	of_node_put(dev->of_node);
	kfree(dev);
}

static int md_attach_domain(struct device *dev, struct ccci_md_platform *md)
{
	struct device_node *node;
	struct device *lookup;
	int ret;

	/* A domain on the platform node would be powered before probe runs. */
	if (of_property_present(dev->of_node, "power-domains"))
		return -EINVAL;
	node = of_get_child_by_name(dev->of_node, "power");
	if (!node)
		return -EINVAL;
	if (!of_device_is_available(node) ||
	    of_count_phandle_with_args(node, "power-domains", "#power-domain-cells") != 1) {
		of_node_put(node);
		return -EINVAL;
	}
	lookup = kzalloc_obj(*lookup);
	if (!lookup) {
		of_node_put(node);
		return -ENOMEM;
	}
	lookup->parent = dev;
	lookup->of_node = node;
	lookup->release = md_lookup_release;
	device_initialize(lookup);
	ret = dev_set_name(lookup, "%s-power", dev_name(dev));
	if (ret)
		goto put;
	ret = device_add(lookup);
	if (ret)
		goto put;
	/* attach_by_id creates a runtime-suspended device WITHOUT powering on. */
	md->domain = dev_pm_domain_attach_by_id(lookup, 0);
	if (IS_ERR_OR_NULL(md->domain)) {
		ret = md->domain ? PTR_ERR(md->domain) : -ENODEV;
		device_unregister(lookup);
		return ret;
	}
	md->lookup = lookup;
	return 0;
put:
	put_device(lookup);
	return ret;
}

int ccci_md_platform_create(struct platform_device *pdev, const struct ccci_smem_layout *layout)
{
	static const char * const supplies[] = { "md-vmodem", "md-vnr", "md-vsram", "md-vdigrf" };
	static const char * const clocks[] = { "ccif-ap", "ccif-md", "ccif1-ap", "ccif1-md" };
	struct device *dev = &pdev->dev;
	struct ccci_md_platform *md;
	int ret;

	md = devm_kzalloc(dev, sizeof(*md), GFP_KERNEL);
	if (!md)
		return -ENOMEM;
	mutex_init(&md->lock);
	md->smem = *layout;
	md->spm = syscon_regmap_lookup_by_phandle(dev->of_node, "mediatek,spm");
	if (IS_ERR(md->spm))
		return PTR_ERR(md->spm);
	md->infra = syscon_regmap_lookup_by_phandle(dev->of_node, "mediatek,infracfg");
	if (IS_ERR(md->infra))
		return PTR_ERR(md->infra);
	for (unsigned int i = 0; i < ARRAY_SIZE(md->rails); i++) {
		md->rails[i] = devm_regulator_get_optional(dev, supplies[i]);
		if (IS_ERR(md->rails[i]))
			return dev_err_probe(dev, PTR_ERR(md->rails[i]),
					     "%s unavailable\n", supplies[i]);
		md->clocks[i].id = clocks[i];
	}
	ret = devm_clk_bulk_get(dev, ARRAY_SIZE(md->clocks), md->clocks);
	if (ret)
		return dev_err_probe(dev, ret, "ordinary CCIF clocks unavailable\n");
	ret = ccci_md_power_init(&md->power, &md_power_ops, md);
	if (ret)
		return ret;
	ret = md_off_check(md);
	if (ret == -EBUSY) {
		ret = md_domain_check(md, true);
		if (!ret) {
			md->power.state = CCCI_MD_INHERITED;
			md->power.step = "lk-on-held";
		}
	}
	if (ret)
		return dev_err_probe(dev, ret, "MD initial state is incomplete\n");
	ret = md_read_rails(md, md->voltage);
	if (!ret)
		ret = md_rails_check(md);
	if (ret)
		return dev_err_probe(dev, ret, "cold rail baseline unavailable/unstable\n");
	if (IS_ENABLED(CONFIG_OP6893_CCCI_CCIF)) {
		md->ccif = ccci_ccif_create(pdev, layout, md->infra);
		if (IS_ERR(md->ccif))
			return dev_err_probe(dev, PTR_ERR(md->ccif), "CCIF reservation failed\n");
	}
	if (IS_ENABLED(CONFIG_OP6893_CCCI_CCISM)) {
		md->bridge = ccci_ccism_bridge_create(pdev, md->ccif, layout);
		if (IS_ERR(md->bridge))
			return dev_err_probe(dev, PTR_ERR(md->bridge),
					     "CCISM reservation failed\n");
	}
	ret = md_attach_domain(dev, md);
	if (ret)
		return dev_err_probe(dev, ret, "MD1 domain attachment failed\n");
	if (IS_ENABLED(CONFIG_OP6893_CCCI_SERVICES)) {
		md->services = ccci_service_endpoint_create(dev, md->ccif);
		if (IS_ERR(md->services)) {
			ret = PTR_ERR(md->services);
			dev_pm_domain_detach(md->domain, false);
			device_unregister(md->lookup);
			return dev_err_probe(dev, ret, "service endpoint unavailable\n");
		}
		if (of_machine_is_compatible("realme,op6893")) {
			ret = ccci_service_endpoint_set_rpc(md->services,
							    ccci_rpc_op6893_provider());
			if (ret) {
				dev_pm_domain_detach(md->domain, false);
				device_unregister(md->lookup);
				return dev_err_probe(dev, ret, "board RPC facts unavailable\n");
			}
		}
	}
	if (IS_ENABLED(CONFIG_OP6893_CCCI_DISPATCH)) {
		md->dispatch = ccci_port_dispatch_create(dev, md->ccif, md->bridge, md->services);
		if (IS_ERR(md->dispatch)) {
			ret = PTR_ERR(md->dispatch);
			dev_pm_domain_detach(md->domain, false);
			device_unregister(md->lookup);
			return dev_err_probe(dev, ret, "port dispatcher unavailable\n");
		}
	}
	if (IS_ENABLED(CONFIG_OP6893_CCCI_NVRAM_CACHE)) {
		md->cache = ccci_nvram_cache_create(dev, &md->smem);
		if (IS_ERR(md->cache)) {
			ret = PTR_ERR(md->cache);
			dev_pm_domain_detach(md->domain, false);
			device_unregister(md->lookup);
			return dev_err_probe(dev, ret, "NVRAM cache geometry unavailable\n");
		}
	}
	if (IS_ENABLED(CONFIG_OP6893_CCCI_MD_BOOT)) {
		md->boot = ccci_md_boot_create(dev, md->ccif, md->dispatch, md->cache);
		if (IS_ERR(md->boot)) {
			ret = PTR_ERR(md->boot);
			dev_pm_domain_detach(md->domain, false);
			device_unregister(md->lookup);
			return dev_err_probe(dev, ret, "MD boot owner unavailable\n");
		}
	}
	platform_set_drvdata(pdev, md);
	ret = devm_device_add_group(dev, &md_group);
	if (ret) {
		platform_set_drvdata(pdev, NULL);
		dev_pm_domain_detach(md->domain, false);
		device_unregister(md->lookup);
		return ret;
	}
	dev_info(dev, "MD owner ready: step=%s, SMEM retained, four rails/clocks and MD1 attached; CPU release not issued\n",
		 md->power.step);
	return 0;
}

void ccci_md_platform_shutdown(struct platform_device *pdev)
{
	struct ccci_md_platform *md = platform_get_drvdata(pdev);
	int ret;

	if (!md)
		return;
	mutex_lock(&md->lock);
	ret = md_platform_off(md);
	if (ret)
		dev_warn(&pdev->dev, "MD shutdown held at %s: %d\n", md->power.step, ret);
	mutex_unlock(&md->lock);
}
