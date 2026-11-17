#!/usr/bin/env python3
# SPDX-License-Identifier: GPL-2.0-only
"""Actual C v5 exception-overview decoder; synthetic records only.

The offsets come from the same-board 4.19 mdee_dumper_v5.h. This checks the
decoder's arithmetic and bounds, not the MD firmware's meaning of any field.
"""
from pathlib import Path
import subprocess
import tempfile

K = Path(__file__).resolve().parents[5]
SRC = K / 'drivers/misc/mediatek/ccci'

TEST = r'''
#include <assert.h>
#include <stdio.h>
#include <stdlib.h>
#include <string.h>
#include <linux/types.h>
#include <linux/errno.h>
#include <linux/unaligned.h>

#include "ccci-md-ee.h"
#include "ccci-md-ee.c"

static void put32(u8 *p, u32 v) { memcpy(p, &v, 4); }
static void put16(u8 *p, u16 v) { memcpy(p, &v, 2); }

/* Record with a caller-chosen core count, so offsets must follow it. */
static u8 *record(u32 cores, u8 content_type, size_t *len)
{
	size_t n = ccci_md_ee_size(cores);
	u8 *p = calloc(1, n);
	size_t info = 8 + cores * 12;

	assert(p);
	*len = n;
	put32(p, 0xab000005);
	put32(p + 4, cores);
	memcpy(p + 8, "MCU", 3);
	p[8 + 11] = 1;
	memcpy(p + 8 + 12, "USIP0", 5);
	put16(p + info, 0x1d);
	p[info + 2] = 0;
	p[info + 3] = content_type;
	return p;
}

static void check_fatal(void)
{
	struct ccci_md_ee ee;
	size_t n, info;
	u8 *p = record(12, 1, &n);

	info = 8 + 12 * 12;
	/* fatal fields, offsets from struct ex_fatal_v5 inside the union */
	put32(p + info + 8, 0x1d);
	put32(p + info + 12, 0x91823b66);
	put32(p + info + 16, 0x90b2d7c2);
	p[info + 8 + 20] = 1;	/* is_cadefa_supported */
	p[info + 8 + 22] = 0;	/* error_section */
	put32(p + info + 8 + 28, 0x2);
	put32(p + info + 8 + 32, 0x24ab42d0);
	put32(p + info + 8 + 36, 0x91823b66);
	put32(p + info + 8 + 40, 0x90b2d7c2);
	put32(p + info + 8 + 44, 0x90d18620);
	put32(p + info + 8 + 48, 0x74);
	assert(ccci_md_ee_decode(p, n, &ee) == 0);
	assert(ee.version == 0xab000005 && ee.cores == 12);
	assert(!strcmp(ee.core, "MCU"));
	assert(ee.ex_type == 0x1d && ee.content_type == 1);
	assert(ee.code[0] == 0x1d && ee.code[1] == 0x91823b66);
	assert(ee.status == 2 && ee.cadefa == 1 && ee.section == 0);
	assert(ee.sp == 0x24ab42d0 && ee.pc == 0x91823b66);
	assert(ee.lr == 0x90b2d7c2 && ee.addr == 0x90d18620 && ee.cause == 0x74);
	free(p);

	/* The same fields move with a different core count. */
	p = record(9, 1, &n);
	info = 8 + 9 * 12;
	put32(p + info + 8 + 36, 0xdeadbeef);
	assert(ccci_md_ee_decode(p, n, &ee) == 0);
	assert(ee.cores == 9 && ee.pc == 0xdeadbeef);
	free(p);
}

static void check_assert(void)
{
	struct ccci_md_ee ee;
	size_t n, info;
	u8 *p = record(12, 0, &n);

	info = 8 + 12 * 12;
	memcpy(p + info + 8, "mcu/service/x.cd", 16);
	p[info + 8 + 16] = 0x01;	/* non-printable becomes '.' */
	p[info + 8 + 17] = 0;
	put32(p + info + 8 + 256, 1302);
	put32(p + info + 8 + 260, 0xffff1001);
	put32(p + info + 8 + 264, 0x1001);
	put32(p + info + 8 + 268, 0);
	put32(p + info + 8 + 272, 0x90b2d7c2);
	assert(ccci_md_ee_decode(p, n, &ee) == 0);
	assert(!strcmp(ee.path, "mcu/service/x.cd."));
	assert(ee.line == 1302 && ee.para[0] == 0xffff1001 && ee.para[1] == 0x1001);
	assert(ee.lr == 0x90b2d7c2);
	free(p);
}

static void check_bounds(void)
{
	struct ccci_md_ee ee;
	size_t n;
	u8 *p;

	assert(ccci_md_ee_size(0) == 0);
	assert(ccci_md_ee_size(CCCI_MD_EE_MAX_CORES + 1) == 0);
	assert(ccci_md_ee_decode(NULL, 64, &ee) == -EINVAL);
	p = record(12, 1, &n);
	assert(ccci_md_ee_decode(p, 7, &ee) == -ENODATA);
	assert(ccci_md_ee_decode(p, 8 + 12 * 12, &ee) == -ENODATA);
	assert(ccci_md_ee_decode(p, n, &ee) == 0);
	/* An out-of-range core count fails closed instead of over-reading. */
	put32(p + 4, 0);
	assert(ccci_md_ee_decode(p, n, &ee) == -ENODATA);
	put32(p + 4, CCCI_MD_EE_MAX_CORES + 1);
	assert(ccci_md_ee_decode(p, n, &ee) == -ENODATA);
	put32(p + 4, 0xffffffff);
	assert(ccci_md_ee_decode(p, n, &ee) == -ENODATA);
	free(p);
}

int main(void)
{
	check_fatal();
	check_assert();
	check_bounds();
	return 0;
}
'''


def main():
    with tempfile.TemporaryDirectory(prefix='op6893-md-ee-') as directory:
        root = Path(directory)
        inc = root / 'linux'
        inc.mkdir()
        files = {
            'types.h': '#pragma once\n#include <stdint.h>\n#include <stdbool.h>\n'
                       '#include <stddef.h>\ntypedef uint8_t u8;typedef uint16_t u16;'
                       'typedef uint32_t u32;typedef uint64_t u64;\n',
            'errno.h': '#include <asm-generic/errno.h>\n',
            'string.h': '#pragma once\n#include <string.h>\n',
            'unaligned.h': '#pragma once\n#include <string.h>\n'
                           '#define get_unaligned_le32(p) ((u32)((p)[0] | ((p)[1] << 8) | '
                           '((p)[2] << 16) | ((u32)(p)[3] << 24)))\n'
                           '#define get_unaligned_le16(p) ((u16)((p)[0] | ((p)[1] << 8)))\n',
        }
        for name, data in files.items():
            (inc / name).write_text(data)
        (root / 'test.c').write_text(TEST)
        subprocess.run(['cc', '-O1', '-g', '-Wall', '-Wextra', '-Werror',
                        '-fsanitize=address,undefined', '-fno-sanitize-recover=all',
                        '-no-pie', '-I' + str(root), '-I' + str(SRC),
                        str(root / 'test.c'), '-o', str(root / 'test')], check=True)
        subprocess.run([str(root / 'test')], check=True)


if __name__ == '__main__':
    main()
