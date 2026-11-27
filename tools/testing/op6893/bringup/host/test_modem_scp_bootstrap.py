#!/usr/bin/env python3
# SPDX-License-Identifier: GPL-2.0-only
"""Run the actual constrained SCP clock callbacks with faulting TOPCK access."""
from pathlib import Path
import subprocess
import tempfile

root = Path(__file__).resolve().parents[5]
source = (root / 'drivers/clk/mediatek/clk-mt6893-pmif.c').read_text()
start = source.index('struct mt6893_scp_bootstrap {')
end = source.index('static const struct clk_ops mt6893_scp_bootstrap_ops', start)
code = r'''
#include <assert.h>
#include <errno.h>
#include <stddef.h>
#include <stdint.h>
#include <stdio.h>
#include <string.h>
#define BIT(n) (1U << (n))
#define GENMASK(h,l) (((~0U) >> (31-(h))) & ((~0U) << (l)))
#define container_of(p,t,m) ((t *)((char *)(p)-offsetof(t,m)))
struct clk_hw { int unused; };
struct regmap {
 unsigned words[3], reads, writes, fault_read;
 int fault_write;
};
static unsigned held;
static int mt6893_pmif_lock;
#define spin_lock_irqsave(lock,flags) do { assert(!held); held=1; (void)(lock); (flags)=0; } while(0)
#define spin_unlock_irqrestore(lock,flags) do { assert(held); held=0; (void)(lock); (void)(flags); } while(0)
static int regmap_read(struct regmap *m, unsigned offset, unsigned *out) {
 assert(offset==0x10 && m->reads<3);
 unsigned n=++m->reads;
 if(n==m->fault_read) return -EIO;
 *out=m->words[n-1];return 0;
}
static int regmap_write(struct regmap *m, unsigned offset, unsigned value) {
 assert(held && offset==0x18 && value==BIT(23));
 assert(m->reads==2 && !m->writes++);
 return m->fault_write;
}
''' + source[start:end] + r'''
int main(void) {
 struct regmap map={0};
 struct mt6893_scp_bootstrap scp={.map=&map};
 assert(!mt6893_scp_bootstrap_enable(&scp.hw));
 assert(map.reads==3 && map.writes==1 && !held);
 /* Every possible selector/gate, before a write and during confirmation. */
 for(unsigned sel=0;sel<8;sel++)for(unsigned gate=0;gate<2;gate++) {
  if(!sel && !gate) continue;
  for(unsigned phase=0;phase<3;phase++) {
   map=(struct regmap){0};map.words[phase]=(sel<<16)|(gate<<23);
   assert(mt6893_scp_bootstrap_enable(&scp.hw)==-EBUSY);
   assert(map.reads==phase+1 && map.writes==(phase==2) && !held);
  }
 }
 for(unsigned fault=1;fault<=3;fault++) {
  map=(struct regmap){.fault_read=fault};
  assert(mt6893_scp_bootstrap_enable(&scp.hw)==-EIO);
  assert(map.reads==fault && map.writes==(fault==3) && !held);
 }
 map=(struct regmap){.fault_write=-ETIMEDOUT};
 assert(mt6893_scp_bootstrap_enable(&scp.hw)==-ETIMEDOUT);
 assert(map.reads==2 && map.writes==1 && !held);
 /* Adjacent AXI/SPM/bus selector bits do not alter SCP interpretation. */
 map=(struct regmap){.words={0xff78ffff,0x5578aaaa,0x11785555}};
 assert(!mt6893_scp_bootstrap_enable(&scp.hw));
 assert(map.reads==3 && map.writes==1 && !held);
 /* A last put or error unwind must not gate an inherited SCP clock. */
 unsigned reads=map.reads,writes=map.writes;
 mt6893_scp_bootstrap_disable(&scp.hw);
 assert(map.reads==reads && map.writes==writes);
 map=(struct regmap){0};
 assert(mt6893_scp_bootstrap_rate(&scp.hw,26000000)==26000000);
 assert(map.reads==2 && !map.writes);
 for(unsigned phase=0;phase<2;phase++) {
  map=(struct regmap){0};map.words[phase]=BIT(23);
  assert(!mt6893_scp_bootstrap_rate(&scp.hw,26000000));
  map=(struct regmap){0};map.words[phase]=1U<<16;
  assert(!mt6893_scp_bootstrap_rate(&scp.hw,26000000));
  map=(struct regmap){.fault_read=phase+1};
  assert(!mt6893_scp_bootstrap_rate(&scp.hw,26000000));
 }
 map=(struct regmap){0};
 assert(!mt6893_scp_bootstrap_rate(&scp.hw,24000000));
 assert(!map.reads && !map.writes);
 puts("PASS: bootstrap selector/gate refusal, exact single-bit write, faults, readback, last-put preservation and live rate");
}
'''
registration = source[end:source.index('\n#endif', end)]
assert 'CLK_IS_CRITICAL | CLK_GET_RATE_NOCACHE' in registration
assert '.set_parent' not in registration and '.set_rate' not in registration
assert 'data->hws[CLK_TOP_SCP] = scp;' in source
with tempfile.TemporaryDirectory(prefix='op6893-scp-bootstrap-') as directory:
    path = Path(directory)
    (path / 'test.c').write_text(code)
    subprocess.run(['cc', '-Wall', '-Wextra', '-Werror', '-Wno-unused-parameter',
                    '-fsanitize=address,undefined', '-fno-sanitize-recover=all',
                    '-no-pie', str(path / 'test.c'), '-o', str(path / 'test')], check=True)
    subprocess.run([str(path / 'test')], check=True)
