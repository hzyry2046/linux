#!/usr/bin/env python3
# SPDX-License-Identifier: GPL-2.0-only
"""Exercise actual resource-check probe and CCIF gate ops on host stubs.

No device access. Optional DTB arguments check board-local wiring and disabled
defaults, including a saved merged FDT. These tests do not emulate PMIC/genpd,
the CCF core, provider shutdown, secure firmware or modem readiness.
"""

import argparse
from pathlib import Path
import struct
import subprocess
import tempfile

KERNEL = Path(__file__).resolve().parents[5]


def function(source, declaration):
    start = source.index(declaration)
    return source[start:source.index("\n}", start) + 2]


def run_c(code):
    with tempfile.TemporaryDirectory() as directory:
        path = Path(directory)
        (path / "test.c").write_text(code)
        subprocess.run(["cc", "-Wall", "-Wextra", "-Werror", "-Wno-sign-compare",
                        "-fsanitize=undefined", "-fno-sanitize-recover=all",
                        str(path / "test.c"), "-o", str(path / "test")], check=True)
        subprocess.run([str(path / "test")], check=True)


def test_probe():
    source = (KERNEL / "drivers/misc/mediatek/ccci/ccci-resources.c").read_text()
    run_c(r'''
#include <assert.h>
#include <errno.h>
#include <stdarg.h>
#include <stdint.h>
#include <stdio.h>
#include <stdlib.h>
#include <string.h>
#define EPROBE_DEFER 517
#define GFP_KERNEL 0
#define ARRAY_SIZE(a) (sizeof(a) / sizeof((a)[0]))
#define ERR_PTR(n) ((void *)(intptr_t)(n))
#define PTR_ERR(p) ((int)(intptr_t)(p))
#define IS_ERR(p) ((uintptr_t)(p) >= (uintptr_t)-4095)
struct device_node { unsigned supplies; };
struct device { struct device_node *of_node; };
struct platform_device { struct device dev; };
struct regulator { int unused; };
struct clk_bulk_data { const char *id; void *clk; };
static const char * const names[] = {
 "md-vmodem", "md-vnr", "md-vsram", "md-vdigrf"
};
static struct regulator rails[4];
static unsigned gets, clock_gets, success_logs;
static int bad_rail, rail_error, clock_error, no_memory;
static void *allocation;
static void *devm_kcalloc(struct device *d, size_t n, size_t s, int flags) {
 (void)d; (void)flags; assert(!allocation);
 if (no_memory) return NULL;
 allocation = calloc(n, s); return allocation;
}
static int of_property_present(struct device_node *n, const char *name) {
 char property[32];
 for (unsigned i = 0; i < 4; i++) {
  snprintf(property, sizeof(property), "%s-supply", names[i]);
  if (!strcmp(property, name)) return !!(n->supplies & (1U << i));
 }
 assert(0); return 0;
}
static struct regulator *devm_regulator_get_optional(struct device *d, const char *name) {
 (void)d; unsigned i = gets++;
 assert(i < 4 && !strcmp(names[i], name));
 return (int)i == bad_rail ? ERR_PTR(rail_error) : &rails[i];
}
static int devm_clk_bulk_get(struct device *d, int count, struct clk_bulk_data *clocks) {
 static const char * const expected[] = { "ccif-ap", "ccif-md", "ccif1-ap", "ccif1-md" };
 (void)d; clock_gets++; assert(count == 4 && gets == 4);
 for (int i = 0; i < count; i++) assert(!strcmp(clocks[i].id, expected[i]));
 return clock_error;
}
static int dev_err_probe(struct device *d, int error, const char *format, ...) {
 (void)d; (void)format; assert(error < 0); return error;
}
static void dev_info(struct device *d, const char *message) {
 (void)d; assert(strstr(message, "references acquired")); success_logs++;
}
''' + function(source, "static int ccci_resources_probe(") + r'''
static void reset(void) {
 free(allocation); allocation = NULL;
 gets = clock_gets = success_logs = 0;
 bad_rail = -1; rail_error = clock_error = no_memory = 0;
}
int main(void) {
 struct device_node n = { .supplies = 15 };
 struct platform_device p = { .dev = { .of_node = &n } };
 reset(); no_memory = 1;
 assert(ccci_resources_probe(&p) == -ENOMEM);
 assert(!gets && !clock_gets && !success_logs);
 for (unsigned missing = 0; missing < 4; missing++) {
  reset(); n.supplies = 15 & ~(1U << missing);
  assert(ccci_resources_probe(&p) == -EINVAL);
  assert(gets == missing && !clock_gets && !success_logs);
 }
 n.supplies = 15;
 int errors[] = { -ENODEV, -ENOENT, -EPROBE_DEFER, -EIO };
 for (unsigned i = 0; i < 4; i++) for (unsigned e = 0; e < ARRAY_SIZE(errors); e++) {
  reset(); bad_rail = i; rail_error = errors[e];
  assert(ccci_resources_probe(&p) == errors[e]);
  assert(gets == i + 1 && !clock_gets && !success_logs);
 }
 for (unsigned e = 0; e < ARRAY_SIZE(errors); e++) {
  reset(); clock_error = errors[e];
  assert(ccci_resources_probe(&p) == errors[e]);
  assert(gets == 4 && clock_gets == 1 && !success_logs);
 }
 reset(); assert(!ccci_resources_probe(&p));
 assert(gets == 4 && clock_gets == 1 && success_logs == 1);
 reset(); return 0;
}
''')
    print("PASS: actual probe: allocation failure, four missing properties, "
          "16 regulator failures, clock failures, success; no enable API in harness")


def test_gates():
    source = (KERNEL / "drivers/clk/mediatek/clk-mt6893-pmif.c").read_text()
    gates = (KERNEL / "drivers/clk/mediatek/clk-gate.c").read_text()
    header = (KERNEL / "drivers/clk/mediatek/clk-gate.h").read_text()
    ids = (KERNEL / "include/dt-bindings/clock/mt6893-clk.h").read_text()
    code = r'''
#include <assert.h>
#include <stddef.h>
#include <stdint.h>
#include <string.h>
typedef uint32_t u32;
#define BIT(n) (1U << (n))
#define ARRAY_SIZE(a) (sizeof(a) / sizeof((a)[0]))
#define CLK_IGNORE_UNUSED BIT(0)
#define container_of(p,t,m) ((t *)((char *)(p)-offsetof(t,m)))
struct clk_hw { int unused; };
struct clk_ops { int (*is_enabled)(struct clk_hw *); int (*enable)(struct clk_hw *);
 void (*disable)(struct clk_hw *); };
struct regmap { u32 status, reg, value; unsigned writes; };
static int regmap_read(struct regmap *m, unsigned reg, u32 *value) {
 assert(reg == 0x94); *value = m->status; return 0;
}
static int regmap_write(struct regmap *m, unsigned reg, u32 value) {
 assert(reg == 0x88 || reg == 0x8c);
 m->reg = reg; m->value = value; m->writes++;
 if (reg == 0x88) m->status |= value; else m->status &= ~value;
 return 0;
}
extern const struct clk_ops mtk_clk_gate_ops_setclr;
'''
    code += ids + header[header.index("struct mtk_gate_regs {"):header.index("\n#define GATE_MTK(")]
    code += gates[gates.index("struct mtk_clk_gate {"):gates.index("\nstatic int mtk_cg_bit_is_set")]
    for name in ("static void mtk_cg_set_bit(", "static void mtk_cg_clr_bit(",
                 "static int mtk_cg_enable(", "static void mtk_cg_disable("):
        code += "\n" + function(gates, name)
    start = gates.index("const struct clk_ops mtk_clk_gate_ops_setclr =")
    code += "\n" + gates[start:gates.index("\n};", start) + 3]
    start = source.index("static const struct mtk_gate_regs ccif_gate_regs")
    code += "\n" + source[start:source.index("\n#endif", start)]
    code += r'''
int main(void) {
 const unsigned expected_ids[] = {28, 29, 33, 35}, shifts[] = {12, 13, 23, 26};
 const u32 patterns[] = {0, ~0U, 0xaaaaaaaa, 0x55555555, BIT(0) | BIT(1)};
 assert(ARRAY_SIZE(ccif_gates) == 4);
 for (unsigned i = 0; i < ARRAY_SIZE(ccif_gates); i++) {
  const struct mtk_gate *d = &ccif_gates[i];
  assert(d->id == (int)expected_ids[i] && d->shift == (int)shifts[i]);
  assert(d->flags == CLK_IGNORE_UNUSED);
  assert(!strcmp(d->parent_name, "mt6893_axi_observed"));
  for (unsigned j = 0; j < ARRAY_SIZE(patterns); j++) {
   struct regmap m = {.status = patterns[j]};
   struct mtk_clk_gate gate = {.regmap = &m, .gate = d};
   assert(!d->ops->enable(&gate.hw));
   assert(m.writes == 1 && m.reg == 0x8c && m.value == BIT(shifts[i]));
   assert(m.status == (patterns[j] & ~BIT(shifts[i])) && d->ops->is_enabled(&gate.hw));
   d->ops->disable(&gate.hw);
   assert(m.writes == 2 && m.reg == 0x88 && m.value == BIT(shifts[i]));
   assert(m.status == (patterns[j] | BIT(shifts[i])) && !d->ops->is_enabled(&gate.hw));
  }
 }
 return 0;
}
'''
    run_c(code)
    print("PASS: actual four CCIF descriptors and set/clear ops: "
          "vendor IDs, offsets, masks, inherited parent and adjacent-bit preservation")


def test_dtb(path, enabled=False):
    import libfdt

    fdt = libfdt.Fdt(path.read_bytes())

    def prop(node, name):
        return bytes(fdt.getprop(node, name))

    def cells(node, name):
        raw = prop(node, name)
        return struct.unpack(">" + "I" * (len(raw) // 4), raw)

    expected_status = b"okay\0" if enabled else b"disabled\0"
    node = fdt.path_offset("/modem-resources")
    assert prop(node, "status") == expected_status
    for supply, buck, rail in (("md-vmodem", "vbuck1", "vmodem"),
                              ("md-vnr", "vbuck3", "vnr"),
                              ("md-vsram", "vbuck4", "vsram_md"),
                              ("md-vdigrf", "buck_vpu", "vdigrf")):
        ref = cells(node, supply + "-supply")
        assert len(ref) == 1
        target = fdt.node_offset_by_phandle(ref[0])
        assert fdt.get_name(target) == buck
        assert prop(target, "regulator-name") == rail.encode() + b"\0"
        # No voltage/mode/enable constraints in these first-stage descriptions.
        offset = fdt.first_property_offset(target)
        while True:
            p = fdt.get_property_by_offset(offset)
            assert p.name in ("regulator-name", "status", "phandle"), p.name
            try:
                offset = fdt.next_property_offset(offset)
            except libfdt.FdtException as exc:
                assert exc.err == -libfdt.NOTFOUND
                break
        if buck == "buck_vpu":
            assert prop(target, "status") == expected_status
        else:
            pmic = fdt.parent_offset(fdt.parent_offset(target))
            assert prop(pmic, "status") == expected_status
            assert cells(pmic, "reg") == (3, 0)
            assert prop(pmic, "compatible") == b"mediatek,mt6315-regulator\0"
    clocks = cells(node, "clocks")
    assert len(clocks) == 8 and clocks[1::2] == (33, 35, 28, 29)
    assert len(set(clocks[0::2])) == 1
    provider = fdt.node_offset_by_phandle(clocks[0])
    assert b"mediatek,mt6893-infracfg_ao\0" in prop(provider, "compatible")
    assert prop(node, "clock-names") == b"ccif-ap\0ccif-md\0ccif1-ap\0ccif1-md\0"
    for name in ("power-domains", "resets", "reg", "interrupts"):
        try:
            fdt.getprop(node, name)
        except libfdt.FdtException as exc:
            assert exc.err == -libfdt.NOTFOUND
        else:
            raise AssertionError(f"unexpected activating resource: {name}")
    state = "explicit enabled variant" if enabled else "disabled defaults"
    print(f"PASS: {path.name}: board-local supplies/clocks, {state}, "
          "no constraints/domain/reset/MMIO")


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--dtb", type=Path, action="append", default=[])
    parser.add_argument("--enabled-dtb", type=Path, action="append", default=[],
                        help="Explicit resource-reference runtime variant only")
    args = parser.parse_args()
    test_probe()
    test_gates()
    for path in args.dtb:
        test_dtb(path)
    for path in args.enabled_dtb:
        test_dtb(path, enabled=True)


if __name__ == "__main__":
    main()
