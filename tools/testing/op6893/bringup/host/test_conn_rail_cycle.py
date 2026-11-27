#!/usr/bin/env python3
# SPDX-License-Identifier: GPL-2.0-only
"""Run actual one-shot common-rail transaction with recursive fake regulators."""
from pathlib import Path
import re
import runpy
import subprocess
import tempfile

here = Path(__file__).resolve().parent
base = runpy.run_path(str(here / 'test_conn_preflight.py'))['harness']
prefix = base[:base.index('static const char * const op6893_conn_rails[]')]
prefix = prefix.replace('struct regmap { unsigned reads; int fail; };',
                        'struct regmap { u32 words[32768]; };')
prefix = prefix.replace('struct regulator { int enabled, voltage; };',
                        'struct regulator { int enabled, voltage, refs, index; };')
prefix = re.sub(r'static int regmap_read\(.*?\n}', '', prefix, flags=re.S)
prefix = re.sub(r'static int regulator_is_enabled[^\n]+\n', '', prefix)
prefix = re.sub(r'static int regulator_get_voltage[^\n]+\n', '', prefix)
prefix = prefix.replace('static bool transition, wrong_id;', 'static bool transition;')
source = (here.parents[4] / 'arch/arm64/kernel/op6893-conn.c').read_text()
actual = source[source.index('static const char * const op6893_conn_rails[]'):
                source.index('static struct attribute *op6893_conn_attrs[]')]
actual = re.sub(r'static DEVICE_ATTR_ADMIN_\w+\([^;]+;', '', actual)
actual = actual.replace('#include "op6893-conn-domain.h"',
                        'static int op6893_conn_domain_cycle(struct op6893_conn *c) { (void)c; abort(); }')
assert 'regulator_disable(conn->rails[i])' not in actual
harness = prefix + r'''
#include <stdlib.h>
#define memzero_explicit(p,n) memset(p,0,n)
#define DEVICE_ATTR_ADMIN_RO(x)
#define DEVICE_ATTR_ADMIN_RW(x)
static unsigned calls, fail_at, writes, max_parent_refs[2];
static bool inject_enable_effect, timeout_on, timeout_off;
static unsigned domain_change;
static struct regmap map;
static struct regulator rails[6];
static int api(void) { return ++calls == fail_at ? -EIO : 0; }
static int regmap_read(struct regmap *m, unsigned reg, u32 *v) {
 int ret=api(); if (ret) return ret;
 *v=m->words[reg/2]; return 0;
}
static int regmap_write(struct regmap *m, unsigned reg, u32 value) {
 int ret=api(); if(ret) return ret;
 writes++;
 if(reg==0x1c36 || reg==0x1c24) m->words[(reg-2)/2] |= value;
 else if(reg==0x1c38 || reg==0x1c26) m->words[(reg-4)/2] &= ~value;
 else { assert(!"unexpected write"); }
 return 0;
}
static int regmap_update_bits(struct regmap *m,unsigned reg,u32 mask,u32 value) {
 int ret=api(); if(ret) return ret;
 assert((reg==0x1c2e || reg==0x1c1c) && mask==2);
 writes++; m->words[reg/2]=(m->words[reg/2]&~mask)|(value&mask); return 0;
}
static int regulator_is_enabled(struct regulator *r) {
 int ret=api(); return ret ? ret : r->enabled;
}
static int regulator_get_voltage(struct regulator *r) {
 int ret=api(); return ret ? ret : r->voltage;
}
static int regulator_enable(struct regulator *r) {
 int ret=api();
 if(r->index<2) {
  if(ret) return ret;
  assert(r->enabled); /* inherited parent must never be brought up */
  r->refs++; if((unsigned)r->refs>max_parent_refs[r->index])max_parent_refs[r->index]=r->refs;
  return 0;
 }
 assert(r->index==2 || r->index==3);
 unsigned parent=r->index==2?1:0, con=r->index==2?0x1c1c:0x1c2e;
 assert(rails[parent].refs>0); /* no unsafe recursive failure unwind */
 if(ret) { if(inject_enable_effect)map.words[con/2]|=1; return ret; }
 rails[parent].refs++; r->refs++; r->enabled=1;
 map.words[con/2]|=1; map.words[(con+4)/2]=timeout_on?0:1;
 if(domain_change && (unsigned)r->index==domain_change)spm[0x16c/4]|=2;
 return 0;
}
static int regulator_disable(struct regulator *r) {
 int ret=api(); if(ret)return ret;
 assert(r->index>=2); /* any parent disable is forbidden */
 unsigned parent=r->index==2?1:0,con=r->index==2?0x1c1c:0x1c2e;
 assert(r->refs==1 && rails[parent].refs>=2);
 r->refs--;rails[parent].refs--;r->enabled=0;
 map.words[con/2]&=~1;map.words[(con+4)/2]=timeout_off?1:0;return 0;
}
#define regmap_read_poll_timeout(m,reg,val,cond,delay,limit) ({ \
 int status=-ETIMEDOUT; \
 for(unsigned tries=0;tries<4;tries++) { \
  status=regmap_read(m,reg,&val); if(status || (cond)) break; \
  status=-ETIMEDOUT; \
 } status; })
static void usleep_range(unsigned lo,unsigned hi) { assert(lo<=hi); }
static bool sysfs_streq(const char *a,const char *b) {
 return strcmp(a,b)==0 || (strlen(a)==strlen(b)+1 && a[strlen(b)]=='\n' && !strncmp(a,b,strlen(b)));
}
''' + actual + r'''
static struct op6893_conn conn;
static struct device dev={.data=&conn};
static void setup(void) {
 conn=(struct op6893_conn){.pmic=&map,.spm=spm,.infra=infra,.host=&host,
                          .cycle_allowed=true,.stage="idle"};
 memset(&map,0,sizeof(map));memset(spm,0,sizeof(spm));
 calls=fail_at=writes=0; timeout_on=timeout_off=inject_enable_effect=false;domain_change=0;
 host=0;spm[0x304/4]=0x12;spm[0x504/4]=1;
 for(unsigned i=0;i<ARRAY_SIZE(op6893_conn_baseline);i++) {
  const struct op6893_conn_check *c=&op6893_conn_baseline[i];map.words[c->reg/2]=c->value;
 }
 int uv[]={2000000,1400000,1300000,1800000,3500000,3500000};
 for(unsigned i=0;i<6;i++) {
  rails[i]=(struct regulator){.index=i,.enabled=i<2,.voltage=uv[i]};conn.rails[i]=&rails[i];
 }
}
int main(void) {
 char rgu_output[4096]; setup(); assert(efuse_status_show(&dev,NULL,rgu_output)>0 && strstr(rgu_output,"requested=0 issued=0 pending=0 complete=0")); assert(adie_status_show(&dev,NULL,rgu_output)>0); assert(strap_status_show(&dev,NULL,rgu_output)>0); assert(sysram_status_show(&dev,NULL,rgu_output)>0); assert(sema_status_show(&dev,NULL,rgu_output)>0); assert(rgu_status_show(&dev,NULL,rgu_output)>0);
 char post_output[4096];setup();
 assert(post_id_show(&dev,NULL,post_output)>0 && strstr(post_output,"samples=0"));
 assert(remap_status_show(&dev,NULL,post_output)>0 && strstr(post_output,"saved=0"));
 assert(spi_baseline_show(&dev,NULL,post_output)>0 && strstr(post_output,"samples=0"));
 assert(spi_config_show(&dev,NULL,post_output)>0 && strstr(post_output,"saved=0"));
 char buf[4096];
 setup();assert(protection_trace_show(&dev,NULL,buf)==0);
 setup();assert(rail_cycle_store(&dev,NULL,"rc-cycle\n",9)==9);
 unsigned total=calls;
 assert(conn.attempted && !conn.faulted && !conn.result && !conn.cleanup_result);
 assert(!strcmp(conn.stage,"complete"));
 assert(conn.parent_votes[0] && conn.parent_votes[1]);
 assert(rails[0].refs==1 && rails[1].refs==1 && rails[0].enabled && rails[1].enabled);
 assert(!conn.dirty[0] && !conn.dirty[1] && !conn.rail_refs[0] && !conn.rail_refs[1]);
 assert(!op6893_conn_check_baseline(&conn));
 assert(rail_cycle_show(&dev,NULL,buf)>0 && strstr(buf,"attempted=1 faulted=0"));
 assert(preflight_show(&dev,NULL,buf)>0);
 unsigned before=calls;assert(rail_cycle_store(&dev,NULL,"rc-cycle",8)==-EALREADY && calls==before);
 for(unsigned fail=1;fail<=total;fail++) {
  setup();fail_at=fail;inject_enable_effect=true;
  assert(rail_cycle_store(&dev,NULL,"rc-cycle",8)<0);
  assert(conn.faulted && conn.attempted && !conn.lock.held);
  assert(rails[0].enabled && rails[1].enabled);
  for(unsigned i=0;i<2;i++) {
   if(conn.parent_votes[i])assert(rails[i].refs>=1);
  }
  before=calls;assert(rail_cycle_store(&dev,NULL,"rc-cycle",8)==-EALREADY && calls==before);
 }
 for(unsigned i=0;i<ARRAY_SIZE(op6893_conn_baseline);i++) {
  setup();const struct op6893_conn_check *c=&op6893_conn_baseline[i];
  map.words[c->reg/2]^=c->mask&-c->mask;
  assert(rail_cycle_store(&dev,NULL,"rc-cycle",8)<0 && !writes);
 }
 for(unsigned i=0;i<6;i++) {
  setup();rails[i].enabled=!rails[i].enabled;
  assert(rail_cycle_store(&dev,NULL,"rc-cycle",8)<0 && !writes);
  setup();rails[i].voltage++;
  assert(rail_cycle_store(&dev,NULL,"rc-cycle",8)==-ERANGE && !writes);
 }
 setup();timeout_on=true;
 assert(rail_cycle_store(&dev,NULL,"rc-cycle",8)==-ETIMEDOUT && conn.faulted);
 assert(!rails[3].enabled && !conn.rail_refs[0]);
 setup();timeout_off=true;
 assert(rail_cycle_store(&dev,NULL,"rc-cycle",8)==-ETIMEDOUT && conn.cleanup_result==-ETIMEDOUT);
 assert(conn.rail_refs[0] && rails[3].enabled); /* retain earlier rail on failed shutdown */
 for(unsigned i=2;i<=3;i++) {
  setup();domain_change=i;
  assert(rail_cycle_store(&dev,NULL,"rc-cycle",8)<0 && conn.cleanup_result==-EBUSY);
  assert(rails[3].enabled); /* never cut supplies with live/mixed domain ACK */
 }
 setup();conn.cycle_allowed=false;
 assert(rail_cycle_store(&dev,NULL,"rc-cycle",8)==-EOPNOTSUPP && !calls && !conn.attempted);
 setup();assert(rail_cycle_store(&dev,NULL,"bad",3)==-EINVAL && !calls);
 setup();lock_error=-EINTR;
 assert(rail_cycle_store(&dev,NULL,"rc-cycle",8)==-EINTR && !calls);lock_error=0;
 printf("PASS: %u API fault points, 26 PMIC baseline mismatches, 12 rail mismatches, "
        "recursive parent references, uncertain enable, finite polls, live-domain "
        "retention, one-shot lockout and invalid triggers\n",total);
}
'''
with tempfile.TemporaryDirectory() as tmp:
    path = Path(tmp)
    (path / 'test.c').write_text(harness)
    subprocess.run(['cc', '-Wall', '-Wextra', '-Werror', '-Wno-unused-parameter',
                    '-fsanitize=undefined', '-fno-sanitize-recover=all',
                    str(path / 'test.c'), '-o', str(path / 'test')], check=True)
    subprocess.run([str(path / 'test')], check=True)
