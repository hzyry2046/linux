/* SPDX-License-Identifier: GPL-2.0-only */
#ifndef __CCCI_RUNTIME_H
#define __CCCI_RUNTIME_H

#include <linux/types.h>

#define CCCI_RUNTIME_FEATURES	64
#define CCCI_RUNTIME_HALF	0x800
#define CCCI_RUNTIME_PAYLOAD	64
#define CCCI_RUNTIME_UPLOAD	0xac

struct ccci_smem_layout;

/* Caller declares implemented capabilities, not just reserved memory. */
struct ccci_runtime_offer {
	bool supported;
	u8 version;
	u16 length;
	u8 data[CCCI_RUNTIME_PAYLOAD];
};

struct ccci_runtime_plan {
	u64 ap;
	u32 md;
	u32 noncache_md;
	u32 noncache_size;
	u32 cache_md;
	u32 cache_size;
};

int ccci_runtime_plan(const struct ccci_smem_layout *smem, struct ccci_runtime_plan *plan);
int ccci_runtime_validate(const struct ccci_runtime_offer offers[CCCI_RUNTIME_FEATURES]);
/* Separate input/output storage; valid output spans are cleared before negotiation. */
int ccci_runtime_encode(const u8 query[CCCI_RUNTIME_FEATURES],
			const struct ccci_runtime_offer offers[CCCI_RUNTIME_FEATURES],
			void *output, u32 capacity, u32 *used,
			u8 negotiated[CCCI_RUNTIME_FEATURES], u32 *rejected);
int ccci_runtime_upload(const struct ccci_runtime_plan *plan, void *output, u32 size);

#endif
