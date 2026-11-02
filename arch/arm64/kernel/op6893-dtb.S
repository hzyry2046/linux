/* SPDX-License-Identifier: GPL-2.0-only */
#include <linux/linkage.h>

	.section .rodata, "a"
	.balign 8
SYM_DATA_START(op6893_dtb)
	.incbin "arch/arm64/kernel/op6893-embed.dtb"
SYM_DATA_END(op6893_dtb)
