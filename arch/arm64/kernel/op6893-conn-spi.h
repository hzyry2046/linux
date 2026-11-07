/* SPDX-License-Identifier: GPL-2.0-only */
/* Included by the board domain diagnostic, with its mutex held. */

static int op6893_conn_spi_config_guard(struct op6893_conn *conn, void __iomem *csr,
				      void __iomem *adie, void __iomem *spi, void __iomem *wt)
{
	int ret;

	/* Any observed loss is latched; do not resume writes on a later sample. */
	if (conn->spi_config_unsafe)
		return -EUCLEAN;
	ret = op6893_conn_check_off(conn, csr);
	if (ret)
		goto unsafe;
	conn->stage = "spi-config-adie-guard";
	conn->spi_config_adie = readl(adie);
	if (conn->spi_config_adie != 2) {
		ret = -EBUSY;
		goto unsafe;
	}
	ret = op6893_conn_check_off(conn, csr);
	if (ret)
		goto unsafe;
	conn->stage = "spi-config-busy-guard";
	conn->spi_config_busy = readl(spi);
	if (conn->spi_config_busy) {
		ret = -EBUSY;
		goto unsafe;
	}
	ret = op6893_conn_check_off(conn, csr);
	if (ret)
		goto unsafe;
	conn->stage = "spi-config-wb-guard";
	conn->spi_config_wb = readl(wt + 8);
	/* Require the complete observed word, not an invented idle-bit mask. */
	if (conn->spi_config_wb != 0x80000) {
		ret = -EBUSY;
		goto unsafe;
	}
	ret = op6893_conn_check_off(conn, csr);
	if (!ret)
		return 0;
unsafe:
	conn->spi_config_unsafe = true;
	return ret;
}

static int op6893_conn_spi_config_cycle(struct op6893_conn *conn, void __iomem *csr)
{
	void __iomem *adie, *spi, *wt, *word;
	const struct op6893_conn_spi_setting *setting;
	unsigned int i;
	int ret, cleanup = 0;

	ret = op6893_conn_check_off(conn, csr);
	if (ret)
		return ret;
	conn->stage = "spi-config-adie-map";
	adie = ioremap(0x18001900, 4);
	if (!adie)
		return -ENOMEM;
	ret = op6893_conn_check_off(conn, csr);
	if (ret)
		goto unmap_adie;
	conn->stage = "spi-config-busy-map";
	spi = ioremap(0x18004000, 4);
	if (!spi) {
		ret = -ENOMEM;
		goto unmap_adie;
	}
	ret = op6893_conn_check_off(conn, csr);
	if (ret)
		goto unmap_spi;
	conn->stage = "spi-config-table-map";
	wt = ioremap(0x18005000, 0x9c);
	if (!wt) {
		ret = -ENOMEM;
		goto unmap_spi;
	}
	/* Save and validate ALL originals before changing any command word. */
	for (i = 0; i < ARRAY_SIZE(op6893_conn_spi_settings); i++) {
		ret = op6893_conn_spi_config_guard(conn, csr, adie, spi, wt);
		if (ret)
			goto unmap_wt;
		setting = &op6893_conn_spi_settings[i];
		conn->stage = "spi-config-save";
		conn->spi_config_before[i] = readl(wt + setting->offset);
		conn->spi_config_saved++;
		conn->spi_config_target[i] = (conn->spi_config_before[i] & ~setting->mask) |
					     setting->value;
		conn->stage = "spi-config-baseline";
		if (conn->spi_config_before[i] != setting->baseline) {
			ret = -EBUSY;
			goto unmap_wt;
		}
	}
	for (i = 0; i < ARRAY_SIZE(op6893_conn_spi_settings); i++) {
		ret = op6893_conn_spi_config_guard(conn, csr, adie, spi, wt);
		if (ret)
			goto restore;
		conn->stage = "spi-config-apply";
		word = wt + op6893_conn_spi_settings[i].offset;
		conn->spi_config_dirty |= BIT_ULL(i);
		writel(conn->spi_config_target[i], word);
		ret = op6893_conn_spi_config_guard(conn, csr, adie, spi, wt);
		if (ret)
			goto restore;
		conn->stage = "spi-config-apply-readback";
		conn->spi_config_on[i] = readl(word);
		if (conn->spi_config_on[i] != conn->spi_config_target[i]) {
			ret = -EIO;
			goto restore;
		}
		conn->spi_config_applied++;
	}
	if (conn->prepare_requested) {
		ret = op6893_conn_sysram_cycle(conn, csr);
		if (!ret)
			ret = op6893_conn_strap_cycle(conn, csr);
	}
restore:
	if (ret && !conn->failure_stage)
		conn->failure_stage = conn->stage;
	/* Length first, then reverse payload order; clear dirty only on readback. */
	for (i = ARRAY_SIZE(op6893_conn_spi_settings); i-- > 0;) {
		if (!(conn->spi_config_dirty & BIT_ULL(i)))
			continue;
		if (conn->prepare_requested &&
		    (conn->sysram_unsafe || conn->strap_dirty || conn->strap_unsafe ||
		     conn->sema_pending || conn->sema_unsafe)) {
			cleanup = -EUCLEAN;
			break;
		}
		cleanup = op6893_conn_spi_config_guard(conn, csr, adie, spi, wt);
		if (cleanup)
			break;
		conn->stage = "spi-config-restore";
		word = wt + op6893_conn_spi_settings[i].offset;
		writel(conn->spi_config_before[i], word);
		cleanup = op6893_conn_spi_config_guard(conn, csr, adie, spi, wt);
		if (cleanup)
			break;
		conn->stage = "spi-config-restore-readback";
		conn->spi_config_after[i] = readl(word);
		if (conn->spi_config_after[i] != conn->spi_config_before[i]) {
			cleanup = -EIO;
			break;
		}
		conn->spi_config_dirty &= ~BIT_ULL(i);
		conn->spi_config_restored++;
	}
	if (!cleanup)
		cleanup = op6893_conn_spi_config_guard(conn, csr, adie, spi, wt);
	conn->spi_config_cleanup_result = cleanup;
	if (cleanup && !conn->failure_stage)
		conn->failure_stage = conn->stage;
unmap_wt:
	iounmap(wt);
unmap_spi:
	iounmap(spi);
unmap_adie:
	iounmap(adie);
	return ret ?: cleanup;
}
