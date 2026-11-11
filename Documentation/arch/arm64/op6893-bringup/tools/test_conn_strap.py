#!/usr/bin/env python3
# SPDX-License-Identifier: GPL-2.0-only
"""Execute the actual strap transaction with partial pinctrl failures and guards."""
from pathlib import Path
import subprocess
import tempfile

root = Path(__file__).resolve().parents[5]
source = (root / 'arch/arm64/kernel/op6893-conn-strap.h').read_text()
assert 'writel(' not in source
harness = r'''
#include <assert.h>
#include <errno.h>
#include <stdbool.h>
#include <stdint.h>
#include <stdio.h>
#include <string.h>
#define __iomem
#define BIT(n) (1U<<(n))
#define ARRAY_SIZE(a) (sizeof(a)/sizeof((a)[0]))
typedef uint32_t u32;
struct pinctrl {};
struct pinctrl_state {unsigned phase;};
struct op6893_conn {
 struct pinctrl *pins;
 struct pinctrl_state *strap_pins[5], *active_pins;
 bool strap_dirty,strap_unsafe,strap_complete,prepare_requested,sema_pending,sema_unsafe;
 const char *failure_stage;
 unsigned strap_selected,strap_samples;
 u32 strap_adie,strap_words[7][8];
 const char *stage;
};
static u32 gpio[0x470/4],io[0xd0/4],adie;
static struct pinctrl pins;
static struct pinctrl_state states[6]={{1},{2},{3},{4},{5},{6}};
static struct op6893_conn conn;
static unsigned maps,unmaps,mapfail,guard_calls,guardfail,selects,selectfail,partial;
static unsigned drop_phase,corrupt_phase,corrupt_field,adie_loss_phase,read_count,loss_read;
static bool no_more_pins;
static void *ioremap(unsigned long address,unsigned size) {
 if(++maps==mapfail)return NULL;
 if(address==0x18001900){assert(size==4);return &adie;}
 if(address==0x10005000){assert(size==sizeof(gpio));return gpio;}
 assert(address==0x11ea0000 && size==sizeof(io));return io;
}
static void iounmap(void *p) {assert(p==gpio || p==io || p==&adie);unmaps++;}
static u32 readl(void *p) {
 if(++read_count==loss_read)adie=3;
 return *(u32 *)p;
}
static int op6893_conn_check_off(struct op6893_conn *c,void *csr) {
 (void)c;(void)csr;
 if(++guard_calls==guardfail){no_more_pins=true;return -EBUSY;}
 return 0;
}
static int pinctrl_select_state(struct pinctrl *p,struct pinctrl_state *s) {
 assert(p==&pins && !no_more_pins && !conn.strap_unsafe && conn.strap_dirty);
 unsigned phase=s->phase;assert(phase==++selects);
 unsigned mode=phase==2?0:1,dir=phase<5,level=phase<4;
 bool fail=phase==selectfail;
 /* Simulate mux first; configuration may then fail partway through. */
 if(phase!=drop_phase) {
  if(!fail || partial>=1)gpio[0x460/4]=(gpio[0x460/4]&~0xf0000)|(mode<<16);
  if(!fail || partial>=2)gpio[0x150/4]=(gpio[0x150/4]&~BIT(20))|(level<<20);
  if(!fail || partial>=3)gpio[0x50/4]=(gpio[0x50/4]&~BIT(20))|(dir<<20);
 }
 if(phase==corrupt_phase) {
  static const unsigned offsets[]={0x50,0x150,0x460,0,0x30,0x50,0x70,0xc0};
  (corrupt_field<3?gpio:io)[offsets[corrupt_field]/4]^=1;
 }
 if(phase==adie_loss_phase)adie=3;
 return fail?-EIO:0;
}
static int op6893_conn_sema_cycle(struct op6893_conn *c,void *csr) {
 (void)c;(void)csr;assert(0);return -EINVAL;
}
''' + source + r'''
static void setup(void) {
 memset(&conn,0,sizeof(conn));memset(gpio,0,sizeof(gpio));memset(io,0,sizeof(io));
 gpio[0x50/4]=0xa2800000;gpio[0x150/4]=0x02800000;gpio[0x460/4]=0x01111111;
 io[0]=0x8248;io[0x30/4]=0xffffffff;io[0x50/4]=0x0c7fb43f;
 io[0x70/4]=0x01804bc0;io[0xc0/4]=0x1c01;adie=2;
 conn.pins=&pins;conn.active_pins=&states[5];
 for(unsigned i=0;i<5;i++)conn.strap_pins[i]=&states[i];
 maps=unmaps=mapfail=guard_calls=guardfail=selects=selectfail=partial=0;
 drop_phase=corrupt_phase=corrupt_field=adie_loss_phase=read_count=loss_read=0;
 no_more_pins=false;
}
static int run(void) {int ret=op6893_conn_strap_cycle(&conn,NULL);assert(unmaps==maps-!!mapfail);return ret;}
int main(void) {
 setup();assert(!run());unsigned guards=guard_calls,reads=read_count;
 assert(conn.strap_complete && !conn.strap_dirty && !conn.strap_unsafe);
 assert(selects==6 && conn.strap_selected==6 && conn.strap_samples==7);
 assert(!memcmp(conn.strap_words[0],conn.strap_words[6],sizeof(conn.strap_words[0])));
 assert((conn.strap_words[2][2]&0xf0000)==0 && (conn.strap_words[2][0]&BIT(20)));
 for(unsigned n=1;n<=3;n++){setup();mapfail=n;assert(run()==-ENOMEM && !selects && !conn.strap_dirty);}
 for(unsigned n=1;n<=guards;n++) {
  setup();guardfail=n;assert(run()==-EBUSY && !conn.strap_complete);
  if(n>1)assert(conn.strap_unsafe);
 }
 for(unsigned n=1;n<=reads;n++) {
  setup();loss_read=n;assert(run()==-EBUSY && conn.strap_unsafe && !conn.strap_complete);
 }
 for(unsigned phase=1;phase<=6;phase++) {
  for(unsigned part=0;part<=3;part++) {
   setup();selectfail=phase;partial=part;
   assert(run()==-EIO && conn.strap_dirty && conn.strap_unsafe && !conn.strap_complete);
   assert(selects==phase && conn.strap_selected==phase-1);
  }
  setup();adie_loss_phase=phase;
  assert(run()==-EBUSY && conn.strap_dirty && conn.strap_unsafe && selects==phase);
  for(unsigned field=0;field<8;field++) {
   setup();corrupt_phase=phase;corrupt_field=field;
   assert(run()==-EIO && conn.strap_dirty && conn.strap_unsafe && selects==phase);
  }
  if(phase<6) {
   setup();drop_phase=phase;
   assert(run()==-EIO && conn.strap_dirty && conn.strap_unsafe && selects==phase);
  }
 }
 /* Unexpected baseline refuses all transitions, without claiming dirty pins. */
 for(unsigned field=0;field<8;field++) {
  setup();
  static const unsigned offsets[]={0x50,0x150,0x460,0,0x30,0x50,0x70,0xc0};
  static const u32 bits[]={BIT(20),BIT(20),BIT(16),BIT(3),BIT(18),BIT(18),BIT(18),BIT(7)};
  (field<3?gpio:io)[offsets[field]/4]^=bits[field];
  assert(run()<0 && !selects && !conn.strap_dirty && !conn.strap_complete);
 }
 setup();conn.strap_unsafe=true;assert(run()==-EUCLEAN && !selects);
 puts("PASS: actual strap sequence,7 readbacks,all mapping/guard/read-loss points,"
      "24 partial state failures,48 adjacent/shared corruptions,baseline refusal and late restore loss");
}
'''
with tempfile.TemporaryDirectory() as tmp:
    path = Path(tmp)
    (path / 'test.c').write_text(harness)
    subprocess.run(['cc', '-O1', '-Wall', '-Wextra', '-Werror',
                    '-fsanitize=undefined', '-fno-sanitize-recover=all',
                    str(path / 'test.c'), '-o', str(path / 'test')], check=True)
    subprocess.run([str(path / 'test')], check=True)
