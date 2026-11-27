// SPDX-License-Identifier: GPL-2.0-only
/*
 * One-shot ACK 6.6 diagnostic, AI assisted. Read CPU caches and reservation
 * bookkeeping only. No MMIO, TCM, firmware payload, IPI, clock or reset access.
 * Requires an independently verified matching scp.ko build ID before loading.
 */
#define pr_fmt(fmt) "op6893-scp-cache: " fmt

#include <linux/kprobes.h>
#include <linux/module.h>
#include <linux/of.h>
#include <linux/of_reserved_mem.h>
#include <linux/string.h>
#include <linux/uaccess.h>
#include <asm/unaligned.h>

#include "ccci-scp-memory.h"

#include "ack-abi.h"

/*
 * Resolve only the fixed cache symbols below. A disabled, handler-free probe
 * obtains the resolver address without arming a breakpoint. This diagnostic
 * uses a private kernel interface and is not a proposed mainline interface.
 * kallsyms has no CFI entry for this indirect private call; keep that single
 * call isolated. Never call any function obtained from the scp module.
 */
static unsigned long __nocfi cache_symbol(const char *name)
{
	unsigned long (*lookup)(const char *name);
	struct kprobe probe = {
		.symbol_name = "kallsyms_lookup_name",
		.flags = KPROBE_FLAG_DISABLED,
	};
	unsigned long address;
	int ret;

	ret = register_kprobe(&probe);
	if (ret)
		return 0;
	lookup = (void *)probe.addr;
	unregister_kprobe(&probe);
	address = lookup(name);
	return address;
}

static int reservation(const char *path, struct ccci_scp_span *span)
{
	struct device_node *node;
	struct reserved_mem *memory;

	node = of_find_node_by_path(path);
	if (!node)
		return -ENOENT;
	memory = of_reserved_mem_lookup(node);
	if (memory) {
		span->base = memory->base;
		span->size = memory->size;
	}
	of_node_put(node);
	return memory ? 0 : -ENODATA;
}

static void report_span(const char *name, const struct ccci_scp_span *span,
			const struct ccci_scp_span *reserved,
			const struct ccci_scp_span *share)
{
	pr_info("%s bytes=%llu in_static=%u in_share=%u\n", name, span->size,
		ccci_scp_span_allowed(reserved, span),
		ccci_scp_span_allowed(share, span));
}

static bool overlap(const struct ccci_scp_span *a,
		    const struct ccci_scp_span *b)
{
	/* Both inputs are validated u32 spans or trusted bounded reservations. */
	return a->size && b->size && a->base < b->base + b->size &&
	       b->base < a->base + a->size;
}

static int __init observe_init(void)
{
	struct ccci_scp_span reserved = {}, share = {}, mapping = {};
	struct ccci_scp_span cached_share = {}, again_share = {};
	u8 raw[CCCI_SCP_REGION_BYTES], again[CCCI_SCP_REGION_BYTES];
	struct ccci_scp_region region;
	unsigned long header, base, size;
	unsigned int ready_before, ready_after;
	u32 struct_size;
	int static_ret, share_ret, ret;

	static_assert(sizeof(phys_addr_t) == sizeof(u64));
	ready_before = is_scp_ready(SCP_A_ID);
	if (ready_before != 1)
		return -EAGAIN;
	header = cache_symbol("scp:scp_region_info_copy");
	base = cache_symbol("scp:scp_mem_base_phys");
	size = cache_symbol("scp:scp_mem_size");
	if (!header || !base || !size)
		return -ENOENT;
	/* Only ordinary CPU memory; never follow a header-controlled pointer. */
	ret = copy_from_kernel_nofault(raw, (void *)header, sizeof(raw));
	ret |= copy_from_kernel_nofault(&cached_share.base, (void *)base,
				       sizeof(phys_addr_t));
	ret |= copy_from_kernel_nofault(&cached_share.size, (void *)size,
				       sizeof(phys_addr_t));
	if (ret)
		return -EFAULT;
	static_ret = reservation("/reserved-memory/mblock-21-SCP-reserved",
				 &reserved);
	share_ret = reservation("/reserved-memory/reserve-memory-scp_share",
				&share);
	ret = copy_from_kernel_nofault(again, (void *)header, sizeof(again));
	ret |= copy_from_kernel_nofault(&again_share.base, (void *)base,
				       sizeof(phys_addr_t));
	ret |= copy_from_kernel_nofault(&again_share.size, (void *)size,
				       sizeof(phys_addr_t));
	ready_after = is_scp_ready(SCP_A_ID);
	if (ret)
		return -EFAULT;
	if (ready_after != 1 || memcmp(raw, again, sizeof(raw)) ||
	    memcmp(&cached_share, &again_share, sizeof(cached_share)))
		return -EAGAIN;
	/* Repeated samples do not establish a reset generation or live TCM ABI. */
	pr_info("ready_before=%u ready_after=%u cache_samples_equal=1\n",
		ready_before, ready_after);
	struct_size = get_unaligned_le32(raw + 28);
	if (struct_size == CCCI_SCP_REGION_LEGACY_BYTES ||
	    struct_size == CCCI_SCP_REGION_BYTES)
		ret = ccci_scp_decode_region(raw, struct_size, &region);
	else
		ret = -EPROTONOSUPPORT;
	pr_info("cached_struct_size=%u decode_result=%d\n",
		get_unaligned_le32(raw + 28), ret);
	pr_info("static_lookup=%d share_lookup=%d share_cache_equal=%u\n",
		static_ret, share_ret,
		!share_ret && share.base == cached_share.base &&
		share.size == cached_share.size);
	if (!share_ret)
		pr_info("share_base=0x%llx share_bytes=0x%llx\n",
			share.base, share.size);
	if (ret)
		return 0;
	report_span("loader", &region.loader, &reserved, &share);
	report_span("firmware", &region.firmware, &reserved, &share);
	report_span("regdump", &region.regdump, &reserved, &share);
	report_span("dram", &region.dram, &reserved, &share);
	ret = ccci_scp_dram_span(&region, &reserved, &mapping);
	pr_info("dram_mapping_static_result=%d bytes=%llu\n", ret,
		mapping.size);
	if (!ret && mapping.size)
		pr_info("mapping_overlap_loader=%u firmware=%u regdump=%u share=%u\n",
			overlap(&mapping, &region.loader),
			overlap(&mapping, &region.firmware),
			overlap(&mapping, &region.regdump),
			overlap(&mapping, &share));
	pr_info("backup_matches_two_core_formula=%u\n",
		region.dram.size && region.backup_start == region.dram.base +
		(((region.dram.size + 1023) & ~1023ULL) * 2));
	return 0;
}

static void __exit observe_exit(void)
{
}

module_init(observe_init);
module_exit(observe_exit);
MODULE_LICENSE("GPL");
MODULE_DESCRIPTION("One-shot cached SCP metadata observation for ACK 6.6");
