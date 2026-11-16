// SPDX-License-Identifier: GPL-2.0-only
/* Ordinary CCIF owner: bounded mappings, preparation and explicit receive lifecycle. */
#include <linux/interrupt.h>
#include <linux/io.h>
#include <linux/irq.h>
#include <linux/platform_device.h>
#include <linux/regmap.h>
#include <linux/slab.h>
#include <linux/sysfs.h>

#include "ccci-ccif.h"
#include "ccci-ccif-control.h"
#include "ccci-ccif-hw.h"
#include "ccci-ccif-ring.h"
#include "ccci-ccif-rx.h"
#include "ccci-smem.h"

struct ccci_ccif_bank {
	void __iomem *base;
	u32 size;
};

struct ccci_ccif {
	struct ccci_ccif_rx *rx;
	struct ccci_ccif_controller *control;
	struct regmap *infra;
	void __iomem *ap;
	void __iomem *md;
	struct ccci_ccif_bank bank[CCCI_CCIF_BANKS];
	struct ccci_ccif_layout layout;
	struct ccci_ccif_ring ring[CCCI_CCIF_BANKS][CCCI_CCIF_QUEUES];
	int irq[2];
	const char *step;
	int error;
	bool prepared;
	bool attempted;
};

static int ccif_bank_read(void *context, u32 offset, u32 *value)
{
	struct ccci_ccif_bank *bank = context;

	if ((offset & 3) || offset > bank->size || bank->size - offset < 4)
		return -ERANGE;
	*value = readl(bank->base + offset);
	return 0;
}

static int ccif_bank_write(void *context, u32 offset, u32 value)
{
	struct ccci_ccif_bank *bank = context;

	if ((offset & 3) || offset > bank->size || bank->size - offset < 4)
		return -ERANGE;
	writel(value, bank->base + offset);
	return 0;
}

static int ccif_bank_from(void *context, u32 offset, void *to, u32 size)
{
	struct ccci_ccif_bank *bank = context;

	if (offset > bank->size || size > bank->size - offset)
		return -ERANGE;
	memcpy_fromio(to, bank->base + offset, size);
	return 0;
}

static int ccif_bank_to(void *context, u32 offset, const void *from, u32 size)
{
	struct ccci_ccif_bank *bank = context;

	if (offset > bank->size || size > bank->size - offset)
		return -ERANGE;
	memcpy_toio(bank->base + offset, from, size);
	return 0;
}

static int ccif_bank_zero(void *context, u32 offset, u32 size)
{
	struct ccci_ccif_bank *bank = context;

	if (offset > bank->size || size > bank->size - offset)
		return -ERANGE;
	memset_io(bank->base + offset, 0, size);
	return 0;
}

static void ccif_bank_barrier(void *context, bool publish)
{
	if (publish) {
		/* Complete WC reads and writes before publishing the AP-owned pointer. */
		mb();
	} else {
		/* Observe peer data after sampling its producer/consumer pointer. */
		rmb();
	}
}

static const struct ccci_ccif_ring_ops ccif_ring_ops = {
	.read32 = ccif_bank_read,
	.write32 = ccif_bank_write,
	.copy_from = ccif_bank_from,
	.copy_to = ccif_bank_to,
	.zero = ccif_bank_zero,
	.fence = ccif_bank_barrier,
};

static int ccif_hw_write(void *context, u32 bank, u32 offset, u32 value)
{
	struct ccci_ccif *ccif = context;

	if (!bank) {
		if ((offset != 0x150 && offset != 0x154) || value != BIT(8))
			return -EINVAL;
		return regmap_write(ccif->infra, offset, value);
	}
	if (bank > 2 || offset < 0x100 || offset >= 0x300 || (offset & 3))
		return -EINVAL;
	writel(value, (bank == 1 ? ccif->ap : ccif->md) + offset);
	return 0;
}

static int ccif_hw_read(void *context, u32 bank, u32 offset, u32 *value)
{
	struct ccci_ccif *ccif = context;

	if (bank < 1 || bank > 2 || (offset & 3) ||
	    !((offset >= 0x100 && offset < 0x300) || offset == 4 || offset == 0x10))
		return -EINVAL;
	*value = readl((bank == 1 ? ccif->ap : ccif->md) + offset);
	return 0;
}

static void ccif_hw_barrier(void *context)
{
	/* Order reset/SRAM stores before explicit device readback. */
	mb();
}

static const struct ccci_ccif_hw_ops ccif_hw_ops = {
	.write = ccif_hw_write,
	.read = ccif_hw_read,
	.fence = ccif_hw_barrier,
};

static irqreturn_t ccif_irq(int irq, void *context)
{
	struct ccci_ccif *ccif = context;

	ccci_ccif_rx_interrupt(ccif->rx, irq);
	return IRQ_HANDLED;
}

static void ccif_irq_flags_clear(void *context)
{
	struct ccci_ccif *ccif = context;

	for (u32 i = 0; i < 2; i++)
		irq_clear_status_flags(ccif->irq[i], IRQ_DISABLE_UNLAZY);
}

static bool ccci_ccif_faulted(struct ccci_ccif *ccif)
{
	return ccif->error || ccci_ccif_rx_error(ccif->rx) ||
	       ccci_ccif_control_error(ccif->control);
}

static int ccif_fail(struct ccci_ccif *ccif, int ret)
{
	ccif->error = ret;
	return ret;
}

static int ccif_irqs_masked(struct ccci_ccif *ccif)
{
	bool masked;
	int ret;

	for (u32 i = 0; i < 2; i++) {
		ret = irq_get_irqchip_state(ccif->irq[i], IRQCHIP_STATE_MASKED, &masked);
		if (ret)
			return ret;
		if (!masked)
			return -EBUSY;
	}
	return 0;
}

int ccci_ccif_prepare(struct ccci_ccif *ccif)
{
	int ret;

	if (ccci_ccif_faulted(ccif))
		return -EIO;
	if (ccif->attempted)
		return -EALREADY;
	ret = ccif_irqs_masked(ccif);
	if (ret)
		return ret;
	ccif->attempted = true;
	ccif->step = "format-rings";
	for (u32 bank = 0; bank < CCCI_CCIF_BANKS; bank++) {
		for (u32 q = 0; q < CCCI_CCIF_QUEUES; q++) {
			ret = ccci_ccif_ring_format(&ccif->ring[bank][q]);
			if (!ret)
				ret = ccci_ccif_ring_verify_empty(&ccif->ring[bank][q]);
			if (ret)
				return ccif_fail(ccif, ret);
		}
	}
	ccif->step = "reset-and-sram";
	ret = ccci_ccif_hw_reset(&ccif_hw_ops, ccif, &ccif->layout);
	if (ret)
		return ccif_fail(ccif, ret);
	ccif->prepared = true;
	ccif->step = "prepared-irqs-masked";
	return 0;
}

int ccci_ccif_receive_start(struct ccci_ccif *ccif, ccci_ccif_consume_fn consume, void *context)
{
	int ret;

	if (ccci_ccif_faulted(ccif))
		return -EIO;
	if (!ccif->prepared)
		return -EAGAIN;
	ret = ccif_irqs_masked(ccif);
	if (ret)
		return ret;
	ret = ccci_ccif_rx_start(ccif->rx, consume, context);
	if (!ret)
		ccif->step = "receive-started";
	return ret;
}

int ccci_ccif_handshake_start(struct ccci_ccif *ccif, const struct ccci_runtime_offer *offers,
			      ccci_ccif_consume_fn port, void *context)
{
	int ret;

	if (ccci_ccif_faulted(ccif))
		return -EIO;
	if (!ccif->prepared)
		return -EAGAIN;
	ret = ccif_irqs_masked(ccif);
	if (ret)
		return ret;
	ret = ccci_ccif_control_start(ccif->control, offers, port, context);
	if (!ret)
		ccif->step = "handshake-started";
	return ret;
}

int ccci_ccif_stop(struct ccci_ccif *ccif)
{
	int ret;

	/* Consumer callbacks must never acquire the parent MD owner mutex. */
	ccci_ccif_control_quiesce(ccif->control);
	ccci_ccif_rx_stop(ccif->rx);
	if (ccci_ccif_faulted(ccif))
		return -EIO;
	if (!ccif->prepared)
		return 0;
	ret = ccif_irqs_masked(ccif);
	if (ret)
		return ccif_fail(ccif, ret);
	ccif->step = "stop-reset";
	ret = ccci_ccif_hw_reset(&ccif_hw_ops, ccif, &ccif->layout);
	if (ret)
		return ccif_fail(ccif, ret);
	ccif->prepared = false;
	ccif->step = "stopped-irqs-masked";
	return 0;
}

ssize_t ccci_ccif_status(struct ccci_ccif *ccif, char *buf)
{
	return sysfs_emit(buf,
			  "step=%s error=%d attempted=%u prepared=%u rx_error=%d irq_armed=%u normal_bytes=%u exception_bytes=%u debug_md=%#x debug_size=%u cpu_release_issued=0\n",
			  ccif->step, ccif->error, ccif->attempted, ccif->prepared,
			  ccci_ccif_rx_error(ccif->rx),
			  ccci_ccif_rx_armed(ccif->rx),
			  ccif->layout.used[0], ccif->layout.used[1],
			  ccif->layout.debug_md, ccif->layout.debug_size);
}

ssize_t ccci_ccif_handshake_status(struct ccci_ccif *ccif, char *buf)
{
	return ccci_ccif_control_status(ccif->control, buf);
}

struct ccci_ccif *ccci_ccif_create(struct platform_device *pdev,
				   const struct ccci_smem_layout *smem, struct regmap *infra)
{
	static const char * const names[] = { "ccif-ap", "ccif-md" };
	static const resource_size_t addresses[] = { 0x10209000, 0x1020a000 };
	const struct ccci_smem_region *normal = &smem->users[CCCI_SMEM_CCISM_MCU];
	const struct ccci_smem_region *exception = &smem->users[CCCI_SMEM_CCISM_EXP];
	struct device *dev = &pdev->dev;
	struct ccci_ccif *ccif;
	void __iomem *mapping;
	int ret;

	ccif = devm_kzalloc(dev, sizeof(*ccif), GFP_KERNEL);
	if (!ccif)
		return ERR_PTR(-ENOMEM);
	ccif->infra = infra;
	ccif->step = "reserved";
	ret = ccci_ccif_plan(smem, &ccif->layout);
	if (ret)
		return ERR_PTR(ret);
	for (u32 i = 0; i < 2; i++) {
		struct resource *res = platform_get_resource_byname(pdev, IORESOURCE_MEM, names[i]);

		if (!res || res->start != addresses[i] || resource_size(res) != 0x1000)
			return ERR_PTR(-EINVAL);
		mapping = devm_ioremap_resource(dev, res);
		if (IS_ERR(mapping))
			return ERR_CAST(mapping);
		if (!i)
			ccif->ap = mapping;
		else
			ccif->md = mapping;
		ccif->irq[i] = platform_get_irq(pdev, i);
		if (ccif->irq[i] < 0)
			return ERR_PTR(ccif->irq[i]);
		if (irq_get_trigger_type(ccif->irq[i]) != IRQ_TYPE_LEVEL_HIGH ||
		    (i && ccif->irq[i] == ccif->irq[0]))
			return ERR_PTR(-EINVAL);
		if (!irq_get_irq_data(ccif->irq[i]) ||
		    irqd_to_hwirq(irq_get_irq_data(ccif->irq[i])) != 226 + i)
			return ERR_PTR(-EINVAL);
	}
	/* These adjacent unaligned subregions share a page: map them together WC. */
	if (normal->ap + normal->size != exception->ap ||
	    (u64)normal->size + exception->size > U32_MAX)
		return ERR_PTR(-ERANGE);
	if (!devm_request_mem_region(dev, normal->ap, normal->size + exception->size,
				     dev_name(dev)))
		return ERR_PTR(-EBUSY);
	mapping = devm_ioremap_wc(dev, normal->ap, normal->size + exception->size);
	if (!mapping)
		return ERR_PTR(-ENOMEM);
	ccif->bank[0] = (struct ccci_ccif_bank) { mapping, normal->size };
	ccif->bank[1] = (struct ccci_ccif_bank) { mapping + normal->size, exception->size };
	for (u32 bank = 0; bank < CCCI_CCIF_BANKS; bank++) {
		for (u32 q = 0; q < CCCI_CCIF_QUEUES; q++) {
			ret = ccci_ccif_ring_init(&ccif->ring[bank][q], &ccif_ring_ops,
						  &ccif->bank[bank], &ccif->layout.slots[bank][q],
						  ccif->bank[bank].size);
			if (ret)
				return ERR_PTR(ret);
		}
	}
	ccif->rx = ccci_ccif_rx_create(dev, ccif->ap, ccif->ring[CCCI_CCIF_NORMAL], ccif->irq);
	if (IS_ERR(ccif->rx))
		return ERR_CAST(ccif->rx);
	ccif->control = ccci_ccif_control_create(dev, ccif->ap, ccif->rx, smem);
	if (IS_ERR(ccif->control))
		return ERR_CAST(ccif->control);
	/* Clear after devm_free_irq on failure, since actions unwind in reverse. */
	ret = devm_add_action_or_reset(dev, ccif_irq_flags_clear, ccif);
	if (ret)
		return ERR_PTR(ret);
	for (u32 i = 0; i < 2; i++) {
		irq_set_status_flags(ccif->irq[i], IRQ_DISABLE_UNLAZY);
		ret = devm_request_irq(dev, ccif->irq[i], ccif_irq, IRQF_NO_AUTOEN,
				       names[i], ccif);
		if (ret)
			return ERR_PTR(ret);
	}
	return ccif;
}
