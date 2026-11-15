// SPDX-License-Identifier: GPL-2.0-only
/* Import memory ownership, without importing Android devices or phandles. */
#include <linux/kernel.h>
#include <linux/libfdt.h>
#include <linux/soc/mediatek/ccci-lk.h>
#include <linux/unaligned.h>

#include "op6893-fdt.h"

static int __init copy_prop(void *dst, int target, const void *src, int node,
			    const char *name)
{
	const void *value;
	int len;

	value = fdt_getprop(src, node, name, &len);
	if (!value)
		return len == -FDT_ERR_NOTFOUND ? 0 : len;
	return fdt_setprop(dst, target, name, value, len);
}

static int __init copy_devinfo(void *dst, const void *lk)
{
	const void *data;
	u32 count;
	int source, target, len;

	source = fdt_path_offset(lk, "/chosen");
	if (source == -FDT_ERR_NOTFOUND)
		source = fdt_path_offset(lk, "/chosen@0");
	if (source < 0)
		return source == -FDT_ERR_NOTFOUND ? 0 : source;
	data = fdt_getprop(lk, source, "atag,devinfo", &len);
	if (!data)
		return len == -FDT_ERR_NOTFOUND ? 0 : len;

	/* Optional LK payload: little-endian count followed by that many words. */
	if (len < sizeof(count))
		return 0;
	count = get_unaligned_le32(data);
	/* LVTS needs words through 207; reject malformed data without blocking boot. */
	if (count < 208 || count > 400 || len != sizeof(count) * (count + 1))
		return 0;

	target = fdt_path_offset(dst, "/chosen");
	if (target < 0)
		return target;
	return fdt_setprop(dst, target, "atag,devinfo", data, len);
}

static int __init copy_ccci_header(void *dst, const void *board, const void *lk)
{
	static const char * const paths[] = { "/chosen", "/chosen@0", "/mddriver" };
	struct ccci_lk_header header;
	struct ccci_lk_region region;
	const void *data = NULL, *candidate, *reg;
	const fdt32_t *phandles;
	int node, len, parent, target, ret;
	unsigned int i;
	bool reserved = false;

	target = fdt_path_offset(dst, "/chosen");
	if (target < 0)
		return target;
	/* Never retain a header baked into the board DTB from an older boot. */
	ret = fdt_delprop(dst, target, CCCI_LK_PROPERTY);
	if (ret && ret != -FDT_ERR_NOTFOUND)
		return ret;
	for (i = 0; i < ARRAY_SIZE(paths); i++) {
		node = fdt_path_offset(lk, paths[i]);
		if (node < 0)
			continue;
		candidate = fdt_getprop(lk, node, CCCI_LK_PROPERTY, &len);
		if (!candidate) {
			if (len != -FDT_ERR_NOTFOUND)
				return 0;
			continue;
		}
		/* Optional handoff failures must not prevent the AP from booting. */
		if (ccci_lk_decode_header(candidate, len, &header) ||
		    (data && memcmp(data, candidate, CCCI_LK_HEADER_SIZE)))
			return 0;
		data = candidate;
	}
	if (!data)
		return 0;

	/* Read the immutable board allowlist, never an imported LK phandle. */
	node = fdt_path_offset(board, "/modem-handoff");
	if (node < 0 || fdt_node_check_compatible(board, node,
						  "realme,op6893-modem-handoff"))
		return 0;
	phandles = fdt_getprop(board, node, "memory-region", &len);
	if (!phandles || len != 3 * sizeof(*phandles))
		return 0;
	node = fdt_node_offset_by_phandle(board, fdt32_to_cpu(phandles[0]));
	parent = fdt_path_offset(board, "/reserved-memory");
	if (node < 0 || parent < 0 || fdt_parent_offset(board, node) != parent ||
	    !fdt_getprop(board, node, "no-map", &len) || len)
		return 0;
	reg = fdt_getprop(board, node, "reg", &len);
	if (!reg || len != 16)
		return 0;
	region.base = get_unaligned_be64(reg);
	region.size = get_unaligned_be64(reg + 8);
	if (!ccci_lk_contains(&region, header.base, header.size))
		return 0;

	/* LK must independently have reserved this boot's entire tag buffer. */
	parent = fdt_path_offset(lk, "/reserved-memory");
	fdt_for_each_subnode(node, lk, parent) {
		reg = fdt_getprop(lk, node, "reg", &len);
		if (!reg || len != 16)
			continue;
		region.base = get_unaligned_be64(reg);
		region.size = get_unaligned_be64(reg + 8);
		if (ccci_lk_contains(&region, header.base, header.size)) {
			reserved = true;
			break;
		}
	}
	if (!reserved)
		return 0;
	return fdt_setprop(dst, target, CCCI_LK_PROPERTY, data, CCCI_LK_HEADER_SIZE);
}

int __init op6893_merge_fdt(void *dst, int size, const void *board,
			    const void *lk)
{
	static const char * const props[] = {
		"reg", "size", "alignment", "alloc-ranges", "no-map",
	};
	int ret, node, target, parent, reserved, len, i, memories = 0;
	const void *reg;
	const char *type;
	u64 address, length;

	ret = fdt_check_header(lk);
	if (ret)
		return ret;
	if (fdt_node_check_compatible(lk, 0, "mediatek,MT6893") &&
	    fdt_node_check_compatible(lk, 0, "mediatek,mt6893"))
		return -FDT_ERR_BADVALUE;
	if (fdt_address_cells(lk, 0) != 2 || fdt_size_cells(lk, 0) != 2)
		return -FDT_ERR_BADNCELLS;
	ret = fdt_open_into(board, dst, size);
	if (ret)
		return ret;

	fdt_for_each_subnode(node, lk, 0) {
		type = fdt_getprop(lk, node, "device_type", &len);
		if (!type || len != sizeof("memory") ||
		    memcmp(type, "memory", sizeof("memory")))
			continue;
		reg = fdt_getprop(lk, node, "reg", &len);
		if (!reg || len <= 0 || len % 16)
			return -FDT_ERR_BADVALUE;
		target = fdt_add_subnode(dst, 0, fdt_get_name(lk, node, NULL));
		if (target < 0)
			return target;
		ret = fdt_setprop(dst, target, "reg", reg, len);
		if (ret)
			return ret;
		ret = fdt_setprop_string(dst, target, "device_type", "memory");
		if (ret)
			return ret;
		memories++;
	}
	if (!memories)
		return -FDT_ERR_NOTFOUND;

	parent = fdt_path_offset(lk, "/reserved-memory");
	if (parent < 0)
		return parent;
	if (fdt_address_cells(lk, parent) != 2 ||
	    fdt_size_cells(lk, parent) != 2)
		return -FDT_ERR_BADNCELLS;
	if (!fdt_getprop(lk, parent, "ranges", &len) || len)
		return -FDT_ERR_BADVALUE;
	/* The board dtb may already carry a reserved-memory node (consys). */
	reserved = fdt_path_offset(dst, "/reserved-memory");
	if (reserved < 0)
		reserved = fdt_add_subnode(dst, 0, "reserved-memory");
	if (reserved < 0)
		return reserved;
	ret = fdt_setprop_u32(dst, reserved, "#address-cells", 2);
	if (ret)
		return ret;
	ret = fdt_setprop_u32(dst, reserved, "#size-cells", 2);
	if (ret)
		return ret;
	ret = fdt_setprop(dst, reserved, "ranges", NULL, 0);
	if (ret)
		return ret;
	fdt_for_each_subnode(node, lk, parent) {
		reg = fdt_getprop(lk, node, "reg", &len);
		if (reg) {
			if (len <= 0 || len % 16)
				return -FDT_ERR_BADVALUE;
		} else if (!fdt_getprop(lk, node, "size", &len)) {
			continue;
		} else if (len != 8) {
			return -FDT_ERR_BADVALUE;
		}
		target = fdt_subnode_offset(dst, reserved,
					    fdt_get_name(lk, node, NULL));
		if (target == -FDT_ERR_NOTFOUND)
			target = fdt_add_subnode(dst, reserved,
						 fdt_get_name(lk, node, NULL));
		if (target < 0)
			return target;
		/* Retain even reusable regions, but do not attach vendor drivers. */
		for (i = 0; i < ARRAY_SIZE(props); i++) {
			ret = copy_prop(dst, target, lk, node, props[i]);
			if (ret)
				return ret;
		}
		/*
		 * LK's scanout buffers: keep them out of the linear map so the
		 * early simple-framebuffer console can map them write-combined.
		 */
#ifdef CONFIG_ARM64_OP6893_FBKICK
		if (!strcmp(fdt_get_name(lk, node, NULL),
			    "mblock-18-framebuffer")) {
			ret = fdt_setprop(dst, target, "no-map", NULL, 0);
			if (ret)
				return ret;
		}
#endif
	}

	for (i = 0; i < fdt_num_mem_rsv(lk); i++) {
		ret = fdt_get_mem_rsv(lk, i, &address, &length);
		if (ret)
			return ret;
		ret = fdt_add_mem_rsv(dst, address, length);
		if (ret)
			return ret;
	}

	/* External initrd and vendor bootargs are intentionally not imported. */
	ret = copy_devinfo(dst, lk);
	if (ret)
		return ret;
	ret = copy_ccci_header(dst, board, lk);
	if (ret)
		return ret;
	return fdt_pack(dst);
}
