/* SPDX-License-Identifier: GPL-2.0-only */
#ifndef __OP6893_FDT_H
#define __OP6893_FDT_H

#include <linux/init.h>

int __init op6893_merge_fdt(void *dst, int size, const void *board,
			    const void *lk);
#endif
