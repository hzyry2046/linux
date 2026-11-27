/* SPDX-License-Identifier: GPL-2.0-only */
/*
 * MT6893 (and the closely related MT6885) MMSYS routing.
 *
 * The register offsets and bit values below are not guesses: they come from the
 * MT6885/MT6893 display driver of the vendor kernel for this very device
 * (drivers/gpu/drm/mediatek/mtk_drm_ddp.c, functions mtk_ddp_mout_en_MT6885(),
 * mtk_ddp_sel_in_MT6885(), mtk_ddp_sout_sel_MT6885(), and
 * mtk_ddp_insert_dsc_prim_MT6885()), cross-checked against
 * drivers/misc/mediatek/video/mt6893/dispsys/ddp_reg_mmsys.h.
 *
 * Note that this SoC belongs to the MT6885 display generation, which is *not*
 * register compatible with mt8183/mt8192: the same offsets carry different
 * meanings (e.g. 0x0f4c is OVL2_2L_MOUT_EN on mt8192 but MMSYS_OVL_CON here).
 */

#ifndef __SOC_MEDIATEK_MT6893_MMSYS_H
#define __SOC_MEDIATEK_MT6893_MMSYS_H

/* Register offsets */
#define MT6893_DISP_AAL0_SEL_IN			0x650
#define MT6893_DISP_COLOR0_OUT_SEL_IN		0x658
#define MT6893_DISP_CCORR0_SOUT_SEL		0xeb4
#define MT6893_DISP_RDMA0_SEL_IN		0xf34
#define MT6893_DISP_RDMA0_SOUT_SEL		0xf38
#define MT6893_DISP_RDMA0_RSZ0_SEL_IN		0xf3c
#define MT6893_DISP_RDMA0_RSZ0_SOUT_SEL		0xf40
#define MT6893_DISP_DSC_WRAP_SOUT_SEL		0xf48
#define MT6893_MMSYS_OVL_CON			0xf4c
#define MT6893_DISP_DITHER0_MOUT_EN		0xf50
#define MT6893_DSI0_SEL_IN			0xf54
#define MT6893_DISP_OVL0_BLENDOUT_SOUT_SEL	0xf6c
#define MT6893_DISP_TOVL0_OUT1_SEL_IN		0xf70
#define MT6893_DISP_TOVL0_OUT1_MOUT_EN		0xf74
#define MT6893_DISP_DSI0_DSC_WRAP_SOUT_SEL	0xf80
#define MT6893_DISP_RDMA4_PQ0_MERGE0_SEL_IN	0xf88
#define MT6893_DISP_PQ0_SOUT_SEL		0xff8

/* Bit values */
#define MT6893_MMSYS_OVL0_BLENDOUT_SOUT			BIT(0)
#define MT6893_OVL0_BLENDOUT_SOUT_TO_TOVL0_OUT1		0x1
#define MT6893_TOVL0_OUT1_SEL_IN_FROM_OVL0_BLENDOUT	0x1
#define MT6893_TOVL0_OUT1_MOUT_EN_TO_RDMA0		BIT(0)
#define MT6893_RDMA0_SEL_IN_FROM_TOVL0_OUT1_MOUT	0x0
#define MT6893_RDMA0_SOUT_SEL_TO_RDMA0_RSZ0		0x0
#define MT6893_RDMA0_RSZ0_SEL_IN_FROM_RDMA0_SOUT	0x0
#define MT6893_RDMA0_RSZ0_SOUT_SEL_TO_COLOR0		0x1
#define MT6893_COLOR0_OUT_SEL_IN_FROM_COLOR0		0x0
#define MT6893_CCORR0_SOUT_SEL_TO_AAL0			0x1
#define MT6893_AAL0_SEL_IN_FROM_CCORR0_SOUT		0x1
#define MT6893_DITHER0_MOUT_EN_TO_DSI0			BIT(0)
#define MT6893_DITHER0_MOUT_EN_TO_PQ0_SOUT		BIT(3)
#define MT6893_DSI0_SEL_IN_FROM_DITHER0_MOUT		0x1
#define MT6893_DSI0_SEL_IN_FROM_DSC_WRAP0		0x3
#define MT6893_DSI0_INPUT_FROM_DSC_WRAP0		0x1
#define MT6893_DSI0_INPUT_BYPASS_DSC_WRAP		0x0
#define MT6893_DSC_WRAP_SOUT_TO_DSI0			0x0
#define MT6893_PQ0_SOUT_TO_RDMA4_PQ0_MERGE0_SEL_IN	0x1
#define MT6893_RDMA4_PQ0_MERGE0_SEL_IN_FROM_PQ0		0x1

/*
 * Main display path used by the board: OVL0 -> RDMA0 -> COLOR0 -> CCORR ->
 * AAL0 -> GAMMA -> POSTMASK0 -> DITHER0 -> DSI0.
 *
 * The mainline DRM path walker only knows about component-to-component hops, so
 * the intermediate muxes of this SoC (TOVL0_OUT1 between OVL0 and RDMA0, the
 * RDMA0/RSZ0 mux between RDMA0 and COLOR0, PQ0_SOUT between DITHER0 and the DSC
 * wrap) are expressed as several route entries for the same hop.  Each entry is
 * applied in order, so a hop can program more than one register.
 */
static const struct mtk_mmsys_routes mmsys_mt6893_routing_table[] = {
	/*
	 * OVL0 -> RDMA0.  OVL0's blend output leaves through the TOVL0_OUT1
	 * mux; there is no direct OVL0->RDMA0 gate.
	 */
	MMSYS_ROUTE(OVL, 0, RDMA, 0, MT6893_MMSYS_OVL_CON,
		    MT6893_MMSYS_OVL0_BLENDOUT_SOUT,
		    MT6893_MMSYS_OVL0_BLENDOUT_SOUT),
	/* ...and do not feed OVL0_2L into OVL0 (bit 3 was already clear in LK's
	 * 0x91; keeping the write makes the intent explicit) */
	MMSYS_ROUTE(OVL, 0, RDMA, 0, MT6893_MMSYS_OVL_CON,
		    BIT(3), 0x0),
	/*
	 * Leave the rest of MMSYS_OVL_CON alone.  It read 0x91 on this board and
	 * those extra bits are the *bootloader's* blendout enables: the frame
	 * interrupts show LK displays through OVL0_2L (0x14001000, virq 286 was
	 * taking 3453-5187 interrupts per boot), so clearing them took the
	 * visible picture away - which is exactly what happened when this cleared
	 * bits 4 and 7 (screen went from "LK logo" to fully black).
	 */
	MMSYS_ROUTE(OVL, 0, RDMA, 0, MT6893_DISP_OVL0_BLENDOUT_SOUT_SEL,
		    0x1, MT6893_OVL0_BLENDOUT_SOUT_TO_TOVL0_OUT1),
	MMSYS_ROUTE(OVL, 0, RDMA, 0, MT6893_DISP_TOVL0_OUT1_SEL_IN,
		    0x1, MT6893_TOVL0_OUT1_SEL_IN_FROM_OVL0_BLENDOUT),
	MMSYS_ROUTE(OVL, 0, RDMA, 0, MT6893_DISP_TOVL0_OUT1_MOUT_EN,
		    MT6893_TOVL0_OUT1_MOUT_EN_TO_RDMA0,
		    MT6893_TOVL0_OUT1_MOUT_EN_TO_RDMA0),
	MMSYS_ROUTE(OVL, 0, RDMA, 0, MT6893_DISP_RDMA0_SEL_IN,
		    0x1, MT6893_RDMA0_SEL_IN_FROM_TOVL0_OUT1_MOUT),

	/*
	 * RDMA0 -> COLOR0 goes through the RDMA0_RSZ0 mux (RDMA0 can also feed
	 * DSI0 directly, which is not the path used here).
	 */
	MMSYS_ROUTE(RDMA, 0, COLOR, 0, MT6893_DISP_RDMA0_SOUT_SEL,
		    0x1, MT6893_RDMA0_SOUT_SEL_TO_RDMA0_RSZ0),
	MMSYS_ROUTE(RDMA, 0, COLOR, 0, MT6893_DISP_RDMA0_RSZ0_SEL_IN,
		    0x1, MT6893_RDMA0_RSZ0_SEL_IN_FROM_RDMA0_SOUT),
	MMSYS_ROUTE(RDMA, 0, COLOR, 0, MT6893_DISP_RDMA0_RSZ0_SOUT_SEL,
		    0x3, MT6893_RDMA0_RSZ0_SOUT_SEL_TO_COLOR0),

	/* COLOR0 -> CCORR */
	MMSYS_ROUTE(COLOR, 0, CCORR, , MT6893_DISP_COLOR0_OUT_SEL_IN,
		    0x1, MT6893_COLOR0_OUT_SEL_IN_FROM_COLOR0),

	/* CCORR -> AAL0 (the CCORR -> MDP_AAL detour is not used) */
	MMSYS_ROUTE(CCORR, , AAL, 0, MT6893_DISP_CCORR0_SOUT_SEL,
		    0x1, MT6893_CCORR0_SOUT_SEL_TO_AAL0),
	MMSYS_ROUTE(CCORR, , AAL, 0, MT6893_DISP_AAL0_SEL_IN,
		    0x1, MT6893_AAL0_SEL_IN_FROM_CCORR0_SOUT),

	/*
	 * DITHER0 -> DSI0, uncompressed.  DSI0's input mux has to be moved away
	 * from the DSC wrap explicitly: the bootloader leaves the panel running
	 * with DSC enabled, i.e. with 0xf80 programmed to 1.
	 */
	MMSYS_ROUTE(DITHER, 0, DSI, 0, MT6893_DISP_DITHER0_MOUT_EN,
		    MT6893_DITHER0_MOUT_EN_TO_DSI0,
		    MT6893_DITHER0_MOUT_EN_TO_DSI0),
	/* ...and undo the bootloader's DITHER0 -> PQ0_SOUT (DSC) feed */
	MMSYS_ROUTE(DITHER, 0, DSI, 0, MT6893_DISP_DITHER0_MOUT_EN,
		    MT6893_DITHER0_MOUT_EN_TO_PQ0_SOUT, 0x0),
	MMSYS_ROUTE(DITHER, 0, DSI, 0, MT6893_DSI0_SEL_IN,
		    0x3, MT6893_DSI0_SEL_IN_FROM_DITHER0_MOUT),
	MMSYS_ROUTE(DITHER, 0, DSI, 0, MT6893_DISP_DSI0_DSC_WRAP_SOUT_SEL,
		    0x1, MT6893_DSI0_INPUT_BYPASS_DSC_WRAP),
	MMSYS_ROUTE(DITHER, 0, DSI, 0, MT6893_DISP_DSC_WRAP_SOUT_SEL,
		    0x1, MT6893_DSC_WRAP_SOUT_TO_DSI0),

	/* DITHER0 -> PQ0 -> DSC0 -> DSI0, compressed. */
	MMSYS_ROUTE(DITHER, 0, DSC, 0, MT6893_DISP_DITHER0_MOUT_EN,
		    MT6893_DITHER0_MOUT_EN_TO_DSI0, 0),
	MMSYS_ROUTE(DITHER, 0, DSC, 0, MT6893_DISP_DITHER0_MOUT_EN,
		    MT6893_DITHER0_MOUT_EN_TO_PQ0_SOUT,
		    MT6893_DITHER0_MOUT_EN_TO_PQ0_SOUT),
	MMSYS_ROUTE(DITHER, 0, DSC, 0, MT6893_DISP_PQ0_SOUT_SEL,
		    0x1, MT6893_PQ0_SOUT_TO_RDMA4_PQ0_MERGE0_SEL_IN),
	MMSYS_ROUTE(DITHER, 0, DSC, 0, MT6893_DISP_RDMA4_PQ0_MERGE0_SEL_IN,
		    0x1, MT6893_RDMA4_PQ0_MERGE0_SEL_IN_FROM_PQ0),
	MMSYS_ROUTE(DITHER, 0, DSC, 0, MT6893_DISP_DSI0_DSC_WRAP_SOUT_SEL,
		    0x1, MT6893_DSI0_INPUT_FROM_DSC_WRAP0),
	MMSYS_ROUTE(DSC, 0, DSI, 0, MT6893_DISP_DSC_WRAP_SOUT_SEL,
		    0x1, MT6893_DSC_WRAP_SOUT_TO_DSI0),
	MMSYS_ROUTE(DSC, 0, DSI, 0, MT6893_DSI0_SEL_IN,
		    0x3, MT6893_DSI0_SEL_IN_FROM_DSC_WRAP0),
};

#endif /* __SOC_MEDIATEK_MT6893_MMSYS_H */
