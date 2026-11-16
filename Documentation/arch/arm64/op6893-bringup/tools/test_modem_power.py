#!/usr/bin/env python3
# SPDX-License-Identifier: GPL-2.0-only
"""Compile the real MD1 sequence with failure-injecting regmap stubs.

Tests register order, preservation of adjacent bits, inherited-state rejection,
bounded ACK failure and refusal to retry after a partial transition. No hardware
access. The stubs do not prove that an actual bus transaction can time out.
"""
import argparse
from pathlib import Path
import struct
import subprocess
import tempfile

KERNEL = Path(__file__).resolve().parents[5]
DRIVER = KERNEL / 'drivers/pmdomain/mediatek'

HARNESS = r'''
#include <assert.h>
#include <errno.h>
#include <stdbool.h>
#include <stdint.h>
#include <stdio.h>
#include <string.h>
#include "mt6893-md-power.h"
struct regmap { unsigned bank; uint32_t reg[0x1000/4]; };
struct event { unsigned bank, op, reg, value; };
static struct event events[64];
static unsigned calls, fail_at, stalled_reads, stall_at;
static bool stall;
static unsigned initial_control = 0x55aa9000, initial_iso = 0xa5a5ff03;
static int event(struct regmap *m, unsigned op, unsigned reg, unsigned value) {
 assert(reg < 0x1000 && !(reg & 3));
 if (stall) { assert(op==0); assert(++stalled_reads <= 100001); return 0; }
 assert(calls < 64);
 events[calls++] = (struct event){m->bank,op,reg,value};
 return calls == fail_at ? -EACCES : 0;
}
static int regmap_read(struct regmap *m, unsigned reg, unsigned *value) {
 int ret=event(m,0,reg,0); if (ret) return ret;
 *value=m->reg[reg/4]; return 0;
}
static int regmap_write(struct regmap *m, unsigned reg, unsigned value) {
 int ret=event(m,1,reg,value); if (ret) return ret;
 if (m->bank) {
  unsigned target=reg==0x2a0 || reg==0x2a4 ? 0x228 :
                  reg==0xb84 || reg==0xb88 ? 0xb90 : 0xbc4;
  assert(reg==0x2a0 || reg==0x2a4 || reg==0xb84 || reg==0xb88 ||
         reg==0xbb8 || reg==0xbbc);
  if (reg==0x2a0 || reg==0xb84 || reg==0xbb8) m->reg[target/4] |= value;
  else m->reg[target/4] &= ~value;
 } else {
  assert(reg==0 && value==0xb160001); m->reg[0]=value;
 }
 return 0;
}
static int update(struct regmap *m, unsigned reg, unsigned mask, bool set) {
 int ret=event(m,set?2:3,reg,mask); if (ret) return ret;
 assert(!m->bank && (reg==0x300 || reg==0x398));
 if (set) m->reg[reg/4] |= mask; else m->reg[reg/4] &= ~mask;
 if (reg==0x300 && mask==4) {
  if (set) m->reg[0x16c/4] |= 1; else m->reg[0x16c/4] &= ~1U;
 }
 return 0;
}
static int regmap_set_bits(struct regmap *m,unsigned reg,unsigned mask) {
 return update(m,reg,mask,true);
}
static int regmap_clear_bits(struct regmap *m,unsigned reg,unsigned mask) {
 return update(m,reg,mask,false);
}
/* Evaluate the real driver's predicate, retain read errors and enforce budget. */
#define regmap_read_poll_timeout(m,r,v,cond,delay,budget) ({ \
 int result=-ETIMEDOUT; \
 assert((delay)==10 && (budget)==1000000); \
 if (stall_at && calls+1==stall_at) stall=true; \
 for (unsigned j=0;j<=(budget)/(delay);j++) { \
  int err=regmap_read(m,r,&v); \
  if (err) { result=err; break; } \
  if (stall) v=~v; \
  if (cond) { result=0; break; } \
 } result; })
#include "mt6893-md-power.c"
/* Independent vendor operation oracle: bank, operation, offset, mask. */
static const struct event expected_on[]={
 {0,1,0,0xb160001},{0,3,0x398,1},{0,3,0x398,2},
 {0,2,0x300,1},{0,2,0x300,4},{0,0,0x16c,0},
 {1,1,0xb88,0x20200400},{1,1,0xbbc,0xc0},{1,1,0x2a4,0x80}
};
static const struct event expected_off[]={
 {0,1,0,0xb160001},{1,1,0x2a0,0x80},{1,0,0x228,0},
 {1,1,0xb84,0x20200400},{1,0,0xb90,0},
 {1,1,0xbb8,0xc0},{1,0,0xbc4,0},
 {0,3,0x300,4},{0,0,0x16c,0},
 {0,2,0x398,1},{0,2,0x398,2},{0,3,0x300,1}
};
static void clear_events(void) { calls=fail_at=stalled_reads=stall_at=0; stall=false; }
static void setup(struct mt6893_md_power *md,struct regmap *s,struct regmap *i) {
 memset(md,0,sizeof(*md)); memset(s,0,sizeof(*s)); memset(i,0,sizeof(*i));
 s->bank=0; i->bank=1;
 s->reg[0x300/4]=initial_control; s->reg[0x398/4]=initial_iso;
 s->reg[0x16c/4]=0x12345678;
 i->reg[0x228/4]=0x55aa55ff;
 i->reg[0xb90/4]=0x77777777 | 0x20200400;
 i->reg[0xbc4/4]=0x123456ff;
 clear_events();
 assert(!mt6893_md_power_init(md,s,i));
 assert(calls==6 && md->state==MT6893_MD_POWER_OFF);
 clear_events();
}
static void compare(const struct event *expected,unsigned n) {
 assert(calls==n);
 for (unsigned k=0;k<n;k++) assert(!memcmp(&events[k],&expected[k],sizeof(*expected)));
}
static void prepare_on(struct mt6893_md_power *md,struct regmap *s,struct regmap *i) {
 setup(md,s,i); assert(!mt6893_md_power_set(md,true)); clear_events();
}
int main(void) {
 struct mt6893_md_power md;
 struct regmap spm,infra;
 setup(&md,&spm,&infra);
 assert(!mt6893_md_power_set(&md,false) && !calls);
 assert(!mt6893_md_power_set(&md,true)); compare(expected_on,9);
 assert(spm.reg[0x300/4]==(initial_control|5));
 assert(spm.reg[0x398/4]==(initial_iso&~3U));
 assert(infra.reg[0x228/4]==(0x55aa55ff&~0x80U));
 assert(infra.reg[0xb90/4]==(0x77777777&~0x20200400U));
 assert(infra.reg[0xbc4/4]==(0x123456ff&~0xc0U));
 clear_events(); assert(!mt6893_md_power_set(&md,true) && !calls);
 assert(!mt6893_md_power_set(&md,false)); compare(expected_off,12);
 assert(spm.reg[0x300/4]==initial_control && spm.reg[0x398/4]==initial_iso);
 assert(spm.reg[0x16c/4]==0x12345678);
 assert(infra.reg[0x228/4]==0x55aa55ff);
 assert(infra.reg[0xb90/4]==(0x77777777|0x20200400));
 assert(infra.reg[0xbc4/4]==0x123456ff);
 for (unsigned on=0;on<2;on++) {
  const struct event *expected=on?expected_on:expected_off;
  unsigned n=on?9:12;
  for (unsigned k=1;k<=n;k++) {
   if (on) setup(&md,&spm,&infra); else prepare_on(&md,&spm,&infra);
   fail_at=k; assert(mt6893_md_power_set(&md,on)==-EACCES);
   compare(expected,k); assert(md.state==MT6893_MD_POWER_FAULT);
   assert(mt6893_md_power_set(&md,on)==-EIO);
   assert(mt6893_md_power_set(&md,!on)==-EIO && calls==k);
  }
 }
 /* Each real transition wait must latch a stuck-ACK timeout in place. */
 for (unsigned on=0;on<2;on++) {
  const unsigned waits[]={3,5,7,9};
  for (unsigned k=0;k<(on?1:4);k++) {
   if (on) setup(&md,&spm,&infra); else prepare_on(&md,&spm,&infra);
   stall_at=on?6:waits[k];
   assert(mt6893_md_power_set(&md,on)==-ETIMEDOUT);
   assert(md.state==MT6893_MD_POWER_FAULT && stalled_reads==100001);
   unsigned before=calls;
   assert(before==stall_at-1);
   assert(mt6893_md_power_set(&md,!on)==-EIO && calls==before);
  }
 }
 /* Every initial read must propagate errors without any write. */
 for (unsigned k=1;k<=6;k++) {
  setup(&md,&spm,&infra); fail_at=k;
  assert(mt6893_md_power_init(&md,&spm,&infra)==-EACCES);
  assert(calls==k && md.state==MT6893_MD_POWER_UNKNOWN);
  assert(mt6893_md_power_set(&md,true)==-EINVAL && calls==k);
 }
 /* Reject ON and every incomplete OFF precondition. */
 for (unsigned k=0;k<8;k++) {
  setup(&md,&spm,&infra);
  switch (k) {
   case 0: spm.reg[0x16c/4]|=1; break;
   case 1: spm.reg[0x300/4]|=1; break;
   case 2: spm.reg[0x300/4]|=4; break;
   case 3: spm.reg[0x398/4]&=~1U; break;
   case 4: spm.reg[0x398/4]&=~2U; break;
   case 5: infra.reg[0x228/4]&=~0x80U; break;
   case 6: infra.reg[0xb90/4]&=~0x400U; break;
   case 7: infra.reg[0xbc4/4]&=~0x40U; break;
  }
  assert(mt6893_md_power_init(&md,&spm,&infra)==-EBUSY && calls==6);
 }
 /* Current mainline, e8509e81dbc3: exact sanitized AP-side LK ON snapshot. */
 setup(&md,&spm,&infra);
 spm.reg[0x16c/4]=0x10580fff;spm.reg[0x300/4]=0xd;spm.reg[0x398/4]=0;
 infra.reg[0x228/4]=0xe70c500e;infra.reg[0xb90/4]=1;infra.reg[0xbc4/4]=0x50000;
 assert(!mt6893_md_power_init(&md,&spm,&infra) && calls==6);
 assert(md.state==MT6893_MD_POWER_ON && md.inherited_on);
 clear_events();assert(mt6893_md_power_set(&md,false)==-EBUSY && !calls);
 assert(!mt6893_md_power_set(&md,true) && !calls);
 assert(!mt6893_md_power_adopt(&md));
 assert(mt6893_md_power_adopt(&md)==-EINVAL);
 assert(!mt6893_md_power_set(&md,false));compare(expected_off,12);
 assert(md.state==MT6893_MD_POWER_OFF && !md.inherited_on);
 assert(mt6893_md_power_adopt(&md)==-EINVAL);
 /* Exercise the actual wait predicate for stuck ON/OFF ACK and read error. */
 for (unsigned set=0;set<2;set++) {
  setup(&md,&spm,&infra); spm.reg[0x16c/4]=set?1:0;
  stall=true; assert(mt6893_md_wait(&spm,0x16c,1,set)==-ETIMEDOUT);
  assert(stalled_reads==100001);
  clear_events(); fail_at=1;
  assert(mt6893_md_wait(&spm,0x16c,1,set)==-EACCES && calls==1);
 }
 puts("PASS: actual MD1 sequence, vendor order, adjacent bits, 21 failure points,");
 puts("      6 initial read errors, 8 invalid states, 5 stuck ACKs and fault latch");
 puts("      exact live LK ON adoption, unused-OFF veto and explicit handoff");
 return 0;
}
'''

with tempfile.TemporaryDirectory(prefix='op6893-md-power-') as temporary:
    root = Path(temporary)
    (root/'linux').mkdir()
    for name, content in {
        'types.h': '#include <stdint.h>\n#include <stdbool.h>\ntypedef uint32_t u32;\n',
        'bitops.h': '#define BIT(n) (1U << (n))\n#define GENMASK(h,l) (((~0U) << (l)) & (~0U >> (31-(h))))\n',
        'errno.h': '#include <asm-generic/errno.h>\n',
        'kernel.h': '#define ARRAY_SIZE(a) (sizeof(a)/sizeof((a)[0]))\n'
                    '#define READ_ONCE(x) (x)\n#define WRITE_ONCE(x,y) ((x)=(y))\n',
        'regmap.h': '', 'iopoll.h': '',
    }.items():
        (root/'linux'/name).write_text(content)
    (root/'test.c').write_text(HARNESS)
    subprocess.run(['cc','-std=gnu11','-Wall','-Wextra','-Werror',
                    '-fsanitize=address,undefined','-fno-sanitize-recover=all',
                    '-I'+str(root),'-I'+str(DRIVER),str(root/'test.c'),
                    '-o',str(root/'test')],check=True)
    subprocess.run([str(root/'test')],check=True)

parser = argparse.ArgumentParser(description=__doc__)
parser.add_argument('--dtb', type=Path, action='append', default=[])
args = parser.parse_args()
for path in args.dtb:
    import libfdt
    fdt = libfdt.Fdt(path.read_bytes())

    def nodes(parent):
        child = fdt.first_subnode(parent, quiet=(libfdt.NOTFOUND,))
        while child >= 0:
            yield child
            yield from nodes(child)
            child = fdt.next_subnode(child, quiet=(libfdt.NOTFOUND,))

    controllers = [n for n in nodes(0)
                   if fdt.getprop(n, 'compatible', quiet=(libfdt.NOTFOUND,)) ==
                   b'mediatek,mt6893-power-controller\0']
    assert len(controllers) == 1
    for n in nodes(controllers[0]):
        reg = fdt.getprop(n, 'reg', quiet=(libfdt.NOTFOUND,))
        assert reg is not None
        if struct.unpack('>I', reg)[0] == 24:
            assert fdt.getprop(n, 'status') == b'disabled\0'
    platform = fdt.path_offset('/modem-platform@10209000', quiet=(libfdt.NOTFOUND,))
    if platform >= 0:
        assert fdt.getprop(platform, 'status') == b'disabled\0'
        assert fdt.getprop(platform, 'power-domains', quiet=(libfdt.NOTFOUND,)) == -libfdt.NOTFOUND
    print(f'PASS: {path.name}: MD1 domain and owner disabled, no automatic attachment')
