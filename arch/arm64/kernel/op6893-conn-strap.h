/* SPDX-License-Identifier: GPL-2.0-only */
/* GPIO180 strap experiment: all pin writes go through the owned pinctrl states. */

static int op6893_conn_strap_guard(struct op6893_conn *conn, void __iomem *csr,
				 void __iomem *adie)
{
	int ret;

	if (conn->strap_unsafe)
		return -EUCLEAN;
	ret = op6893_conn_check_off(conn, csr);
	if (ret)
		goto unsafe;
	conn->stage = "strap-adie-guard";
	conn->strap_adie = readl(adie);
	if (conn->strap_adie != 2) {
		ret = -EBUSY;
		goto unsafe;
	}
	ret = op6893_conn_check_off(conn, csr);
	if (!ret)
		return 0;
unsafe:
	conn->strap_unsafe = true;
	return ret;
}

static int op6893_conn_strap_sample(struct op6893_conn *conn, void __iomem *gpio,
				  void __iomem *io, unsigned int phase)
{
	static const u32 offsets[] = { 0x50, 0x150, 0x460, 0, 0x30, 0x50, 0x70, 0xc0 };
	static const u32 masks[] = { BIT(20), BIT(20), 0xf0000, 0, 0, 0, 0, 0 };
	static const u32 dir[] = { 0, 1, 1, 1, 1, 0, 0 };
	static const u32 dout[] = { 0, 1, 1, 1, 0, 0, 0 };
	static const u32 mode[] = { 1, 1, 0, 1, 1, 1, 1 };
	u32 expected, *words = conn->strap_words[phase];
	unsigned int i;

	conn->stage = "strap-pin-readback";
	for (i = 0; i < ARRAY_SIZE(offsets); i++)
		words[i] = readl((i < 3 ? gpio : io) + offsets[i]);
	conn->strap_samples++;
	if ((words[0] & BIT(20)) != dir[phase] * BIT(20) ||
	    (words[1] & BIT(20)) != dout[phase] * BIT(20) ||
	    (words[2] & 0xf0000) != mode[phase] << 16)
		return -EIO;
	if (!phase) {
		/* Audited idle-derived electrical baseline; never alter these fields. */
		if ((words[3] & 0x38) != 8 || !(words[4] & BIT(18)) ||
		    !(words[5] & BIT(18)) || (words[6] & BIT(18)) || (words[7] & BIT(7)))
			return -EINVAL;
		return 0;
	}
	for (i = 0; i < ARRAY_SIZE(offsets); i++) {
		expected = conn->strap_words[0][i] & ~masks[i];
		if ((words[i] & ~masks[i]) != expected)
			return -EIO;
	}
	return 0;
}

static int op6893_conn_strap_cycle(struct op6893_conn *conn, void __iomem *csr)
{
	void __iomem *adie, *gpio, *io;
	unsigned int i;
	int ret, child = 0;

	ret = op6893_conn_check_off(conn, csr);
	if (ret)
		return ret;
	conn->stage = "strap-adie-map";
	adie = ioremap(0x18001900, 4);
	if (!adie)
		return -ENOMEM;
	ret = op6893_conn_strap_guard(conn, csr, adie);
	if (ret)
		goto unmap_adie;
	conn->stage = "strap-ap-map";
	gpio = ioremap(0x10005000, 0x470);
	if (!gpio) {
		ret = -ENOMEM;
		goto unmap_adie;
	}
	io = ioremap(0x11ea0000, 0xd0);
	if (!io) {
		ret = -ENOMEM;
		goto unmap_gpio;
	}
	ret = op6893_conn_strap_sample(conn, gpio, io, 0);
	if (ret)
		goto unmap_io;
	/* Each state retains all CONN pins. No GPIO/raw-write bypass of ownership. */
	for (i = 0; i < 6; i++) {
		ret = op6893_conn_strap_guard(conn, csr, adie);
		if (ret)
			goto unmap_io;
		conn->stage = "strap-select-state";
		conn->strap_dirty = true;
		ret = pinctrl_select_state(conn->pins, i < 5 ?
					   conn->strap_pins[i] : conn->active_pins);
		/* A failure can leave partial hardware changes despite core rollback. */
		if (ret)
			goto unsafe;
		conn->strap_selected++;
		ret = op6893_conn_strap_guard(conn, csr, adie);
		if (ret)
			goto unmap_io;
		ret = op6893_conn_strap_sample(conn, gpio, io, i + 1);
		if (ret)
			goto unsafe;
		if (conn->prepare_requested && i == 1) {
			/* Keep GPIO output-high until the nested lock test has finished. */
			child = op6893_conn_sema_cycle(conn, csr);
			if (child && !conn->failure_stage)
				conn->failure_stage = conn->stage;
			if (conn->sema_pending || conn->sema_unsafe) {
				ret = child ?: -EUCLEAN;
				goto unsafe;
			}
		}
	}
	ret = op6893_conn_strap_guard(conn, csr, adie);
	if (ret)
		goto unmap_io;
	conn->strap_dirty = false;
	conn->strap_complete = true;
	goto unmap_io;
unsafe:
	conn->strap_unsafe = true;
unmap_io:
	iounmap(io);
unmap_gpio:
	iounmap(gpio);
unmap_adie:
	iounmap(adie);
	return child ?: ret;
}
