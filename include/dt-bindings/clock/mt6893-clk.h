/* SPDX-License-Identifier: (GPL-2.0-only OR BSD-2-Clause) */
#ifndef _DT_BINDINGS_CLK_MT6893_H
#define _DT_BINDINGS_CLK_MT6893_H

#define CLK_APMIXED_MAINPLL	6
#define CLK_APMIXED_UNIVPLL	7
#define CLK_APMIXED_MMPLL	9
#define CLK_APMIXED_MFGPLL	11

/* Diagnostic clock subset; retain the MT6893 vendor clock indices. */
#define CLK_TOP_MAINPLL_D5_D2	15
#define CLK_TOP_UNIVPLL_D5_D2	35
#define CLK_TOP_UNIVPLL_D5_D4	36
#define CLK_TOP_UNIVPLL_D6_D4	41
#define CLK_TOP_OSC_D4		109
#define CLK_TOP_OSC_D8		110
#define CLK_TOP_OSC_D16		111
#define CLK_TOP_OSC_D10		112
#define CLK_TOP_AXI		117
#define CLK_TOP_SCP		119
#define CLK_TOP_AXI_SEL		189
#define CLK_TOP_DISP_SEL	193
#define CLK_TOP_FPWRAP_ULPOSC	150
#define CLK_TOP_MFG_SEL		210
#define CLK_TOP_PWRAP_ULPOSC_SEL	222
#define CLK_TOP_USB_TOP_SEL	228
#define CLK_TOP_SSUSB_XHCI_SEL	229

#define CLK_IFRAO_PMIC_TMR	0
#define CLK_IFRAO_PMIC_AP		1
#define CLK_IFRAO_THERM		4
#define CLK_IFRAO_CCIF1_AP	28
#define CLK_IFRAO_CCIF1_MD	29
#define CLK_IFRAO_CCIF_AP	33
#define CLK_IFRAO_CCIF_MD	35
#define CLK_IFRAO_CCIF2_AP	68
#define CLK_IFRAO_CCIF2_MD	69
/* DPMAIF data-path gates; same vendor indices as the same-board trees. */
#define CLK_IFRAO_DPMAIF	39
#define CLK_IFRAO_DPMAIF_MAIN	74

#define CLK_INFRA_AO_SSUSB	37
#define CLK_INFRA_AO_SSUSB_XHCI	59

#endif
