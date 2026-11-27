#!/usr/bin/env python3
# SPDX-License-Identifier: GPL-2.0-only
"""Compile actual snapshot code against read-only fake AP/PMIC/regulators."""
from pathlib import Path
import subprocess
import tempfile

kernel = Path(__file__).resolve().parents[5]
source = (kernel / 'arch/arm64/kernel/op6893-conn.c').read_text()
code = source[source.index('static const char * const op6893_conn_rails[]'):
              source.index('static DEVICE_ATTR_ADMIN_RO(preflight)')]
readonly = code + source[source.index('static int op6893_conn_probe('):]
assert not any(token in readonly for token in (
    'writel(', 'regmap_write(', 'regmap_update_bits(', 'regulator_enable(',
    'regulator_set_voltage(', 'pinctrl_select_state(', 'clk_prepare_enable(',
))
assert source.count('devm_ioremap(') == 3
assert 'devm_ioremap(dev, 0x180' not in source
assert 'devm_regulator_get_optional(' in source

harness = r'''
#include <assert.h>
#include <errno.h>
#include <stdbool.h>
#include <stdarg.h>
#include <stdint.h>
#include <stdio.h>
#include <string.h>
#include <sys/types.h>
#define __iomem
#define BIT(n) (1U << (n))
#define ARRAY_SIZE(a) (sizeof(a) / sizeof((a)[0]))
typedef uint8_t u8;
typedef uint32_t u32;
typedef unsigned long long u64;
struct mutex { bool held; };
struct regmap { unsigned reads; int fail; };
struct regulator { int enabled, voltage; };
struct device { void *data; };
struct device_attribute {};
static int lock_error;
static int mutex_lock_interruptible(struct mutex *m) {
 if (lock_error) return lock_error;
 assert(!m->held); m->held = true; return 0;
}
static void mutex_unlock(struct mutex *m) { assert(m->held); m->held = false; }
static void *dev_get_drvdata(struct device *d) { return d->data; }
static u64 ktime_get_boottime_ns(void) { static u64 n; return ++n; }
static unsigned int spm[1024], infra[1024], host;
static bool transition, wrong_id;
static u32 readl(void *p) {
 if (p == &spm[0x16c / 4] && transition) {
  u32 result = *(u32 *)p; *(u32 *)p |= BIT(1); return result;
 }
 return *(u32 *)p;
}
static int regmap_read(struct regmap *m, unsigned int reg, u32 *v) {
 if (++m->reads == (unsigned int)m->fail) return -EIO;
 *v = reg == 8 ? (wrong_id ? 0x5900 : 0x5930) : reg; return 0;
}
static int regulator_is_enabled(struct regulator *r) { return r->enabled; }
static int regulator_get_voltage(struct regulator *r) { return r->voltage; }
static int emit(char *buf, size_t at, const char *fmt, va_list ap) {
 int n = vsnprintf(buf + at, 4096 - at, fmt, ap);
 assert(n >= 0 && at + n < 4096); return n;
}
static int sysfs_emit(char *buf, const char *fmt, ...) {
 va_list ap; va_start(ap, fmt); int n = emit(buf, 0, fmt, ap); va_end(ap); return n;
}
static int sysfs_emit_at(char *buf, size_t at, const char *fmt, ...) {
 va_list ap; va_start(ap, fmt); int n = emit(buf, at, fmt, ap); va_end(ap); return n;
}
''' + code + r'''
int main(void) {
 struct regmap map = {0}; struct regulator rails[6]; char buf[4096];
 struct op6893_conn conn = {.pmic = &map, .spm = spm, .infra = infra, .host = &host};
 struct device dev = {.data = &conn};
 for (unsigned i = 0; i < 6; i++) {
  rails[i] = (struct regulator){.enabled = 1, .voltage = 1800000};
  conn.rails[i] = &rails[i];
 }
 spm[0x304 / 4] = 0x12; spm[0x504 / 4] = 1;
 infra[0x228 / 4] = BIT(13) | BIT(14); infra[0x724 / 4] = BIT(2);
 assert(preflight_show(&dev, NULL, buf) > 0);
 assert(strstr(buf, "off_at_both_samples=1 rc_mode=1 legacy_protection_complete=1"));
 assert(strstr(buf, "activation_ready=0 upstream_policy=unresolved"));
 assert(map.reads == ARRAY_SIZE(op6893_conn_pmic_regs));
 /* A single live ACK or any mixed low control bits rejects the off label. */
 for (unsigned a = 0; a < 2; a++) for (unsigned b = 0; b < 2; b++)
  for (unsigned c = 0; c < 32; c++)
   assert(op6893_conn_is_off(a * BIT(1), b * BIT(1), c) ==
          (!a && !b && c == 0x12));
 assert(op6893_conn_is_off(0xfffffffd, 0xfffffffd, 0xfffffff2));
 transition = true;
 assert(preflight_show(&dev, NULL, buf) > 0);
 assert(strstr(buf, "off_at_both_samples=0"));
 transition = false; spm[0x16c / 4] = 0;
 /* Historical inherited off state lacks step1; it must remain visible. */
 infra[0x228 / 4] = BIT(14); spm[0x504 / 4] = 0;
 assert(preflight_show(&dev, NULL, buf) > 0);
 assert(strstr(buf, "off_at_both_samples=1 rc_mode=0 legacy_protection_complete=0"));
 for (unsigned i = 1; i <= ARRAY_SIZE(op6893_conn_pmic_regs); i++) {
  map = (struct regmap){.fail = i};
  assert(preflight_show(&dev, NULL, buf) == -EIO);
  assert(map.reads == i && !conn.lock.held);
 }
 map = (struct regmap){0}; wrong_id = true;
 assert(preflight_show(&dev, NULL, buf) == -ENODEV && !conn.lock.held);
 wrong_id = false;
 for (unsigned i = 0; i < 6; i++) {
  rails[i].enabled = -EIO;
  assert(preflight_show(&dev, NULL, buf) == -EIO && !conn.lock.held);
  rails[i].enabled = 1; rails[i].voltage = -EINVAL;
  assert(preflight_show(&dev, NULL, buf) == -EINVAL && !conn.lock.held);
  rails[i].voltage = 1800000;
 }
 lock_error = -EINTR;
 assert(preflight_show(&dev, NULL, buf) == -EINTR && !conn.lock.held);
 lock_error = 0;
 assert(preflight_show(&dev, NULL, buf) > 0); /* Read errors permit retry. */
}
'''
with tempfile.TemporaryDirectory() as tmp:
    path = Path(tmp)
    (path / 'test.c').write_text(harness)
    subprocess.run(['cc', '-Wall', '-Wextra', '-Werror',
                    '-Wno-unused-parameter', '-fsanitize=undefined',
                    '-fno-sanitize-recover=all', str(path / 'test.c'),
                    '-o', str(path / 'test')], check=True)
    subprocess.run([str(path / 'test')], check=True)
print('PASS: extracted snapshot, 128 off states, transition, inherited protection, '
      '20 PMIC faults, identity, 12 regulator faults, interrupted read and retry')
