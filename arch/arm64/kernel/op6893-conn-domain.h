/* SPDX-License-Identifier: GPL-2.0-only */
/* Included only by the board diagnostic, with its mutex held. */

static void op6893_conn_trace_protection(struct op6893_conn *conn, const char *point)
{
	struct op6893_conn_trace *t;

	if (conn->trace_count >= ARRAY_SIZE(conn->trace))
		return;
	t = &conn->trace[conn->trace_count++];
	t->point = point;
	t->time_ns = ktime_get_boottime_ns();
	t->request = readl(conn->infra + 0x220);
	t->status0 = readl(conn->infra + 0x224);
	t->status1 = readl(conn->infra + 0x228);
	t->request2 = readl(conn->infra + 0x710);
	t->status20 = readl(conn->infra + 0x720);
	t->status21 = readl(conn->infra + 0x724);
	t->power = readl(conn->spm + 0x16c);
	t->power2 = readl(conn->spm + 0x170);
	t->control = readl(conn->spm + 0x304);
	t->host = readl(conn->host);
}

static void op6893_conn_record_domain(struct op6893_conn *conn)
{
	conn->last_status = readl(conn->spm + 0x16c);
	conn->last_status2 = readl(conn->spm + 0x170);
	conn->last_control = readl(conn->spm + 0x304);
	conn->last_protect = readl(conn->infra + 0x228);
	conn->last_protect2 = readl(conn->infra + 0x724);
	conn->last_host = readl(conn->host);
}

static int op6893_conn_poll(void __iomem *addr, u32 mask, u32 expected)
{
	u32 value;

	return readl_poll_timeout(addr, value, (value & mask) == expected, 50, 20000);
}

static int op6893_conn_control(struct op6893_conn *conn, u32 set, u32 clear)
{
	u32 value = (readl(conn->spm + 0x304) | set) & ~clear;

	writel(value, conn->spm + 0x304);
	return readl(conn->spm + 0x304) == value ? 0 : -EIO;
}

static int op6893_conn_power_ack(struct op6893_conn *conn, bool on)
{
	u32 value;

	/* One deadline covers the dual acknowledgement, including mixed states. */
	return read_poll_timeout(readl, value,
				!!(value & BIT(1)) == on &&
				!!(readl(conn->spm + 0x170) & BIT(1)) == on,
				50, 20000, false, conn->spm + 0x16c);
}

static int op6893_conn_protect(struct op6893_conn *conn, u32 alias, u32 status,
			       u32 mask, bool enable)
{
	/* SET/CLR aliases require exact writes, never read-modify-write. */
	writel(mask, conn->infra + alias);
	return op6893_conn_poll(conn->infra + status, mask, enable ? mask : 0);
}

static int op6893_conn_stop_domain(struct op6893_conn *conn)
{
	int ret;

	conn->stage = "protect-step1";
	writel(0x0b160001, conn->spm);
	ret = op6893_conn_protect(conn, 0x2a0, 0x228, BIT(13), true);
	if (ret)
		return ret;
	conn->stage = "protect-step2";
	ret = op6893_conn_protect(conn, 0x2a0, 0x228, BIT(14), true);
	if (ret)
		return ret;
	conn->stage = "protect-bank2";
	ret = op6893_conn_protect(conn, 0x714, 0x724, BIT(2), true);
	if (ret)
		return ret;
	conn->stage = "isolate-reset";
	ret = op6893_conn_control(conn, BIT(1), 0);
	if (ret)
		return ret;
	ret = op6893_conn_control(conn, BIT(4), 0);
	if (ret)
		return ret;
	ret = op6893_conn_control(conn, 0, BIT(0));
	if (ret)
		return ret;
	conn->stage = "power-off";
	ret = op6893_conn_control(conn, 0, BIT(2));
	if (ret)
		return ret;
	ret = op6893_conn_control(conn, 0, BIT(3));
	if (ret)
		return ret;
	ret = op6893_conn_power_ack(conn, false);
	if (ret)
		return ret;
	if (!op6893_conn_is_off(readl(conn->spm + 0x16c),
				readl(conn->spm + 0x170), readl(conn->spm + 0x304)))
		return -EIO;
	writel(readl(conn->host) & ~BIT(0), conn->host);
	ret = op6893_conn_domain_off(conn);
	if (!ret)
		conn->domain_uncertain = false;
	return ret;
}

static bool op6893_conn_access_ready(struct op6893_conn *conn, u32 protect_mask)
{
	/* Preserve the rejecting sample before normal shutdown overwrites state. */
	conn->access_status = readl(conn->spm + 0x16c);
	conn->access_status2 = readl(conn->spm + 0x170);
	conn->access_control = readl(conn->spm + 0x304);
	conn->access_protect = readl(conn->infra + 0x228);
	conn->access_protect2 = readl(conn->infra + 0x724);
	conn->access_host = readl(conn->host);
	return (conn->access_status & BIT(1)) && (conn->access_status2 & BIT(1)) &&
	       (conn->access_control & 0x1f) == 0x0d &&
	       !(conn->access_protect & protect_mask) &&
	       !(conn->access_protect2 & BIT(2)) && (conn->access_host & BIT(0));
}

/* HOST_CSR is on-domain; bit14 protects the reverse CONN-to-AP path. */
static int op6893_conn_sample_csr(struct op6893_conn *conn)
{
	static const unsigned long addresses[] = { 0x18060000, 0x18060184, 0x180602d4 };
	void __iomem *word;
	unsigned int i;

	for (i = 0; i < ARRAY_SIZE(addresses); i++) {
		conn->stage = "csr-access-guard";
		if (!op6893_conn_access_ready(conn, BIT(13)))
			return -EBUSY;
		conn->stage = "csr-map";
		word = ioremap(addresses[i], 4);
		if (!word)
			return -ENOMEM;
		/* Recheck after mapping, before each individual hardware read. */
		if (!op6893_conn_access_ready(conn, BIT(13))) {
			iounmap(word);
			conn->stage = "csr-access-guard";
			return -EBUSY;
		}
		conn->stage = "csr-sample";
		conn->csr_words[i] = readl(word);
		conn->csr_samples++;
		iounmap(word);
	}
	/* Raw observations only: the clock detector has NOT been reset. */
	return 0;
}

static int op6893_conn_identify(struct op6893_conn *conn)
{
	void __iomem *csr, *cfg;
	int ret;

	conn->stage = "id-access-guard";
	if (!op6893_conn_access_ready(conn, BIT(13) | BIT(14)))
		return -EBUSY;
	/* Map only after AP-side prerequisites; no writes to either aperture. */
	csr = ioremap(0x18060184, 4);
	if (!csr)
		return -ENOMEM;
	conn->stage = "id-sleep-protection";
	ret = op6893_conn_poll(csr, BIT(5), 0);
	if (ret)
		goto unmap_csr;
	if (!op6893_conn_access_ready(conn, BIT(13) | BIT(14))) {
		ret = -EBUSY;
		goto unmap_csr;
	}
	cfg = ioremap(0x18001000, 8);
	if (!cfg) {
		ret = -ENOMEM;
		goto unmap_csr;
	}
	conn->stage = "read-digital-id";
	conn->id_read = true;
	conn->hw_version = readl(cfg);
	conn->config_id = readl(cfg + 4);
	ret = conn->hw_version == 0x20010101 && conn->config_id == 3 ? 0 : -ENODEV;
	iounmap(cfg);
unmap_csr:
	iounmap(csr);
	return ret;
}

static int op6893_conn_read_on(struct op6893_conn *conn, void __iomem *addr, u32 *value)
{
	if (!op6893_conn_access_ready(conn, BIT(13)))
		return -EBUSY;
	*value = readl(addr);
	return 0;
}

static int op6893_conn_check_off(struct op6893_conn *conn, void __iomem *csr)
{
	int ret;

	conn->off_ready = false;
	conn->stage = "id-clock-check";
	ret = op6893_conn_read_on(conn, csr, &conn->fresh_clock);
	if (ret)
		return ret;
	if ((conn->fresh_clock & 6) != 6)
		return -EBUSY;
	conn->stage = "id-timeout-check";
	ret = op6893_conn_read_on(conn, csr + 0x2d4, &conn->fresh_timeout);
	if (ret)
		return ret;
	if (!(conn->fresh_timeout & BIT(0)))
		return -EIO;
	conn->stage = "id-internal-sleep-check";
	ret = op6893_conn_read_on(conn, csr + 0x184, &conn->fresh_sleep);
	if (ret)
		return ret;
	if (conn->fresh_sleep & BIT(5))
		return -EBUSY;
	if (!op6893_conn_access_ready(conn, BIT(13)))
		return -EBUSY;
	conn->off_ready = true;
	return 0;
}

static int op6893_conn_sample_post_id(struct op6893_conn *conn, void __iomem *csr)
{
	void __iomem *word;
	unsigned int i;
	int ret;

	if (!conn->emi_valid) {
		conn->stage = "post-id-memory-guard";
		return -EINVAL;
	}
	for (i = 0; i < ARRAY_SIZE(op6893_conn_post_addresses); i++) {
		ret = op6893_conn_check_off(conn, csr);
		if (ret)
			return ret;
		conn->stage = "post-id-map";
		word = ioremap(op6893_conn_post_addresses[i], 4);
		if (!word)
			return -ENOMEM;
		ret = op6893_conn_check_off(conn, csr);
		if (!ret) {
			conn->stage = "post-id-sample";
			conn->post_words[i] = readl(word);
			conn->post_samples++;
		}
		iounmap(word);
		if (ret)
			return ret;
	}
	return 0;
}

static int op6893_conn_rgu_cycle(struct op6893_conn *conn, void __iomem *csr);
static int op6893_conn_spi_config_cycle(struct op6893_conn *conn, void __iomem *csr);
static int op6893_conn_sema_cycle(struct op6893_conn *conn, void __iomem *csr);

static int op6893_conn_remap_cycle(struct op6893_conn *conn, void __iomem *csr)
{
	void __iomem *word;
	unsigned int i;
	int ret, cleanup = 0;

	conn->stage = "remap-memory-guard";
	if (!conn->emi_valid || !op6893_conn_emi_valid(conn->emi_base, conn->emi_size))
		return -EINVAL;
	/* Save all originals before the first write, including unrelated high bits. */
	for (i = 0; i < ARRAY_SIZE(op6893_conn_remap_offsets); i++) {
		ret = op6893_conn_check_off(conn, csr);
		if (ret)
			return ret;
		conn->stage = "remap-save";
		word = csr + op6893_conn_remap_offsets[i];
		conn->remap_before[i] = readl(word);
		conn->remap_saved++;
		conn->remap_target[i] = (conn->remap_before[i] & ~0xfffff) |
			(i ? 0x1000 : (u32)(conn->emi_base >> 16));
	}
	for (i = 0; i < ARRAY_SIZE(op6893_conn_remap_offsets); i++) {
		ret = op6893_conn_check_off(conn, csr);
		if (ret)
			goto restore;
		conn->stage = "remap-apply";
		word = csr + op6893_conn_remap_offsets[i];
		/* A missing/ambiguous write still requires verified restoration. */
		conn->remap_dirty |= BIT(i);
		writel(conn->remap_target[i], word);
		ret = op6893_conn_check_off(conn, csr);
		if (ret)
			goto restore;
		conn->stage = "remap-apply-readback";
		conn->remap_on[i] = readl(word);
		if (conn->remap_on[i] != conn->remap_target[i]) {
			ret = -EIO;
			goto restore;
		}
		conn->remap_applied++;
	}
	if (conn->prepare_requested)
		ret = op6893_conn_rgu_cycle(conn, csr);
restore:
	if (ret && !conn->failure_stage)
		conn->failure_stage = conn->stage;
	for (i = ARRAY_SIZE(op6893_conn_remap_offsets); i-- > 0;) {
		if (!(conn->remap_dirty & BIT(i)))
			continue;
		if (conn->prepare_requested &&
		    (conn->rgu_dirty || conn->spi_config_dirty || conn->spi_config_unsafe ||
		     conn->sysram_unsafe || conn->strap_dirty || conn->strap_unsafe ||
		     conn->sema_pending || conn->sema_unsafe)) {
			cleanup = -EUCLEAN;
			break;
		}
		cleanup = op6893_conn_check_off(conn, csr);
		if (cleanup)
			break;
		conn->stage = "remap-restore";
		word = csr + op6893_conn_remap_offsets[i];
		writel(conn->remap_before[i], word);
		cleanup = op6893_conn_check_off(conn, csr);
		if (cleanup)
			break;
		conn->stage = "remap-restore-readback";
		conn->remap_after[i] = readl(word);
		if (conn->remap_after[i] != conn->remap_before[i]) {
			cleanup = -EIO;
			break;
		}
		conn->remap_dirty &= ~BIT(i);
		conn->remap_restored++;
	}
	conn->remap_cleanup_result = cleanup;
	if (cleanup && !conn->failure_stage)
		conn->failure_stage = conn->stage;
	return ret ?: cleanup;
}

#include "op6893-conn-sysram.h"
#include "op6893-conn-strap.h"

static int op6893_conn_rgu_cycle(struct op6893_conn *conn, void __iomem *csr)
{
	static const u32 baseline[] = { 0xff, 0, 1, 0 };
	static const u32 target[] = { 0, 0xff, 0, 1 };
	void __iomem *word, *rgu;
	unsigned int i;
	int ret, cleanup = 0;

	ret = op6893_conn_check_off(conn, csr);
	if (ret)
		return ret;
	conn->stage = "rgu-map";
	rgu = ioremap(0x18000000, 0x58);
	if (!rgu)
		return -ENOMEM;
	/* Register restoration cannot establish SRAM data retention. */
	/* Save all originals before the first write, including unrelated high bits. */
	for (i = 0; i < ARRAY_SIZE(op6893_conn_rgu_offsets); i++) {
		ret = op6893_conn_check_off(conn, csr);
		if (ret)
			goto unmap;
		conn->stage = "rgu-save";
		word = rgu + op6893_conn_rgu_offsets[i];
		conn->rgu_before[i] = readl(word);
		conn->rgu_saved++;
		conn->rgu_target[i] = target[i];
		conn->stage = "rgu-baseline";
		if (conn->rgu_before[i] != baseline[i]) {
			ret = -EBUSY;
			goto unmap;
		}
	}
	for (i = 0; i < ARRAY_SIZE(op6893_conn_rgu_offsets); i++) {
		ret = op6893_conn_check_off(conn, csr);
		if (ret)
			goto restore;
		conn->stage = "rgu-apply";
		word = rgu + op6893_conn_rgu_offsets[i];
		/* A missing/ambiguous write still requires verified restoration. */
		conn->rgu_dirty |= BIT(i);
		writel(conn->rgu_target[i], word);
		ret = op6893_conn_check_off(conn, csr);
		if (ret)
			goto restore;
		conn->stage = "rgu-apply-readback";
		conn->rgu_on[i] = readl(word);
		if (conn->rgu_on[i] != conn->rgu_target[i]) {
			ret = -EIO;
			goto restore;
		}
		conn->rgu_applied++;
	}
	if (conn->prepare_requested)
		ret = op6893_conn_spi_config_cycle(conn, csr);
	else if (conn->sysram_requested)
		ret = op6893_conn_sysram_cycle(conn, csr);
restore:
	if (ret && !conn->failure_stage)
		conn->failure_stage = conn->stage;
	for (i = ARRAY_SIZE(op6893_conn_rgu_offsets); i-- > 0;) {
		if (!(conn->rgu_dirty & BIT(i)))
			continue;
		if (conn->sysram_unsafe || (conn->prepare_requested &&
		    (conn->spi_config_dirty || conn->spi_config_unsafe ||
		     conn->strap_dirty || conn->strap_unsafe ||
		     conn->sema_pending || conn->sema_unsafe))) {
			cleanup = -EUCLEAN;
			break;
		}
		cleanup = op6893_conn_check_off(conn, csr);
		if (cleanup)
			break;
		conn->stage = "rgu-restore";
		word = rgu + op6893_conn_rgu_offsets[i];
		writel(conn->rgu_before[i], word);
		cleanup = op6893_conn_check_off(conn, csr);
		if (cleanup)
			break;
		conn->stage = "rgu-restore-readback";
		conn->rgu_after[i] = readl(word);
		if (conn->rgu_after[i] != conn->rgu_before[i]) {
			cleanup = -EIO;
			break;
		}
		conn->rgu_dirty &= ~BIT(i);
		conn->rgu_restored++;
	}
	conn->rgu_cleanup_result = cleanup;
	if (cleanup && !conn->failure_stage)
		conn->failure_stage = conn->stage;
unmap:
	iounmap(rgu);
	return ret ?: cleanup;
}

static int op6893_conn_sample_spi(struct op6893_conn *conn, void __iomem *csr)
{
	void __iomem *word;
	unsigned int i;
	int ret;

	conn->spi_start_ns = ktime_get_boottime_ns();
	for (i = 0; i < ARRAY_SIZE(op6893_conn_spi_addresses); i++) {
		ret = op6893_conn_check_off(conn, csr);
		if (ret)
			goto done;
		conn->stage = "spi-baseline-map";
		word = ioremap(op6893_conn_spi_addresses[i], 4);
		if (!word) {
			ret = -ENOMEM;
			goto done;
		}
		ret = op6893_conn_check_off(conn, csr);
		if (!ret) {
			/* No command/data/semaphore access and no SPI transaction. */
			conn->stage = "spi-baseline-sample";
			conn->spi_words[i] = readl(word);
			conn->spi_samples++;
		}
		iounmap(word);
		if (ret)
			goto done;
	}
	/* A full sample count alone does not imply this final guard passed. */
	ret = op6893_conn_check_off(conn, csr);
done:
	conn->spi_end_ns = ktime_get_boottime_ns();
	return ret;
}

#include "op6893-conn-spi.h"
#include "op6893-conn-sema.h"

static int op6893_conn_identify_fresh(struct op6893_conn *conn)
{
	void __iomem *csr, *cfg;
	u32 value;
	unsigned int i;
	int ret, error;

	conn->stage = "id-on-domain-guard";
	if (!op6893_conn_access_ready(conn, BIT(13)))
		return -EBUSY;
	csr = ioremap(0x18060000, 0x2d8);
	if (!csr)
		return -ENOMEM;
	conn->stage = "id-clock-reset";
	ret = op6893_conn_read_on(conn, csr, &value);
	if (ret)
		goto unmap_csr;
	if (!op6893_conn_access_ready(conn, BIT(13))) {
		ret = -EBUSY;
		goto unmap_csr;
	}
	/* ACK resets the detector by setting bit0, preserving the other bits. */
	writel(value | BIT(0), csr);
	conn->clock_reset_requested = true;
	udelay(1);
	conn->stage = "id-clock-poll";
	ret = read_poll_timeout(op6893_conn_read_on, error,
				error || (conn->fresh_clock & 6) == 6,
				50, 20000, false, conn, csr, &conn->fresh_clock);
	ret = ret ?: error;
	if (ret)
		goto unmap_csr;
	ret = op6893_conn_check_off(conn, csr);
	if (ret)
		goto unmap_csr;
	conn->stage = "id-config-map";
	cfg = ioremap(0x18001000, 8);
	if (!cfg) {
		ret = -ENOMEM;
		goto unmap_csr;
	}
	for (i = 0; i < 2; i++) {
		/* Revalidate clocks, timeout and sleep before each off-domain read. */
		ret = op6893_conn_check_off(conn, csr);
		if (ret)
			break;
		conn->stage = "read-fresh-digital-id";
		conn->id_read = true;
		value = readl(cfg + i * 4);
		conn->id_samples++;
		if (!i)
			conn->hw_version = value;
		else
			conn->config_id = value;
	}
	if (!ret && (conn->hw_version != 0x20010101 || conn->config_id != 3))
		ret = -ENODEV;
	iounmap(cfg);
	if (!ret && conn->post_requested)
		ret = op6893_conn_sample_post_id(conn, csr);
	if (!ret && conn->remap_requested)
		ret = op6893_conn_remap_cycle(conn, csr);
	if (!ret && !conn->prepare_requested && conn->rgu_requested)
		ret = op6893_conn_rgu_cycle(conn, csr);
	if (!ret && conn->spi_requested)
		ret = op6893_conn_sample_spi(conn, csr);
	if (!ret && !conn->prepare_requested && conn->spi_config_requested)
		ret = op6893_conn_spi_config_cycle(conn, csr);
	if (!ret && !conn->prepare_requested && conn->sema_requested)
		ret = op6893_conn_sema_cycle(conn, csr);
	if (!ret && !conn->prepare_requested && conn->strap_requested)
		ret = op6893_conn_strap_cycle(conn, csr);
unmap_csr:
	iounmap(csr);
	return ret;
}

static int op6893_conn_domain_cycle(struct op6893_conn *conn)
{
	int ret, cleanup;

	conn->stage = "domain-start-guard";
	if (!conn->rail_refs[0] || !conn->rail_refs[1] ||
	    !(readl(conn->infra + 0x228) & BIT(14)) ||
	    !(readl(conn->infra + 0x724) & BIT(2)))
		return -EBUSY;
	op6893_conn_trace_protection(conn, "before-pins");
	conn->stage = "select-active-pins";
	conn->pins_dirty = true;
	ret = pinctrl_select_state(conn->pins, conn->active_pins);
	if (ret)
		goto idle_pins;
	conn->stage = "power-on-requests";
	/* Active ACK wrapper, then legacy PG_CONN unlock and request order. */
	conn->domain_uncertain = true;
	writel((readl(conn->spm) & ~0xffff0001) | 0x0b160001, conn->spm);
	writel(readl(conn->host) | BIT(0), conn->host);
	writel(0x0b160001, conn->spm);
	ret = op6893_conn_control(conn, BIT(2), 0);
	if (ret)
		goto retain;
	ret = op6893_conn_control(conn, BIT(3), 0);
	if (ret)
		goto retain;
	conn->stage = "power-on-dual-ack";
	ret = op6893_conn_power_ack(conn, true);
	if (ret)
		goto retain;
	conn->stage = "release-clock-isolation-reset";
	ret = op6893_conn_control(conn, 0, BIT(4));
	if (ret)
		goto retain;
	ret = op6893_conn_control(conn, 0, BIT(1));
	if (ret)
		goto retain;
	ret = op6893_conn_control(conn, BIT(0), 0);
	if (ret)
		goto retain;
	op6893_conn_trace_protection(conn, "before-release");
	conn->stage = "release-protect-step2";
	ret = op6893_conn_protect(conn, 0x2a4, 0x228, BIT(14), false);
	op6893_conn_trace_protection(conn, "after-release14");
	if (ret)
		goto stop;
	conn->stage = "release-protect-bank2";
	ret = op6893_conn_protect(conn, 0x718, 0x724, BIT(2), false);
	op6893_conn_trace_protection(conn, "after-release-bank2");
	if (ret)
		goto stop;
	conn->stage = "release-protect-step1";
	ret = op6893_conn_protect(conn, 0x2a4, 0x228, BIT(13), false);
	op6893_conn_trace_protection(conn, "after-release13");
	if (ret)
		goto stop;
	conn->stage = "xo-settle";
	usleep_range(6000, 7000);
	op6893_conn_trace_protection(conn, "after-settle");
	if (conn->id_requested)
		ret = op6893_conn_identify_fresh(conn);
	else if (conn->csr_requested)
		ret = op6893_conn_sample_csr(conn);
	else
		ret = op6893_conn_identify(conn);
stop:
	if (ret && !conn->failure_stage)
		conn->failure_stage = conn->stage;
	if (conn->remap_dirty || conn->rgu_dirty ||
	    conn->spi_config_dirty || conn->spi_config_unsafe ||
	    conn->sema_pending || conn->sema_unsafe || conn->sysram_unsafe ||
	    conn->strap_dirty || conn->strap_unsafe ||
	    conn->adie_reset_dirty || conn->adie_addr_dirty || conn->adie_write_dirty ||
	    conn->adie_mailbox_dirty ||
	    conn->adie_prefix_dirty || conn->adie_fm_dirty ||
	    conn->adie_efuse_pending || conn->adie_unsafe) {
		/* Unverified register restoration: retain domain, pins and supplies. */
		conn->domain_cleanup_result = -EUCLEAN;
		goto retain;
	}
	cleanup = op6893_conn_stop_domain(conn);
	op6893_conn_trace_protection(conn, "after-stop");
	conn->domain_cleanup_result = cleanup;
	if (cleanup) {
		if (!ret)
			ret = cleanup;
		goto retain;
	}
idle_pins:
	if (ret && !conn->failure_stage)
		conn->failure_stage = conn->stage;
	conn->stage = "select-idle-pins";
	cleanup = pinctrl_select_state(conn->pins, conn->idle_pins);
	conn->domain_cleanup_result = cleanup;
	if (!cleanup)
		conn->pins_dirty = false;
	op6893_conn_record_domain(conn);
	return ret ?: cleanup;
retain:
	op6893_conn_record_domain(conn);
	/* Uncertain domain/register state: do not change pins or remove supplies. */
	return ret;
}
