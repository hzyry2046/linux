// SPDX-License-Identifier: GPL-2.0-only
/* Board-only CONN preflight and explicit common-rail experiment. */

#include <linux/delay.h>
#include <linux/io.h>
#include <linux/iopoll.h>
#include <linux/ktime.h>
#include <linux/module.h>
#include <linux/mutex.h>
#include <linux/soc/mediatek/op6893-conn.h>
#include <linux/of.h>
#include <linux/of_platform.h>
#include <linux/of_reserved_mem.h>
#include <linux/platform_device.h>
#include <linux/pinctrl/consumer.h>
#include <linux/regmap.h>
#include <linux/regulator/consumer.h>
#include <linux/slab.h>
#include <linux/string.h>
#include <linux/sysfs.h>

static const char * const op6893_conn_rails[] = {
	"vs1", "vs2", "vcn13", "vcn18", "vcn33-1", "vcn33-2",
};

static const unsigned int op6893_conn_pmic_regs[] = {
	0x0008, 0x1888, 0x188e, 0x18a6, 0x18a8, 0x18aa, 0x18b4,
	0x1c1c, 0x1c20, 0x1c22, 0x1c28, 0x1c2e, 0x1c32, 0x1c34,
	0x1c3a, 0x202e, 0x1be2, 0x1be6, 0x1c08, 0x1c0c,
};

/* Audited RGU, SYSRAM software-control and HOST_CSR remap words only. */
static const u32 op6893_conn_post_addresses[] = {
	0x18000038, 0x1800003c, 0x18000050, 0x18000054,
	0x18052830, 0x18052834, 0x18052838,
	0x180601c4, 0x180601cc, 0x180601d0,
	0x180601d4, 0x180601d8, 0x180601dc,
};

static const u32 op6893_conn_remap_offsets[] = { 0x1c4, 0x1d4, 0x1d8, 0x1dc };

static const u32 op6893_conn_rgu_offsets[] = { 0x38, 0x3c, 0x50, 0x54 };

/* ADIE reset, RF SPI busy, WB status, then ACK's 36 sleep-command words. */
static const u32 op6893_conn_spi_addresses[] = {
	0x18001900, 0x18004000, 0x18005008,
	0x18005070, 0x18005074, 0x18005078, 0x1800507c,
	0x18005080, 0x18005084, 0x18005088, 0x1800508c,
	0x18005090, 0x18005094, 0x18005098, 0x18005004,
	0x18005010, 0x18005014, 0x18005018, 0x1800501c,
	0x18005020, 0x18005024, 0x18005028, 0x1800502c,
	0x18005030, 0x18005034, 0x18005038, 0x1800503c,
	0x18005040, 0x18005044, 0x18005048, 0x1800504c,
	0x18005050, 0x18005054, 0x18005058, 0x1800505c,
	0x18005060, 0x18005064, 0x18005068, 0x1800506c,
};

struct op6893_conn_spi_setting {
	u32 offset;
	u32 mask;
	u32 value;
	u32 baseline;
};

/* ACK non-BT targets; commit command length last, restore it first. */
static const struct op6893_conn_spi_setting op6893_conn_spi_settings[] = {
	{ 0x70, 0xffffffff, 0xaf40a04, 0xaf40a04 },
	{ 0x74, 0xffffffff, 0xa00090, 0xa00090 },
	{ 0x78, 0xffffffff, 0x9c008c, 0x9c008c },
	{ 0x7c, 0xfff, 0xa08, 0xa08 },
	{ 0x80, 0xfff, 0x94, 0x94 },
	{ 0x84, 0xfff, 0x2c, 0xa00 },
	{ 0x88, 0xffffffff, 0xafc0a0c, 0xafc0a0c },
	{ 0x8c, 0xfff, 0xf0, 0xf0 },
	{ 0x90, 0xfff, 0xf4, 0xf4 },
	{ 0x94, 0xfff, 0xfc, 0xfc },
	{ 0x98, 0xfff, 0xf8, 0xf8 },
	{ 0x10, 0xffff, 0xa03c, 0xa001 },
	{ 0x14, 0xffff, 0xa03c, 0xa002 },
	{ 0x18, 0xffff, 0xaa18, 0xa003 },
	{ 0x1c, 0xffff, 0xaa18, 0xa004 },
	{ 0x20, 0xffff, 0xa0c8, 0xa005 },
	{ 0x24, 0xffff, 0xaa00, 0xa006 },
	{ 0x28, 0xffff, 0xa0b4, 0xa007 },
	{ 0x2c, 0xffff, 0xa34c, 0xa008 },
	{ 0x30, 0xffffffff, 0x0, 0xfffffff1 },
	{ 0x34, 0xffffffff, 0x0, 0xfffffff2 },
	{ 0x38, 0xffffffff, 0x74e0fff5, 0xfffffff3 },
	{ 0x3c, 0xffffffff, 0x76e8fff5, 0xfffffff4 },
	{ 0x40, 0xffffffff, 0x0, 0xfffffff5 },
	{ 0x44, 0xffffffff, 0xffffffff, 0xfffffff6 },
	{ 0x48, 0xffffffff, 0x19, 0xfffffff7 },
	{ 0x4c, 0xffffffff, 0x10400, 0xfffffff8 },
	{ 0x50, 0xffffffff, 0x57400000, 0x1 },
	{ 0x54, 0xffffffff, 0x57400000, 0x2 },
	{ 0x58, 0xffffffff, 0x44e0fff5, 0x3 },
	{ 0x5c, 0xffffffff, 0x44e0fff5, 0x4 },
	{ 0x60, 0xffffffff, 0x1, 0x5 },
	{ 0x64, 0xffffffff, 0x0, 0x6 },
	{ 0x68, 0xffffffff, 0x40019, 0x7 },
	{ 0x6c, 0xffffffff, 0x410440, 0x8 },
	{ 0x4, 0x1f, 0x8, 0xf801 },
};

static bool op6893_conn_emi_valid(u64 base, u64 size)
{
	/* Exact board allocation contract; subtraction avoids end overflow. */
	return size == 0x450000 && !(base & 0xfffff) &&
	       base >= 0x50000000 && base <= 0x90000000 - size;
}

struct op6893_conn_trace {
	u64 time_ns;
	const char *point;
	u32 request;
	u32 status0;
	u32 status1;
	u32 request2;
	u32 status20;
	u32 status21;
	u32 power;
	u32 power2;
	u32 control;
	u32 host;
};

struct op6893_conn {
	struct mutex lock;
	struct regmap *pmic;
	void __iomem *spm;
	void __iomem *infra;
	void __iomem *host;
	struct regulator *rails[ARRAY_SIZE(op6893_conn_rails)];
	bool cycle_allowed;
	bool attempted;
	bool faulted;
	bool parent_votes[2];
	bool rail_refs[2];
	bool dirty[2];
	bool uncertain_enable;
	const char *stage;
	const char *failure_stage;
	int result;
	int cleanup_result;
	u32 mismatch_reg;
	u32 mismatch_value;
	u32 on[2][4];
	struct pinctrl *pins;
	struct pinctrl_state *active_pins;
	struct pinctrl_state *idle_pins;
	struct pinctrl_state *strap_pins[5];
	bool prepare_requested;
	bool adie_requested;
	bool adie_efuse_requested;
	bool adie_pad_cycle_requested;
	bool adie_cfg_requested;
	bool adie_pad_baseline_supported;
	bool adie_pad_dirty;
	bool adie_pad_applied;
	bool adie_pad_restored;
	u32 adie_pad_write_issued;
	bool adie_pad_requested;
	bool adie_pad_started;
	bool adie_pad_complete;
	bool adie_pad_cleared;
	bool adie_pad_matched;
	bool adie_pad_target_match;
	u32 adie_pad_value;
	bool adie_pad_value_valid;
	u32 adie_pad_issued;
	u32 adie_pad_read;
	unsigned int adie_pad_transfers;
	unsigned int adie_pad_busy_count;
	bool adie_cfg_started;
	bool adie_cfg_complete;
	bool adie_cfg_cleared;
	bool adie_cfg_valid;
	u32 adie_cfg_issued;
	u32 adie_cfg_read;
	u32 adie_cfg_matched;
	u32 adie_cfg_target_match;
	u32 adie_cfg_value[6];
	unsigned int adie_cfg_transfers;
	unsigned int adie_cfg_busy_count;
	bool adie_cal_cycle_requested;
	bool adie_cal_started;
	bool adie_cal_complete;
	bool adie_cal_gate_ok;
	u32 adie_cal_write_issued;
	u32 adie_cal_applied;
	u32 adie_cal_restored;
	u32 adie_cal_dirty;
	u32 adie_cal_issued;
	u32 adie_cal_read;
	unsigned int adie_cal_transfers;
	unsigned int adie_cal_busy_count;
	bool adie_ir_cycle_requested;
	bool adie_ir_started;
	bool adie_ir_complete;
	bool adie_ir_gate_ok;
	u32 adie_ir_write_issued;
	u32 adie_ir_applied;
	u32 adie_ir_restored;
	u32 adie_ir_dirty;
	u32 adie_ir_issued;
	u32 adie_ir_read;
	unsigned int adie_ir_transfers;
	unsigned int adie_ir_busy_count;
	bool adie_trim_plan_requested;
	bool adie_trim_plan_complete;
	bool adie_trim_plan_cleared;
	bool adie_trim_vendor_noop;
	bool adie_trim_bounded_noop;
	bool adie_trim_equivalent;
	bool adie_thermal_requested;
	bool adie_thermal_started;
	bool adie_thermal_complete;
	bool adie_thermal_cleared;
	u32 adie_thermal_issued;
	u32 adie_thermal_read;
	u32 adie_thermal_matched;
	unsigned int adie_thermal_transfers;
	unsigned int adie_thermal_busy_count;
	bool adie_efuse_handoff_requested;
	bool adie_efuse_handoff_complete;
	u32 adie_efuse_handoff_issued;
	u32 adie_efuse_handoff_verified;
	u32 adie_efuse_handoff_cleared;
	u32 adie_efuse_handoff_dirty;
	bool adie_efuse_data_requested;
	bool adie_efuse_data_started;
	bool adie_efuse_data_complete;
	bool adie_efuse_data_cleared;
	unsigned int adie_efuse_data_issued;
	unsigned int adie_efuse_data_read;
	unsigned int adie_efuse_data_matched;
	unsigned int adie_efuse_data_transfers;
	unsigned int adie_efuse_data_busy_count;
	u64 adie_efuse_data_start_ns;
	u64 adie_efuse_data_elapsed_ns;
	u64 adie_efuse_data_phase_start_ns;
	u64 adie_efuse_data_phase_budget_ns;
	u64 adie_efuse_data_phase_elapsed_ns;
	unsigned int adie_efuse_data_phase;
	bool adie_efuse_observe;
	bool adie_efuse_stable_cycle;
	bool adie_efuse_observe_stable;
	unsigned int adie_efuse_observed;
	u32 adie_efuse_observe_delta[3];
	bool adie_efuse_pending;
	bool adie_efuse_issued;
	bool adie_efuse_complete;
	bool adie_efuse_busy_seen;
	bool adie_efuse_active;
	bool adie_efuse_spi_busy_seen;
	unsigned int adie_efuse_transfers;
	unsigned int adie_efuse_spi_busy_count;
	unsigned int adie_efuse_polls;
	unsigned int adie_efuse_confirmed;
	u32 adie_efuse_last;
	u32 adie_efuse_changed;
	u64 adie_efuse_start_ns;
	u64 adie_efuse_elapsed_ns;
	bool adie_efuse_ctrl_requested;
	bool adie_efuse_ctrl_active;
	bool adie_efuse_ctrl_busy_seen;
	bool adie_efuse_ctrl_stable;
	unsigned int adie_efuse_ctrl_read;
	unsigned int adie_efuse_ctrl_valid;
	unsigned int adie_efuse_ctrl_busy_mask;
	u32 adie_efuse_ctrl_value[4];
	bool adie_fm_requested;
	bool adie_fm_dirty;
	bool adie_fm_applied;
	bool adie_fm_restored;
	unsigned int adie_fm_issued;
	unsigned int adie_fm_read;
	u32 adie_fm_before;
	u32 adie_fm_target;
	u32 adie_fm_on;
	u32 adie_fm_after;
	u32 adie_fm_thermal[4];
	int adie_fm_cleanup;
	bool adie_route_requested;
	bool adie_route_stable;
	bool adie_route_idle;
	unsigned int adie_route_read;
	u32 adie_route_value[10];
	bool adie_prefix_requested;
	bool adie_prefix_active;
	bool adie_prefix_busy_seen;
	unsigned int adie_prefix_step;
	unsigned int adie_prefix_dirty;
	unsigned int adie_prefix_issued;
	unsigned int adie_prefix_applied;
	unsigned int adie_prefix_restored;
	unsigned int adie_prefix_read;
	unsigned int adie_prefix_busy_mask;
	u32 adie_prefix_before[6];
	u32 adie_prefix_value[6];
	int adie_prefix_cleanup;
	bool adie_config_requested;
	bool adie_config_active;
	bool adie_config_busy_seen;
	bool adie_config_stable;
	unsigned int adie_config_read;
	unsigned int adie_config_valid;
	unsigned int adie_config_busy_mask;
	u32 adie_config_before[8];
	u32 adie_config_value[8];
	bool adie_mailbox_requested;
	bool adie_mailbox_dirty;
	bool adie_mailbox_issued;
	bool adie_mailbox_applied;
	bool adie_mailbox_restored;
	u32 adie_mailbox_on;
	u32 adie_mailbox_after;
	int adie_mailbox_cleanup;
	bool adie_write_requested;
	bool adie_write_active;
	bool adie_write_busy_seen;
	bool adie_write_dirty;
	bool adie_write_applied;
	bool adie_write_restored;
	unsigned int adie_write_step;
	unsigned int adie_write_issued;
	unsigned int adie_write_read;
	unsigned int adie_write_busy_mask;
	u32 adie_write_before[3];
	u32 adie_write_value[3];
	int adie_write_cleanup;
	bool adie_xtal_requested;
	bool adie_xtal_active;
	bool adie_xtal_busy_seen;
	unsigned int adie_xtal_read;
	unsigned int adie_xtal_valid;
	unsigned int adie_xtal_busy_mask;
	u32 adie_xtal_before[2];
	u32 adie_xtal_value[2];
	bool adie_reset_dirty;
	bool adie_addr_dirty;
	bool adie_unsafe;
	bool adie_release_issued;
	bool adie_release_verified;
	bool adie_triggered;
	bool adie_busy_seen;
	bool adie_id_read;
	bool adie_id_valid;
	bool adie_reset_restored;
	bool adie_complete;
	unsigned int adie_polls;
	u32 adie_control;
	u32 adie_busy;
	u32 adie_wb;
	u32 adie_addr_before;
	u32 adie_addr_on;
	u32 adie_addr_after;
	u32 adie_data_before;
	u32 adie_id;
	int adie_cleanup_result;
	bool strap_requested;
	bool strap_dirty;
	bool strap_unsafe;
	bool strap_complete;
	unsigned int strap_selected;
	unsigned int strap_samples;
	u32 strap_adie;
	u32 strap_words[7][8];
	bool domain_allowed;
	bool domain_requested;
	bool csr_requested;
	bool id_requested;
	bool post_requested;
	bool remap_requested;
	unsigned int remap_saved;
	unsigned int remap_applied;
	unsigned int remap_restored;
	u32 remap_dirty;
	u32 remap_before[ARRAY_SIZE(op6893_conn_remap_offsets)];
	u32 remap_target[ARRAY_SIZE(op6893_conn_remap_offsets)];
	u32 remap_on[ARRAY_SIZE(op6893_conn_remap_offsets)];
	u32 remap_after[ARRAY_SIZE(op6893_conn_remap_offsets)];
	int remap_cleanup_result;
	bool rgu_requested;
	unsigned int rgu_saved;
	unsigned int rgu_applied;
	unsigned int rgu_restored;
	u32 rgu_dirty;
	u32 rgu_before[ARRAY_SIZE(op6893_conn_rgu_offsets)];
	u32 rgu_target[ARRAY_SIZE(op6893_conn_rgu_offsets)];
	u32 rgu_on[ARRAY_SIZE(op6893_conn_rgu_offsets)];
	u32 rgu_after[ARRAY_SIZE(op6893_conn_rgu_offsets)];
	int rgu_cleanup_result;
	bool spi_config_requested;
	bool spi_config_unsafe;
	unsigned int spi_config_saved;
	unsigned int spi_config_applied;
	unsigned int spi_config_restored;
	u64 spi_config_dirty;
	u32 spi_config_before[ARRAY_SIZE(op6893_conn_spi_settings)];
	u32 spi_config_target[ARRAY_SIZE(op6893_conn_spi_settings)];
	u32 spi_config_on[ARRAY_SIZE(op6893_conn_spi_settings)];
	u32 spi_config_after[ARRAY_SIZE(op6893_conn_spi_settings)];
	u32 spi_config_adie;
	u32 spi_config_busy;
	u32 spi_config_wb;
	int spi_config_cleanup_result;
	bool sema_requested;
	bool sema_pending;
	bool sema_acquired;
	bool sema_released;
	bool sema_unsafe;
	bool sema_request_issued;
	bool sema_release_issued;
	u32 sema_grant;
	u32 sema_report[3][4];
	unsigned int sema_samples[3];
	unsigned int sema_polls;
	int sema_cleanup_result;
	bool sysram_requested;
	bool sysram_started;
	bool sysram_complete;
	bool sysram_unsafe;
	unsigned int sysram_written;
	unsigned int sysram_verified;
	unsigned int sysram_scanned;
	u32 sysram_bad_offset;
	u32 sysram_adie;
	bool spi_requested;
	unsigned int spi_samples;
	u64 spi_start_ns;
	u64 spi_end_ns;
	u32 spi_words[ARRAY_SIZE(op6893_conn_spi_addresses)];
	unsigned int post_samples;
	u32 post_words[ARRAY_SIZE(op6893_conn_post_addresses)];
	bool emi_valid;
	u64 emi_base;
	u64 emi_size;
	bool clock_reset_requested;
	bool off_ready;
	unsigned int id_samples;
	u32 fresh_clock;
	u32 fresh_timeout;
	u32 fresh_sleep;
	unsigned int csr_samples;
	u32 csr_words[3];
	bool domain_uncertain;
	bool vendor_hold;
	bool vendor_domain_on;
	bool pins_dirty;
	bool id_read;
	u32 hw_version;
	u32 config_id;
	u32 last_status;
	u32 last_status2;
	u32 last_control;
	u32 last_protect;
	u32 last_protect2;
	u32 last_host;
	int domain_cleanup_result;
	u32 access_status;
	u32 access_status2;
	u32 access_control;
	u32 access_protect;
	u32 access_protect2;
	u32 access_host;
	unsigned int trace_count;
	struct op6893_conn_trace trace[8];
};

/* This is only an off-state check, never permission to access dark CONN. */
static bool op6893_conn_is_off(u32 status, u32 status2, u32 control)
{
	return !((status | status2) & BIT(1)) && (control & 0x1f) == 0x12;
}

static ssize_t preflight_show(struct device *dev,
			      struct device_attribute *attr, char *buf)
{
	struct op6893_conn *conn = dev_get_drvdata(dev);
	u32 values[ARRAY_SIZE(op6893_conn_pmic_regs)];
	u32 status, status2, control, rc, protect, protect1, protect2, host;
	u32 end_status, end_status2, end_control;
	int enabled[ARRAY_SIZE(op6893_conn_rails)];
	int voltage[ARRAY_SIZE(op6893_conn_rails)];
	u64 start, end;
	ssize_t len;
	unsigned int i;
	int ret;

	ret = mutex_lock_interruptible(&conn->lock);
	if (ret)
		return ret;
	start = ktime_get_boottime_ns();
	status = readl(conn->spm + 0x16c);
	status2 = readl(conn->spm + 0x170);
	control = readl(conn->spm + 0x304);
	rc = readl(conn->spm + 0x504);
	protect = readl(conn->infra + 0x228);
	protect1 = readl(conn->infra + 0x258);
	protect2 = readl(conn->infra + 0x724);
	host = readl(conn->host);
	for (i = 0; i < ARRAY_SIZE(values); i++) {
		ret = regmap_read(conn->pmic, op6893_conn_pmic_regs[i], &values[i]);
		if (ret)
			goto unlock;
	}
	if (values[0] != 0x5930) {
		ret = -ENODEV;
		goto unlock;
	}
	for (i = 0; i < ARRAY_SIZE(conn->rails); i++) {
		enabled[i] = regulator_is_enabled(conn->rails[i]);
		voltage[i] = regulator_get_voltage(conn->rails[i]);
		if (enabled[i] < 0 || voltage[i] < 0) {
			ret = enabled[i] < 0 ? enabled[i] : voltage[i];
			goto unlock;
		}
	}
	end_status = readl(conn->spm + 0x16c);
	end_status2 = readl(conn->spm + 0x170);
	end_control = readl(conn->spm + 0x304);
	end = ktime_get_boottime_ns();
	len = sysfs_emit(buf, "start_ns=%llu end_ns=%llu sequential=1\n", start, end);
	len += sysfs_emit_at(buf, len,
		"status=%#x status2=%#x control=%#x rc=%#x host=%#x\n",
		status, status2, control, rc, host);
	len += sysfs_emit_at(buf, len, "protect=%#x protect1=%#x protect2=%#x\n",
			     protect, protect1, protect2);
	len += sysfs_emit_at(buf, len, "end_status=%#x end_status2=%#x end_control=%#x\n",
			     end_status, end_status2, end_control);
	len += sysfs_emit_at(buf, len,
		"off_at_both_samples=%u rc_mode=%u legacy_protection_complete=%u\n",
		op6893_conn_is_off(status, status2, control) &&
		op6893_conn_is_off(end_status, end_status2, end_control), !!(rc & BIT(0)),
		(protect & (BIT(13) | BIT(14))) == (BIT(13) | BIT(14)) &&
		!!(protect2 & BIT(2)));
	for (i = 0; i < ARRAY_SIZE(values); i++)
		len += sysfs_emit_at(buf, len, "pmic[%#06x]=%#06x\n",
				     op6893_conn_pmic_regs[i], values[i]);
	for (i = 0; i < ARRAY_SIZE(conn->rails); i++)
		len += sysfs_emit_at(buf, len, "rail=%s enabled=%d nominal_uv=%d\n",
				     op6893_conn_rails[i], enabled[i], voltage[i]);
	len += sysfs_emit_at(buf, len,
		"activation_ready=0 upstream_policy=unresolved dark_conn_access=%s\n",
		conn->id_read ? "guarded-id-read" :
		conn->csr_samples ? "guarded-csr-only" :
		conn->clock_reset_requested ? "guarded-csr-clock-reset" : "none");
	len += sysfs_emit_at(buf, len, "emi_valid=%u base=%#llx size=%#llx\n",
			     conn->emi_valid && op6893_conn_emi_valid(conn->emi_base, conn->emi_size),
			     conn->emi_base, conn->emi_size);
	ret = len;
unlock:
	mutex_unlock(&conn->lock);
	return ret;
}
static DEVICE_ATTR_ADMIN_RO(preflight);

/* All checks are specific to the observed cold-boot baseline, not general PM. */
struct op6893_conn_check {
	u32 reg;
	u32 mask;
	u32 value;
};

static const struct op6893_conn_check op6893_conn_baseline[] = {
	{ 0x0008, 0xffff, 0x5930 },
	{ 0x1808, 0x0001, 0x0001 }, /* VS1 SW enable. */
	{ 0x1828, 0x0001, 0x0001 }, /* VS1 enable monitor. */
	{ 0x1826, 0x007f, 0x0060 }, /* VS1 actual selector. */
	{ 0x1834, 0x007f, 0x0060 }, /* VS1 requested selector. */
	{ 0x1888, 0x0001, 0x0001 },
	{ 0x18a8, 0x0001, 0x0001 },
	{ 0x18a6, 0x007f, 0x002c }, /* VS2 actual selector, not requested. */
	{ 0x18b4, 0x007f, 0x0030 },
	{ 0x188e, 0x007f, 0x002c },
	{ 0x18aa, 0x0fff, 0x0000 }, /* No VS2 voter changes in this experiment. */
	{ 0x202e, 0x070f, 0x0400 }, /* VCN13 selector 4, VOCAL zero. */
	{ 0x1c1c, 0x0003, 0x0000 },
	{ 0x1c20, 0x0001, 0x0000 },
	{ 0x1c22, 0xffff, 0x8000 },
	{ 0x1c28, 0xffff, 0x0000 },
	{ 0x1c2e, 0x0003, 0x0000 },
	{ 0x1c32, 0x0001, 0x0000 },
	{ 0x1c34, 0xffff, 0x8000 },
	{ 0x1c3a, 0xffff, 0x0000 },
	{ 0x1be2, 0x0001, 0x0000 },
	{ 0x1be6, 0x0001, 0x0000 },
	{ 0x1bf4, 0x8000, 0x0000 }, /* VCN33 Wi-Fi aliases must also be off. */
	{ 0x1c08, 0x0001, 0x0000 },
	{ 0x1c0c, 0x0001, 0x0000 },
	{ 0x1c1a, 0x8000, 0x0000 },
};

/* Order is VCN18 then VCN13, matching ACK first common-power enable. */
static const u32 op6893_conn_con[] = { 0x1c2e, 0x1c1c };
static const unsigned int op6893_conn_rail_index[] = { 3, 2 };

static int op6893_conn_domain_off(struct op6893_conn *conn)
{
	if (!op6893_conn_is_off(readl(conn->spm + 0x16c),
				readl(conn->spm + 0x170), readl(conn->spm + 0x304)) ||
	    readl(conn->host) || !(readl(conn->spm + 0x504) & BIT(0)))
		return -EBUSY;
	return 0;
}

static int op6893_conn_check_value(struct op6893_conn *conn, u32 reg, u32 mask, u32 want)
{
	u32 value;
	int ret;

	ret = regmap_read(conn->pmic, reg, &value);
	if (ret)
		return ret;
	if ((value & mask) != want) {
		conn->mismatch_reg = reg;
		conn->mismatch_value = value;
		return -EBUSY;
	}
	return 0;
}

static int op6893_conn_check_baseline(struct op6893_conn *conn)
{
	static const int uv[] = { 2000000, 1400000, 1300000, 1800000, 3500000, 3500000 };
	unsigned int i;
	int ret;

	ret = op6893_conn_domain_off(conn);
	if (ret)
		return ret;
	for (i = 0; i < ARRAY_SIZE(op6893_conn_baseline); i++) {
		const struct op6893_conn_check *check = &op6893_conn_baseline[i];

		ret = op6893_conn_check_value(conn, check->reg, check->mask, check->value);
		if (ret)
			return ret;
	}
	for (i = 0; i < ARRAY_SIZE(conn->rails); i++) {
		ret = regulator_is_enabled(conn->rails[i]);
		if (ret < 0)
			return ret;
		if (!!ret != (i < 2))
			return -EBUSY;
		ret = regulator_get_voltage(conn->rails[i]);
		if (ret < 0)
			return ret;
		if (ret != uv[i])
			return -ERANGE;
	}
	return op6893_conn_domain_off(conn);
}

static int op6893_conn_wait_rail(struct op6893_conn *conn, unsigned int rail, bool on)
{
	u32 value;
	int ret;

	/* Enable monitor acknowledgement only, not electrical power-good. */
	ret = regmap_read_poll_timeout(conn->pmic, op6893_conn_con[rail] + 4,
				       value, !!(value & BIT(0)) == on, 50, 20000);
	if (ret)
		return ret;
	return op6893_conn_check_value(conn, op6893_conn_con[rail], BIT(0), on);
}

static int op6893_conn_restore_rails(struct op6893_conn *conn)
{
	int i, ret;
	u32 con;

	/* Failed enable may have taken effect despite its error: retain supplies. */
	if (conn->uncertain_enable || conn->domain_uncertain || conn->pins_dirty ||
	    conn->remap_dirty || conn->rgu_dirty ||
	    conn->spi_config_dirty || conn->spi_config_unsafe ||
	    conn->sema_pending || conn->sema_unsafe || conn->sysram_unsafe ||
	    conn->strap_dirty || conn->strap_unsafe ||
	    conn->adie_reset_dirty || conn->adie_addr_dirty || conn->adie_write_dirty ||
	    conn->adie_mailbox_dirty || conn->adie_prefix_dirty || conn->adie_fm_dirty ||
	    conn->adie_efuse_pending || conn->adie_unsafe)
		return -EUCLEAN;
	ret = op6893_conn_domain_off(conn);
	if (ret)
		return ret;
	for (i = 1; i >= 0; i--) {
		if (!conn->rail_refs[i])
			continue;
		ret = op6893_conn_domain_off(conn);
		if (ret)
			return ret;
		conn->stage = i ? "disable-vcn13" : "disable-vcn18";
		ret = regulator_disable(conn->rails[op6893_conn_rail_index[i]]);
		if (ret)
			return ret;
		conn->rail_refs[i] = false;
		ret = op6893_conn_wait_rail(conn, i, false);
		if (ret)
			return ret;
	}
	for (i = 1; i >= 0; i--) {
		if (!conn->dirty[i])
			continue;
		ret = op6893_conn_domain_off(conn);
		if (ret)
			return ret;
		conn->stage = i ? "restore-vcn13" : "restore-vcn18";
		con = op6893_conn_con[i];
		ret = regmap_update_bits(conn->pmic, con, BIT(1), 0);
		if (ret)
			return ret;
		/* Clear only newly acquired RC enables, preserving original bit15. */
		ret = regmap_write(conn->pmic, con + 10, 0xf0);
		if (ret)
			return ret;
		ret = op6893_conn_check_value(conn, con, 3, 0);
		if (ret)
			return ret;
		ret = op6893_conn_check_value(conn, con + 6, 0xffff, 0x8000);
		if (ret)
			return ret;
		conn->dirty[i] = false;
	}
	/* Intentionally no regulator_disable on shared parents, even on success. */
	return 0;
}

#include "op6893-conn-domain.h"

static int op6893_conn_cycle(struct op6893_conn *conn)
{
	u32 con;
	unsigned int i, bit, j;
	int ret;

	conn->stage = "baseline";
	ret = op6893_conn_check_baseline(conn);
	if (ret)
		return ret;
	for (i = 0; i < 2; i++) {
		conn->stage = i ? "hold-vs2" : "hold-vs1";
		/* Already-on parents get lifetime votes before any leaf operation. */
		ret = regulator_enable(conn->rails[i]);
		if (ret)
			return ret;
		conn->parent_votes[i] = true;
	}
	conn->stage = "recheck-baseline";
	ret = op6893_conn_check_baseline(conn);
	if (ret)
		return ret;
	for (i = 0; i < 2; i++) {
		conn->stage = i ? "configure-vcn13" : "configure-vcn18";
		con = op6893_conn_con[i];
		conn->dirty[i] = true;
		for (bit = 7; bit >= 4; bit--) {
			ret = regmap_write(conn->pmic, con + 8, BIT(bit));
			if (ret)
				goto cleanup;
		}
		/* ACK's zero writes to OP_CFG_SET are no-ops; baseline requires zero. */
		ret = regmap_update_bits(conn->pmic, con, BIT(1), BIT(1));
		if (ret)
			goto cleanup;
		ret = op6893_conn_check_value(conn, con + 6, 0xffff, 0x80f0);
		if (ret)
			goto cleanup;
		ret = op6893_conn_check_value(conn, con + 12, 0xffff, 0);
		if (ret)
			goto cleanup;
		ret = op6893_conn_domain_off(conn);
		if (ret)
			goto cleanup;
		conn->stage = i ? "enable-vcn13" : "enable-vcn18";
		conn->uncertain_enable = true;
		ret = regulator_enable(conn->rails[op6893_conn_rail_index[i]]);
		if (ret)
			goto cleanup;
		conn->uncertain_enable = false;
		conn->rail_refs[i] = true;
		ret = op6893_conn_wait_rail(conn, i, true);
		if (ret)
			goto cleanup;
	}
	conn->stage = "sample-on";
	for (i = 0; i < 2; i++) {
		static const u32 offsets[] = { 0, 4, 6, 12 };

		for (j = 0; j < ARRAY_SIZE(offsets); j++) {
			ret = regmap_read(conn->pmic, op6893_conn_con[i] + offsets[j],
					  &conn->on[i][j]);
			if (ret)
				goto cleanup;
		}
	}
	if (conn->domain_requested) {
		ret = op6893_conn_domain_cycle(conn);
		if (ret)
			goto cleanup;
	} else {
		usleep_range(1000, 2000);
	}
cleanup:
	if (ret && !conn->failure_stage)
		conn->failure_stage = conn->stage;
	conn->cleanup_result = op6893_conn_restore_rails(conn);
	if (conn->cleanup_result)
		return ret ?: conn->cleanup_result;
	conn->stage = "verify-restored";
	usleep_range(1000, 2000);
	conn->cleanup_result = op6893_conn_check_baseline(conn);
	if (ret || conn->cleanup_result)
		return ret ?: conn->cleanup_result;
	conn->stage = "complete";
	return 0;
}

static ssize_t rail_cycle_show(struct device *dev, struct device_attribute *attr, char *buf)
{
	struct op6893_conn *conn = dev_get_drvdata(dev);
	ssize_t len;
	int ret;

	ret = mutex_lock_interruptible(&conn->lock);
	if (ret)
		return ret;
	len = sysfs_emit(buf,
		"allowed=%u attempted=%u faulted=%u result=%d cleanup_result=%d\n",
		conn->cycle_allowed, conn->attempted, conn->faulted,
		conn->result, conn->cleanup_result);
	len += sysfs_emit_at(buf, len, "stage=%s failure_stage=%s mismatch_reg=%#x value=%#x\n",
			     conn->stage, conn->failure_stage ?: "none",
			     conn->mismatch_reg, conn->mismatch_value);
	len += sysfs_emit_at(buf, len,
		"parent_votes=%u,%u rail_refs=%u,%u dirty=%u,%u uncertain_enable=%u\n",
		conn->parent_votes[0], conn->parent_votes[1], conn->rail_refs[0],
		conn->rail_refs[1], conn->dirty[0], conn->dirty[1], conn->uncertain_enable);
	len += sysfs_emit_at(buf, len,
		"on_vcn18=%#x,%#x,%#x,%#x on_vcn13=%#x,%#x,%#x,%#x\n",
		conn->on[0][0], conn->on[0][1], conn->on[0][2], conn->on[0][3],
		conn->on[1][0], conn->on[1][1], conn->on[1][2], conn->on[1][3]);
	len += sysfs_emit_at(buf, len,
		"domain_allowed=%u requested=%u uncertain=%u pins_dirty=%u id_read=%u hw=%#x cfg=%#x\n",
		conn->domain_allowed, conn->domain_requested, conn->domain_uncertain,
		conn->pins_dirty, conn->id_read, conn->hw_version, conn->config_id);
	len += sysfs_emit_at(buf, len, "domain_cleanup_result=%d\n", conn->domain_cleanup_result);
	len += sysfs_emit_at(buf, len,
		"access_status=%#x status2=%#x control=%#x protect=%#x protect2=%#x host=%#x\n",
		conn->access_status, conn->access_status2, conn->access_control,
		conn->access_protect, conn->access_protect2, conn->access_host);
	len += sysfs_emit_at(buf, len,
		"last_status=%#x status2=%#x control=%#x protect=%#x protect2=%#x host=%#x\n",
		conn->last_status, conn->last_status2, conn->last_control,
		conn->last_protect, conn->last_protect2, conn->last_host);
	len += sysfs_emit_at(buf, len,
		"csr_requested=%u samples=%u clock_raw=%#x sleep_raw=%#x timeout_raw=%#x\n",
		conn->csr_requested, conn->csr_samples, conn->csr_words[0],
		conn->csr_words[1], conn->csr_words[2]);
	len += sysfs_emit_at(buf, len,
		"id_requested=%u clock_reset_requested=%u off_ready=%u id_samples=%u fresh_clock=%#x fresh_timeout=%#x fresh_sleep=%#x\n",
		conn->id_requested, conn->clock_reset_requested, conn->off_ready,
		conn->id_samples, conn->fresh_clock, conn->fresh_timeout, conn->fresh_sleep);
	mutex_unlock(&conn->lock);
	return len;
}

static ssize_t rail_cycle_store(struct device *dev, struct device_attribute *attr,
				const char *buf, size_t count)
{
	struct op6893_conn *conn = dev_get_drvdata(dev);
	int ret;

	if (!sysfs_streq(buf, "rc-cycle") && !sysfs_streq(buf, "domain-cycle") &&
	    !sysfs_streq(buf, "csr-cycle") && !sysfs_streq(buf, "id-cycle") &&
	    !sysfs_streq(buf, "post-id-cycle") && !sysfs_streq(buf, "remap-cycle") &&
	    !sysfs_streq(buf, "rgu-cycle") && !sysfs_streq(buf, "spi-baseline") &&
	    !sysfs_streq(buf, "spi-config-cycle") && !sysfs_streq(buf, "sema-cycle") &&
	    !sysfs_streq(buf, "sysram-cycle") && !sysfs_streq(buf, "strap-cycle") &&
	    !sysfs_streq(buf, "prepare-cycle") && !sysfs_streq(buf, "adie-id-cycle") &&
	    !sysfs_streq(buf, "adie-xtal-cycle") && !sysfs_streq(buf, "adie-write-cycle") &&
	    !sysfs_streq(buf, "adie-mailbox-cycle") &&
	    !sysfs_streq(buf, "adie-config-read") && !sysfs_streq(buf, "adie-config-cycle") &&
	    !sysfs_streq(buf, "adie-route-read") && !sysfs_streq(buf, "adie-fm-cycle") &&
	    !sysfs_streq(buf, "adie-efuse-ctrl-read") && !sysfs_streq(buf, "adie-efuse-cycle") &&
	    !sysfs_streq(buf, "adie-efuse-observe") && !sysfs_streq(buf, "adie-efuse-stable-cycle") &&
	    !sysfs_streq(buf, "adie-efuse-data-read") &&
	    !sysfs_streq(buf, "adie-efuse-handoff-cycle") &&
	    !sysfs_streq(buf, "adie-thermal-read") &&
	    !sysfs_streq(buf, "adie-thermal-plan") &&
	    !sysfs_streq(buf, "adie-pad-read") && !sysfs_streq(buf, "adie-pad-cycle") &&
	    !sysfs_streq(buf, "adie-cfg-read") && !sysfs_streq(buf, "adie-cal-cycle") &&
	    !sysfs_streq(buf, "adie-ir-cycle"))
		return -EINVAL;
	ret = mutex_lock_interruptible(&conn->lock);
	if (ret)
		return ret;
	if (!conn->cycle_allowed) {
		ret = -EOPNOTSUPP;
		goto unlock;
	}
	if (conn->attempted) {
		ret = -EALREADY;
		goto unlock;
	}
	conn->csr_requested = sysfs_streq(buf, "csr-cycle");
	conn->post_requested = sysfs_streq(buf, "post-id-cycle");
	conn->remap_requested = sysfs_streq(buf, "remap-cycle");
	conn->rgu_requested = sysfs_streq(buf, "rgu-cycle");
	conn->spi_requested = sysfs_streq(buf, "spi-baseline");
	conn->spi_config_requested = sysfs_streq(buf, "spi-config-cycle");
	conn->sema_requested = sysfs_streq(buf, "sema-cycle");
	conn->sysram_requested = sysfs_streq(buf, "sysram-cycle");
	conn->strap_requested = sysfs_streq(buf, "strap-cycle");
	conn->adie_pad_cycle_requested = sysfs_streq(buf, "adie-pad-cycle");
	conn->adie_cal_cycle_requested = sysfs_streq(buf, "adie-cal-cycle");
	conn->adie_ir_cycle_requested = sysfs_streq(buf, "adie-ir-cycle");
	conn->adie_cfg_requested = sysfs_streq(buf, "adie-cfg-read") ||
				  conn->adie_cal_cycle_requested || conn->adie_ir_cycle_requested;
	conn->adie_pad_requested = sysfs_streq(buf, "adie-pad-read") ||
				   conn->adie_pad_cycle_requested || conn->adie_cfg_requested;
	conn->adie_trim_plan_requested = sysfs_streq(buf, "adie-thermal-plan") ||
					 conn->adie_pad_requested;
	conn->adie_thermal_requested = sysfs_streq(buf, "adie-thermal-read") ||
				       conn->adie_trim_plan_requested;
	conn->adie_efuse_handoff_requested = sysfs_streq(buf, "adie-efuse-handoff-cycle") ||
					     conn->adie_thermal_requested;
	conn->adie_efuse_data_requested = sysfs_streq(buf, "adie-efuse-data-read") ||
					  conn->adie_efuse_handoff_requested;
	conn->adie_efuse_stable_cycle = sysfs_streq(buf, "adie-efuse-stable-cycle") ||
				       conn->adie_efuse_data_requested;
	conn->adie_efuse_observe = sysfs_streq(buf, "adie-efuse-observe") ||
				 conn->adie_efuse_stable_cycle;
	conn->adie_efuse_requested = sysfs_streq(buf, "adie-efuse-cycle") ||
				     conn->adie_efuse_observe;
	conn->adie_efuse_ctrl_requested = sysfs_streq(buf, "adie-efuse-ctrl-read") ||
					  conn->adie_efuse_requested;
	conn->adie_fm_requested = sysfs_streq(buf, "adie-fm-cycle") ||
				  conn->adie_efuse_ctrl_requested;
	conn->adie_route_requested = sysfs_streq(buf, "adie-route-read") ||
				     conn->adie_fm_requested;
	conn->adie_prefix_requested = sysfs_streq(buf, "adie-config-cycle") ||
				      conn->adie_route_requested;
	conn->adie_config_requested = sysfs_streq(buf, "adie-config-read") ||
				      conn->adie_prefix_requested;
	conn->adie_mailbox_requested = sysfs_streq(buf, "adie-mailbox-cycle") ||
				       conn->adie_prefix_requested;
	conn->adie_write_requested = sysfs_streq(buf, "adie-write-cycle");
	conn->adie_xtal_requested = sysfs_streq(buf, "adie-xtal-cycle") ||
				    conn->adie_write_requested;
	conn->adie_requested = sysfs_streq(buf, "adie-id-cycle") || conn->adie_xtal_requested ||
			       conn->adie_mailbox_requested || conn->adie_config_requested;
	conn->prepare_requested = sysfs_streq(buf, "prepare-cycle") || conn->adie_requested;
	if (conn->prepare_requested) {
		conn->remap_requested = true;
		conn->rgu_requested = true;
		conn->spi_config_requested = true;
		conn->sysram_requested = true;
		conn->strap_requested = true;
		conn->sema_requested = true;
	}
	conn->rgu_requested |= conn->sysram_requested;
	conn->id_requested = conn->post_requested || conn->remap_requested ||
			     conn->rgu_requested || conn->spi_requested || conn->spi_config_requested ||
			     conn->sema_requested || conn->strap_requested || sysfs_streq(buf, "id-cycle");
	if (conn->vendor_hold) {
		ret = -EBUSY;
		goto unlock;
	}
	conn->domain_requested = conn->csr_requested || conn->id_requested ||
				 sysfs_streq(buf, "domain-cycle");
	if (conn->domain_requested && !conn->domain_allowed) {
		ret = -EOPNOTSUPP;
		goto unlock;
	}
	if ((conn->post_requested || conn->remap_requested) && !conn->emi_valid) {
		ret = -EINVAL;
		goto unlock;
	}
	conn->attempted = true;
	ret = op6893_conn_cycle(conn);
	if (conn->adie_efuse_data_requested) {
		/* Erase inherited RDAT diagnostics only after all cleanup has finished. */
		conn->adie_data_before = 0;
		conn->adie_id = 0;
		memzero_explicit(conn->adie_xtal_before, sizeof(conn->adie_xtal_before));
		memzero_explicit(conn->adie_xtal_value, sizeof(conn->adie_xtal_value));
		memzero_explicit(conn->adie_write_before, sizeof(conn->adie_write_before));
		memzero_explicit(conn->adie_write_value, sizeof(conn->adie_write_value));
		memzero_explicit(conn->adie_config_before, sizeof(conn->adie_config_before));
		memzero_explicit(conn->adie_config_value, sizeof(conn->adie_config_value));
		memzero_explicit(conn->adie_prefix_before, sizeof(conn->adie_prefix_before));
		memzero_explicit(conn->adie_prefix_value, sizeof(conn->adie_prefix_value));
		memzero_explicit(conn->adie_efuse_ctrl_value, sizeof(conn->adie_efuse_ctrl_value));
		if (conn->adie_efuse_complete) {
			conn->adie_efuse_last &= 0x63ff00c0;
			conn->adie_efuse_changed &= 0x3f;
		} else {
			conn->adie_efuse_last = 0;
			conn->adie_efuse_changed = 0;
			memzero_explicit(conn->adie_efuse_observe_delta,
					 sizeof(conn->adie_efuse_observe_delta));
		}
	}
	conn->result = ret;
	conn->faulted = ret != 0;
	if (ret && !conn->failure_stage)
		conn->failure_stage = conn->stage;
unlock:
	mutex_unlock(&conn->lock);
	return ret ? ret : (ssize_t)count;
}
static DEVICE_ATTR_ADMIN_RW(rail_cycle);

static ssize_t protection_trace_show(struct device *dev,
				     struct device_attribute *attr, char *buf)
{
	struct op6893_conn *conn = dev_get_drvdata(dev);
	ssize_t len = 0;
	unsigned int i;
	int ret;

	ret = mutex_lock_interruptible(&conn->lock);
	if (ret)
		return ret;
	for (i = 0; i < conn->trace_count; i++) {
		const struct op6893_conn_trace *t = &conn->trace[i];

		len += sysfs_emit_at(buf, len,
			"point=%s ns=%llu request=%#x sta0=%#x sta1=%#x request2=%#x sta20=%#x sta21=%#x power=%#x power2=%#x control=%#x host=%#x\n",
			t->point, t->time_ns, t->request, t->status0, t->status1,
			t->request2, t->status20, t->status21, t->power, t->power2,
			t->control, t->host);
	}
	mutex_unlock(&conn->lock);
	return len;
}
static DEVICE_ATTR_ADMIN_RO(protection_trace);

static ssize_t post_id_show(struct device *dev, struct device_attribute *attr, char *buf)
{
	struct op6893_conn *conn = dev_get_drvdata(dev);
	ssize_t len;
	unsigned int i;
	int ret;

	ret = mutex_lock_interruptible(&conn->lock);
	if (ret)
		return ret;
	len = sysfs_emit(buf, "requested=%u samples=%u emi_valid=%u base=%#llx size=%#llx\n",
			 conn->post_requested, conn->post_samples, conn->emi_valid,
			 conn->emi_base, conn->emi_size);
	for (i = 0; i < conn->post_samples; i++)
		len += sysfs_emit_at(buf, len, "address=%#x value=%#x\n",
				     op6893_conn_post_addresses[i], conn->post_words[i]);
	mutex_unlock(&conn->lock);
	return len;
}
static DEVICE_ATTR_ADMIN_RO(post_id);

static ssize_t remap_status_show(struct device *dev, struct device_attribute *attr, char *buf)
{
	struct op6893_conn *conn = dev_get_drvdata(dev);
	ssize_t len;
	unsigned int i;
	int ret;

	ret = mutex_lock_interruptible(&conn->lock);
	if (ret)
		return ret;
	len = sysfs_emit(buf,
		"requested=%u saved=%u applied=%u restored=%u dirty=%#x cleanup_result=%d\n",
		conn->remap_requested, conn->remap_saved, conn->remap_applied,
		conn->remap_restored, conn->remap_dirty, conn->remap_cleanup_result);
	for (i = 0; i < conn->remap_saved; i++)
		len += sysfs_emit_at(buf, len,
			"offset=%#x before=%#x target=%#x on=%#x after=%#x\n",
			op6893_conn_remap_offsets[i], conn->remap_before[i],
			conn->remap_target[i], conn->remap_on[i], conn->remap_after[i]);
	mutex_unlock(&conn->lock);
	return len;
}
static DEVICE_ATTR_ADMIN_RO(remap_status);

static ssize_t rgu_status_show(struct device *dev, struct device_attribute *attr, char *buf)
{
	struct op6893_conn *conn = dev_get_drvdata(dev);
	ssize_t len;
	unsigned int i;
	int ret;

	ret = mutex_lock_interruptible(&conn->lock);
	if (ret)
		return ret;
	len = sysfs_emit(buf,
		"requested=%u saved=%u applied=%u restored=%u dirty=%#x cleanup_result=%d\n",
		conn->rgu_requested, conn->rgu_saved, conn->rgu_applied,
		conn->rgu_restored, conn->rgu_dirty, conn->rgu_cleanup_result);
	for (i = 0; i < conn->rgu_saved; i++)
		len += sysfs_emit_at(buf, len,
			"offset=%#x before=%#x target=%#x on=%#x after=%#x\n",
			op6893_conn_rgu_offsets[i], conn->rgu_before[i],
			conn->rgu_target[i], conn->rgu_on[i], conn->rgu_after[i]);
	mutex_unlock(&conn->lock);
	return len;
}
static DEVICE_ATTR_ADMIN_RO(rgu_status);

static ssize_t spi_baseline_show(struct device *dev, struct device_attribute *attr, char *buf)
{
	struct op6893_conn *conn = dev_get_drvdata(dev);
	ssize_t len;
	unsigned int i;
	int ret;

	ret = mutex_lock_interruptible(&conn->lock);
	if (ret)
		return ret;
	len = sysfs_emit(buf,
		"requested=%u samples=%u start_ns=%llu end_ns=%llu sequential=1\n",
		conn->spi_requested, conn->spi_samples, conn->spi_start_ns, conn->spi_end_ns);
	for (i = 0; i < conn->spi_samples; i++)
		len += sysfs_emit_at(buf, len, "address=%#x value=%#x\n",
				     op6893_conn_spi_addresses[i], conn->spi_words[i]);
	mutex_unlock(&conn->lock);
	return len;
}
static DEVICE_ATTR_ADMIN_RO(spi_baseline);

static ssize_t spi_config_show(struct device *dev, struct device_attribute *attr, char *buf)
{
	struct op6893_conn *conn = dev_get_drvdata(dev);
	ssize_t len;
	unsigned int i;
	int ret;

	ret = mutex_lock_interruptible(&conn->lock);
	if (ret)
		return ret;
	len = sysfs_emit(buf,
		"requested=%u saved=%u applied=%u restored=%u dirty=%#llx unsafe=%u cleanup_result=%d\n",
		conn->spi_config_requested, conn->spi_config_saved, conn->spi_config_applied,
		conn->spi_config_restored, conn->spi_config_dirty, conn->spi_config_unsafe,
		conn->spi_config_cleanup_result);
	len += sysfs_emit_at(buf, len, "adie=%#x busy=%#x wb=%#x\n",
			     conn->spi_config_adie, conn->spi_config_busy, conn->spi_config_wb);
	for (i = 0; i < conn->spi_config_saved; i++)
		len += sysfs_emit_at(buf, len,
			"offset=%#x before=%#x target=%#x on=%#x after=%#x\n",
			op6893_conn_spi_settings[i].offset, conn->spi_config_before[i],
			conn->spi_config_target[i], conn->spi_config_on[i], conn->spi_config_after[i]);
	mutex_unlock(&conn->lock);
	return len;
}
static DEVICE_ATTR_ADMIN_RO(spi_config);

static ssize_t sema_status_show(struct device *dev, struct device_attribute *attr, char *buf)
{
	struct op6893_conn *conn = dev_get_drvdata(dev);
	ssize_t len;
	unsigned int i;
	int ret;

	ret = mutex_lock_interruptible(&conn->lock);
	if (ret)
		return ret;
	len = sysfs_emit(buf,
		"requested=%u request_issued=%u grant=%#x acquired=%u release_issued=%u released=%u pending=%u unsafe=%u cleanup_result=%d polls=%u\n",
		conn->sema_requested, conn->sema_request_issued, conn->sema_grant,
		conn->sema_acquired, conn->sema_release_issued, conn->sema_released,
		conn->sema_pending, conn->sema_unsafe, conn->sema_cleanup_result, conn->sema_polls);
	for (i = 0; i < 3; i++)
		len += sysfs_emit_at(buf, len, "phase=%u samples=%u m0=%#x m1=%#x m2=%#x m3=%#x\n",
			i, conn->sema_samples[i], conn->sema_report[i][0], conn->sema_report[i][1],
			conn->sema_report[i][2], conn->sema_report[i][3]);
	mutex_unlock(&conn->lock);
	return len;
}
static DEVICE_ATTR_ADMIN_RO(sema_status);

static ssize_t sysram_status_show(struct device *dev, struct device_attribute *attr, char *buf)
{
	struct op6893_conn *conn = dev_get_drvdata(dev);
	ssize_t len;
	int ret;

	ret = mutex_lock_interruptible(&conn->lock);
	if (ret)
		return ret;
	len = sysfs_emit(buf,
		"requested=%u started=%u complete=%u unsafe=%u written=%u verified=%u scanned=%u bad_offset=%#x adie=%#x\n",
		conn->sysram_requested, conn->sysram_started, conn->sysram_complete,
		conn->sysram_unsafe, conn->sysram_written, conn->sysram_verified,
		conn->sysram_scanned, conn->sysram_bad_offset, conn->sysram_adie);
	mutex_unlock(&conn->lock);
	return len;
}
static DEVICE_ATTR_ADMIN_RO(sysram_status);

static ssize_t strap_status_show(struct device *dev, struct device_attribute *attr, char *buf)
{
	struct op6893_conn *conn = dev_get_drvdata(dev);
	unsigned int i;
	ssize_t len;
	int ret;

	ret = mutex_lock_interruptible(&conn->lock);
	if (ret)
		return ret;
	len = sysfs_emit(buf,
		"requested=%u selected=%u samples=%u complete=%u dirty=%u unsafe=%u adie=%#x prepare=%u\n",
		conn->strap_requested, conn->strap_selected, conn->strap_samples,
		conn->strap_complete, conn->strap_dirty, conn->strap_unsafe, conn->strap_adie,
		conn->prepare_requested);
	for (i = 0; i < conn->strap_samples; i++)
		len += sysfs_emit_at(buf, len,
			"phase=%u dir=%#x dout=%#x mode=%#x drive=%#x ies=%#x pd=%#x pu=%#x smt=%#x\n",
			i, conn->strap_words[i][0], conn->strap_words[i][1], conn->strap_words[i][2],
			conn->strap_words[i][3], conn->strap_words[i][4], conn->strap_words[i][5],
			conn->strap_words[i][6], conn->strap_words[i][7]);
	mutex_unlock(&conn->lock);
	return len;
}
static DEVICE_ATTR_ADMIN_RO(strap_status);

static ssize_t adie_status_show(struct device *dev, struct device_attribute *attr, char *buf)
{
	struct op6893_conn *conn = dev_get_drvdata(dev);
	ssize_t len;
	unsigned int i;
	int ret;

	ret = mutex_lock_interruptible(&conn->lock);
	if (ret)
		return ret;
	len = sysfs_emit(buf,
		"requested=%u release_issued=%u release_verified=%u triggered=%u busy_seen=%u polls=%u id_read=%u id_valid=%u reset_restored=%u complete=%u reset_dirty=%u addr_dirty=%u unsafe=%u cleanup_result=%d\n",
		conn->adie_requested, conn->adie_release_issued, conn->adie_release_verified,
		conn->adie_triggered, conn->adie_busy_seen, conn->adie_polls, conn->adie_id_read,
		conn->adie_id_valid, conn->adie_reset_restored, conn->adie_complete,
		conn->adie_reset_dirty, conn->adie_addr_dirty, conn->adie_unsafe,
		conn->adie_cleanup_result);
	if (conn->adie_efuse_data_requested) {
		/* RDAT-derived diagnostics may inherit private words, including on errors. */
		len += sysfs_emit_at(buf, len,
			"private_diagnostics=redacted fm_restored=%u fm_dirty=%u fm_cleanup=%d prefix_restored=%#x prefix_dirty=%#x prefix_cleanup=%d mailbox_restored=%u mailbox_dirty=%u mailbox_cleanup=%d\n",
			conn->adie_fm_restored, conn->adie_fm_dirty, conn->adie_fm_cleanup,
			conn->adie_prefix_restored, conn->adie_prefix_dirty, conn->adie_prefix_cleanup,
			conn->adie_mailbox_restored, conn->adie_mailbox_dirty, conn->adie_mailbox_cleanup);
		mutex_unlock(&conn->lock);
		return len;
	}
	len += sysfs_emit_at(buf, len,
		"control=%#x busy=%#x wb=%#x addr_before=%#x addr_on=%#x addr_after=%#x data_before=%#x id=%#x\n",
		conn->adie_control, conn->adie_busy, conn->adie_wb, conn->adie_addr_before,
		conn->adie_addr_on, conn->adie_addr_after, conn->adie_data_before, conn->adie_id);
	len += sysfs_emit_at(buf, len,
		"xtal_requested=%u xtal_read=%#x xtal_valid=%#x xtal_busy_mask=%#x a18_before=%#x a18=%#x a1c_before=%#x a1c=%#x\n",
		conn->adie_xtal_requested, conn->adie_xtal_read, conn->adie_xtal_valid,
		conn->adie_xtal_busy_mask, conn->adie_xtal_before[0], conn->adie_xtal_value[0],
		conn->adie_xtal_before[1], conn->adie_xtal_value[1]);
	len += sysfs_emit_at(buf, len,
		"write_requested=%u write_step=%u write_issued=%#x write_read=%#x write_busy_mask=%#x write_applied=%u write_restored=%u write_dirty=%u write_cleanup=%d\n",
		conn->adie_write_requested, conn->adie_write_step, conn->adie_write_issued,
		conn->adie_write_read, conn->adie_write_busy_mask, conn->adie_write_applied,
		conn->adie_write_restored, conn->adie_write_dirty, conn->adie_write_cleanup);
	len += sysfs_emit_at(buf, len,
		"apply_before=%#x apply=%#x separator_before=%#x separator=%#x restore_before=%#x restore=%#x\n",
		conn->adie_write_before[0], conn->adie_write_value[0],
		conn->adie_write_before[1], conn->adie_write_value[1],
		conn->adie_write_before[2], conn->adie_write_value[2]);
	len += sysfs_emit_at(buf, len,
		"mailbox_requested=%u mailbox_issued=%u mailbox_applied=%u mailbox_restored=%u mailbox_dirty=%u mailbox_cleanup=%d mailbox_on=%#x mailbox_after=%#x\n",
		conn->adie_mailbox_requested, conn->adie_mailbox_issued,
		conn->adie_mailbox_applied, conn->adie_mailbox_restored,
		conn->adie_mailbox_dirty, conn->adie_mailbox_cleanup,
		conn->adie_mailbox_on, conn->adie_mailbox_after);
	len += sysfs_emit_at(buf, len,
		"config_requested=%u config_read=%#x config_valid=%#x config_busy_mask=%#x config_stable=%u\n",
		conn->adie_config_requested, conn->adie_config_read, conn->adie_config_valid,
		conn->adie_config_busy_mask, conn->adie_config_stable);
	for (i = 0; i < 8; i++)
		len += sysfs_emit_at(buf, len, "config_sample=%u before=%#x value=%#x\n",
				     i, conn->adie_config_before[i], conn->adie_config_value[i]);
	len += sysfs_emit_at(buf, len,
		"prefix_requested=%u prefix_step=%u prefix_issued=%#x prefix_applied=%#x prefix_restored=%#x prefix_dirty=%#x prefix_read=%#x prefix_busy_mask=%#x prefix_cleanup=%d\n",
		conn->adie_prefix_requested, conn->adie_prefix_step, conn->adie_prefix_issued,
		conn->adie_prefix_applied, conn->adie_prefix_restored, conn->adie_prefix_dirty,
		conn->adie_prefix_read, conn->adie_prefix_busy_mask, conn->adie_prefix_cleanup);
	for (i = 0; i < 6; i++) {
		/* The first restore ID read can inherit the control word in RDAT. */
		if (conn->adie_efuse_ctrl_requested && i == 2)
			len += sysfs_emit_at(buf, len,
				"prefix_sample=%u before_masked=%#x value_masked=%#x\n",
				i, conn->adie_prefix_before[i] & 0x63ff00c0,
				conn->adie_prefix_value[i] & 0x63ff00c0);
		else
			len += sysfs_emit_at(buf, len, "prefix_sample=%u before=%#x value=%#x\n",
					     i, conn->adie_prefix_before[i], conn->adie_prefix_value[i]);
	}
	len += sysfs_emit_at(buf, len,
		"route_requested=%u route_read=%#x route_stable=%u route_idle=%u\n",
		conn->adie_route_requested, conn->adie_route_read,
		conn->adie_route_stable, conn->adie_route_idle);
	for (i = 0; i < 10; i++)
		len += sysfs_emit_at(buf, len, "route_sample=%u value=%#x\n",
				     i, conn->adie_route_value[i]);
	len += sysfs_emit_at(buf, len,
		"fm_requested=%u fm_issued=%#x fm_read=%#x fm_applied=%u fm_restored=%u fm_dirty=%u fm_cleanup=%d\n",
		conn->adie_fm_requested, conn->adie_fm_issued, conn->adie_fm_read,
		conn->adie_fm_applied, conn->adie_fm_restored, conn->adie_fm_dirty,
		conn->adie_fm_cleanup);
	len += sysfs_emit_at(buf, len,
		"fm_before=%#x fm_target=%#x fm_on=%#x fm_after=%#x therm_addr=%#x therm_cr1=%#x therm_cal=%#x therm_gpt=%#x\n",
		conn->adie_fm_before, conn->adie_fm_target, conn->adie_fm_on,
		conn->adie_fm_after, conn->adie_fm_thermal[0], conn->adie_fm_thermal[1],
		conn->adie_fm_thermal[2], conn->adie_fm_thermal[3]);
	/* Only documented control fields: no raw efuse/calibration data. */
	len += sysfs_emit_at(buf, len,
		"efuse_ctrl_requested=%u efuse_ctrl_read=%#x efuse_ctrl_valid=%#x efuse_ctrl_busy_mask=%#x efuse_ctrl_stable=%u efuse_ctrl_flags0=%#x efuse_ctrl_flags1=%#x\n",
		conn->adie_efuse_ctrl_requested, conn->adie_efuse_ctrl_read,
		conn->adie_efuse_ctrl_valid, conn->adie_efuse_ctrl_busy_mask,
		conn->adie_efuse_ctrl_stable, conn->adie_efuse_ctrl_value[1] & 0x63ff00c0,
		conn->adie_efuse_ctrl_value[3] & 0x63ff00c0);
	mutex_unlock(&conn->lock);
	return len;
}
static DEVICE_ATTR_ADMIN_RO(adie_status);

static ssize_t efuse_status_show(struct device *dev, struct device_attribute *attr, char *buf)
{
	struct op6893_conn *conn = dev_get_drvdata(dev);
	bool public_control;
	ssize_t len;
	int ret;

	ret = mutex_lock_interruptible(&conn->lock);
	if (ret)
		return ret;
	public_control = !conn->adie_efuse_data_requested || conn->adie_efuse_complete;
	len = sysfs_emit(buf,
		"requested=%u issued=%u pending=%u complete=%u engine_busy_seen=%u transfers=%u spi_busy_count=%u polls=%u confirmed=%u flags=%#x elapsed_ns=%llu changed=%#x\n",
		conn->adie_efuse_requested, conn->adie_efuse_issued, conn->adie_efuse_pending,
		conn->adie_efuse_complete, conn->adie_efuse_busy_seen, conn->adie_efuse_transfers,
		conn->adie_efuse_spi_busy_count, conn->adie_efuse_polls,
		conn->adie_efuse_confirmed, public_control ? conn->adie_efuse_last & 0x63ff00c0 : 0,
		(unsigned long long)conn->adie_efuse_elapsed_ns,
		public_control ? conn->adie_efuse_changed : 0);
	len += sysfs_emit_at(buf, len,
		"observe=%u observed=%u stable=%u delta0=%#x delta1=%#x delta2=%#x\n",
		conn->adie_efuse_observe, conn->adie_efuse_observed,
		conn->adie_efuse_observe_stable,
		public_control ? conn->adie_efuse_observe_delta[0] : 0,
		public_control ? conn->adie_efuse_observe_delta[1] : 0,
		public_control ? conn->adie_efuse_observe_delta[2] : 0);
	len += sysfs_emit_at(buf, len, "stable_cycle=%u\n", conn->adie_efuse_stable_cycle);
	len += sysfs_emit_at(buf, len,
		"data_requested=%u data_started=%u data_complete=%u data_cleared=%u data_issued=%#x data_read=%#x data_matched=%#x data_transfers=%u data_busy_count=%u data_elapsed_ns=%llu data_phase=%u phase_elapsed_ns=%llu\n",
		conn->adie_efuse_data_requested, conn->adie_efuse_data_started,
		conn->adie_efuse_data_complete, conn->adie_efuse_data_cleared,
		conn->adie_efuse_data_issued, conn->adie_efuse_data_read,
		conn->adie_efuse_data_matched, conn->adie_efuse_data_transfers,
		conn->adie_efuse_data_busy_count, (unsigned long long)conn->adie_efuse_data_elapsed_ns,
		conn->adie_efuse_data_phase,
		(unsigned long long)conn->adie_efuse_data_phase_elapsed_ns);
	len += sysfs_emit_at(buf, len,
		"handoff_requested=%u handoff_complete=%u handoff_issued=%#x handoff_verified=%#x handoff_cleared=%#x handoff_dirty=%#x\n",
		conn->adie_efuse_handoff_requested, conn->adie_efuse_handoff_complete,
		conn->adie_efuse_handoff_issued, conn->adie_efuse_handoff_verified,
		conn->adie_efuse_handoff_cleared, conn->adie_efuse_handoff_dirty);
	len += sysfs_emit_at(buf, len,
		"thermal_requested=%u thermal_started=%u thermal_complete=%u thermal_cleared=%u thermal_issued=%#x thermal_read=%#x thermal_matched=%#x thermal_transfers=%u thermal_busy_count=%u\n",
		conn->adie_thermal_requested, conn->adie_thermal_started,
		conn->adie_thermal_complete, conn->adie_thermal_cleared,
		conn->adie_thermal_issued, conn->adie_thermal_read, conn->adie_thermal_matched,
		conn->adie_thermal_transfers, conn->adie_thermal_busy_count);
	len += sysfs_emit_at(buf, len,
		"plan_requested=%u plan_complete=%u plan_cleared=%u vendor_noop=%u bounded_noop=%u policies_equivalent=%u\n",
		conn->adie_trim_plan_requested, conn->adie_trim_plan_complete,
		conn->adie_trim_plan_cleared,
		conn->adie_trim_plan_complete && conn->adie_trim_vendor_noop,
		conn->adie_trim_plan_complete && conn->adie_trim_bounded_noop,
		conn->adie_trim_plan_complete && conn->adie_trim_equivalent);
	len += sysfs_emit_at(buf, len,
		"pad_requested=%u pad_started=%u pad_complete=%u pad_cleared=%u pad_issued=%#x pad_read=%#x pad_matched=%u pad_target_match=%u pad_transfers=%u pad_busy_count=%u pad_value_valid=%u pad_value=%#x\n",
		conn->adie_pad_requested, conn->adie_pad_started,
		conn->adie_pad_complete, conn->adie_pad_cleared,
		conn->adie_pad_issued, conn->adie_pad_read, conn->adie_pad_matched,
		conn->adie_pad_complete && conn->adie_pad_target_match,
		conn->adie_pad_transfers, conn->adie_pad_busy_count,
		conn->adie_pad_value_valid,
		conn->adie_pad_value_valid ? conn->adie_pad_value : 0);
	len += sysfs_emit_at(buf, len,
		"pad_cycle_requested=%u pad_baseline_supported=%u pad_write_issued=%#x pad_applied=%u pad_restored=%u pad_dirty=%u\n",
		conn->adie_pad_cycle_requested, conn->adie_pad_baseline_supported,
		conn->adie_pad_write_issued, conn->adie_pad_applied,
		conn->adie_pad_restored, conn->adie_pad_dirty);
	/* TOP380/384/390/394/A18/A1C are vendor-fixed whole-word config constants, not efuse/calibration. */
	len += sysfs_emit_at(buf, len,
		"cfg_requested=%u cfg_started=%u cfg_complete=%u cfg_cleared=%u cfg_issued=%#x cfg_read=%#x cfg_matched=%#x cfg_target_match=%#x cfg_transfers=%u cfg_busy_count=%u cfg_valid=%u top380=%#x top384=%#x top390=%#x top394=%#x topa18=%#x topa1c=%#x\n",
		conn->adie_cfg_requested, conn->adie_cfg_started,
		conn->adie_cfg_complete, conn->adie_cfg_cleared,
		conn->adie_cfg_issued, conn->adie_cfg_read, conn->adie_cfg_matched,
		conn->adie_cfg_target_match, conn->adie_cfg_transfers,
		conn->adie_cfg_busy_count, conn->adie_cfg_valid,
		conn->adie_cfg_valid ? conn->adie_cfg_value[0] : 0,
		conn->adie_cfg_valid ? conn->adie_cfg_value[1] : 0,
		conn->adie_cfg_valid ? conn->adie_cfg_value[2] : 0,
		conn->adie_cfg_valid ? conn->adie_cfg_value[3] : 0,
		conn->adie_cfg_valid ? conn->adie_cfg_value[4] : 0,
		conn->adie_cfg_valid ? conn->adie_cfg_value[5] : 0);
	len += sysfs_emit_at(buf, len,
		"cal_requested=%u cal_started=%u cal_complete=%u cal_gate_ok=%u cal_write_issued=%#x cal_applied=%#x cal_restored=%#x cal_dirty=%#x cal_transfers=%u cal_busy_count=%u\n",
		conn->adie_cal_cycle_requested, conn->adie_cal_started,
		conn->adie_cal_complete, conn->adie_cal_gate_ok,
		conn->adie_cal_write_issued, conn->adie_cal_applied,
		conn->adie_cal_restored, conn->adie_cal_dirty,
		conn->adie_cal_transfers, conn->adie_cal_busy_count);
	len += sysfs_emit_at(buf, len,
		"ir_requested=%u ir_started=%u ir_complete=%u ir_gate_ok=%u ir_write_issued=%#x ir_applied=%#x ir_restored=%#x ir_dirty=%#x ir_transfers=%u ir_busy_count=%u\n",
		conn->adie_ir_cycle_requested, conn->adie_ir_started,
		conn->adie_ir_complete, conn->adie_ir_gate_ok,
		conn->adie_ir_write_issued, conn->adie_ir_applied,
		conn->adie_ir_restored, conn->adie_ir_dirty,
		conn->adie_ir_transfers, conn->adie_ir_busy_count);
	mutex_unlock(&conn->lock);
	return len;
}
static DEVICE_ATTR_ADMIN_RO(efuse_status);

int op6893_conn_mtcmos_on(void);
void op6893_conn_mtcmos_off(void);

/* Reset-surviving breadcrumb ring for the power-off bisection. */
#define OP6893_CRUMB_ADDR	0x48180000
#define OP6893_CRUMB_MAGIC	0x43524d42
#define OP6893_CRUMB_SLOTS	64
#define OP6893_CRUMB_STRIDE	24

static void __iomem *op6893_crumb_base;
static u32 op6893_crumb_idx;
static u32 op6893_crumb_seq;
static char *op6893_crumb_prev;
static size_t op6893_crumb_prev_len;
u32 op6893_off_skip_mask = BIT(4);

static ssize_t op6893_crumb_format(const void __iomem *base, u32 count, char *buf)
{
	size_t len = 0;
	unsigned int i, n = min(count, (u32)OP6893_CRUMB_SLOTS);

	for (i = 0; i < n; i++) {
		const void __iomem *slot = base + 16 + i * OP6893_CRUMB_STRIDE;

		if (readl(slot) != OP6893_CRUMB_MAGIC)
			continue;
		len += sysfs_emit_at(buf, len, "%u seq=%u id=%#x ns=%llu\n", i,
			readl(slot + 4), readl(slot + 8),
			((u64)readl(slot + 16) << 32) | readl(slot + 12));
	}
	return len;
}

static ssize_t crumbs_cur_show(struct device *dev,
			       struct device_attribute *attr, char *buf)
{
	if (!op6893_crumb_base)
		return 0;
	return op6893_crumb_format(op6893_crumb_base, op6893_crumb_idx, buf);
}
static DEVICE_ATTR_ADMIN_RO(crumbs_cur);

static ssize_t crumbs_prev_show(struct device *dev,
				struct device_attribute *attr, char *buf)
{
	if (!op6893_crumb_prev_len)
		return 0;
	memcpy(buf, op6893_crumb_prev, op6893_crumb_prev_len);
	return op6893_crumb_prev_len;
}
static DEVICE_ATTR_ADMIN_RO(crumbs_prev);

static struct attribute *op6893_conn_attrs[] = {
	&dev_attr_preflight.attr,
	&dev_attr_rail_cycle.attr,
	&dev_attr_protection_trace.attr,
	&dev_attr_post_id.attr,
	&dev_attr_remap_status.attr,
	&dev_attr_rgu_status.attr,
	&dev_attr_spi_baseline.attr,
	&dev_attr_spi_config.attr,
	&dev_attr_sema_status.attr,
	&dev_attr_sysram_status.attr,
	&dev_attr_strap_status.attr,
	&dev_attr_adie_status.attr,
	&dev_attr_efuse_status.attr,
	&dev_attr_crumbs_cur.attr,
	&dev_attr_crumbs_prev.attr,
	NULL,
};

static void op6893_crumb_init(void)
{
	char *dump;
	size_t len;

	op6893_crumb_base = ioremap(OP6893_CRUMB_ADDR, 0x1000);
	if (!op6893_crumb_base)
		return;
	if (readl_relaxed(op6893_crumb_base) == OP6893_CRUMB_MAGIC) {
		dump = kzalloc(PAGE_SIZE, GFP_KERNEL);
		if (dump) {
			len = op6893_crumb_format(op6893_crumb_base,
						  readl_relaxed(op6893_crumb_base + 4),
						  dump);
			op6893_crumb_prev = dump;
			op6893_crumb_prev_len = len;
		}
		op6893_crumb_seq = readl_relaxed(op6893_crumb_base + 8) + 1;
	} else {
		op6893_crumb_seq = 1;
	}
	memset_io(op6893_crumb_base, 0, 0x1000);
	writel_relaxed(OP6893_CRUMB_MAGIC, op6893_crumb_base);
	writel_relaxed(0, op6893_crumb_base + 4);
	writel_relaxed(op6893_crumb_seq, op6893_crumb_base + 8);
	dsb(sy);
}


u32 op6893_crumb(u32 id)
{
	void __iomem *slot;
	u64 ns;

	if (!op6893_crumb_base)
		return id;
	slot = op6893_crumb_base + 16 +
	       (op6893_crumb_idx & (OP6893_CRUMB_SLOTS - 1)) * OP6893_CRUMB_STRIDE;
	ns = ktime_get_ns();
	writel_relaxed(OP6893_CRUMB_MAGIC, slot);
	writel_relaxed(op6893_crumb_seq, slot + 4);
	writel_relaxed(id, slot + 8);
	writel_relaxed((u32)ns, slot + 12);
	writel_relaxed((u32)(ns >> 32), slot + 16);
	writel_relaxed(++op6893_crumb_idx, op6893_crumb_base + 4);
	dsb(sy);
	return id;
}

void op6893_crumb_dump(void)
{
	unsigned int i, n;

	if (!op6893_crumb_base)
		return;
	n = min(op6893_crumb_idx, (u32)OP6893_CRUMB_SLOTS);
	for (i = 0; i < n; i++) {
		void __iomem *slot = op6893_crumb_base + 16 + i * OP6893_CRUMB_STRIDE;

		if (readl_relaxed(slot) != OP6893_CRUMB_MAGIC)
			continue;
		pr_info("crumb %u seq=%u id=%#x ns=%llu\n", i,
			readl_relaxed(slot + 4), readl_relaxed(slot + 8),
			((u64)readl_relaxed(slot + 16) << 32) | readl_relaxed(slot + 12));
	}
}


static struct op6893_conn *op6893_vendor_conn __attribute__((unused));

/*
 * Domain-only CONN power for the vendor conninfra stack. Reuses the exact
 * rail_cycle SPM/protection sequence; mutex + refcount serialise it and the
 * preflight experiment is excluded in both directions.
 */



ATTRIBUTE_GROUPS(op6893_conn);

static unsigned int op6893_mtcmos_refs;

static int op6893_mtcmos_poll(void __iomem *addr, u32 mask, u32 expected)
{
	unsigned int tries = 400;

	while (tries--) {
		if ((readl(addr) & mask) == expected)
			return 0;
		udelay(50);
	}
	return -ETIMEDOUT;
}

static int op6893_mtcmos_power_ack(bool on)
{
	unsigned int tries = 400;

	while (tries--) {
		u32 v = readl(op6893_vendor_conn->spm + 0x16c);
		u32 v2 = readl(op6893_vendor_conn->spm + 0x170);

		if ((!!(v & BIT(1))) == on && (!!(v2 & BIT(1))) == on)
			return 0;
		udelay(50);
	}
	return -ETIMEDOUT;
}

static int op6893_mtcmos_control(u32 set, u32 clear)
{
	void __iomem *spm = op6893_vendor_conn->spm;
	u32 value = (readl(spm + 0x304) | set) & ~clear;

	writel(value, spm + 0x304);
	return readl(spm + 0x304) == value ? 0 : -EIO;
}

static int op6893_mtcmos_protect(u32 alias, u32 status, u32 mask, bool enable)
{
	void __iomem *infra = op6893_vendor_conn->infra;

	writel(mask, infra + alias);
	return op6893_mtcmos_poll(infra + status, mask, enable ? mask : 0);
}

int op6893_conn_mtcmos_on(void)
{
	struct op6893_conn *conn = op6893_vendor_conn;
	void __iomem *spm, *host;
	int ret;

	if (!conn || !conn->spm || !conn->infra || !conn->host)
		return -ENODEV;
	ret = mutex_lock_interruptible(&conn->lock);
	if (ret)
		return ret;
	if (op6893_mtcmos_refs++)
		goto out;
	if (conn->vendor_domain_on) {
		conn->vendor_hold = true;
		goto out;
	}
	if (conn->attempted || conn->adie_unsafe || conn->sysram_unsafe ||
	    conn->strap_unsafe || conn->spi_config_unsafe || conn->domain_uncertain) {
		ret = -EBUSY;
		goto fail;
	}
	conn->vendor_hold = true;
	spm = conn->spm;
	host = conn->host;
	/* ACK wrapper, host request, then legacy PG_CONN request + control seq. */
	writel((readl(spm) & ~0xffff0001) | 0x0b160001, spm);
	writel(readl(host) | BIT(0), host);
	writel(0x0b160001, spm);
	ret = op6893_mtcmos_control(BIT(2), 0);
	if (ret)
		goto fail;
	ret = op6893_mtcmos_control(BIT(3), 0);
	if (ret)
		goto fail;
	ret = op6893_mtcmos_power_ack(true);
	if (ret)
		goto fail;
	ret = op6893_mtcmos_control(0, BIT(4));
	if (ret)
		goto fail;
	ret = op6893_mtcmos_control(0, BIT(1));
	if (ret)
		goto fail;
	ret = op6893_mtcmos_control(BIT(0), 0);
	if (ret)
		goto fail;
	ret = op6893_mtcmos_protect(0x2a4, 0x228, BIT(14), false);
	if (ret)
		goto fail;
	ret = op6893_mtcmos_protect(0x718, 0x724, BIT(2), false);
	if (ret)
		goto fail;
	ret = op6893_mtcmos_protect(0x2a4, 0x228, BIT(13), false);
	if (ret)
		goto fail;
	usleep_range(6000, 7000);
	conn->vendor_domain_on = true;
out:
	mutex_unlock(&conn->lock);
	return 0;
fail:
	op6893_mtcmos_refs--;
	if (!op6893_mtcmos_refs)
		conn->vendor_hold = false;
	mutex_unlock(&conn->lock);
	return ret;
}

#ifdef CONFIG_OP6893_CONN_MTCMOS_OFF
static void op6893_conn_mtcmos_off_hw(struct op6893_conn *conn)
{
	writel(0x0b160001, conn->spm);
	if (op6893_mtcmos_protect(0x2a0, 0x228, BIT(13), true) ||
	    op6893_mtcmos_protect(0x2a0, 0x228, BIT(14), true) ||
	    op6893_mtcmos_protect(0x714, 0x724, BIT(2), true) ||
	    op6893_mtcmos_control(BIT(1), 0) ||
	    op6893_mtcmos_control(BIT(4), 0) ||
	    op6893_mtcmos_control(0, BIT(0)) ||
	    op6893_mtcmos_control(0, BIT(2)) ||
	    op6893_mtcmos_control(0, BIT(3)) ||
	    op6893_mtcmos_power_ack(false))
		conn->adie_unsafe = true;
	writel(readl(conn->host) & ~BIT(0), conn->host);
	conn->vendor_hold = false;
	conn->vendor_domain_on = false;
}
#endif /* CONFIG_OP6893_CONN_MTCMOS_OFF */

void op6893_conn_mtcmos_off(void)
{
	struct op6893_conn *conn = op6893_vendor_conn;

	if (mutex_lock_interruptible(&conn->lock))
		return;
	if (!conn || !op6893_mtcmos_refs) {
		mutex_unlock(&conn->lock);
		return;
	}
	--op6893_mtcmos_refs;
#ifdef CONFIG_OP6893_CONN_MTCMOS_OFF
	if (!op6893_mtcmos_refs)
		op6893_conn_mtcmos_off_hw(conn);
#else
	/*
	 * On uncertainty retain parent resources: leave the domain powered.
	 * vendor_hold stays set so the preflight experiment remains blocked;
	 * a later mtcmos_on is a cheap refcount no-op, never re-writing.
	 */
	if (!op6893_mtcmos_refs)
		pr_info("op6893-conn: CONN domain retained on (vendor path)\n");
#endif
	mutex_unlock(&conn->lock);
}

static int op6893_conn_probe(struct platform_device *pdev)
{
	static const char * const strap_names[] = {
		"strap-prepare", "strap-high", "strap-mux", "strap-low", "strap-input",
	};
	struct device *dev = &pdev->dev;
	struct platform_device *wrapper;
	struct reserved_mem *rmem;
	struct device_node *np;
	struct op6893_conn *conn;
	char property[32];
	unsigned int i;

	if (!of_machine_is_compatible("realme,op6893"))
		return -ENODEV;
	conn = devm_kzalloc(dev, sizeof(*conn), GFP_KERNEL);
	op6893_vendor_conn = conn;
	op6893_crumb_init();
	if (!conn)
		return -ENOMEM;
	/* Imported LK size-only node: use Linux's allocation, never a saved ACK base. */
	np = of_find_node_by_path("/reserved-memory/consys-reserve-memory");
	if (np && of_property_read_bool(np, "no-map")) {
		rmem = of_reserved_mem_lookup(np);
		if (rmem) {
			conn->emi_base = rmem->base;
			conn->emi_size = rmem->size;
			conn->emi_valid = op6893_conn_emi_valid(rmem->base, rmem->size);
		}
	}
	of_node_put(np);
	mutex_init(&conn->lock);
	conn->stage = "idle";
	conn->cycle_allowed = of_property_read_bool(dev->of_node,
				"realme,allow-inherited-parent-rail-cycle");
	conn->domain_allowed = of_property_read_bool(dev->of_node,
				"realme,allow-conn-domain-cycle");
	if (conn->domain_allowed) {
		conn->pins = devm_pinctrl_get(dev);
		if (IS_ERR(conn->pins))
			return PTR_ERR(conn->pins);
		conn->active_pins = pinctrl_lookup_state(conn->pins, "conn-active");
		if (IS_ERR(conn->active_pins))
			return PTR_ERR(conn->active_pins);
		conn->idle_pins = pinctrl_lookup_state(conn->pins, "conn-idle");
		if (IS_ERR(conn->idle_pins))
			return PTR_ERR(conn->idle_pins);
		for (i = 0; i < ARRAY_SIZE(strap_names); i++) {
			conn->strap_pins[i] = pinctrl_lookup_state(conn->pins, strap_names[i]);
			if (IS_ERR(conn->strap_pins[i]))
				return PTR_ERR(conn->strap_pins[i]);
		}
	}
	np = of_parse_phandle(dev->of_node, "mediatek,pmic-wrapper", 0);
	if (!np)
		return -EINVAL;
	wrapper = of_find_device_by_node(np);
	of_node_put(np);
	if (!wrapper)
		return -EPROBE_DEFER;
	conn->pmic = dev_get_regmap(&wrapper->dev, NULL);
	if (conn->pmic && !device_link_add(dev, &wrapper->dev,
					 DL_FLAG_AUTOREMOVE_CONSUMER)) {
		put_device(&wrapper->dev);
		return -ENOMEM;
	}
	put_device(&wrapper->dev);
	if (!conn->pmic)
		return -EPROBE_DEFER;
	/* Audited always-on AP ranges only; no 0x18000000 CONN mapping. */
	conn->spm = devm_ioremap(dev, 0x10006000, 0x1000);
	conn->infra = devm_ioremap(dev, 0x10001000, 0x1000);
	conn->host = devm_ioremap(dev, 0x1020e504, 4);
	if (!conn->spm || !conn->infra || !conn->host)
		return -ENOMEM;
	for (i = 0; i < ARRAY_SIZE(conn->rails); i++) {
		snprintf(property, sizeof(property), "%s-supply", op6893_conn_rails[i]);
		if (!of_find_property(dev->of_node, property, NULL))
			return -EINVAL;
		/* Optional get rejects an absent leaf instead of using a dummy. */
		conn->rails[i] = devm_regulator_get_optional(dev, op6893_conn_rails[i]);
		if (IS_ERR(conn->rails[i]))
			return dev_err_probe(dev, PTR_ERR(conn->rails[i]),
					     "missing %s provider\n", op6893_conn_rails[i]);
	}
	platform_set_drvdata(pdev, conn);
	dev_info(dev, "preflight ready; explicit rail cycle allowed=%u; upstream inherited\n",
		 conn->cycle_allowed);
	return 0;
}

static const struct of_device_id op6893_conn_match[] = {
	{ .compatible = "realme,op6893-conn-preflight" },
	{ }
};

static struct platform_driver op6893_conn_driver = {
	.probe = op6893_conn_probe,
	.driver = {
		.name = "op6893-conn-preflight",
		.of_match_table = op6893_conn_match,
		.dev_groups = op6893_conn_groups,
		.suppress_bind_attrs = true,
	},
};
builtin_platform_driver(op6893_conn_driver);


