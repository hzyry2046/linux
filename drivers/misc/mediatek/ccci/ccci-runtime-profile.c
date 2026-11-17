// SPDX-License-Identifier: GPL-2.0-only
/* Typed bootstrap payloads from the validated same-board SMEM layout. */
#include <linux/errno.h>
#include <linux/kernel.h>
#include <linux/string.h>
#include <linux/unaligned.h>

#include "ccci-runtime.h"
#include "ccci-smem.h"

#define EXCEPTION_BYTES (64 * 1024)

static int profile_region(const struct ccci_smem_layout *smem, u32 id, bool cached)
{
	const struct ccci_smem_region *region = &smem->users[id];
	const struct ccci_lk_region *bank = cached ? &smem->cached : &smem->noncached;
	u64 md_base = cached ? smem->cache_md_base :
		0x40000000ULL + (bank->base & 0x1ffffff);

	if (!region->present || region->cached != cached || region->no_map ||
	    (region->ap | region->md | region->size) & 3 ||
	    !ccci_lk_contains(bank, region->ap, region->size) ||
	    region->ap - bank->base != region->offset ||
	    md_base + region->offset != region->md ||
	    (u64)region->md + region->size > 0x100000000ULL)
		return -ERANGE;
	return 0;
}

static void profile_offer(struct ccci_runtime_offer *offer, u16 length, u32 first, u32 second)
{
	offer->supported = true;
	offer->length = length;
	put_unaligned_le32(first, offer->data);
	put_unaligned_le32(second, offer->data + 4);
}

int ccci_runtime_bootstrap(const struct ccci_smem_layout *smem,
			   const struct ccci_runtime_boot *boot,
			   struct ccci_runtime_offer offers[CCCI_RUNTIME_FEATURES])
{
	static const u32 users[] = { 12, CCCI_SMEM_CCISM_MCU, CCCI_SMEM_CCISM_SCP,
				    CCCI_SMEM_CCISM_EXP, CCCI_SMEM_NVRAM };
	static const u32 features[] = { 1, 2, 14, 28, 36 };
	const struct ccci_smem_region *region, *other;
	struct ccci_runtime_plan plan;
	int ret;
	u32 i, j;

	if (!offers)
		return -EINVAL;
	memset(offers, 0, sizeof(*offers) * CCCI_RUNTIME_FEATURES);
	if (!smem || !boot)
		return -EINVAL;
	if (boot->crystal != CCCI_RUNTIME_CRYSTAL_PRESENT &&
	    boot->crystal != CCCI_RUNTIME_CRYSTAL_ABSENT)
		return -ENODATA;
	ret = ccci_runtime_plan(smem, &plan);
	if (ret)
		return ret;
	/* Validate all sources before emitting even the first capability. */
	for (i = 0; i < ARRAY_SIZE(users); i++) {
		ret = profile_region(smem, users[i], users[i] == CCCI_SMEM_NVRAM);
		if (ret)
			return ret;
		region = &smem->users[users[i]];
		if (users[i] == CCCI_SMEM_CCISM_SCP && region->size < 32768)
			return -ERANGE;
		for (j = 0; j < i; j++) {
			other = &smem->users[users[j]];
			if (region->ap < other->ap + other->size &&
			    other->ap < region->ap + region->size)
				return -EINVAL;
		}
	}
	region = &smem->users[12];
	/* Vendor exception feature spans 64 KiB, not just the 2 KiB debug user. */
	if (!ccci_lk_contains(&smem->noncached, region->ap, EXCEPTION_BYTES) ||
	    (u64)region->md + EXCEPTION_BYTES > 0x100000000ULL)
		return -ERANGE;
	for (i = 1; i < ARRAY_SIZE(users); i++) {
		other = &smem->users[users[i]];
		if (region->ap < other->ap + other->size &&
		    other->ap < region->ap + EXCEPTION_BYTES)
			return -EINVAL;
	}
	profile_offer(&offers[0], 16, 0, boot->booting_start_id);
	for (i = 0; i < ARRAY_SIZE(users); i++) {
		region = &smem->users[users[i]];
		profile_offer(&offers[features[i]], 8, region->md,
			      i ? region->size : EXCEPTION_BYTES);
	}
	/* ENABLE_32K_CLK_LESS: support means no external 32 kHz crystal. */
	if (boot->crystal == CCCI_RUNTIME_CRYSTAL_ABSENT)
		profile_offer(&offers[6], 16, 0, 0);
	offers[27].supported = true;
	/* MD_MEM_AP_VIEW_INF: bank0, noncached bank4, cached bank4 as 16B entries. */
	if (smem->bank0.size) {
		u8 *view = offers[38].data;

		put_unaligned_le32(0, view);
		put_unaligned_le32(smem->bank0.size, view + 4);
		put_unaligned_le32(smem->bank0.base, view + 8);
		put_unaligned_le32(smem->bank0.base >> 32, view + 12);
		put_unaligned_le32(plan.noncache_md, view + 16);
		put_unaligned_le32(plan.noncache_size, view + 20);
		put_unaligned_le32(smem->noncached.base, view + 24);
		put_unaligned_le32(smem->noncached.base >> 32, view + 28);
		put_unaligned_le32(plan.cache_md, view + 32);
		put_unaligned_le32(plan.cache_size, view + 36);
		put_unaligned_le32(smem->cached.base, view + 40);
		put_unaligned_le32(smem->cached.base >> 32, view + 44);
		offers[38].supported = true;
		offers[38].length = 48;
	}
	return 0;
}
