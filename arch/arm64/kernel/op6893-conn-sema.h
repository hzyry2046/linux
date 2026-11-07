/* SPDX-License-Identifier: GPL-2.0-only */
/* Board-only semaphore11 experiment; caller holds the diagnostic mutex. */

static int op6893_conn_sema_read(struct op6893_conn *conn, void __iomem *csr,
			       void __iomem *word, u32 *value)
{
	int ret = op6893_conn_check_off(conn, csr);

	if (ret) {
		conn->sema_unsafe = true;
		return ret;
	}
	*value = readl(word);
	return 0;
}

static int op6893_conn_sema_report(struct op6893_conn *conn, void __iomem *csr,
				 void __iomem *sema, unsigned int phase)
{
	unsigned int i;
	int ret;

	for (i = 0; i < 4; i++) {
		ret = op6893_conn_sema_read(conn, csr, sema + 0x400 + i * 0x1000,
					   &conn->sema_report[phase][i]);
		if (ret)
			return ret;
		conn->sema_samples[phase]++;
	}
	ret = op6893_conn_check_off(conn, csr);
	if (ret)
		conn->sema_unsafe = true;
	return ret;
}

static bool op6893_conn_sema_matches(struct op6893_conn *conn, unsigned int phase,
				    bool owned)
{
	unsigned int i;

	for (i = 0; i < 4; i++)
		if (!!(conn->sema_report[phase][i] & BIT(11)) != (owned && i == 2))
			return false;
	return true;
}

static int op6893_conn_sema_poll(struct op6893_conn *conn, void __iomem *csr,
			       void __iomem *sema, u32 *value)
{
	conn->sema_polls++;
	return op6893_conn_sema_read(conn, csr, sema + 0x2400, value);
}

#include "op6893-conn-adie.h"

static int op6893_conn_sema_cycle(struct op6893_conn *conn, void __iomem *csr)
{
	void __iomem *sema;
	u32 value;
	int ret, error, cleanup = 0;

	conn->stage = "sema-preparation-guard";
	if (conn->prepare_requested &&
	    (conn->remap_dirty != 0xf || conn->rgu_dirty != 0xf ||
	     conn->spi_config_dirty != BIT_ULL(36) - 1 || !conn->sysram_complete ||
	     !conn->strap_dirty || conn->strap_selected != 2))
		return -EINVAL;

	ret = op6893_conn_check_off(conn, csr);
	if (ret)
		return ret;
	conn->stage = "sema-map";
	sema = ioremap(0x18070000, 0x3404);
	if (!sema)
		return -ENOMEM;
	ret = op6893_conn_sema_report(conn, csr, sema, 0);
	if (ret)
		goto unmap;
	conn->stage = "sema-baseline";
	if (!op6893_conn_sema_matches(conn, 0, false)) {
		/* Never release an inherited owner or shut down its domain. */
		conn->sema_unsafe = true;
		ret = -EBUSY;
		goto unmap;
	}
	ret = op6893_conn_check_off(conn, csr);
	if (ret) {
		conn->sema_unsafe = true;
		goto unmap;
	}
	conn->stage = "sema-acquire";
	/* This READ requests ownership. Mark pending before its side effect. */
	conn->sema_pending = true;
	conn->sema_request_issued = true;
	conn->sema_grant = readl(sema + 0x202c);
	conn->sema_acquired = !!(conn->sema_grant & BIT(0));
	ret = op6893_conn_sema_report(conn, csr, sema, 1);
	if (ret)
		goto release;
	conn->stage = "sema-own-report";
	if (conn->sema_grant == 0 && op6893_conn_sema_matches(conn, 1, false)) {
		conn->sema_pending = false;
		ret = -EBUSY;
		goto unmap;
	}
	if (conn->sema_grant != 1 || !op6893_conn_sema_matches(conn, 1, true)) {
		conn->sema_unsafe = true;
		ret = -EIO;
	}
	if (!ret && conn->adie_requested) {
		ret = op6893_conn_adie_cycle(conn, csr, sema);
		if (conn->adie_reset_dirty || conn->adie_addr_dirty ||
		    conn->adie_write_dirty || conn->adie_mailbox_dirty ||
		    conn->adie_prefix_dirty || conn->adie_fm_dirty ||
		    conn->adie_efuse_pending || conn->adie_unsafe)
			conn->sema_unsafe = true;
	}
release:
	if (ret && !conn->failure_stage)
		conn->failure_stage = conn->stage;
	/* Only an acknowledged grant permits a release; never blindly unlock. */
	if (!conn->sema_acquired || conn->sema_unsafe) {
		cleanup = -EUCLEAN;
		goto done;
	}
	cleanup = op6893_conn_check_off(conn, csr);
	if (cleanup) {
		conn->sema_unsafe = true;
		goto done;
	}
	conn->stage = "sema-release";
	conn->sema_release_issued = true;
	writel(1, sema + 0x222c);
	/* Poll passive M2 report, never reread OWN_STA and reacquire the lock. */
	conn->stage = "sema-release-poll";
	cleanup = read_poll_timeout(op6893_conn_sema_poll, error,
				    error || !(value & BIT(11)), 50, 20000, false,
				    conn, csr, sema, &value);
	cleanup = cleanup ?: error;
	if (cleanup)
		goto done;
	cleanup = op6893_conn_sema_report(conn, csr, sema, 2);
	if (cleanup)
		goto done;
	conn->stage = "sema-release-report";
	if (!op6893_conn_sema_matches(conn, 2, false)) {
		conn->sema_unsafe = true;
		cleanup = -EIO;
		goto done;
	}
	cleanup = op6893_conn_check_off(conn, csr);
	if (cleanup) {
		conn->sema_unsafe = true;
		goto done;
	}
	conn->sema_pending = false;
	conn->sema_released = true;
done:
	conn->sema_cleanup_result = cleanup;
	if (cleanup && !conn->failure_stage)
		conn->failure_stage = conn->stage;
unmap:
	iounmap(sema);
	return ret ?: cleanup;
}
