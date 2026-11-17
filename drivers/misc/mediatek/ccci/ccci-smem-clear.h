/* SPDX-License-Identifier: GPL-2.0-only */
#ifndef __CCCI_SMEM_CLEAR_H
#define __CCCI_SMEM_CLEAR_H

struct device;
struct ccci_smem_layout;

/*
 * Clear, once per AP boot, the shared-memory users the same-board vendor also
 * clears on the first MD boot. Caller must hold the stopped-only MD boot gate.
 */
int ccci_smem_clear_first(struct device *dev, const struct ccci_smem_layout *smem);

#endif
