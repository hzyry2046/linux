/* SPDX-License-Identifier: GPL-2.0-only */
/* Bounded TOP transactions inside nested preparation and semaphore lifetime. */

static int op6893_conn_adie_guard(struct op6893_conn *conn, void __iomem *csr,
				 void __iomem *sema, void __iomem *adie,
				 void __iomem *wb, u32 expected)
{
	unsigned int i;
	u32 value;
	int ret;

	if (conn->adie_unsafe)
		return -EUCLEAN;
	ret = op6893_conn_check_off(conn, csr);
	if (ret)
		goto unsafe;
	conn->stage = "adie-reset-guard";
	conn->adie_control = readl(adie);
	if (conn->adie_control != expected) {
		ret = -EBUSY;
		goto unsafe;
	}
	/* Passive reports only: never reacquire through a second OWN_STA read. */
	for (i = 0; i < 4; i++) {
		ret = op6893_conn_check_off(conn, csr);
		if (ret)
			goto unsafe;
		conn->stage = "adie-owner-guard";
		value = readl(sema + 0x400 + i * 0x1000);
		if (!!(value & BIT(11)) != (i == 2)) {
			ret = -EBUSY;
			goto unsafe;
		}
	}
	ret = op6893_conn_check_off(conn, csr);
	if (ret)
		goto unsafe;
	conn->stage = "adie-wb-guard";
	conn->adie_wb = readl(wb);
	if (conn->adie_wb != 0x80000) {
		ret = -EBUSY;
		goto unsafe;
	}
	ret = op6893_conn_check_off(conn, csr);
	if (!ret)
		return 0;
unsafe:
	conn->adie_unsafe = true;
	return ret;
}

static int op6893_conn_adie_poll(struct op6893_conn *conn, void __iomem *csr,
				void __iomem *sema, void __iomem *adie,
				void __iomem *wb, void __iomem *spi, u32 expected)
{
	int ret = op6893_conn_adie_guard(conn, csr, sema, adie, wb, expected);

	if (ret)
		return ret;
	conn->stage = "adie-spi-busy";
	conn->adie_polls++;
	conn->adie_busy = readl(spi);
	if (conn->adie_busy & ~BIT(5)) {
		conn->adie_unsafe = true;
		return -EBUSY;
	}
	if (conn->adie_busy & BIT(5)) {
		if (conn->adie_efuse_active)
			conn->adie_efuse_spi_busy_seen = true;
		else if (conn->adie_efuse_ctrl_active)
			conn->adie_efuse_ctrl_busy_seen = true;
		else if (conn->adie_prefix_active)
			conn->adie_prefix_busy_seen = true;
		else if (conn->adie_config_active)
			conn->adie_config_busy_seen = true;
		else if (conn->adie_write_active)
			conn->adie_write_busy_seen = true;
		else if (conn->adie_xtal_active)
			conn->adie_xtal_busy_seen = true;
		else if (conn->adie_triggered)
			conn->adie_busy_seen = true;
	}
	return 0;
}

static int op6893_conn_adie_idle(struct op6893_conn *conn, void __iomem *csr,
				void __iomem *sema, void __iomem *adie,
				void __iomem *wb, void __iomem *spi, u32 expected)
{
	int ret, error;

	ret = read_poll_timeout(op6893_conn_adie_poll, error,
				error || !conn->adie_busy, 50, 20000, false,
				conn, csr, sema, adie, wb, spi, expected);
	ret = ret ?: error;
	if (!ret)
		ret = op6893_conn_adie_guard(conn, csr, sema, adie, wb, expected);
	if (ret)
		conn->adie_unsafe = true;
	return ret;
}

/* Fixed non-efuse addresses, used by the vendor XTAL read/modify/write path. */
static int op6893_conn_adie_xtal(struct op6893_conn *conn, void __iomem *csr,
				void __iomem *sema, void __iomem *adie,
				void __iomem *wb, void __iomem *spi)
{
	unsigned int i;
	int ret;

	for (i = 0; i < 2; i++) {
		u32 addr = 0xba18 + i * 4;

		conn->adie_xtal_active = false;
		conn->adie_xtal_busy_seen = false;
		ret = op6893_conn_adie_idle(conn, csr, sema, adie, wb, spi, 3);
		if (ret)
			return ret;
		conn->stage = "adie-xtal-baseline";
		conn->adie_xtal_before[i] = readl(spi + 0x58);
		ret = op6893_conn_adie_guard(conn, csr, sema, adie, wb, 3);
		if (ret)
			return ret;
		conn->stage = "adie-xtal-address";
		writel(addr, spi + 0x50);
		ret = op6893_conn_adie_guard(conn, csr, sema, adie, wb, 3);
		if (ret)
			return ret;
		conn->stage = "adie-xtal-address-readback";
		if (readl(spi + 0x50) != addr)
			return -EIO;
		ret = op6893_conn_adie_idle(conn, csr, sema, adie, wb, spi, 3);
		if (ret)
			return ret;
		conn->stage = "adie-xtal-trigger";
		conn->adie_xtal_active = true;
		writel(0, spi + 0x54);
		ret = op6893_conn_adie_idle(conn, csr, sema, adie, wb, spi, 3);
		if (ret)
			return ret;
		conn->stage = "adie-xtal-data";
		conn->adie_xtal_value[i] = readl(spi + 0x58);
		conn->adie_xtal_read |= BIT(i);
		if (conn->adie_xtal_busy_seen)
			conn->adie_xtal_busy_mask |= BIT(i);
		else if (conn->adie_xtal_value[i] == conn->adie_xtal_before[i])
			/* Do not reuse the ID transfer's busy pulse as evidence. */
			return -EAGAIN;
		conn->adie_xtal_valid |= BIT(i);
	}
	return 0;
}

/* Five fixed transfers: apply, readback, restore, ID separator, readback. */
static int op6893_conn_adie_transfer(struct op6893_conn *conn, void __iomem *csr,
				    void __iomem *sema, void __iomem *adie,
				    void __iomem *wb, void __iomem *spi,
				    unsigned int step)
{
	u32 addr, data = 0;
	unsigned int slot = 0;
	bool write = step == 0 || step == 2;
	int ret;

	conn->adie_write_step = step;
	conn->adie_xtal_active = false;
	conn->adie_write_active = false;
	conn->adie_write_busy_seen = false;
	addr = write ? 0xaa18 : (step == 3 ? 0xb02c : 0xba18);
	if (write)
		data = step == 0 ? 0xf6e8fff5 : conn->adie_xtal_value[0];
	else
		slot = step == 1 ? 0 : step - 2;
	ret = op6893_conn_adie_idle(conn, csr, sema, adie, wb, spi, 3);
	if (ret)
		return ret;
	if (!write) {
		conn->stage = "adie-write-data-baseline";
		conn->adie_write_before[slot] = readl(spi + 0x58);
		ret = op6893_conn_adie_guard(conn, csr, sema, adie, wb, 3);
		if (ret)
			return ret;
	}
	conn->stage = "adie-write-address";
	writel(addr, spi + 0x50);
	ret = op6893_conn_adie_guard(conn, csr, sema, adie, wb, 3);
	if (ret)
		return ret;
	conn->stage = "adie-write-address-readback";
	if (readl(spi + 0x50) != addr)
		return -EIO;
	ret = op6893_conn_adie_idle(conn, csr, sema, adie, wb, spi, 3);
	if (ret)
		return ret;
	conn->stage = "adie-write-trigger";
	conn->adie_write_active = true;
	if (write) {
		/* A failed or unobserved transfer may already have changed A-die. */
		conn->adie_write_dirty = true;
		conn->adie_write_issued |= BIT(step / 2);
	}
	writel(data, spi + 0x54);
	ret = op6893_conn_adie_idle(conn, csr, sema, adie, wb, spi, 3);
	conn->adie_write_active = false;
	if (ret)
		return ret;
	if (conn->adie_write_busy_seen)
		conn->adie_write_busy_mask |= BIT(step);
	if (write)
		return 0;
	conn->stage = "adie-write-data";
	conn->adie_write_value[slot] = readl(spi + 0x58);
	conn->adie_write_read |= BIT(slot);
	if (!conn->adie_write_busy_seen &&
	    conn->adie_write_value[slot] == conn->adie_write_before[slot])
		return -EAGAIN;
	return 0;
}

static int op6893_conn_adie_write_cycle(struct op6893_conn *conn, void __iomem *csr,
				      void __iomem *sema, void __iomem *adie,
				      void __iomem *wb, void __iomem *spi)
{
	int ret, cleanup;

	conn->stage = "adie-write-baseline-guard";
	/* Limit this first write experiment to the measured E3 configuration. */
	if (!conn->adie_id_valid || conn->adie_id != 0x66358a11 ||
	    conn->adie_xtal_valid != 3 || conn->adie_xtal_value[0] != 0xf668fff5 ||
	    conn->adie_xtal_value[1] != 0x55555fff)
		return -EINVAL;
	ret = op6893_conn_adie_transfer(conn, csr, sema, adie, wb, spi, 0);
	if (!ret)
		ret = op6893_conn_adie_transfer(conn, csr, sema, adie, wb, spi, 1);
	if (!ret) {
		conn->stage = "adie-write-apply-verify";
		if (conn->adie_write_value[0] != 0xf6e8fff5)
			ret = -EIO;
		else
			conn->adie_write_applied = true;
	}
	if (ret && !conn->failure_stage)
		conn->failure_stage = conn->stage;
	if (!conn->adie_write_dirty)
		return ret;
	/* Only the cleanup path is attempted after a failed apply, never a retry. */
	cleanup = op6893_conn_adie_transfer(conn, csr, sema, adie, wb, spi, 2);
	if (!cleanup)
		cleanup = op6893_conn_adie_transfer(conn, csr, sema, adie, wb, spi, 3);
	if (!cleanup) {
		conn->stage = "adie-write-separator-verify";
		if (conn->adie_write_value[1] != conn->adie_id)
			cleanup = -EIO;
	}
	if (!cleanup)
		cleanup = op6893_conn_adie_transfer(conn, csr, sema, adie, wb, spi, 4);
	if (!cleanup) {
		conn->stage = "adie-write-restore-verify";
		if (conn->adie_write_value[2] != conn->adie_xtal_value[0])
			cleanup = -EIO;
	}
	if (!cleanup)
		cleanup = op6893_conn_adie_idle(conn, csr, sema, adie, wb, spi, 3);
	conn->adie_write_cleanup = cleanup;
	if (cleanup) {
		if (!conn->failure_stage)
			conn->failure_stage = conn->stage;
		conn->adie_unsafe = true;
	} else {
		conn->adie_write_dirty = false;
		conn->adie_write_restored = true;
	}
	return ret ?: cleanup;
}

/* Retain the published ID throughout all analog configuration transfers. */
static int op6893_conn_adie_prefix_guard(struct op6893_conn *conn, void __iomem *csr,
					void __iomem *sema, void __iomem *adie,
					void __iomem *wb, void __iomem *spi,
					void __iomem *mailbox)
{
	int ret = op6893_conn_adie_idle(conn, csr, sema, adie, wb, spi, 3);

	if (ret)
		return ret;
	conn->stage = "adie-prefix-mailbox-guard";
	if (readl(mailbox) != conn->adie_id) {
		conn->adie_unsafe = true;
		return -EBUSY;
	}
	return op6893_conn_adie_guard(conn, csr, sema, adie, wb, 3);
}

static int op6893_conn_adie_prefix_transfer(struct op6893_conn *conn, void __iomem *csr,
					   void __iomem *sema, void __iomem *adie,
					   void __iomem *wb, void __iomem *spi,
					   void __iomem *mailbox, unsigned int step)
{
	static const struct {
		u32 addr;
		u32 data;
		int bit;
		int slot;
	} ops[] = {
		{ 0xa064, 0x7700, 0, -1 }, { 0xb064, 0, -1, 0 },
		{ 0xa0bc, 0x21, 1, -1 }, { 0xb0bc, 0, -1, 1 },
		{ 0xa0bc, 1, 1, -1 }, { 0xb02c, 0, -1, 2 }, { 0xb0bc, 0, -1, 3 },
		{ 0xa064, 0, 0, -1 }, { 0xb02c, 0, -1, 4 }, { 0xb064, 0, -1, 5 },
	};
	int slot = ops[step].slot;
	int ret;

	conn->adie_prefix_step = step;
	conn->adie_prefix_active = false;
	conn->adie_prefix_busy_seen = false;
	ret = op6893_conn_adie_prefix_guard(conn, csr, sema, adie, wb, spi, mailbox);
	if (ret)
		return ret;
	if (slot >= 0) {
		conn->stage = "adie-prefix-baseline";
		conn->adie_prefix_before[slot] = readl(spi + 0x58);
		ret = op6893_conn_adie_prefix_guard(conn, csr, sema, adie, wb, spi, mailbox);
		if (ret)
			return ret;
	}
	conn->stage = "adie-prefix-address";
	writel(ops[step].addr, spi + 0x50);
	ret = op6893_conn_adie_prefix_guard(conn, csr, sema, adie, wb, spi, mailbox);
	if (ret)
		return ret;
	conn->stage = "adie-prefix-address-readback";
	if (readl(spi + 0x50) != ops[step].addr)
		return -EIO;
	ret = op6893_conn_adie_prefix_guard(conn, csr, sema, adie, wb, spi, mailbox);
	if (ret)
		return ret;
	conn->stage = "adie-prefix-trigger";
	conn->adie_prefix_active = true;
	if (slot < 0) {
		conn->adie_prefix_dirty |= BIT(ops[step].bit);
		conn->adie_prefix_issued |= BIT(step);
	}
	writel(ops[step].data, spi + 0x54);
	ret = op6893_conn_adie_prefix_guard(conn, csr, sema, adie, wb, spi, mailbox);
	conn->adie_prefix_active = false;
	if (ret)
		return ret;
	if (conn->adie_prefix_busy_seen)
		conn->adie_prefix_busy_mask |= BIT(step);
	if (slot < 0)
		return 0;
	conn->stage = "adie-prefix-data";
	conn->adie_prefix_value[slot] = readl(spi + 0x58);
	conn->adie_prefix_read |= BIT(slot);
	if (!conn->adie_prefix_busy_seen &&
	    conn->adie_prefix_value[slot] == conn->adie_prefix_before[slot])
		return -EAGAIN;
	return 0;
}

/* Fixed digital baselines only; neither thermal triggers nor efuse reads. */
static int op6893_conn_adie_route_guard(struct op6893_conn *conn, void __iomem *csr,
				       void __iomem *sema, void __iomem *adie,
				       void __iomem *wb, void __iomem *spi,
				       void __iomem *mailbox)
{
	unsigned int i;
	int ret;

	/* Thermal uses semaphore13, distinct from the held RFSPI semaphore11. */
	for (i = 0; i < 4; i++) {
		ret = op6893_conn_adie_prefix_guard(conn, csr, sema, adie, wb, spi, mailbox);
		if (ret)
			return ret;
		conn->stage = "adie-route-owner";
		if (readl(sema + 0x400 + i * 0x1000) & BIT(13)) {
			conn->adie_unsafe = true;
			return -EBUSY;
		}
	}
	return op6893_conn_adie_prefix_guard(conn, csr, sema, adie, wb, spi, mailbox);
}

/* Recheck all sampled thermal words; never clear a trigger or acquire ownership. */
static int op6893_conn_adie_fm_guard(struct op6893_conn *conn, void __iomem *csr,
				    void __iomem *sema, void __iomem *adie,
				    void __iomem *wb, void __iomem *spi,
				    void __iomem *mailbox, void __iomem **regs)
{
	unsigned int i;
	int ret;

	for (i = 0; i < 4; i++) {
		ret = op6893_conn_adie_route_guard(conn, csr, sema, adie, wb, spi, mailbox);
		if (ret)
			return ret;
		conn->stage = "adie-fm-thermal";
		conn->adie_fm_thermal[i] = readl(regs[i + 1]);
		if (conn->adie_fm_thermal[i] != conn->adie_route_value[i + 1]) {
			conn->adie_unsafe = true;
			return -EBUSY;
		}
	}
	return op6893_conn_adie_route_guard(conn, csr, sema, adie, wb, spi, mailbox);
}

static int op6893_conn_adie_efuse_guard(struct op6893_conn *conn, void __iomem *csr,
				       void __iomem *sema, void __iomem *adie,
				       void __iomem *wb, void __iomem *spi,
				       void __iomem *mailbox, void __iomem **regs)
{
	int ret;

	ret = op6893_conn_adie_fm_guard(conn, csr, sema, adie, wb, spi, mailbox, regs);
	if (ret)
		return ret;
	conn->stage = "adie-efuse-fm-guard";
	if (readl(regs[0]) != conn->adie_fm_target) {
		conn->adie_unsafe = true;
		return -EBUSY;
	}
	return op6893_conn_adie_route_guard(conn, csr, sema, adie, wb, spi, mailbox);
}

/* ID, control, ID, control: no TOP write prefix or efuse data addresses. */
static int op6893_conn_adie_efuse_ctrl(struct op6893_conn *conn, void __iomem *csr,
				      void __iomem *sema, void __iomem *adie,
				      void __iomem *wb, void __iomem *spi,
				      void __iomem *mailbox, void __iomem **regs)
{
	unsigned int i;
	int ret;

	conn->stage = "adie-efuse-prerequisite";
	if (!conn->adie_fm_dirty || !conn->adie_fm_applied || conn->adie_fm_target ||
	    conn->adie_prefix_applied != 3 || conn->adie_prefix_dirty != 3 ||
	    !conn->adie_mailbox_dirty || !conn->adie_mailbox_applied)
		return -EINVAL;
	for (i = 0; i < 4; i++) {
		u32 addr = i & 1 ? 0xb108 : 0xb02c;
		u32 before, value;

		conn->adie_efuse_ctrl_active = false;
		conn->adie_efuse_ctrl_busy_seen = false;
		ret = op6893_conn_adie_efuse_guard(conn, csr, sema, adie, wb, spi, mailbox, regs);
		if (ret)
			return ret;
		conn->stage = "adie-efuse-before";
		before = readl(spi + 0x58);
		ret = op6893_conn_adie_efuse_guard(conn, csr, sema, adie, wb, spi, mailbox, regs);
		if (ret)
			return ret;
		conn->stage = "adie-efuse-address";
		writel(addr, spi + 0x50);
		ret = op6893_conn_adie_efuse_guard(conn, csr, sema, adie, wb, spi, mailbox, regs);
		if (ret)
			return ret;
		conn->stage = "adie-efuse-address-readback";
		if (readl(spi + 0x50) != addr)
			return -EIO;
		ret = op6893_conn_adie_efuse_guard(conn, csr, sema, adie, wb, spi, mailbox, regs);
		if (ret)
			return ret;
		conn->stage = "adie-efuse-read-trigger";
		conn->adie_efuse_ctrl_active = true;
		writel(0, spi + 0x54);
		ret = op6893_conn_adie_efuse_guard(conn, csr, sema, adie, wb, spi, mailbox, regs);
		conn->adie_efuse_ctrl_active = false;
		if (ret)
			return ret;
		conn->stage = "adie-efuse-response";
		value = readl(spi + 0x58);
		conn->adie_efuse_ctrl_value[i] = value;
		conn->adie_efuse_ctrl_read |= BIT(i);
		if (conn->adie_efuse_ctrl_busy_seen)
			conn->adie_efuse_ctrl_busy_mask |= BIT(i);
		else if (value == before)
			return -EAGAIN;
		if (!(i & 1)) {
			if (value != conn->adie_id)
				return -ENODEV;
		} else {
			conn->stage = "adie-efuse-control-state";
			/* An inherited kick or non-read mode is not ours to clear. */
			if ((value & (BIT(30) | 0xc0)) ||
			    (i == 3 && value != conn->adie_efuse_ctrl_value[1])) {
				conn->adie_unsafe = true;
				return -EBUSY;
			}
		}
		conn->adie_efuse_ctrl_valid |= BIT(i);
	}
	ret = op6893_conn_adie_efuse_guard(conn, csr, sema, adie, wb, spi, mailbox, regs);
	if (!ret)
		conn->adie_efuse_ctrl_stable = true;
	return ret;
}

/* Diagnostic wall-clock budget includes guards and confirmation transfers. */
#define OP6893_EFUSE_TIMEOUT_NS 250000000ULL

static int op6893_conn_adie_efuse_deadline(struct op6893_conn *conn)
{
	if (!conn->adie_efuse_pending)
		return 0;
	conn->adie_efuse_elapsed_ns = ktime_get_ns() - conn->adie_efuse_start_ns;
	if (conn->adie_efuse_elapsed_ns < OP6893_EFUSE_TIMEOUT_NS)
		return 0;
	conn->stage = "adie-efuse-deadline";
	conn->adie_unsafe = true;
	return -ETIMEDOUT;
}

static int op6893_conn_adie_efuse_engine_guard(struct op6893_conn *conn, void __iomem *csr,
					      void __iomem *sema, void __iomem *adie,
					      void __iomem *wb, void __iomem *spi,
					      void __iomem *mailbox, void __iomem **regs)
{
	int ret;

	ret = op6893_conn_adie_efuse_deadline(conn);
	if (!ret)
		ret = op6893_conn_adie_efuse_guard(conn, csr, sema, adie, wb, spi, mailbox, regs);
	if (!ret)
		ret = op6893_conn_adie_efuse_deadline(conn);
	return ret;
}

/* Only ID read, control read, or a single address0/read-mode kick. */
static int op6893_conn_adie_efuse_transfer(struct op6893_conn *conn, void __iomem *csr,
					 void __iomem *sema, void __iomem *adie,
					 void __iomem *wb, void __iomem *spi,
					 void __iomem *mailbox, void __iomem **regs,
					 unsigned int op)
{
	u32 addr, before, value;
	int ret;

	if (op > 2 || (op == 2 && conn->adie_efuse_issued))
		return -EINVAL;
	addr = op == 2 ? 0xa108 : op == 1 ? 0xb108 : 0xb02c;
	conn->adie_efuse_active = false;
	conn->adie_efuse_spi_busy_seen = false;
	ret = op6893_conn_adie_efuse_engine_guard(conn, csr, sema, adie, wb, spi, mailbox, regs);
	if (ret)
		return ret;
	conn->stage = "adie-efuse-engine-before";
	before = readl(spi + 0x58);
	ret = op6893_conn_adie_efuse_engine_guard(conn, csr, sema, adie, wb, spi, mailbox, regs);
	if (ret)
		return ret;
	conn->stage = "adie-efuse-engine-address";
	writel(addr, spi + 0x50);
	ret = op6893_conn_adie_efuse_engine_guard(conn, csr, sema, adie, wb, spi, mailbox, regs);
	if (ret)
		return ret;
	conn->stage = "adie-efuse-engine-address-readback";
	if (readl(spi + 0x50) != addr)
		return -EIO;
	ret = op6893_conn_adie_efuse_engine_guard(conn, csr, sema, adie, wb, spi, mailbox, regs);
	if (ret)
		return ret;
	conn->stage = "adie-efuse-engine-trigger";
	conn->adie_efuse_active = true;
	value = 0;
	if (op == 2) {
		/* Prerequisite requires mode/address/kick/valid zero; preserve other bits. */
		value = conn->adie_efuse_ctrl_value[3] | BIT(30);
		conn->adie_efuse_start_ns = ktime_get_ns();
		conn->adie_efuse_pending = true;
		conn->adie_efuse_issued = true;
	}
	conn->adie_efuse_transfers++;
	writel(value, spi + 0x54);
	ret = op6893_conn_adie_efuse_engine_guard(conn, csr, sema, adie, wb, spi, mailbox, regs);
	conn->adie_efuse_active = false;
	if (ret)
		return ret;
	if (conn->adie_efuse_spi_busy_seen)
		conn->adie_efuse_spi_busy_count++;
	if (op == 2)
		return 0;
	conn->stage = "adie-efuse-engine-response";
	value = readl(spi + 0x58);
	if (!conn->adie_efuse_spi_busy_seen && value == before)
		return -EAGAIN;
	if (!op)
		return value == conn->adie_id ? 0 : -ENODEV;
	conn->adie_efuse_last = value;
	conn->adie_efuse_polls++;
	return 0;
}

static int op6893_conn_adie_efuse_cycle(struct op6893_conn *conn, void __iomem *csr,
				       void __iomem *sema, void __iomem *adie,
				       void __iomem *wb, void __iomem *spi,
				       void __iomem *mailbox, void __iomem **regs)
{
	unsigned int i;
	u32 value;
	int ret;

	conn->stage = "adie-efuse-engine-prerequisite";
	if (!conn->adie_efuse_ctrl_stable || conn->adie_efuse_ctrl_valid != 0xf ||
	    (conn->adie_efuse_ctrl_value[3] & 0x63ff00c0) ||
	    !conn->adie_fm_dirty || !conn->adie_fm_applied)
		return -EINVAL;
	ret = op6893_conn_adie_efuse_transfer(conn, csr, sema, adie, wb, spi, mailbox, regs, 2);
	if (ret)
		goto done;
	for (i = 0; i < (conn->adie_efuse_observe ? 3 : 70); i++) {
		ret = op6893_conn_adie_efuse_transfer(conn, csr, sema, adie, wb, spi, mailbox, regs, 0);
		if (ret)
			break;
		ret = op6893_conn_adie_efuse_transfer(conn, csr, sema, adie, wb, spi, mailbox, regs, 1);
		if (ret)
			break;
		ret = op6893_conn_adie_efuse_engine_guard(conn, csr, sema, adie, wb, spi, mailbox, regs);
		if (ret)
			break;
		conn->stage = "adie-efuse-engine-state";
		value = conn->adie_efuse_last;
		/* Report changed positions, never the original or resulting private bits. */
		conn->adie_efuse_changed = (value ^ conn->adie_efuse_ctrl_value[3]) &
					   ~(BIT(30) | BIT(29));
		if (conn->adie_efuse_observe) {
			/* Low-six-bit exception is empirical for this E3 diagnostic path. */
			conn->stage = "adie-efuse-observe-state";
			conn->adie_efuse_observe_delta[i] = conn->adie_efuse_changed;
			conn->adie_efuse_observed++;
			if ((conn->adie_efuse_changed & ~0x3f) ||
			    (value & (BIT(30) | BIT(29))) != BIT(29) ||
			    (i && conn->adie_efuse_changed != conn->adie_efuse_observe_delta[0])) {
				ret = -EIO;
				break;
			}
			if (i == 2) {
				conn->adie_efuse_observe_stable = true;
				if (conn->adie_efuse_stable_cycle) {
					conn->adie_efuse_confirmed = 3;
					conn->adie_efuse_pending = false;
					conn->adie_efuse_complete = true;
					return 0;
				}
				conn->stage = "adie-efuse-observe-held";
				ret = -EUCLEAN;
				break;
			}
			udelay(30);
			continue;
		}
		if (conn->adie_efuse_changed) {
			ret = -EIO;
			break;
		}
		if (value & BIT(30)) {
			conn->adie_efuse_busy_seen = true;
			conn->adie_efuse_confirmed = 0;
		} else if (value & BIT(29)) {
			if (++conn->adie_efuse_confirmed == 2) {
				conn->adie_efuse_pending = false;
				conn->adie_efuse_complete = true;
				return 0;
			}
		} else {
			conn->adie_efuse_confirmed = 0;
			if (conn->adie_efuse_busy_seen) {
				ret = -ENODATA;
				break;
			}
		}
		udelay(30);
	}
	if (!ret) {
		conn->stage = "adie-efuse-poll-limit";
		ret = -ETIMEDOUT;
	}
done:
	/* Never replay a kick or speculate about cancellation after an uncertain read. */
	if (conn->adie_efuse_pending)
		conn->adie_unsafe = true;
	return ret;
}

/* Prerequisite phase keeps the original 2 s budget measured from the data start. */
#define OP6893_EFUSE_DATA_TIMEOUT_NS 2000000000ULL
/* Pad stage gets its own 2 s phase measured from pad entry. */
#define OP6893_PAD_DATA_TIMEOUT_NS 2000000000ULL
/* Six-register config reads (~2.6 s at ~48-55 ms per transfer) get 4 s from entry. */
#define OP6893_CFG_DATA_TIMEOUT_NS 4000000000ULL
/* Register write-cycle stages (cal, ir) get 3 s each measured from their entry. */
#define OP6893_CYCLE_DATA_TIMEOUT_NS 3000000000ULL
/* One shared global cap across all phases; the global start is never reset. */
#define OP6893_DATA_TOTAL_CAP_NS 8000000000ULL

/* Stage boundary: the phase clock restarts per stage; the global start never resets. */
static void op6893_conn_adie_phase_begin(struct op6893_conn *conn, unsigned int phase,
					u64 budget_ns)
{
	conn->adie_efuse_data_phase = phase;
	conn->adie_efuse_data_phase_start_ns = ktime_get_ns();
	conn->adie_efuse_data_phase_budget_ns = budget_ns;
}

static int op6893_conn_adie_data_guard(struct op6893_conn *conn, void __iomem *csr,
				      void __iomem *sema, void __iomem *adie,
				      void __iomem *wb, void __iomem *spi,
				      void __iomem *mailbox, void __iomem **regs)
{
	unsigned int i;
	int ret;

	for (i = 0; i < 2; i++) {
		u64 now = ktime_get_ns();

		conn->adie_efuse_data_elapsed_ns = now - conn->adie_efuse_data_start_ns;
		conn->adie_efuse_data_phase_elapsed_ns = now - conn->adie_efuse_data_phase_start_ns;
		if (conn->adie_efuse_data_elapsed_ns >= OP6893_DATA_TOTAL_CAP_NS ||
		    conn->adie_efuse_data_phase_elapsed_ns >= conn->adie_efuse_data_phase_budget_ns) {
			conn->stage = "adie-efuse-data-deadline";
			return -ETIMEDOUT;
		}
		if (!i) {
			ret = op6893_conn_adie_efuse_guard(conn, csr, sema, adie, wb, spi, mailbox, regs);
			if (ret)
				return ret;
		}
	}
	return 0;
}

/* Fixed ID, control, efuse-result and optional thermal read addresses only. */
static int op6893_conn_adie_data_transfer(struct op6893_conn *conn, void __iomem *csr,
					 void __iomem *sema, void __iomem *adie,
					 void __iomem *wb, void __iomem *spi,
					 void __iomem *mailbox, void __iomem **regs,
					 unsigned int op, unsigned int bit, u32 *result)
{
	static const u32 cfg_addrs[] = { 0xb380, 0xb384, 0xb390, 0xb394, 0xba18, 0xba1c };
	struct {
		u32 before;
		u32 value;
	} sample = {};
	u32 addr;
	int ret;

	if (op > 14 || bit > 15 || (op >= 2 && !result))
		return -EINVAL;
	if (conn->adie_ir_started) {
		if (!conn->adie_ir_cycle_requested || bit > 2 ||
		    (op >= 2 && op != 10 && op != 12 && op != 13))
			return -EINVAL;
	} else if (conn->adie_cal_started) {
		if (!conn->adie_cal_cycle_requested || bit > 1 || (op >= 2 && op != 9 && op != 11))
			return -EINVAL;
	} else if (conn->adie_cfg_started) {
		if (!conn->adie_cfg_requested || bit > 11 || (op >= 2 && (op < 9 || op > 14)))
			return -EINVAL;
	} else if (conn->adie_pad_started) {
		if (!conn->adie_pad_requested || bit > 1 || (op >= 2 && op != 8))
			return -EINVAL;
	} else if (conn->adie_thermal_started) {
		if (!conn->adie_thermal_requested || bit > 3 || op > 7 || (op >= 2 && op < 6))
			return -EINVAL;
	} else if (op > 5) {
		return -EINVAL;
	}
	addr = !op ? 0xb02c : op == 1 ? 0xb108 :
		op < 6 ? 0xb130 + (op - 2) * 4 : op < 8 ? 0xb034 + (op - 6) * 4 :
		op == 8 ? 0xb070 : cfg_addrs[op - 9];
	conn->adie_efuse_active = false;
	conn->adie_efuse_spi_busy_seen = false;
	ret = op6893_conn_adie_data_guard(conn, csr, sema, adie, wb, spi, mailbox, regs);
	if (ret)
		goto out;
	conn->stage = "adie-efuse-data-before";
	sample.before = readl(spi + 0x58);
	ret = op6893_conn_adie_data_guard(conn, csr, sema, adie, wb, spi, mailbox, regs);
	if (ret)
		goto out;
	conn->stage = "adie-efuse-data-address";
	writel(addr, spi + 0x50);
	ret = op6893_conn_adie_data_guard(conn, csr, sema, adie, wb, spi, mailbox, regs);
	if (ret)
		goto out;
	conn->stage = "adie-efuse-data-address-readback";
	if (readl(spi + 0x50) != addr) {
		ret = -EIO;
		goto out;
	}
	ret = op6893_conn_adie_data_guard(conn, csr, sema, adie, wb, spi, mailbox, regs);
	if (ret)
		goto out;
	conn->stage = "adie-efuse-data-trigger";
	conn->adie_efuse_active = true;
	if (conn->adie_ir_started) {
		conn->adie_ir_transfers++;
		if (op >= 9)
			conn->adie_ir_issued |= BIT(bit);
	} else if (conn->adie_cal_started) {
		conn->adie_cal_transfers++;
		if (op >= 9)
			conn->adie_cal_issued |= BIT(bit);
	} else if (conn->adie_cfg_started) {
		conn->adie_cfg_transfers++;
		if (op >= 9)
			conn->adie_cfg_issued |= BIT(bit);
	} else if (conn->adie_pad_started) {
		conn->adie_pad_transfers++;
		if (op == 8)
			conn->adie_pad_issued |= BIT(bit);
	} else if (conn->adie_thermal_started) {
		conn->adie_thermal_transfers++;
		if (op >= 6)
			conn->adie_thermal_issued |= BIT(bit);
	} else {
		conn->adie_efuse_data_transfers++;
		if (op >= 2)
			conn->adie_efuse_data_issued |= BIT(bit);
	}
	writel(0, spi + 0x54);
	ret = op6893_conn_adie_data_guard(conn, csr, sema, adie, wb, spi, mailbox, regs);
	conn->adie_efuse_active = false;
	if (ret)
		goto out;
	if (conn->adie_efuse_spi_busy_seen) {
		if (conn->adie_ir_started)
			conn->adie_ir_busy_count++;
		else if (conn->adie_cal_started)
			conn->adie_cal_busy_count++;
		else if (conn->adie_cfg_started)
			conn->adie_cfg_busy_count++;
		else if (conn->adie_pad_started)
			conn->adie_pad_busy_count++;
		else if (conn->adie_thermal_started)
			conn->adie_thermal_busy_count++;
		else
			conn->adie_efuse_data_busy_count++;
	}
	conn->stage = "adie-efuse-data-response";
	sample.value = readl(spi + 0x58);
	if (!conn->adie_efuse_spi_busy_seen && sample.value == sample.before) {
		ret = -EAGAIN;
		goto out;
	}
	if (!op)
		ret = sample.value == conn->adie_id ? 0 : -ENODEV;
	else if (op == 1)
		ret = sample.value == conn->adie_efuse_last ? 0 : -EIO;
	else {
		*result = sample.value;
		if (conn->adie_ir_started)
			conn->adie_ir_read |= BIT(bit);
		else if (conn->adie_cal_started)
			conn->adie_cal_read |= BIT(bit);
		else if (conn->adie_cfg_started)
			conn->adie_cfg_read |= BIT(bit);
		else if (conn->adie_pad_started)
			conn->adie_pad_read |= BIT(bit);
		else if (conn->adie_thermal_started)
			conn->adie_thermal_read |= BIT(bit);
		else
			conn->adie_efuse_data_read |= BIT(bit);
	}
out:
	memzero_explicit(&sample, sizeof(sample));
	return ret;
}

/* Four private software-control slots only; verified erase precedes parent cleanup. */
static int op6893_conn_adie_handoff(struct op6893_conn *conn, void __iomem *csr,
				    void __iomem *sema, void __iomem *adie,
				    void __iomem *wb, void __iomem *spi,
				    void __iomem *mailbox, void __iomem **regs,
				    const u32 *words)
{
	void __iomem *slots;
	unsigned int i;
	int ret = -ENOMEM;

	conn->stage = "adie-efuse-handoff-map";
	slots = ioremap(0x18052804, 16);
	if (!slots)
		return ret;
	for (i = 0; i < 4; i++) {
		ret = op6893_conn_adie_data_guard(conn, csr, sema, adie, wb, spi, mailbox, regs);
		if (ret)
			goto out;
		conn->stage = "adie-efuse-handoff-baseline";
		if (readl(slots + i * 4)) {
			ret = -EBUSY;
			goto out;
		}
	}
	for (i = 0; i < 4; i++) {
		ret = op6893_conn_adie_data_guard(conn, csr, sema, adie, wb, spi, mailbox, regs);
		if (ret)
			goto out;
		conn->stage = "adie-efuse-handoff-write";
		conn->adie_efuse_handoff_dirty |= BIT(i);
		conn->adie_efuse_handoff_issued |= BIT(i);
		writel(words[i], slots + i * 4);
		ret = op6893_conn_adie_data_guard(conn, csr, sema, adie, wb, spi, mailbox, regs);
		if (ret)
			goto out;
		conn->stage = "adie-efuse-handoff-readback";
		if (readl(slots + i * 4) != words[i]) {
			ret = -EIO;
			goto out;
		}
		conn->adie_efuse_handoff_verified |= BIT(i);
	}
	for (i = 0; i < 4; i++) {
		ret = op6893_conn_adie_data_guard(conn, csr, sema, adie, wb, spi, mailbox, regs);
		if (ret)
			goto out;
		conn->stage = "adie-efuse-handoff-clear";
		writel(0, slots + i * 4);
		ret = op6893_conn_adie_data_guard(conn, csr, sema, adie, wb, spi, mailbox, regs);
		if (ret)
			goto out;
		conn->stage = "adie-efuse-handoff-clear-readback";
		if (readl(slots + i * 4)) {
			ret = -EIO;
			goto out;
		}
		conn->adie_efuse_handoff_cleared |= BIT(i);
	}
	/* Recheck the entire group before permitting mailbox/reset/power cleanup. */
	for (i = 0; i < 4; i++) {
		ret = op6893_conn_adie_data_guard(conn, csr, sema, adie, wb, spi, mailbox, regs);
		if (ret)
			goto out;
		conn->stage = "adie-efuse-handoff-final";
		if (readl(slots + i * 4)) {
			ret = -EIO;
			goto out;
		}
	}
	ret = op6893_conn_adie_data_guard(conn, csr, sema, adie, wb, spi, mailbox, regs);
	if (!ret) {
		conn->adie_efuse_handoff_dirty = 0;
		conn->adie_efuse_handoff_complete = true;
	}
out:
	iounmap(slots);
	return ret;
}

/* Compare candidate sequences privately; this helper performs no hardware access. */
static void op6893_conn_adie_trim_plan(struct op6893_conn *conn, const u32 *efuse,
				     const u32 *baseline)
{
	static const struct {
		u8 valid, word, dst, src, width;
	} steps[] = {
		{ 7, 0, 12, 3, 4 },
		{ 7, 1, 23, 0, 3 },
		{ 15, 1, 26, 13, 2 },
	};
	struct {
		u32 vendor[2], bounded[2];
		u32 mask, vendor_next, bounded_next;
	} private = {};
	unsigned int i, word;

	private.vendor[0] = private.bounded[0] = baseline[0];
	private.vendor[1] = private.bounded[1] = baseline[1];
	conn->adie_trim_vendor_noop = true;
	conn->adie_trim_bounded_noop = true;
	conn->adie_trim_equivalent = true;
	for (i = 0; i < ARRAY_SIZE(steps); i++) {
		if (!(*efuse & BIT(steps[i].valid)))
			continue;
		word = steps[i].word;
		private.mask = ((1U << steps[i].width) - 1) << steps[i].dst;
		private.vendor_next = (private.vendor[word] & ~private.mask) |
			(((*efuse >> steps[i].src) & ((1U << (steps[i].width + 1)) - 1)) <<
			 steps[i].dst);
		private.bounded_next = (private.bounded[word] & ~private.mask) |
			(((*efuse >> steps[i].src) & ((1U << steps[i].width) - 1)) <<
			 steps[i].dst);
		/* A transient change is not a no-op even if a later step undoes it. */
		conn->adie_trim_vendor_noop &= private.vendor_next == private.vendor[word];
		conn->adie_trim_bounded_noop &= private.bounded_next == private.bounded[word];
		conn->adie_trim_equivalent &= private.vendor_next == private.bounded_next;
		private.vendor[word] = private.vendor_next;
		private.bounded[word] = private.bounded_next;
	}
	memzero_explicit(&private, sizeof(private));
	conn->adie_trim_plan_cleared = true;
}

/* One fixed write plus verify sequence, shared by the pad and cal cycles. */
static int op6893_conn_adie_write_verify(struct op6893_conn *conn, void __iomem *csr,
					 void __iomem *sema, void __iomem *adie,
					 void __iomem *wb, void __iomem *spi,
					 void __iomem *mailbox, void __iomem **regs,
					 u32 addr, u32 value, unsigned int op,
					 unsigned int bit)
{
	struct {
		u32 value;
	} data = {};
	int ret;

	ret = op6893_conn_adie_data_guard(conn, csr, sema, adie, wb, spi, mailbox, regs);
	if (ret)
		goto out;
	conn->stage = "adie-pad-write-address";
	writel(addr, spi + 0x50);
	ret = op6893_conn_adie_data_guard(conn, csr, sema, adie, wb, spi, mailbox, regs);
	if (ret)
		goto out;
	if (readl(spi + 0x50) != addr) {
		ret = -EIO;
		goto out;
	}
	ret = op6893_conn_adie_data_guard(conn, csr, sema, adie, wb, spi, mailbox, regs);
	if (ret)
		goto out;
	conn->stage = "adie-pad-write-trigger";
	if (conn->adie_ir_started) {
		conn->adie_ir_dirty |= BIT(bit);
		conn->adie_ir_write_issued |= BIT(bit);
		conn->adie_ir_transfers++;
	} else if (conn->adie_cal_started) {
		conn->adie_cal_dirty |= BIT(bit);
		conn->adie_cal_write_issued |= BIT(bit);
		conn->adie_cal_transfers++;
	} else {
		conn->adie_pad_dirty = true;
		conn->adie_pad_write_issued |= BIT(bit);
		conn->adie_pad_transfers++;
	}
	conn->adie_efuse_spi_busy_seen = false;
	conn->adie_efuse_active = true;
	writel(value, spi + 0x54);
	ret = op6893_conn_adie_data_guard(conn, csr, sema, adie, wb, spi, mailbox, regs);
	conn->adie_efuse_active = false;
	if (ret)
		goto out;
	if (conn->adie_efuse_spi_busy_seen) {
		if (conn->adie_ir_started)
			conn->adie_ir_busy_count++;
		else if (conn->adie_cal_started)
			conn->adie_cal_busy_count++;
		else
			conn->adie_pad_busy_count++;
	}
	ret = op6893_conn_adie_data_transfer(conn, csr, sema, adie, wb, spi,
					     mailbox, regs, 0, bit, NULL);
	if (ret)
		goto out;
	ret = op6893_conn_adie_data_transfer(conn, csr, sema, adie, wb, spi,
					     mailbox, regs, op, bit, &data.value);
	if (ret)
		goto out;
	conn->stage = "adie-pad-write-compare";
	if (data.value != value) {
		ret = -EIO;
		goto out;
	}
	ret = op6893_conn_adie_data_transfer(conn, csr, sema, adie, wb, spi,
					     mailbox, regs, 0, bit, NULL);
	if (ret)
		goto out;
	ret = op6893_conn_adie_data_transfer(conn, csr, sema, adie, wb, spi,
					     mailbox, regs, 1, bit, NULL);
	if (ret)
		goto out;
	ret = op6893_conn_adie_data_guard(conn, csr, sema, adie, wb, spi, mailbox, regs);
out:
	memzero_explicit(&data, sizeof(data));
	return ret;
}

/* Fixed public values only; never replay an arbitrary analog baseline. */
static int op6893_conn_adie_pad_cycle(struct op6893_conn *conn, void __iomem *csr,
				    void __iomem *sema, void __iomem *adie,
				    void __iomem *wb, void __iomem *spi,
				    void __iomem *mailbox, void __iomem **regs)
{
	unsigned int step;
	int ret;

	for (step = 0; step < 2; step++) {
		ret = op6893_conn_adie_write_verify(conn, csr, sema, adie, wb, spi, mailbox,
						    regs, 0xa070, step ? 0x0 : 0x80000000, 8,
						    step);
		if (ret)
			goto out;
		if (!step) {
			conn->adie_pad_applied = true;
		} else {
			conn->adie_pad_restored = true;
			conn->adie_pad_dirty = false;
		}
	}
out:
	/* Any failure retains all parents; no speculative analog recovery. */
	if (ret)
		conn->adie_unsafe = true;
	return ret;
}

/* Observe TOP070 twice before any optional fixed-value write cycle. */
static int op6893_conn_adie_pad_read(struct op6893_conn *conn, void __iomem *csr,
				   void __iomem *sema, void __iomem *adie,
				   void __iomem *wb, void __iomem *spi,
				   void __iomem *mailbox, void __iomem **regs)
{
	struct {
		u32 first;
		u32 value;
	} data = {};
	unsigned int round;
	int ret = -EOPNOTSUPP;

	conn->stage = "adie-pad-noop-prerequisite";
	if (!conn->adie_trim_plan_complete || !conn->adie_trim_plan_cleared ||
	    !conn->adie_trim_vendor_noop || !conn->adie_trim_bounded_noop ||
	    !conn->adie_trim_equivalent)
		goto out;
	conn->adie_pad_started = true;
	op6893_conn_adie_phase_begin(conn, 2, OP6893_PAD_DATA_TIMEOUT_NS);
	for (round = 0; round < 2; round++) {
		ret = op6893_conn_adie_data_transfer(conn, csr, sema, adie, wb, spi,
						 mailbox, regs, 0, round, NULL);
		if (ret)
			goto out;
		ret = op6893_conn_adie_data_transfer(conn, csr, sema, adie, wb, spi,
						 mailbox, regs, 8, round, &data.value);
		if (ret)
			goto out;
		ret = op6893_conn_adie_data_transfer(conn, csr, sema, adie, wb, spi,
						 mailbox, regs, 0, round, NULL);
		if (ret)
			goto out;
		ret = op6893_conn_adie_data_transfer(conn, csr, sema, adie, wb, spi,
						 mailbox, regs, 1, round, NULL);
		if (ret)
			goto out;
		conn->stage = "adie-pad-compare";
		if (!round) {
			data.first = data.value;
		} else if (data.first != data.value) {
			ret = -EIO;
			goto out;
		} else {
			conn->adie_pad_matched = true;
		}
	}
	ret = op6893_conn_adie_data_guard(conn, csr, sema, adie, wb, spi, mailbox, regs);
	if (ret)
		goto out;
	conn->adie_pad_target_match = data.first == 0x80000000;
	conn->adie_pad_value = data.first;
	conn->adie_pad_value_valid = true;
	conn->adie_pad_baseline_supported = data.first == 0x0;
	if (conn->adie_pad_cycle_requested) {
		conn->stage = "adie-pad-baseline-prerequisite";
		if (!conn->adie_pad_baseline_supported) {
			ret = -EOPNOTSUPP;
			goto out;
		}
		ret = op6893_conn_adie_pad_cycle(conn, csr, sema, adie, wb, spi, mailbox, regs);
	}
	if (!ret)
		conn->adie_pad_complete = true;
out:
	memzero_explicit(&data, sizeof(data));
	conn->adie_pad_cleared = true;
	if (ret)
		conn->adie_unsafe = true;
	return ret;
}

/* Vendor-fixed whole-word config baselines; two matching reads each, no writes. */
static int op6893_conn_adie_cfg_read(struct op6893_conn *conn, void __iomem *csr,
				   void __iomem *sema, void __iomem *adie,
				   void __iomem *wb, void __iomem *spi,
				   void __iomem *mailbox, void __iomem **regs)
{
	static const u32 targets[] = { 0xe8002, 0x2008, 0xe8002, 0x2008, 0xf6e8fff5,
				       0x55555fff };
	struct {
		u32 first[6];
		u32 value;
	} data = {};
	unsigned int round, reg;
	int ret = -EOPNOTSUPP;

	conn->stage = "adie-cfg-prerequisite";
	if (!conn->adie_pad_complete)
		goto out;
	conn->adie_cfg_started = true;
	op6893_conn_adie_phase_begin(conn, 3, OP6893_CFG_DATA_TIMEOUT_NS);
	for (reg = 0; reg < 6; reg++) {
		for (round = 0; round < 2; round++) {
			ret = op6893_conn_adie_data_transfer(conn, csr, sema, adie, wb, spi,
							 mailbox, regs, 0, reg * 2 + round,
							 NULL);
			if (ret)
				goto out;
			ret = op6893_conn_adie_data_transfer(conn, csr, sema, adie, wb, spi,
							 mailbox, regs, 9 + reg,
							 reg * 2 + round, &data.value);
			if (ret)
				goto out;
			ret = op6893_conn_adie_data_transfer(conn, csr, sema, adie, wb, spi,
							 mailbox, regs, 0, reg * 2 + round,
							 NULL);
			if (ret)
				goto out;
			ret = op6893_conn_adie_data_transfer(conn, csr, sema, adie, wb, spi,
							 mailbox, regs, 1, reg * 2 + round,
							 NULL);
			if (ret)
				goto out;
			conn->stage = "adie-cfg-compare";
			if (!round)
				data.first[reg] = data.value;
			else if (data.first[reg] != data.value) {
				ret = -EIO;
				goto out;
			} else {
				conn->adie_cfg_matched |= BIT(reg);
			}
		}
	}
	ret = op6893_conn_adie_data_guard(conn, csr, sema, adie, wb, spi, mailbox, regs);
	if (ret)
		goto out;
	for (reg = 0; reg < 6; reg++) {
		conn->adie_cfg_value[reg] = data.first[reg];
		if (data.first[reg] == targets[reg])
			conn->adie_cfg_target_match |= BIT(reg);
	}
	conn->adie_cfg_valid = true;
	if (!ret)
		conn->adie_cfg_complete = true;
out:
	memzero_explicit(&data, sizeof(data));
	conn->adie_cfg_cleared = true;
	if (ret)
		conn->adie_unsafe = true;
	return ret;
}

/* Apply the vendor target then restore the measured baseline on one register. */
static int op6893_conn_adie_reg_cycle(struct op6893_conn *conn, void __iomem *csr,
				      void __iomem *sema, void __iomem *adie,
				      void __iomem *wb, void __iomem *spi,
				      void __iomem *mailbox, void __iomem **regs,
				      u32 addr, unsigned int op, unsigned int bit,
				      u32 target, u32 restore)
{
	int ret;

	ret = op6893_conn_adie_write_verify(conn, csr, sema, adie, wb, spi, mailbox,
					    regs, addr, target, op, bit);
	if (ret)
		return ret;
	if (conn->adie_ir_started)
		conn->adie_ir_applied |= BIT(bit);
	else
		conn->adie_cal_applied |= BIT(bit);
	ret = op6893_conn_adie_write_verify(conn, csr, sema, adie, wb, spi, mailbox,
					    regs, addr, restore, op, bit);
	if (ret)
		return ret;
	if (conn->adie_ir_started) {
		conn->adie_ir_restored |= BIT(bit);
		conn->adie_ir_dirty &= ~BIT(bit);
	} else {
		conn->adie_cal_restored |= BIT(bit);
		conn->adie_cal_dirty &= ~BIT(bit);
	}
	return 0;
}

/* Vendor CAL-LDO words on the two registers this board measured; no speculative writes. */
static int op6893_conn_adie_cal_cycle(struct op6893_conn *conn, void __iomem *csr,
				      void __iomem *sema, void __iomem *adie,
				      void __iomem *wb, void __iomem *spi,
				      void __iomem *mailbox, void __iomem **regs)
{
	static const u32 gate[] = { 0xe0002, 0x8, 0xe0002, 0x8 };
	static const struct {
		u32 addr;
		unsigned int op;
		u32 target;
		u32 restore;
	} steps[2] = {
		{ 0xa380, 9, 0xe8002, 0xe0002 },
		{ 0xa390, 11, 0xe8002, 0xe0002 },
	};
	unsigned int reg, i;
	int ret = -EOPNOTSUPP;

	conn->stage = "adie-cal-prerequisite";
	if (!conn->adie_pad_complete || !conn->adie_cfg_complete || !conn->adie_cfg_valid)
		goto out;
	for (i = 0; i < 4; i++) {
		if (conn->adie_cfg_value[i] != gate[i]) {
			ret = -EOPNOTSUPP;
			goto out;
		}
	}
	conn->adie_cal_gate_ok = true;
	conn->adie_cal_started = true;
	op6893_conn_adie_phase_begin(conn, 4, OP6893_CYCLE_DATA_TIMEOUT_NS);
	for (reg = 0; reg < 2; reg++) {
		ret = op6893_conn_adie_reg_cycle(conn, csr, sema, adie, wb, spi, mailbox,
					       regs, steps[reg].addr, steps[reg].op, reg,
					       steps[reg].target, steps[reg].restore);
		if (ret)
			goto out;
	}
	if (!ret)
		conn->adie_cal_complete = true;
out:
	/* Any failure retains all parents; no speculative analog recovery. */
	if (ret)
		conn->adie_unsafe = true;
	return ret;
}

/* THADC IR words in vendor order A18, 384, 394; TOPA1C already equals its target. */
static int op6893_conn_adie_ir_cycle(struct op6893_conn *conn, void __iomem *csr,
				     void __iomem *sema, void __iomem *adie,
				     void __iomem *wb, void __iomem *spi,
				     void __iomem *mailbox, void __iomem **regs)
{
	static const u32 gate[] = { 0xe0002, 0x8, 0xe0002, 0x8, 0xf668fff5,
				    0x55555fff };
	static const struct {
		u32 addr;
		unsigned int op;
		u32 target;
		u32 restore;
	} steps[3] = {
		{ 0xaa18, 13, 0xf6e8fff5, 0xf668fff5 },
		{ 0xa384, 10, 0x2008, 0x8 },
		{ 0xa394, 12, 0x2008, 0x8 },
	};
	unsigned int reg, i;
	int ret = -EOPNOTSUPP;

	conn->stage = "adie-ir-prerequisite";
	if (!conn->adie_pad_complete || !conn->adie_cfg_complete || !conn->adie_cfg_valid)
		goto out;
	for (i = 0; i < 6; i++) {
		if (conn->adie_cfg_value[i] != gate[i]) {
			ret = -EOPNOTSUPP;
			goto out;
		}
	}
	conn->adie_ir_gate_ok = true;
	conn->adie_ir_started = true;
	op6893_conn_adie_phase_begin(conn, 5, OP6893_CYCLE_DATA_TIMEOUT_NS);
	for (reg = 0; reg < 3; reg++) {
		ret = op6893_conn_adie_reg_cycle(conn, csr, sema, adie, wb, spi, mailbox,
					       regs, steps[reg].addr, steps[reg].op, reg,
					       steps[reg].target, steps[reg].restore);
		if (ret)
			goto out;
	}
	if (!ret)
		conn->adie_ir_complete = true;
out:
	/* Any failure retains all parents; no speculative analog recovery. */
	if (ret)
		conn->adie_unsafe = true;
	return ret;
}

/* Baselines can contain inherited calibration: keep even read-only values private. */
static int op6893_conn_adie_thermal_read(struct op6893_conn *conn, void __iomem *csr,
				       void __iomem *sema, void __iomem *adie,
				       void __iomem *wb, void __iomem *spi,
				       void __iomem *mailbox, void __iomem **regs,
				       const u32 *efuse)
{
	struct {
		u32 words[2];
		u32 value;
	} data = {};
	unsigned int round, word, bit;
	int ret = -EINVAL;

	conn->stage = "adie-thermal-prerequisite";
	if (!conn->adie_efuse_data_complete || !conn->adie_efuse_handoff_complete ||
	    conn->adie_efuse_handoff_dirty)
		goto out;
	conn->adie_thermal_started = true;
	for (round = 0; round < 2; round++) {
		for (word = 0; word < 2; word++) {
			bit = round * 2 + word;
			ret = op6893_conn_adie_data_transfer(conn, csr, sema, adie, wb, spi,
							 mailbox, regs, 0, bit, NULL);
			if (ret)
				goto out;
			ret = op6893_conn_adie_data_transfer(conn, csr, sema, adie, wb, spi,
							 mailbox, regs, word + 6, bit, &data.value);
			if (ret)
				goto out;
			ret = op6893_conn_adie_data_transfer(conn, csr, sema, adie, wb, spi,
							 mailbox, regs, 0, bit, NULL);
			if (ret)
				goto out;
			ret = op6893_conn_adie_data_transfer(conn, csr, sema, adie, wb, spi,
							 mailbox, regs, 1, bit, NULL);
			if (ret)
				goto out;
			conn->stage = "adie-thermal-compare";
			if (!round)
				data.words[word] = data.value;
			else if (data.words[word] != data.value) {
				ret = -EIO;
				goto out;
			} else {
				conn->adie_thermal_matched |= BIT(word);
			}
		}
	}
	ret = op6893_conn_adie_data_guard(conn, csr, sema, adie, wb, spi, mailbox, regs);
	if (!ret)
		conn->adie_thermal_complete = true;
	if (!ret && conn->adie_trim_plan_requested) {
		op6893_conn_adie_trim_plan(conn, efuse, data.words);
		ret = op6893_conn_adie_data_guard(conn, csr, sema, adie, wb, spi, mailbox, regs);
		if (!ret)
			conn->adie_trim_plan_complete = true;
	}
	if (!ret && conn->adie_pad_requested)
		ret = op6893_conn_adie_pad_read(conn, csr, sema, adie, wb, spi, mailbox, regs);
	if (!ret && conn->adie_cfg_requested)
		ret = op6893_conn_adie_cfg_read(conn, csr, sema, adie, wb, spi, mailbox, regs);
	if (!ret && conn->adie_cal_cycle_requested)
		ret = op6893_conn_adie_cal_cycle(conn, csr, sema, adie, wb, spi, mailbox, regs);
	if (!ret && conn->adie_ir_cycle_requested)
		ret = op6893_conn_adie_ir_cycle(conn, csr, sema, adie, wb, spi, mailbox, regs);
out:
	memzero_explicit(&data, sizeof(data));
	conn->adie_thermal_cleared = true;
	if (ret)
		conn->adie_unsafe = true;
	return ret;
}

static int op6893_conn_adie_data_read(struct op6893_conn *conn, void __iomem *csr,
				     void __iomem *sema, void __iomem *adie,
				     void __iomem *wb, void __iomem *spi,
				     void __iomem *mailbox, void __iomem **regs)
{
	struct {
		u32 words[4];
		u32 value;
	} data = {};
	unsigned int round, word, bit;
	int ret = -EINVAL;

	conn->stage = "adie-efuse-data-prerequisite";
	if (!conn->adie_efuse_complete || conn->adie_efuse_pending ||
	    !conn->adie_efuse_stable_cycle || !conn->adie_efuse_observe_stable ||
	    conn->adie_efuse_confirmed != 3 ||
	    (conn->adie_efuse_last & 0x63ff00c0) != BIT(29))
		goto out;
	conn->adie_efuse_data_started = true;
	conn->adie_efuse_data_start_ns = ktime_get_ns();
	op6893_conn_adie_phase_begin(conn, 1, OP6893_EFUSE_DATA_TIMEOUT_NS);
	for (round = 0; round < 2; round++) {
		for (word = 0; word < 4; word++) {
			bit = round * 4 + word;
			ret = op6893_conn_adie_data_transfer(conn, csr, sema, adie, wb, spi,
							 mailbox, regs, 0, bit, NULL);
			if (ret)
				goto out;
			ret = op6893_conn_adie_data_transfer(conn, csr, sema, adie, wb, spi,
							 mailbox, regs, word + 2, bit, &data.value);
			if (ret)
				goto out;
			ret = op6893_conn_adie_data_transfer(conn, csr, sema, adie, wb, spi,
							 mailbox, regs, 0, bit, NULL);
			if (ret)
				goto out;
			ret = op6893_conn_adie_data_transfer(conn, csr, sema, adie, wb, spi,
							 mailbox, regs, 1, bit, NULL);
			if (ret)
				goto out;
			conn->stage = "adie-efuse-data-compare";
			if (!round)
				data.words[word] = data.value;
			else if (data.words[word] != data.value) {
				ret = -EIO;
				goto out;
			} else {
				conn->adie_efuse_data_matched |= BIT(word);
			}
		}
	}
	ret = op6893_conn_adie_data_guard(conn, csr, sema, adie, wb, spi, mailbox, regs);
	if (!ret)
		conn->adie_efuse_data_complete = true;
	if (!ret && conn->adie_efuse_handoff_requested)
		ret = op6893_conn_adie_handoff(conn, csr, sema, adie, wb, spi, mailbox, regs, data.words);
	if (!ret && conn->adie_thermal_requested)
		ret = op6893_conn_adie_thermal_read(conn, csr, sema, adie, wb, spi,
						 mailbox, regs, &data.words[1]);
out:
	memzero_explicit(&data, sizeof(data));
	conn->adie_efuse_data_cleared = true;
	if (ret)
		conn->adie_unsafe = true;
	return ret;
}

static int op6893_conn_adie_fm_cycle(struct op6893_conn *conn, void __iomem *csr,
				    void __iomem *sema, void __iomem *adie,
				    void __iomem *wb, void __iomem *spi,
				    void __iomem *mailbox, void __iomem **regs)
{
	int ret, cleanup = 0;

	conn->stage = "adie-fm-prerequisite";
	if (!conn->adie_route_stable || !conn->adie_route_idle ||
	    conn->adie_route_read != 0x3ff || conn->adie_route_value[0] != 0x801f ||
	    conn->adie_route_value[1] != 0x50305a00 ||
	    conn->adie_route_value[2] != 0x7f0300ff ||
	    conn->adie_route_value[3] || conn->adie_route_value[4])
		return -EINVAL;
	ret = op6893_conn_adie_fm_guard(conn, csr, sema, adie, wb, spi, mailbox, regs);
	if (ret)
		return ret;
	conn->stage = "adie-fm-baseline";
	conn->adie_fm_before = readl(regs[0]);
	conn->adie_fm_read |= BIT(0);
	if (conn->adie_fm_before != conn->adie_route_value[0]) {
		conn->adie_unsafe = true;
		return -EAGAIN;
	}
	conn->adie_fm_target = conn->adie_fm_before & ~0x80ff;
	ret = op6893_conn_adie_fm_guard(conn, csr, sema, adie, wb, spi, mailbox, regs);
	if (ret)
		return ret;
	conn->stage = "adie-fm-apply";
	conn->adie_fm_dirty = true;
	conn->adie_fm_issued |= BIT(0);
	writel(conn->adie_fm_target, regs[0]);
	ret = op6893_conn_adie_fm_guard(conn, csr, sema, adie, wb, spi, mailbox, regs);
	if (ret)
		goto restore;
	conn->stage = "adie-fm-apply-readback";
	conn->adie_fm_on = readl(regs[0]);
	conn->adie_fm_read |= BIT(1);
	if (conn->adie_fm_on != conn->adie_fm_target)
		ret = -EIO;
	else
		conn->adie_fm_applied = true;
	if (!ret && conn->adie_efuse_ctrl_requested)
		ret = op6893_conn_adie_efuse_ctrl(conn, csr, sema, adie, wb, spi, mailbox, regs);
	if (!ret && conn->adie_efuse_requested)
		ret = op6893_conn_adie_efuse_cycle(conn, csr, sema, adie, wb, spi, mailbox, regs);
	if (!ret && conn->adie_efuse_data_requested)
		ret = op6893_conn_adie_data_read(conn, csr, sema, adie, wb, spi, mailbox, regs);
restore:
	if (ret && !conn->failure_stage)
		conn->failure_stage = conn->stage;
	cleanup = op6893_conn_adie_fm_guard(conn, csr, sema, adie, wb, spi, mailbox, regs);
	if (cleanup)
		goto done;
	conn->stage = "adie-fm-restore";
	conn->adie_fm_issued |= BIT(1);
	writel(conn->adie_fm_before, regs[0]);
	cleanup = op6893_conn_adie_fm_guard(conn, csr, sema, adie, wb, spi, mailbox, regs);
	if (cleanup)
		goto done;
	conn->stage = "adie-fm-restore-readback";
	conn->adie_fm_after = readl(regs[0]);
	conn->adie_fm_read |= BIT(2);
	if (conn->adie_fm_after != conn->adie_fm_before) {
		cleanup = -EIO;
		goto done;
	}
	cleanup = op6893_conn_adie_fm_guard(conn, csr, sema, adie, wb, spi, mailbox, regs);
	if (!cleanup) {
		conn->adie_fm_dirty = false;
		conn->adie_fm_restored = true;
	}
done:
	conn->adie_fm_cleanup = cleanup;
	if (cleanup || conn->adie_fm_dirty) {
		if (!conn->failure_stage)
			conn->failure_stage = conn->stage;
		conn->adie_unsafe = true;
	}
	return ret ?: cleanup;
}

static int op6893_conn_adie_route_read(struct op6893_conn *conn, void __iomem *csr,
				      void __iomem *sema, void __iomem *adie,
				      void __iomem *wb, void __iomem *spi,
				      void __iomem *mailbox)
{
	void __iomem *therm, *gpt, *regs[5];
	unsigned int i;
	int ret;

	conn->stage = "adie-route-prerequisite";
	if (conn->adie_prefix_applied != 3 || conn->adie_prefix_dirty != 3 ||
	    !conn->adie_mailbox_dirty || !conn->adie_mailbox_applied)
		return -EINVAL;
	ret = op6893_conn_adie_route_guard(conn, csr, sema, adie, wb, spi, mailbox);
	if (ret)
		return ret;
	conn->stage = "adie-route-map";
	therm = ioremap(0x18002000, 0x28);
	if (!therm)
		return -ENOMEM;
	gpt = ioremap(0x18007000, 0x3c);
	if (!gpt) {
		iounmap(therm);
		return -ENOMEM;
	}
	regs[0] = spi + 0x0c;
	regs[1] = therm + 0x18;
	regs[2] = therm + 0x04;
	regs[3] = therm + 0x24;
	regs[4] = gpt + 0x38;
	for (i = 0; i < 10; i++) {
		ret = op6893_conn_adie_route_guard(conn, csr, sema, adie, wb, spi, mailbox);
		if (ret)
			break;
		conn->stage = "adie-route-read";
		conn->adie_route_value[i] = readl(regs[i % 5]);
		conn->adie_route_read |= BIT(i);
		ret = op6893_conn_adie_route_guard(conn, csr, sema, adie, wb, spi, mailbox);
		if (ret)
			break;
		conn->stage = "adie-route-active";
		if ((i % 5 == 3 && (conn->adie_route_value[i] & (BIT(19) | BIT(18)))) ||
		    (i % 5 == 4 && (conn->adie_route_value[i] & BIT(0)))) {
			ret = -EBUSY;
			conn->adie_unsafe = true;
			break;
		}
		conn->stage = "adie-route-stability";
		if (i >= 5 && conn->adie_route_value[i] != conn->adie_route_value[i - 5]) {
			ret = -EAGAIN;
			conn->adie_unsafe = true;
			break;
		}
	}
	if (!ret) {
		conn->adie_route_stable = true;
		conn->adie_route_idle = true;
	}
	if (!ret && conn->adie_fm_requested)
		ret = op6893_conn_adie_fm_cycle(conn, csr, sema, adie, wb, spi, mailbox, regs);
	iounmap(gpt);
	iounmap(therm);
	return ret;
}

static int op6893_conn_adie_prefix_cycle(struct op6893_conn *conn, void __iomem *csr,
					void __iomem *sema, void __iomem *adie,
					void __iomem *wb, void __iomem *spi,
					void __iomem *mailbox)
{
	unsigned int i;
	int ret = 0, cleanup = 0;

	conn->stage = "adie-prefix-prerequisite";
	if (!conn->adie_id_valid || conn->adie_id != 0x66358a11 ||
	    !conn->adie_config_stable || conn->adie_config_valid != 0xff ||
	    conn->adie_config_value[0] || conn->adie_config_value[4] ||
	    conn->adie_config_value[2] != 1 || conn->adie_config_value[6] != 1 ||
	    !conn->adie_mailbox_dirty || !conn->adie_mailbox_applied)
		return -EINVAL;
	for (i = 0; i < 4; i++) {
		ret = op6893_conn_adie_prefix_transfer(conn, csr, sema, adie, wb, spi, mailbox, i);
		if (ret)
			break;
		if (i & 1) {
			conn->stage = "adie-prefix-apply-verify";
			if (conn->adie_prefix_value[i / 2] != (i == 1 ? 0x7700 : 0x21)) {
				ret = -EIO;
				break;
			}
			conn->adie_prefix_applied |= BIT(i / 2);
		}
	}
	if (!ret && conn->adie_route_requested)
		ret = op6893_conn_adie_route_read(conn, csr, sema, adie, wb, spi, mailbox);
	if (ret && !conn->failure_stage)
		conn->failure_stage = conn->stage;
	/* Reverse order. Only clear a dirty bit after independent restoration evidence. */
	for (i = 4; i < 10; i++) {
		unsigned int bit = i < 7 ? 1 : 0;

		if (!(conn->adie_prefix_dirty & BIT(bit)))
			continue;
		cleanup = op6893_conn_adie_prefix_transfer(conn, csr, sema, adie, wb, spi, mailbox, i);
		if (cleanup)
			break;
		conn->stage = "adie-prefix-restore-verify";
		if ((i == 5 && conn->adie_prefix_value[2] != conn->adie_id) ||
		    (i == 8 && conn->adie_prefix_value[4] != conn->adie_id) ||
		    (i == 6 && conn->adie_prefix_value[3] != 1) ||
		    (i == 9 && conn->adie_prefix_value[5] != 0)) {
			cleanup = -EIO;
			break;
		}
		if (i == 6 || i == 9) {
			cleanup = op6893_conn_adie_prefix_guard(conn, csr, sema, adie, wb, spi, mailbox);
			if (cleanup)
				break;
			conn->adie_prefix_dirty &= ~BIT(bit);
			conn->adie_prefix_restored |= BIT(bit);
		}
	}
	conn->adie_prefix_cleanup = cleanup;
	if (cleanup || conn->adie_prefix_dirty) {
		if (!conn->failure_stage)
			conn->failure_stage = conn->stage;
		conn->adie_unsafe = true;
	}
	return ret ?: cleanup;
}

/* Vendor A-die ID mailbox: SYSRAM base 0x18050000 plus SW_CR offset 0x2800. */
static int op6893_conn_adie_mailbox(struct op6893_conn *conn, void __iomem *csr,
				   void __iomem *sema, void __iomem *adie,
				   void __iomem *wb, void __iomem *spi)
{
	void __iomem *mailbox;
	int ret, cleanup = 0;

	conn->stage = "adie-mailbox-prerequisite";
	if (!conn->adie_id_valid || !conn->sysram_complete || conn->sysram_unsafe ||
	    conn->sysram_verified != 4096 || conn->sysram_scanned != 4096 ||
	    conn->rgu_applied != 4 || conn->rgu_dirty != 0xf)
		return -EINVAL;
	ret = op6893_conn_adie_idle(conn, csr, sema, adie, wb, spi, 3);
	if (ret)
		return ret;
	conn->stage = "adie-mailbox-map";
	mailbox = ioremap(0x18052800, 4);
	if (!mailbox)
		return -ENOMEM;
	ret = op6893_conn_adie_idle(conn, csr, sema, adie, wb, spi, 3);
	if (ret)
		goto done;
	conn->stage = "adie-mailbox-baseline";
	/* Refuse unexpected contents; do not expose or overwrite another owner. */
	if (readl(mailbox)) {
		conn->adie_unsafe = true;
		ret = -EBUSY;
		goto done;
	}
	ret = op6893_conn_adie_idle(conn, csr, sema, adie, wb, spi, 3);
	if (ret)
		goto done;
	conn->stage = "adie-mailbox-write";
	conn->adie_mailbox_dirty = true;
	conn->adie_mailbox_issued = true;
	writel(conn->adie_id, mailbox);
	ret = op6893_conn_adie_idle(conn, csr, sema, adie, wb, spi, 3);
	if (ret)
		goto restore;
	conn->stage = "adie-mailbox-readback";
	conn->adie_mailbox_on = readl(mailbox);
	if (conn->adie_mailbox_on != conn->adie_id)
		ret = -EIO;
	else
		conn->adie_mailbox_applied = true;
	if (!ret && conn->adie_prefix_requested)
		ret = op6893_conn_adie_prefix_cycle(conn, csr, sema, adie, wb, spi, mailbox);
restore:
	if (ret && !conn->failure_stage)
		conn->failure_stage = conn->stage;
	cleanup = op6893_conn_adie_idle(conn, csr, sema, adie, wb, spi, 3);
	if (cleanup)
		goto done;
	conn->stage = "adie-mailbox-clear";
	writel(0, mailbox);
	cleanup = op6893_conn_adie_idle(conn, csr, sema, adie, wb, spi, 3);
	if (cleanup)
		goto done;
	conn->stage = "adie-mailbox-clear-readback";
	conn->adie_mailbox_after = readl(mailbox);
	if (conn->adie_mailbox_after) {
		cleanup = -EIO;
		goto done;
	}
	cleanup = op6893_conn_adie_idle(conn, csr, sema, adie, wb, spi, 3);
	if (!cleanup) {
		conn->adie_mailbox_dirty = false;
		conn->adie_mailbox_restored = true;
	}
done:
	if ((ret || cleanup) && !conn->failure_stage)
		conn->failure_stage = conn->stage;
	if (conn->adie_mailbox_dirty)
		conn->adie_unsafe = true;
	conn->adie_mailbox_cleanup = cleanup;
	iounmap(mailbox);
	return ret ?: cleanup;
}

/* Two rounds of the first vendor config addresses, separated by known IDs. */
static int op6893_conn_adie_config_read(struct op6893_conn *conn, void __iomem *csr,
				      void __iomem *sema, void __iomem *adie,
				      void __iomem *wb, void __iomem *spi)
{
	unsigned int i;
	int ret;

	for (i = 0; i < 8; i++) {
		u32 addr = i & 1 ? 0xb02c : (i & 2 ? 0xb0bc : 0xb064);

		conn->adie_config_active = false;
		conn->adie_config_busy_seen = false;
		ret = op6893_conn_adie_idle(conn, csr, sema, adie, wb, spi, 3);
		if (ret)
			return ret;
		conn->stage = "adie-config-baseline";
		conn->adie_config_before[i] = readl(spi + 0x58);
		ret = op6893_conn_adie_guard(conn, csr, sema, adie, wb, 3);
		if (ret)
			return ret;
		conn->stage = "adie-config-address";
		writel(addr, spi + 0x50);
		ret = op6893_conn_adie_guard(conn, csr, sema, adie, wb, 3);
		if (ret)
			return ret;
		conn->stage = "adie-config-address-readback";
		if (readl(spi + 0x50) != addr)
			return -EIO;
		ret = op6893_conn_adie_idle(conn, csr, sema, adie, wb, spi, 3);
		if (ret)
			return ret;
		conn->stage = "adie-config-trigger";
		conn->adie_config_active = true;
		writel(0, spi + 0x54);
		ret = op6893_conn_adie_idle(conn, csr, sema, adie, wb, spi, 3);
		conn->adie_config_active = false;
		if (ret)
			return ret;
		conn->stage = "adie-config-data";
		conn->adie_config_value[i] = readl(spi + 0x58);
		conn->adie_config_read |= BIT(i);
		if (conn->adie_config_busy_seen)
			conn->adie_config_busy_mask |= BIT(i);
		else if (conn->adie_config_before[i] == conn->adie_config_value[i])
			return -EAGAIN;
		if ((i & 1) && conn->adie_config_value[i] != conn->adie_id)
			return -ENODEV;
		conn->adie_config_valid |= BIT(i);
		if (i >= 4 && conn->adie_config_value[i] != conn->adie_config_value[i - 4])
			return -EIO;
	}
	conn->adie_config_stable = true;
	return 0;
}

static int op6893_conn_adie_cycle(struct op6893_conn *conn, void __iomem *csr,
				void __iomem *sema)
{
	void __iomem *adie, *spi, *wb;
	int ret, cleanup = 0;

	conn->stage = "adie-prerequisite-guard";
	if (!conn->prepare_requested || !conn->sema_acquired || !conn->sema_pending ||
	    conn->sema_unsafe || conn->sema_grant != 1)
		return -EINVAL;
	ret = op6893_conn_check_off(conn, csr);
	if (ret) {
		conn->adie_unsafe = true;
		return ret;
	}
	conn->stage = "adie-map";
	adie = ioremap(0x18001900, 4);
	if (!adie)
		return -ENOMEM;
	spi = ioremap(0x18004000, 0x5c);
	if (!spi) {
		ret = -ENOMEM;
		goto unmap_adie;
	}
	wb = ioremap(0x18005008, 4);
	if (!wb) {
		ret = -ENOMEM;
		goto unmap_spi;
	}
	ret = op6893_conn_adie_poll(conn, csr, sema, adie, wb, spi, 2);
	if (ret)
		goto done;
	if (conn->adie_busy) {
		conn->adie_unsafe = true;
		ret = -EBUSY;
		goto done;
	}
	ret = op6893_conn_adie_guard(conn, csr, sema, adie, wb, 2);
	if (ret)
		goto done;
	conn->stage = "adie-save-address";
	conn->adie_addr_before = readl(spi + 0x50);
	ret = op6893_conn_adie_guard(conn, csr, sema, adie, wb, 2);
	if (ret)
		goto done;
	conn->stage = "adie-data-baseline";
	conn->adie_data_before = readl(spi + 0x58);
	ret = op6893_conn_adie_guard(conn, csr, sema, adie, wb, 2);
	if (ret)
		goto done;
	conn->stage = "adie-release-reset";
	conn->adie_reset_dirty = true;
	conn->adie_release_issued = true;
	writel(3, adie);
	ret = op6893_conn_adie_guard(conn, csr, sema, adie, wb, 3);
	if (ret)
		goto done;
	conn->adie_release_verified = true;
	ret = op6893_conn_adie_idle(conn, csr, sema, adie, wb, spi, 3);
	if (ret)
		goto done;
	conn->stage = "adie-top-address";
	conn->adie_addr_dirty = true;
	writel(0xb02c, spi + 0x50);
	ret = op6893_conn_adie_guard(conn, csr, sema, adie, wb, 3);
	if (ret)
		goto done;
	conn->stage = "adie-top-address-readback";
	conn->adie_addr_on = readl(spi + 0x50);
	if (conn->adie_addr_on != 0xb02c) {
		ret = -EIO;
		goto restore;
	}
	ret = op6893_conn_adie_idle(conn, csr, sema, adie, wb, spi, 3);
	if (ret)
		goto done;
	conn->stage = "adie-top-trigger";
	conn->adie_triggered = true;
	/* Zero WDAT triggers the READ selected by address prefix 0xb000. */
	writel(0, spi + 0x54);
	ret = op6893_conn_adie_idle(conn, csr, sema, adie, wb, spi, 3);
	if (ret)
		goto done;
	ret = op6893_conn_adie_guard(conn, csr, sema, adie, wb, 3);
	if (ret)
		goto done;
	conn->stage = "adie-top-id";
	conn->adie_id = readl(spi + 0x58);
	conn->adie_id_read = true;
	if (conn->adie_id != 0x66358a00 && conn->adie_id != 0x66358a10 &&
	    conn->adie_id != 0x66358a11)
		ret = -ENODEV;
	else if (!conn->adie_busy_seen && conn->adie_id == conn->adie_data_before)
		/* A known-looking unchanged latch alone is not a fresh response. */
		ret = -EAGAIN;
	else
		conn->adie_id_valid = true;
	if (!ret && conn->adie_config_requested)
		ret = op6893_conn_adie_config_read(conn, csr, sema, adie, wb, spi);
	if (!ret && conn->adie_mailbox_requested)
		ret = op6893_conn_adie_mailbox(conn, csr, sema, adie, wb, spi);
	if (!ret && conn->adie_xtal_requested)
		ret = op6893_conn_adie_xtal(conn, csr, sema, adie, wb, spi);
	if (!ret && conn->adie_write_requested)
		ret = op6893_conn_adie_write_cycle(conn, csr, sema, adie, wb, spi);
restore:
	conn->adie_xtal_active = false;
	if (ret && !conn->failure_stage)
		conn->failure_stage = conn->stage;
	cleanup = op6893_conn_adie_idle(conn, csr, sema, adie, wb, spi, 3);
	if (cleanup)
		goto done;
	conn->stage = "adie-reassert-reset";
	writel(2, adie);
	cleanup = op6893_conn_adie_guard(conn, csr, sema, adie, wb, 2);
	if (cleanup)
		goto done;
	conn->adie_reset_dirty = false;
	conn->adie_reset_restored = true;
	if (conn->adie_addr_dirty) {
		cleanup = op6893_conn_adie_idle(conn, csr, sema, adie, wb, spi, 2);
		if (cleanup)
			goto done;
		conn->stage = "adie-restore-address";
		writel(conn->adie_addr_before, spi + 0x50);
		cleanup = op6893_conn_adie_guard(conn, csr, sema, adie, wb, 2);
		if (cleanup)
			goto done;
		conn->stage = "adie-restore-address-readback";
		conn->adie_addr_after = readl(spi + 0x50);
		if (conn->adie_addr_after != conn->adie_addr_before) {
			cleanup = -EIO;
			goto done;
		}
		conn->adie_addr_dirty = false;
	}
	cleanup = op6893_conn_adie_idle(conn, csr, sema, adie, wb, spi, 2);
	if (!cleanup && !ret)
		conn->adie_complete = true;
done:
	if ((ret || cleanup) && !conn->failure_stage)
		conn->failure_stage = conn->stage;
	if (!cleanup && (conn->adie_unsafe || conn->adie_reset_dirty || conn->adie_addr_dirty ||
			 conn->adie_write_dirty || conn->adie_mailbox_dirty ||
			 conn->adie_prefix_dirty || conn->adie_fm_dirty || conn->adie_efuse_pending))
		cleanup = -EUCLEAN;
	conn->adie_cleanup_result = cleanup;
	iounmap(wb);
unmap_spi:
	iounmap(spi);
unmap_adie:
	iounmap(adie);
	return ret ?: cleanup;
}
