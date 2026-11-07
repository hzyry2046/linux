/* SPDX-License-Identifier: GPL-2.0 */
/* Exported CONN domain power hooks for the vendor conninfra stack. */
#ifndef _OP6893_CONN_H_
#define _OP6893_CONN_H_

int op6893_conn_mtcmos_on(void);
void op6893_conn_mtcmos_off(void);

u32 op6893_crumb(u32 id);
void op6893_crumb_dump(void);
extern u32 op6893_off_skip_mask;

/* crumb id encoding */
#define OP6893_CRUMB_CMD_ON	0x101
#define OP6893_CRUMB_CMD_OFF	0x102
#define OP6893_CRUMB_ON_ENTER	0x103
#define OP6893_CRUMB_ON_EXIT	0x104
#define OP6893_CRUMB_OFF_ENTER	0x105
#define OP6893_CRUMB_OFF_EXIT	0x106
#define OP6893_CRUMB_OFF_CORE_ENTER	0x107
#define OP6893_CRUMB_OFF_CORE_EXIT	0x108
#define OP6893_CRUMB_STEP_BASE	0x200	/* + step*2 (before) / +1 (after) */
#define OP6893_CRUMB_SKIP_BASE	0x300	/* + step */

/* power-off hardware steps (skip-mask bit index) */
enum {
	OP6893_OFF_STEP_RAISE_VOLTAGE = 0, /* consys_hw_raise_voltage */
	OP6893_OFF_STEP_SPM_CTRL = 1,	/* consys_plt_conninfra_on_power_ctrl(0) */
	OP6893_OFF_STEP_PINMUX = 2,	/* set_if_pinmux(0), GPIO MMIO */
	OP6893_OFF_STEP_CLKBUF = 3,	/* consys_plt_clock_buffer_ctrl(0) */
	OP6893_OFF_STEP_PMIC = 4,	/* pmic_mng_common_power_ctrl(0) */
	OP6893_OFF_STEP_WAKEUP = 5,	/* _consys_hw_conninfra_wakeup */
	OP6893_OFF_STEP_SUBSYS_STATUS = 6, /* subsys_status_update(false) */
	OP6893_OFF_STEP_SPI_CFG = 7,	/* spi_master_cfg(next_status) */
	OP6893_OFF_STEP_LOWPOWER = 8,	/* low_power_setting(curr,next) */
	OP6893_OFF_STEP_MAX = 9
};

#endif /* _OP6893_CONN_H_ */
