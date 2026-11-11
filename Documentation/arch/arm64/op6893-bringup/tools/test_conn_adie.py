#!/usr/bin/env python3
# SPDX-License-Identifier: GPL-2.0-only
"""Actual bounded A-die ID transaction, fault injection at every guard/write."""
from pathlib import Path
import subprocess
import tempfile

root = Path(__file__).resolve().parents[5]
source = (root / 'arch/arm64/kernel/op6893-conn-adie.h').read_text()
conn_source = (root / 'arch/arm64/kernel/op6893-conn.c').read_text()
fields = conn_source[conn_source.index('\tbool adie_requested;'):
                     conn_source.index('\tbool strap_requested;')]
harness = r'''
#include <assert.h>
#include <errno.h>
#include <stdbool.h>
#include <stdint.h>
#include <stdio.h>
#include <string.h>
#define memzero_explicit(p,n) memset(p,0,n)
#define __iomem
#define ARRAY_SIZE(a) (sizeof(a) / sizeof((a)[0]))
#define BIT(n) (1U<<(n))
typedef uint8_t u8;
typedef uint32_t u32;
typedef unsigned long long u64;
static u64 adie_clock,adie_clock_step=1000;
static u64 ktime_get_ns(void) {return adie_clock+=adie_clock_step;}
static void udelay(unsigned us) {assert(us==30);adie_clock+=us*1000ULL;}
struct op6893_conn {
 bool prepare_requested,sema_acquired,sema_pending,sema_unsafe;
 u32 sema_grant;
 bool sysram_complete,sysram_unsafe;
 unsigned sysram_verified,sysram_scanned,rgu_applied,rgu_dirty;
 const char *stage,*failure_stage;
''' + fields + r'''
};
static struct op6893_conn conn;
static u32 control,spi[0x5c/4],wb,sema[0x3404/4];
static unsigned maps,unmaps,mapfail,guards,guardfail,writes,dropwrite,losswrite,losstype;
static unsigned reads,lossread,busy_reads,busy_cycles;
static unsigned owner_reads[1024],owner_count;
static u32 response;
static bool inaccessible,stuck,triggered;
static void lose(void) {
 if(losstype==1)inaccessible=true;
 if(losstype==2)control^=1;
 if(losstype==3)sema[0x2400/4]=0;
 if(losstype==4)wb^=BIT(26);
 if(losstype==5)spi[0]=2;
}
static int op6893_conn_check_off(struct op6893_conn *c,void *csr) {
 (void)c;(void)csr;
 if(++guards==guardfail || inaccessible)return -EBUSY;
 return 0;
}
static void *ioremap(unsigned long addr,unsigned size) {
 if(++maps==mapfail)return NULL;
 if(addr==0x18001900){assert(size==4);return &control;}
 if(addr==0x18004000){assert(size==sizeof(spi));return spi;}
 assert(addr==0x18005008 && size==4);return &wb;
}
static void iounmap(void *p) {assert(p==&control || p==spi || p==&wb);unmaps++;}
static u32 readl(void *p) {
 assert(!inaccessible);
 if(++reads==lossread)lose();
 if(p==sema+0x2400/4)owner_reads[owner_count++]=reads;
 if(p==spi && triggered && !(spi[0]&~BIT(5))) {
  if(stuck || busy_reads++<busy_cycles)return BIT(5);
  spi[0]=0;
 }
 return *(u32 *)p;
}
static void writel(u32 value,void *p) {
 assert(!inaccessible && !conn.adie_unsafe && sema[0x2400/4]==0x800 && wb==0x80000);
 assert(p==&control || p==spi+0x50/4 || p==spi+0x54/4);
 unsigned n=++writes;
 if(p==&control) {
  assert(value==2 || value==3);
  assert(conn.adie_reset_dirty);
  if(n!=dropwrite)control=value;
 } else if(p==spi+0x50/4) {
  assert(conn.adie_addr_dirty && (value==0xb02c || value==0x1234));
  if(n!=dropwrite)*(u32 *)p=value;
 } else {
  assert(value==0 && control==3 && spi[0x50/4]==0xb02c && !triggered);
  assert(conn.adie_triggered);
  if(n!=dropwrite){triggered=true;spi[0x58/4]=response;}
 }
 if(n==losswrite)lose();
}
#define read_poll_timeout(op,val,cond,delay,limit,sleep,args...) ({ \
 int result=-ETIMEDOUT; assert((delay)==50 && (limit)==20000); \
 for(unsigned attempt=0;attempt<4;attempt++){val=op(args);if(cond){result=0;break;}} result; })
''' + source + r'''
static void setup(void) {
 memset(&conn,0,sizeof(conn));memset(spi,0,sizeof(spi));memset(sema,0,sizeof(sema));
 conn.prepare_requested=conn.sema_acquired=conn.sema_pending=true;conn.sema_grant=1;
 control=2;wb=0x80000;sema[0x2400/4]=0x800;spi[0x50/4]=0x1234;
 maps=unmaps=mapfail=guards=guardfail=writes=dropwrite=losswrite=losstype=reads=lossread=busy_reads=0;
 owner_count=0;busy_cycles=1;response=0x66358a10;inaccessible=stuck=triggered=false;
}
static int run(void) {
 int ret=op6893_conn_adie_cycle(&conn,NULL,sema);assert(unmaps==maps-!!mapfail);return ret;
}
static void restored(void) {
 assert(control==2 && spi[0x50/4]==0x1234 && !conn.adie_reset_dirty && !conn.adie_addr_dirty);
 assert(conn.adie_reset_restored && !conn.adie_unsafe && !conn.adie_cleanup_result);
}
int main(void) {
 setup();assert(!run());unsigned total_guards=guards;
 unsigned owner_points[1024],owners=owner_count;memcpy(owner_points,owner_reads,sizeof(owner_points));
 restored();assert(conn.adie_complete && conn.adie_id_valid && conn.adie_busy_seen && writes==5);
 assert(conn.adie_id==response && conn.adie_release_verified && conn.adie_id_read);
 u32 ids[]={0x66358a00,0x66358a10,0x66358a11};
 for(unsigned i=0;i<3;i++){setup();response=ids[i];busy_cycles=0;assert(!run());restored();assert(!conn.adie_busy_seen);}
 setup();response=0xffffffff;assert(run()==-ENODEV);restored();assert(!conn.adie_id_valid);
 setup();spi[0x58/4]=response;busy_cycles=0;assert(run()==-EAGAIN);restored();assert(!conn.adie_complete);
 setup();spi[0x58/4]=response;assert(!run());restored();
 for(unsigned i=1;i<=3;i++){setup();mapfail=i;assert(run()==-ENOMEM && !writes);}
 for(unsigned i=1;i<=total_guards;i++) {
  setup();guardfail=i;assert(run()<0 && conn.adie_unsafe && !conn.adie_complete);
 }
 for(unsigned i=1;i<=5;i++) {
  setup();dropwrite=i;assert(run()<0 && !conn.adie_complete);
  if(i==2 || i==3)restored();
  else assert(conn.adie_reset_dirty || conn.adie_addr_dirty || conn.adie_unsafe);
 }
 for(unsigned i=1;i<=5;i++)for(unsigned kind=1;kind<=5;kind++) {
  setup();losswrite=i;losstype=kind;
  assert(run()<0 && conn.adie_unsafe && !conn.adie_complete);
  assert(writes==i);
 }
 for(unsigned i=0;i<owners;i++) {
  setup();lossread=owner_points[i];losstype=3;
  assert(run()<0 && !conn.adie_complete);
 }
 setup();stuck=true;assert(run()==-ETIMEDOUT && writes==3 && conn.adie_reset_dirty && conn.adie_addr_dirty);
 setup();spi[0]=32;assert(run()==-EBUSY && !writes && conn.adie_unsafe);
 setup();control=3;assert(run()==-EBUSY && !writes && conn.adie_unsafe);
 setup();conn.sema_acquired=false;assert(run()==-EINVAL && !maps);
 puts("PASS: actual A-die reset/read/reset/address restoration,3 IDs,stale-data refusal,"
      "all guard/ownership-read losses,5 dropped writes,25 write-time guard losses,"
      "busy timeout,baseline refusal and mapping failures");
}
'''
with tempfile.TemporaryDirectory() as tmp:
    path = Path(tmp)
    (path / 'test.c').write_text(harness)
    subprocess.run(['cc', '-O1', '-Wall', '-Wextra', '-Werror',
                    '-fsanitize=undefined', '-fno-sanitize-recover=all',
                    str(path / 'test.c'), '-o', str(path / 'test')], check=True)
    subprocess.run([str(path / 'test')], check=True)
