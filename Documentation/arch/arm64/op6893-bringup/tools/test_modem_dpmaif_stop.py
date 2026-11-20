#!/usr/bin/env python3
# SPDX-License-Identifier: GPL-2.0-only
"""Exercise the actual DL stop path with injected register timeouts."""
from pathlib import Path
import subprocess
import tempfile

root = Path(__file__).resolve().parents[5]
driver = root / 'drivers/misc/mediatek/ccci'
code = (driver / 'ccci-dpmaif.c').read_text()
prelude = r'''
#include <assert.h>
#include <stdbool.h>
#include <errno.h>
#include <stdint.h>
#include <stddef.h>
#include <sys/types.h>
#define IS_ENABLED(config) 1
typedef uint8_t u8;
typedef uint64_t u64;
#define BIT(n) (1U << (n))
typedef uint32_t u32;
#define __iomem
#include "ccci-dpmaif.h"
struct ccci_dpmaif_dl {
 int lock, pit_rd, pit_entries, pit_dma, bat, frg, fail_reg;
 bool started, rx_head;
 void *pit;
};
struct ccci_dpmaif { struct ccci_dpmaif_dl dl; int dev, clk_bus, clk_main; };
static int step, fail_at, releases, irq_puts, addr_writes;
static bool failed(void) { return ++step == fail_at; }
#define spin_lock_irq(x) ((void)(x))
#define spin_unlock_irq(x) ((void)(x))
#define readl_poll_timeout(addr, value, cond, delay, timeout) \
 ({ (void)(addr); value = step == 1 ? 0 : CCCI_DPMAIF_DL_IDLE; \
    assert(cond); failed() ? -ETIMEDOUT : 0; })
static u32 pd[256], ao[256], misc[256];
static void *dpmaif_pd_dl(struct ccci_dpmaif *d) { (void)d; return pd; }
static void *dpmaif_ao_dl(struct ccci_dpmaif *d) { (void)d; return ao; }
static void *dpmaif_ap_misc(struct ccci_dpmaif *d) { (void)d; return misc; }
static u32 readl(void *addr) { return *(u32 *)addr; }
static void writel(u32 data, void *addr)
{
 if (addr == (void *)pd + CCCI_DPMAIF_PD_DL_PIT_INIT_CON0 ||
     addr == (void *)pd + CCCI_DPMAIF_PD_DL_BAT_INIT_CON0)
  addr_writes++;
 *(u32 *)addr = data;
}
static int dpmaif_dl_timeout(struct ccci_dpmaif *d, u32 reg)
{
 d->dl.fail_reg = reg;
 return -ETIMEDOUT;
}
static int dpmaif_dl_update(struct ccci_dpmaif *d, u32 reg, u32 command)
{
 (void)command;
 return failed() ? dpmaif_dl_timeout(d, reg) : 0;
}
static int dpmaif_dl_queue_enable(struct ccci_dpmaif *d, bool enable, bool frag)
{
 assert(!enable);
 assert(frag == (step == 3));
 return dpmaif_dl_update(d, CCCI_DPMAIF_PD_DL_BAT_INIT, 0);
}
static void dpmaif_dl_irq_mask(struct ccci_dpmaif *d) { (void)d; }
static void dpmaif_irq_put(struct ccci_dpmaif *d) { assert(!d->dl.started); irq_puts++; }
#define dma_free_coherent(...) (++releases)
#define dpmaif_dl_ring_free(...) (++releases)
#define clk_disable_unprepare(...) (++releases)
'''
test = r'''
int main(void)
{
 int buffer;
 for (int failure = 1; failure <= 5; ++failure) {
  struct ccci_dpmaif d = {.dl = {.pit = &buffer, .started = true, .rx_head = true}};
  step = releases = irq_puts = addr_writes = 0;
  fail_at = failure;
  assert(dpmaif_dl_stop(&d) == -ETIMEDOUT);
  assert(!d.dl.started && !d.dl.rx_head && d.dl.pit == &buffer);
  assert(irq_puts == 1 && !releases && !addr_writes);
  step = fail_at = 0;
  assert(!dpmaif_dl_stop(&d));
  assert(!d.dl.pit && !d.dl.fail_reg && releases == 5 && irq_puts == 1);
  assert(addr_writes == 2);
  assert(!dpmaif_dl_stop(&d) && releases == 5 && irq_puts == 1);
 }
}
'''
with tempfile.TemporaryDirectory() as directory:
    work = Path(directory)
    source = work / 'test.c'
    source.write_text(prelude + code[
        code.index('static int dpmaif_dl_unprogram('):
        code.index('static int dpmaif_dl_start(')
    ] + code[
        code.index('static int dpmaif_dl_stop('):
        code.index('static struct ccci_dpmaif *dpmaif_net_priv(')
    ] + test)
    binary = work / 'test'
    subprocess.run(['cc', '-I', str(driver), '-fsanitize=address,undefined',
                    '-no-pie', str(source), '-o', str(binary)], check=True)
    subprocess.run([str(binary)], check=True)
print('PASS: DPMAIF DL stop retains DMA on five timeout paths; retry frees once')
