/* SPDX-License-Identifier: GPL-2.0-only */
/* Volatile SYSRAM initialization while the tested RGU targets are installed. */

static int op6893_conn_sysram_guard(struct op6893_conn *conn, void __iomem *csr,
				  void __iomem *adie)
{
	int ret;

	if (conn->sysram_unsafe)
		return -EUCLEAN;
	ret = op6893_conn_check_off(conn, csr);
	if (ret)
		goto unsafe;
	conn->stage = "sysram-adie-guard";
	conn->sysram_adie = readl(adie);
	if (conn->sysram_adie != 2) {
		ret = -EBUSY;
		goto unsafe;
	}
	ret = op6893_conn_check_off(conn, csr);
	if (!ret)
		return 0;
unsafe:
	conn->sysram_unsafe = true;
	return ret;
}

static int op6893_conn_sysram_cycle(struct op6893_conn *conn, void __iomem *csr)
{
	void __iomem *adie, *ram;
	unsigned int offset;
	int ret;

	conn->stage = "sysram-rgu-guard";
	if (conn->rgu_applied != 4 || conn->rgu_dirty != 0xf)
		return -EINVAL;
	ret = op6893_conn_check_off(conn, csr);
	if (ret) {
		conn->sysram_unsafe = true;
		return ret;
	}
	conn->stage = "sysram-adie-map";
	adie = ioremap(0x18001900, 4);
	if (!adie)
		return -ENOMEM;
	ret = op6893_conn_sysram_guard(conn, csr, adie);
	if (ret)
		goto unmap_adie;
	conn->stage = "sysram-map";
	ram = ioremap(0x18050000, 0x4000);
	if (!ram) {
		ret = -ENOMEM;
		goto unmap_adie;
	}
	/* Old contents are discarded, not saved, exported or restored. */
	for (offset = 0; offset < 0x4000; offset += 4) {
		ret = op6893_conn_sysram_guard(conn, csr, adie);
		if (ret)
			goto unmap_ram;
		conn->stage = "sysram-clear";
		conn->sysram_started = true;
		writel(0, ram + offset);
		conn->sysram_written++;
		ret = op6893_conn_sysram_guard(conn, csr, adie);
		if (ret)
			goto unmap_ram;
		conn->stage = "sysram-readback";
		if (readl(ram + offset)) {
			conn->sysram_bad_offset = offset;
			ret = -EIO;
			goto unmap_ram;
		}
		conn->sysram_verified++;
	}
	/* Recheck every word after all writes, catching later corruption. */
	for (offset = 0; offset < 0x4000; offset += 4) {
		ret = op6893_conn_sysram_guard(conn, csr, adie);
		if (ret)
			goto unmap_ram;
		conn->stage = "sysram-final-scan";
		if (readl(ram + offset)) {
			conn->sysram_bad_offset = offset;
			ret = -EIO;
			goto unmap_ram;
		}
		conn->sysram_scanned++;
	}
	ret = op6893_conn_sysram_guard(conn, csr, adie);
	if (!ret)
		conn->sysram_complete = true;
unmap_ram:
	iounmap(ram);
unmap_adie:
	iounmap(adie);
	return ret;
}
