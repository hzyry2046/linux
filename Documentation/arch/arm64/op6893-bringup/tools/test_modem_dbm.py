#!/usr/bin/env python3
# SPDX-License-Identifier: GPL-2.0-only
"""Actual C DBM pattern writer; synthetic SMEM only.

The same-board AP writes two 0x44444444 guards around a cleared 160-byte body
in SMEM user 0 before the runtime doorbell. This checks the emitted bytes and
that nothing outside the pattern is touched, not what the MD does with them.
"""
from pathlib import Path
import subprocess
import tempfile

K = Path(__file__).resolve().parents[5]
SRC = K / 'drivers/misc/mediatek/ccci'

TEST_HEAD = r'''
#include <assert.h>
#include <stdio.h>
#include <string.h>
#include <linux/types.h>

typedef unsigned char u8;
typedef unsigned int u32;
#define __iomem
#define le32toh(x) (x)

static u8 image[512];
static unsigned writes;

#define CCCI_DBM_GUARD	0x44444444
#define CCCI_DBM_BODY	160

static void writel(u32 value, void *addr)
{
	u32 *p = addr;

	assert((u8 *)p >= image && (u8 *)p + 4 <= image + sizeof(image));
	assert(!(((u8 *)p - image) & 3));
	memcpy(p, &value, 4);
	writes++;
}

static void memset_io(void *addr, int value, size_t size)
{
	assert((u8 *)addr >= image && (u8 *)addr + size <= image + sizeof(image));
	assert(!value);
	memset(addr, value, size);
}
'''

TEST_BODY = r'''
int main(void)
{
	u32 word;
	size_t guard = 8 + 160;

	memset(image, 0xff, sizeof(image));
	writes = 0;
	control_dbm_pattern(image);

	/* Two leading guards, a cleared body and two trailing guards. */
	assert(writes == 4);
	for (size_t i = 0; i < sizeof(image); i++) {
		u32 expected;

		if (i < 8 || (i >= guard && i < guard + 8))
			expected = 0x44444444;
		else if (i < guard)
			expected = 0;
		else
			expected = 0xffffffff;
		memcpy(&word, image + i, 4);
		assert(word == expected);
		i += 3;
	}
	puts("PASS: actual DBM pattern: guard, cleared 160-byte body, guard, and");
	puts("      no write outside the 176 bytes the same-board AP owns");
	return 0;
}
'''

with tempfile.TemporaryDirectory(prefix='op6893-dbm-') as temporary:
    root = Path(temporary)
    (root / 'linux').mkdir()
    (root / 'linux/types.h').write_text('#include <stdbool.h>\n')
    source = (SRC / 'ccci-ccif-control.c').read_text()
    start = source.index('static void control_dbm_pattern')
    pattern = source[start:source.index('static void control_dbm_init')]
    (root / 'test.c').write_text(TEST_HEAD + '\n' + pattern + TEST_BODY)
    subprocess.run(['cc', '-std=gnu11', '-Wall', '-Wextra', '-Werror',
                    '-fsanitize=address,undefined', '-fno-sanitize-recover=all',
                    '-I' + str(root), str(root / 'test.c'), '-o', str(root / 'test')],
                   check=True)
    subprocess.run([str(root / 'test')], check=True)
