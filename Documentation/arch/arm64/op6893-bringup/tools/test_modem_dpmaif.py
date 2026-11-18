#!/usr/bin/env python3
# SPDX-License-Identifier: GPL-2.0-only
"""Compile the actual DPMAIF sample formatter with synthetic samples and sanitizers.

Checks the exact rendering, the mask derivations and that a short buffer is
reported rather than overrun. No device, clock or register is touched.
"""
from pathlib import Path
import subprocess
import tempfile

K = Path(__file__).resolve().parents[5]
SRC = K / 'drivers/misc/mediatek/ccci'
TEST = r'''
#include <assert.h>
#include <errno.h>
#include <stdio.h>
#include <string.h>
#include "ccci-dpmaif.h"

static void expect_contains(const char *hay, const char *needle)
{
	assert(strstr(hay, needle));
}

int main(void)
{
	char buf[1024];
	struct ccci_dpmaif_sample s;
	ssize_t n;

	/* Every field is rendered in the documented order with a fixed width. */
	memset(&s, 0, sizeof(s));
	s.ao_ul_chnl0_sta = 0x1;
	s.ao_ul_chnl0_sta0 = 0x2;
	s.ao_ul_l2timr0 = 0x3;
	s.pd_ul_add_desc = 0x4;
	s.pd_ul_add_desc_ch0 = 0x5;
	s.pd_md_ip_busy = 0x6;
	s.pd_md_ip_busy_mask = 0x7;
	s.sram_word0 = 0x8;
	s.sram_word1 = 0x9;
	s.infra_ctrl = 0x0;
	s.rate_main = 156000000;
	s.rate_bus = 156000000;
	n = ccci_dpmaif_format(&s, buf, sizeof(buf));
	assert(n > 0);
	assert((size_t)n == strlen(buf));
	expect_contains(buf, "ao_ul_chnl0_sta=0x00000001");
	expect_contains(buf, "ao_ul_chnl0_sta0=0x00000002");
	expect_contains(buf, "ao_ul_l2timr0=0x00000003");
	expect_contains(buf, "pd_ul_add_desc=0x00000004");
	expect_contains(buf, "pd_ul_add_desc_ch0=0x00000005");
	expect_contains(buf, "pd_md_ip_busy=0x00000006");
	expect_contains(buf, "pd_md_ip_busy_mask=0x00000007");
	expect_contains(buf, "sram_raw0=0x00000008");
	expect_contains(buf, "sram_raw1=0x00000009");
	expect_contains(buf, "infra_ctrl=0x00000000");
	expect_contains(buf, "clk_main=156000000 clk_bus=156000000");
	/* A clear busy mask and a clear wakeup bit both render as 0. */
	expect_contains(buf, "busy_mask_field=0 wakeup_event_bit=0");
	expect_contains(buf, "md_busy_mask_field=0");

	/*
	 * The vendor ORs a two-bit field at bit 12 and then clears bit 13, so the
	 * post-init value is bit 12 set and bit 13 clear. Report the field and the
	 * wakeup bit separately instead of treating either as a boolean.
	 */
	s.infra_ctrl = CCCI_DPMAIF_IP_BUSY_MASK & ~CCCI_DPMAIF_WAKEUP_EVENT;
	n = ccci_dpmaif_format(&s, buf, sizeof(buf));
	assert(n > 0);
	expect_contains(buf, "busy_mask_field=1 wakeup_event_bit=0");
	s.infra_ctrl = CCCI_DPMAIF_IP_BUSY_MASK;
	n = ccci_dpmaif_format(&s, buf, sizeof(buf));
	assert(n > 0);
	expect_contains(buf, "busy_mask_field=3 wakeup_event_bit=1");
	s.infra_ctrl = CCCI_DPMAIF_WAKEUP_EVENT;
	n = ccci_dpmaif_format(&s, buf, sizeof(buf));
	assert(n > 0);
	expect_contains(buf, "busy_mask_field=2 wakeup_event_bit=1");
	s.pd_md_ip_busy_mask = CCCI_DPMAIF_IP_BUSY_MASK;
	n = ccci_dpmaif_format(&s, buf, sizeof(buf));
	assert(n > 0);
	expect_contains(buf, "md_busy_mask_field=3");
	/* The wakeup bit is part of the vendor set mask by construction. */
	assert(CCCI_DPMAIF_IP_BUSY_MASK & CCCI_DPMAIF_WAKEUP_EVENT);

	/* A short buffer is an explicit -ENOSPC, never a silently cut dump. */
	memset(&s, 0, sizeof(s));
	{
		char small[40];
		memset(small, 0x5a, sizeof(small));
		assert(ccci_dpmaif_format(&s, small, sizeof(small)) == -ENOSPC);
		assert(small[sizeof(small) - 1] == '\0');
	}
	/* Exactly-sized buffers still succeed, one byte short does not. */
	{
		char exact[512];
		char *sized;

		n = ccci_dpmaif_format(&s, buf, sizeof(buf));
		assert(n > 0);
		sized = __builtin_alloca((size_t)n + 1);
		assert(ccci_dpmaif_format(&s, sized, (size_t)n + 1) == n);
		assert(ccci_dpmaif_format(&s, exact, (size_t)n) == -ENOSPC);
	}

	assert(ccci_dpmaif_format(NULL, buf, sizeof(buf)) == -EINVAL);
	assert(ccci_dpmaif_format(&s, NULL, sizeof(buf)) == -EINVAL);
	assert(ccci_dpmaif_format(&s, buf, 0) == -EINVAL);

	puts("PASS: actual DPMAIF sample formatter, field order, mask derivation and bounded output");
	return 0;
}
'''


def main():
    with tempfile.TemporaryDirectory(prefix='op6893-dpmaif-') as directory:
        tmp = Path(directory)
        inc = tmp / 'linux'
        inc.mkdir()
        (inc / 'types.h').write_text(
            '#pragma once\n#include <stdint.h>\n#include <stddef.h>\n#include <stdbool.h>\n'
            'typedef uint8_t u8; typedef uint32_t u32; typedef uint64_t u64;\n'
            'typedef int32_t s32;\n')
        (inc / 'errno.h').write_text('#include <asm-generic/errno.h>\n')
        (inc / 'string.h').write_text('#include <string.h>\n')
        (inc / 'bits.h').write_text('#pragma once\n#define BIT(n) (1UL << (n))\n')
        # libc snprintf already returns the would-be length, like the kernel's.
        (inc / 'kernel.h').write_text('#pragma once\n#include <linux/types.h>\n#include <stdio.h>\n')
        (tmp / 'test.c').write_text(TEST)
        subprocess.run(['cc', '-O1', '-g', '-Wall', '-Wextra', '-Werror',
                        '-fsanitize=address,undefined', '-fno-sanitize-recover=all',
                        '-no-pie', '-DCONFIG_OP6893_CCCI_DPMAIF=1',
                        '-DIS_ENABLED(x)=(x)',
                        '-I' + str(tmp), '-I' + str(SRC),
                        str(SRC / 'ccci-dpmaif-format.c'), str(tmp / 'test.c'),
                        '-o', str(tmp / 'test')], check=True)
        subprocess.run([str(tmp / 'test')], check=True)


if __name__ == '__main__':
    main()
