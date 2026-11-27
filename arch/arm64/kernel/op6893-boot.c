// SPDX-License-Identifier: GPL-2.0-only
/* Experimental direct LK boot, restricted to the op6893 bring-up config. */
#include <linux/console.h>
#include <linux/io.h>
#include <linux/libfdt.h>
#include <linux/mm.h>
#include <linux/printk.h>
#include <linux/sizes.h>
#include <linux/uts.h>

#include <asm/fixmap.h>
#include <asm/memory.h>
#include <asm/pgtable.h>

#include "op6893-boot.h"
#include "op6893-fdt.h"

/* ACK: 0xe0000 total, 0x40000 console, 0x10000 pmsg, 0x1000 ftrace. */
#define OP6893_CONSOLE_PA	0x4811f000
#define OP6893_CONSOLE_SIZE	SZ_256K
#define OP6893_RAM_SIG		0x43474244
#define OP6893_HEADER_SIZE	12
#define OP6893_CAPACITY		(OP6893_CONSOLE_SIZE - OP6893_HEADER_SIZE)

static char board_fdt[SZ_64K] __aligned(8);
static u32 *console_buffer;
static u32 cursor, used;

static void op6893_console_write(struct console *con, const char *s,
				 unsigned int count)
{
	char *data = (char *)console_buffer + OP6893_HEADER_SIZE;

	/* Only the boot CPU runs while this console is registered. */
	while (count--) {
		WRITE_ONCE(data[cursor], *s++);
		cursor = (cursor + 1) % OP6893_CAPACITY;
		if (used < OP6893_CAPACITY)
			used++;
	}
	/* Publish the bytes before advancing the persistent ring header. */
	wmb();
	WRITE_ONCE(console_buffer[1], cursor);
	WRITE_ONCE(console_buffer[2], used);
	dsb(sy);
}

static struct console op6893_console = {
	.name = "op6893",
	.write = op6893_console_write,
	.flags = CON_BOOT | CON_PRINTBUFFER,
	.index = -1,
};

static bool __init has_pstore(const void *lk)
{
	const fdt32_t *reg;
	int parent, node, len;

	parent = fdt_path_offset(lk, "/reserved-memory");
	if (parent < 0)
		return false;
	fdt_for_each_subnode(node, lk, parent) {
		reg = fdt_getprop(lk, node, "reg", &len);
		if (reg && len == 16 && !fdt32_to_cpu(reg[0]) &&
		    fdt32_to_cpu(reg[1]) == 0x48090000 &&
		    !fdt32_to_cpu(reg[2]) && fdt32_to_cpu(reg[3]) == 0xe0000)
			return true;
	}
	return false;
}

phys_addr_t __init op6893_prepare_fdt(phys_addr_t lk_phys)
{
	void *lk;
	int size = 0, ret, i;
	u32 old_start, old_size;

	lk = fixmap_remap_fdt(lk_phys, &size, PAGE_KERNEL_RO);
	if (!lk || fdt_check_header(lk) ||
	    (fdt_node_check_compatible(lk, 0, "mediatek,MT6893") &&
	     fdt_node_check_compatible(lk, 0, "mediatek,mt6893")))
		panic("op6893: invalid LK FDT at %pa", &lk_phys);
	if (!has_pstore(lk))
		panic("op6893: LK pstore reservation differs from ACK baseline");

	/* Normal non-cacheable RAM, not Device memory (unaligned stores). */
	console_buffer = early_memremap_prot(OP6893_CONSOLE_PA,
					     OP6893_CONSOLE_SIZE,
					     pgprot_val(pgprot_writecombine(PAGE_KERNEL)));
	if (!console_buffer)
		panic("op6893: cannot map early console");
	/*
	 * Ramoops snapshots this same console zone later. Preserve a valid,
	 * nonempty ring until then; CON_PRINTBUFFER will replay this boot.
	 */
	old_start = READ_ONCE(console_buffer[1]);
	old_size = READ_ONCE(console_buffer[2]);
	if (READ_ONCE(console_buffer[0]) == OP6893_RAM_SIG &&
	    old_size && old_size <= OP6893_CAPACITY &&
	    old_start < OP6893_CAPACITY && old_start <= old_size) {
		early_memunmap(console_buffer, OP6893_CONSOLE_SIZE);
		console_buffer = NULL;
	} else {
		WRITE_ONCE(console_buffer[0], 0);
		WRITE_ONCE(console_buffer[1], 0);
		WRITE_ONCE(console_buffer[2], 0);
		/* Publish the empty header before marking it valid. */
		wmb();
		WRITE_ONCE(console_buffer[0], OP6893_RAM_SIG);
		dsb(sy);
		register_console(&op6893_console);
	}
	pr_info("OP6893-DIRECT: setup_arch reached; LK FDT=%pa\n", &lk_phys);
	pr_info("OP6893-DIRECT: %s", linux_banner);

	ret = op6893_merge_fdt(board_fdt, sizeof(board_fdt), op6893_dtb, lk);
	if (ret)
		panic("op6893: FDT merge failed: %d", ret);
	pr_info("OP6893-DIRECT: board FDT ready (%u bytes), LK memory retained\n",
		fdt_totalsize(board_fdt));

	/* Break the LK mapping before reusing FIX_FDT for a different PFN. */
	for (i = 0; i < DIV_ROUND_UP(offset_in_page(lk_phys) + size, PAGE_SIZE); i++)
		clear_fixmap(FIX_FDT - i);
	return __pa_symbol(board_fdt);
}

void __init op6893_early_console_exit(void)
{
	if (!console_buffer)
		return;
	pr_info("OP6893-DIRECT: entering paging_init; next console is ramoops\n");
	unregister_console(&op6893_console);
	early_memunmap(console_buffer, OP6893_CONSOLE_SIZE);
	console_buffer = NULL;
}
