/* SPDX-License-Identifier: (GPL-2.0-only OR BSD-2-Clause) */
#ifndef _DT_BINDINGS_CLK_MT6893_H
#define _DT_BINDINGS_CLK_MT6893_H

#define CLK_APMIXED_MAINPLL	6

/* Diagnostic clock subset; retain the MT6893 vendor clock indices. */
#define CLK_TOP_OSC_D4		109
#define CLK_TOP_OSC_D8		110
#define CLK_TOP_OSC_D16		111
#define CLK_TOP_OSC_D10		112
#define CLK_TOP_AXI		117
#define CLK_TOP_AXI_SEL		189
#define CLK_TOP_FPWRAP_ULPOSC	150
#define CLK_TOP_PWRAP_ULPOSC_SEL	222

#define CLK_IFRAO_PMIC_TMR	0
#define CLK_IFRAO_PMIC_AP		1
#define CLK_IFRAO_THERM		4

#endif
