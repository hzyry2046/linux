#!/usr/bin/env python3
# SPDX-License-Identifier: GPL-2.0-only
"""Actual C text conversion of the MD DFD region; synthetic bytes only.

The MD writes its own log into the DFD SMEM user. This checks only the
conversion arithmetic and its cross-window state, not the log's content.
"""
from pathlib import Path
import subprocess
import tempfile

K = Path(__file__).resolve().parents[5]
SRC = K / 'drivers/misc/mediatek/ccci'

TEST_HEAD = r'''
#include <assert.h>
#include <stdio.h>
#include <stdlib.h>
#include <string.h>
#include <linux/types.h>

typedef unsigned char u8;
#define __iomem

/* readb() over a plain buffer: the span helper never touches real I/O. */
static u8 image[4096];
static u8 readb(const void *addr) { return *(const u8 *)addr; }
'''

TEST_BODY = r'''
/* Drain the whole region in caller-chosen windows, like a paged reader. */
static size_t drain(size_t window, char *out, size_t capacity)
{
	size_t total = 0;
	loff_t pos = 0;
	bool nl = true;

	while (pos < (loff_t)sizeof(image)) {
		size_t n = 0;

		/* Mirror the reader: skip padding windows, never signal EOF early. */
		while (!n && pos < (loff_t)sizeof(image))
			n = md_dfd_span(image, &pos, sizeof(image),
				       out + total, window, &nl);

		assert(n <= window);
		total += n;
		assert(total <= capacity);
		if (!n)
			break;
	}
	out[total] = 0;
	return total;
}

static void reset(const char *text)
{
	memset(image, 0, sizeof(image));
	memcpy(image, text, strlen(text));
}

int main(void)
{
	char out[8192];
	size_t n;
	bool nl;

	/* A printable run is copied verbatim and ends as a newline. */
	reset("MD1 boot ok");
	n = drain(2048, out, sizeof(out));
	assert(!strcmp(out, "MD1 boot ok\n"));
	assert(n == 12);

	/* An all-zero region is empty text, not one separator per zero. */
	memset(image, 0, sizeof(image));
	n = drain(2048, out, sizeof(out));
	assert(n == 0 && !strcmp(out, ""));

	/* Runs collapse across the window boundary: no doubled separator. */
	reset("AB");
	memset(image + 2, 0, 100);
	memcpy(image + 102, "CD", 2);
	n = drain(1, out, sizeof(out));
	assert(!strcmp(out, "AB\nCD\n"));

	/* Non-ASCII is a separator too, not text. */
	reset("A\xff\xfe" "B");
	n = drain(2048, out, sizeof(out));
	assert(!strcmp(out, "A\nB\n"));

	/* An empty region writes nothing. */
	memset(image, 0, sizeof(image));
	{
		loff_t pos = 0;

		nl = true;
		assert(md_dfd_span(image, &pos, 0, out, sizeof(out), &nl) == 0);
		assert(pos == 0);
	}

	/* Capacity is a hard stop and position follows the consumed bytes. */
	reset("ABCDEF");
	{
		loff_t pos = 0;

		nl = true;
		assert(md_dfd_span(image, &pos, 6, out, 3, &nl) == 3);
		assert(pos == 3);
		assert(md_dfd_span(image, &pos, 6, out + 3, 3, &nl) == 3);
		assert(pos == 6);
		out[6] = 0;
		assert(!strcmp(out, "ABCDEF"));
	}

	/* Leading separators are suppressed when the caller enters mid-run. */
	memset(image, 0, sizeof(image));
	memcpy(image + 10, "X", 1);
	{
		loff_t pos = 4;

		nl = true;
		n = md_dfd_span(image, &pos, sizeof(image), out, 2048, &nl);
		out[n] = 0;
		assert(n == 2 && !strcmp(out, "X\n"));
	}

	puts("PASS: actual DFD text conversion: verbatim runs, collapsed separators,");
	puts("      cross-window state, hard capacity stop and exact position");
	return 0;
}
'''

with tempfile.TemporaryDirectory(prefix='op6893-md-dfd-') as temporary:
    root = Path(temporary)
    (root / 'linux').mkdir()
    (root / 'linux/types.h').write_text('#include <stdbool.h>\n')
    source = (SRC / 'ccci-md-platform.c').read_text()
    span = source[source.index('static size_t md_dfd_span'):
                  source.index('/*\n * Streaming text view')]
    (root / 'test.c').write_text(TEST_HEAD + '\n' + span + TEST_BODY)
    subprocess.run(['cc', '-std=gnu11', '-Wall', '-Wextra', '-Werror',
                    '-fsanitize=address,undefined', '-fno-sanitize-recover=all',
                    '-I' + str(root), str(root / 'test.c'), '-o', str(root / 'test')],
                   check=True)
    subprocess.run([str(root / 'test')], check=True)
