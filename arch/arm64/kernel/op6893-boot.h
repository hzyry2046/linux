/* SPDX-License-Identifier: GPL-2.0-only */
#ifndef __OP6893_BOOT_H
#define __OP6893_BOOT_H

#include <linux/init.h>
#include <linux/types.h>

#ifdef CONFIG_ARM64_OP6893_BRINGUP
extern const char op6893_dtb[];
phys_addr_t __init op6893_prepare_fdt(phys_addr_t lk_phys);
void __init op6893_early_console_exit(void);
#else
static inline phys_addr_t op6893_prepare_fdt(phys_addr_t lk_phys)
{
	return lk_phys;
}

static inline void op6893_early_console_exit(void) { }
#endif
#endif
