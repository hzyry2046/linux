#!/usr/bin/env python3
# SPDX-License-Identifier: GPL-2.0-only
"""Run extracted ACK connectivity PMIC functions with host-only fake APIs.

No device access. Traces API order and return handling, not voltage behavior.
"""
import hashlib
import json
from pathlib import Path
import subprocess
import tempfile

BASE = Path('/data/src/6.6-exp/android_kernel_modules_oneplus_mt6833/vendor/'
            'mediatek/kernel_modules/connectivity/conninfra/conn_drv/connv2/'
            'platform/mt6893')


def function(text, signature):
    start = text.index(signature + '\n{')
    brace = text.index('{', start)
    depth = 1
    end = brace + 1
    while depth:
        depth += (text[end] == '{') - (text[end] == '}')
        end += 1
    return text[start:end]


HARNESS = r'''
#include <stdbool.h>
#include <stdint.h>
#include <stdio.h>
#include <stdlib.h>
#define COMMON_KERNEL_PMIC_SUPPORT 1
#define pr_info(...) ((void)0)
#define pr_err(...) ((void)0)
static int rc_mode, event, fail_at, g_voltage_change_status;
static int g_voltage_change_timer;
static void *g_regmap;
static void *reg_VCN18 = (void *)18, *reg_VCN13 = (void *)13;
static int consys_is_rc_mode_enable_mt6893(void) { return rc_mode; }
static int result(void) { return ++event == fail_at ? -5 : 0; }
static int regmap_write(void *map, unsigned int addr, unsigned int value) {
 int ret = result(); (void)map;
 printf("write %04x %04x ret=%d\n", addr, value, ret); return ret;
}
static int regmap_update_bits(void *map, unsigned int addr,
 unsigned int mask, unsigned int value) {
 int ret = result(); (void)map;
 printf("update %04x %04x %04x ret=%d\n", addr, mask, value, ret); return ret;
}
static int regulator_set_voltage(void *reg, int min, int max) {
 int ret = result();
 printf("voltage %ld %d %d ret=%d\n", (long)reg, min, max, ret); return ret;
}
static int regulator_enable(void *reg) {
 int ret = result(); printf("enable %ld ret=%d\n", (long)reg, ret); return ret;
}
static int regulator_disable(void *reg) {
 int ret = result(); printf("disable %ld ret=%d\n", (long)reg, ret); return ret;
}
static int atomic_read(int *value) { return *value; }
static void atomic_set(int *value, int next) { *value = next; }
static void udelay(unsigned int usec) { printf("delay_us %u\n", usec); }
static void osal_timer_modify(int *timer, unsigned int milliseconds) {
 (void)timer; printf("timer_ms %u\n", milliseconds);
 /* Model the completion before the next call; no real host timer exists. */
 g_voltage_change_status = 0;
}
enum vcn13_state { vcn13_1_3v, vcn13_1_32v, vcn13_1_37v };
'''


def main():
    source = BASE / 'mt6893_pmic.c'
    header = BASE / 'include/mt6893_pmic.h'
    text = source.read_text()
    defines = header.read_text().split('#ifndef MT6359_PMIC_REG_BASE', 1)[1].split('#endif', 1)[0]
    common = function(text, 'int consys_plt_pmic_common_power_ctrl(unsigned int enable, unsigned int curr_status, unsigned int next_status)')
    raise_voltage = function(text, 'static void consys_raise_vcn13_vs2_voltage(enum vcn13_state next_state)')
    program = HARNESS + defines + '\n' + common + '\n' + raise_voltage + r'''
int main(int argc, char **argv) {
 int ret;
 if (argc != 6) return 2;
 rc_mode = atoi(argv[1]); fail_at = atoi(argv[5]);
 if (argv[2][0] == 'r') {
  consys_raise_vcn13_vs2_voltage(vcn13_1_37v);
  consys_raise_vcn13_vs2_voltage(vcn13_1_3v);
  ret = 0;
 } else {
  ret = consys_plt_pmic_common_power_ctrl(atoi(argv[2]),
       (unsigned int)atoi(argv[3]), (unsigned int)atoi(argv[4]));
 }
 printf("return %d events %d\n", ret, event); return 0;
}
'''
    traces = {}
    with tempfile.TemporaryDirectory() as directory:
        root = Path(directory)
        (root / 'trace.c').write_text(program)
        subprocess.run(['cc', '-std=c11', '-Wall', '-Wextra', '-Werror',
                        '-fsanitize=undefined', str(root / 'trace.c'),
                        '-o', str(root / 'trace')], check=True)

        def run(rc, enable, current=0, next_status=1, fail=0):
            result = subprocess.run([str(root / 'trace'), str(rc), str(enable),
                                     str(current), str(next_status), str(fail)],
                                    check=True, capture_output=True, text=True, timeout=2)
            if result.stderr:
                raise RuntimeError(result.stderr)
            return result.stdout.splitlines()

        for rc in (0, 1):
            traces[f'on_rc{rc}'] = run(rc, 1)
            traces[f'on_already_active_rc{rc}'] = run(rc, 1, 1, 3)
            traces[f'off_last_rc{rc}'] = run(rc, 0, 1, 0)
            traces[f'off_still_active_rc{rc}'] = run(rc, 0, 3, 1)
        traces['raise_and_restore'] = run(0, 'r')
        # Inject an error at every modeled regmap/regulator API call. Record
        # actual vendor behavior without claiming a corrected transaction.
        faults = {}
        for rc in (0, 1):
            count = int(traces[f'on_rc{rc}'][-1].split()[-1])
            faults[f'on_rc{rc}'] = [run(rc, 1, fail=index)
                                    for index in range(1, count + 1)]
    print(json.dumps({
        'inputs': {str(path): hashlib.sha256(path.read_bytes()).hexdigest()
                   for path in (source, header)},
        'traces': traces, 'fault_injection': faults,
        'limits': ['Host API order only; no physical writes or rail measurements.',
                   'Timer completes immediately in the model; busy wait not validated.',
                   'SET/CLR alias side effects are not modeled as ordinary registers.',
                   'Return values are observations of extracted vendor code.'],
    }, indent=2))


if __name__ == '__main__':
    main()
