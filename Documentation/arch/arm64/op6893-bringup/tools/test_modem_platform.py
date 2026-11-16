#!/usr/bin/env python3
# SPDX-License-Identifier: GPL-2.0-only
"""Exercise actual cold MD sequencing with injected provider failures, no I/O."""
from pathlib import Path
import subprocess
import tempfile

K = Path(__file__).resolve().parents[5]
HARNESS = r'''
#include <assert.h>
#include <stdbool.h>
#include <stdio.h>
#include <string.h>
#include <errno.h>
#include "ccci-md-power.c"
/* Independent order from same-board 4.19 md_sys1_platform.c plus HIF clocks. */
enum event { OFF_CHECK=1, RAILS, CLK_ON, SRC_ON, O1, FLIGHT_OFF, DOMAIN_ON,
 DOMAIN_OFF, SRC_OFF, FLIGHT_ON, CLK_OFF, HANDOFF_CHECK, HANDOFF_ACQUIRE };
static const int on_order[]={OFF_CHECK,RAILS,CLK_ON,SRC_ON,O1,FLIGHT_OFF,DOMAIN_ON};
static const int off_order[]={DOMAIN_OFF,OFF_CHECK,SRC_OFF,FLIGHT_ON,CLK_OFF};
struct fake { int log[32]; unsigned count, fail; };
static int record(void *ctx, int op) {
 struct fake *f=ctx; assert(f->count<32); f->log[f->count++]=op;
 return f->count==f->fail?-EACCES:0;
}
static int off_check(void *c){return record(c,OFF_CHECK);}
static int rails(void *c){return record(c,RAILS);}
static int clocks(void *c,bool on){return record(c,on?CLK_ON:CLK_OFF);}
static int srcclk(void *c,bool on){return record(c,on?SRC_ON:SRC_OFF);}
static int o1(void *c){return record(c,O1);}
static int flight(void *c,bool on){return record(c,on?FLIGHT_ON:FLIGHT_OFF);}
static int domain(void *c,bool on){return record(c,on?DOMAIN_ON:DOMAIN_OFF);}
static int handoff_check(void *c){return record(c,HANDOFF_CHECK);}
static int handoff_acquire(void *c){return record(c,HANDOFF_ACQUIRE);}
static const struct ccci_md_power_ops ops={off_check,rails,clocks,srcclk,o1,flight,domain,
 handoff_check,handoff_acquire};
static void setup(struct ccci_md_power *p,struct fake *f) {
 memset(f,0,sizeof(*f)); assert(!ccci_md_power_init(p,&ops,f));
 assert(p->state==CCCI_MD_COLD && !p->attempted && !p->error);
}
static void compare(struct fake *f,const int *want,unsigned n) {
 assert(f->count==n); assert(!memcmp(f->log,want,n*sizeof(*want)));
}
int main(void) {
 struct ccci_md_power p; struct fake f;
 assert(ccci_md_power_init(NULL,&ops,&f)==-EINVAL);
 assert(ccci_md_power_init(&p,NULL,&f)==-EINVAL);
 /* Missing provider operations must never become silent success. */
 for(unsigned n=0;n<9;n++) {
  struct ccci_md_power_ops bad=ops;
  switch(n) {
  case 0: bad.off_check=NULL;break; case 1: bad.rails_check=NULL;break;
  case 2: bad.clocks=NULL;break; case 3: bad.srcclk=NULL;break;
  case 4: bad.srclken_o1=NULL;break; case 5: bad.flight=NULL;break;
  case 6: bad.domain=NULL;break;
  case 7: bad.handoff_check=NULL;break;case 8: bad.handoff_acquire=NULL;break;
  }
  assert(ccci_md_power_init(&p,&bad,&f)==-EINVAL);
 }
 setup(&p,&f); assert(!ccci_md_power_off(&p) && !f.count);
 assert(!ccci_md_power_on(&p)); compare(&f,on_order,7);
 assert(p.state==CCCI_MD_POWERED && p.clocks && p.domain && p.attempted);
 assert(ccci_md_power_on(&p)==-EALREADY && f.count==7);
 f.count=0; assert(!ccci_md_power_off(&p)); compare(&f,off_order,5);
 assert(p.state==CCCI_MD_STOPPED && !p.clocks && !p.domain);
 assert(!ccci_md_power_off(&p) && f.count==5);
 assert(ccci_md_power_on(&p)==-EALREADY && f.count==5);
 for(unsigned n=1;n<=7;n++) {
  setup(&p,&f); f.fail=n;
  assert(ccci_md_power_on(&p)==-EACCES); compare(&f,on_order,n);
  assert(p.error==-EACCES);
  if(n<=2) {
   /* Read-only prerequisite rejection leaves the cold attempt available. */
   assert(!p.attempted && p.state==CCCI_MD_COLD);
   f.count=f.fail=0; assert(!ccci_md_power_on(&p)); compare(&f,on_order,7);
   assert(!p.error); continue;
  }
  assert(p.attempted && p.state==CCCI_MD_FAULT);
  assert(p.clocks==(n>3) && !p.domain);
  assert(ccci_md_power_on(&p)==-EIO);
  assert(ccci_md_power_off(&p)==-EIO && f.count==n);
 }
 for(unsigned n=1;n<=5;n++) {
  setup(&p,&f); assert(!ccci_md_power_on(&p)); f.count=0; f.fail=n;
  assert(ccci_md_power_off(&p)==-EACCES); compare(&f,off_order,n);
  assert(p.state==CCCI_MD_FAULT && p.error==-EACCES && p.clocks);
  assert(p.domain==(n==1));
  assert(ccci_md_power_on(&p)==-EIO);
  assert(ccci_md_power_off(&p)==-EIO && f.count==n);
 }
 const int handoff_order[]={HANDOFF_CHECK,RAILS,HANDOFF_ACQUIRE,DOMAIN_OFF,
  OFF_CHECK,SRC_OFF,FLIGHT_ON};
 setup(&p,&f);p.state=CCCI_MD_INHERITED;
 assert(ccci_md_power_on(&p)==-EAGAIN && ccci_md_power_off(&p)==-EAGAIN && !f.count);
 assert(!ccci_md_power_takeover(&p));compare(&f,handoff_order,7);
 assert(p.state==CCCI_MD_COLD && !p.attempted && !p.domain && !p.clocks);
 assert(ccci_md_power_takeover(&p)==-EALREADY && f.count==7);
 f.count=0;assert(!ccci_md_power_on(&p));compare(&f,on_order,7);
 for(unsigned n=1;n<=7;n++) {
  setup(&p,&f);p.state=CCCI_MD_INHERITED;f.fail=n;
  assert(ccci_md_power_takeover(&p)==-EACCES);compare(&f,handoff_order,n);
  if(n<=2) {
   assert(p.state==CCCI_MD_INHERITED && !p.attempted);
   f.fail=f.count=0;assert(!ccci_md_power_takeover(&p));continue;
  }
  assert(p.state==CCCI_MD_FAULT && p.attempted);
  assert(ccci_md_power_takeover(&p)==-EIO && f.count==n);
 }
 puts("PASS: actual cold MD cycle: vendor ordering, 12 failure points,");
 puts("      read-only retries, sticky write failures, retained references, one-shot OFF");
 puts("      inherited LK takeover, 7 failure points, no unowned-clock disable");
}
'''

# Compile the register/runtime-PM callbacks verbatim, without Linux device/sysfs
# scaffolding. The full file is separately checked by the enabled ARM64 build.
BACKEND = r'''
#include <assert.h>
#include <errno.h>
#include <stdbool.h>
#include <stdint.h>
#include <stdio.h>
#include <string.h>
#include "ccci-md-power.h"
typedef uint32_t u32;
#define BIT(n) (1U<<(n))
#define GENMASK(h,l) ((~0U<<(l))&(~0U>>(31-(h))))
#define ARRAY_SIZE(a) (sizeof(a)/sizeof((a)[0]))
#define MTK_SIP_KERNEL_CCCI_CONTROL 0xc2000505UL
#define SMCCC_RET_NOT_SUPPORTED (-1)
struct mutex { int unused; };
struct ccci_smem_layout { int unused; };
struct clk_bulk_data { int unused; };
struct regmap { u32 words[0x1000/4]; };
struct regulator { int enabled, voltage; };
struct device { int unused; };
struct arm_smccc_res { unsigned long a0, a1, a2, a3; };
static unsigned calls,fail,op[512],reg[512],value[512],sleeps;
static bool stale;
static int runtime_result;
static unsigned long smc_result;
static int allow_off_result;
static int event(unsigned o,unsigned r,unsigned v) {
 assert(calls<512);op[calls]=o;reg[calls]=r;value[calls++]=v;
 return calls==fail?-EACCES:0;
}
static int regmap_read(struct regmap *m,unsigned r,u32 *v) {
 int ret=event(0,r,0);assert(r<0x1000 && !(r&3));
 if(!ret) *v=m->words[r/4];return ret;
}
static int regmap_write(struct regmap *m,unsigned r,unsigned v) {
 int ret=event(1,r,v);if(!ret && !stale)m->words[r/4]=v;return ret;
}
static int regmap_update_bits(struct regmap *m,unsigned r,unsigned mask,unsigned v) {
 int ret=event(2,r,v);if(!ret && !stale)m->words[r/4]=(m->words[r/4]&~mask)|(v&mask);
 return ret;
}
static int regmap_set_bits(struct regmap *m,unsigned r,unsigned mask) {
 int ret=event(3,r,mask);if(!ret && !stale)m->words[r/4]|=mask;return ret;
}
static int regulator_is_enabled(struct regulator *r){return r->enabled;}
static int regulator_get_voltage(struct regulator *r){return r->voltage;}
static int clk_bulk_prepare_enable(unsigned n,struct clk_bulk_data *c) {
 (void)c;assert(n==4);return event(4,0,1);
}
static void clk_bulk_disable_unprepare(unsigned n,struct clk_bulk_data *c) {
 (void)c;assert(n==4);assert(!event(4,0,0));
}
static void arm_smccc_smc(unsigned long id,unsigned long a1,unsigned long a2,
 unsigned long a3,unsigned long a4,unsigned long a5,unsigned long a6,
 unsigned long a7,struct arm_smccc_res *res) {
 assert(id==0xc2000505UL && ((a1==7 && a2<=1) || (a1==6 && a2==3)));
 assert(!a3 && !a4 && !a5 && !a6 && !a7);
 assert(!event(5,a1,a2));res->a0=smc_result;
}
static void msleep(unsigned n){assert(n==20);assert(++sleeps<=100);}
static int mt6893_md_domain_allow_off(struct device *d) {
 (void)d;assert(!event(7,0,0));return allow_off_result;
}
static int pm_runtime_resume_and_get(struct device *d) {
 (void)d;assert(!event(6,0,1));return runtime_result;
}
static int pm_runtime_put_sync_suspend(struct device *d) {
 (void)d;assert(!event(6,0,0));return runtime_result;
}
'''

BACKEND_TEST = r'''
static void clear(void) {
 calls=fail=sleeps=0;stale=false;runtime_result=allow_off_result=0;smc_result=0;
}
static void state(struct ccci_md_platform *md,bool on) {
 memset(md->spm,0,sizeof(*md->spm));memset(md->infra,0,sizeof(*md->infra));
 md->spm->words[0x16c/4]=0x12345678|(on?1:0);
 md->spm->words[0x300/4]=0x12345670|(on?5:0);
 md->spm->words[0x398/4]=0x12345670|(on?0:3);
 md->infra->words[0x228/4]=0x12345600|(on?0:0x80);
 md->infra->words[0xb90/4]=(0x12340000&~0x20200400U)|(on?0:0x20200400);
 md->infra->words[0xbc4/4]=0x12345600|(on?0:0xc0);
 clear();
}
int main(void) {
 struct regmap spm,infra;
 struct ccci_md_platform md={.spm=&spm,.infra=&infra};
 for(unsigned on=0;on<2;on++) {
  state(&md,on);assert(!md_domain_check(&md,on) && calls==6);
  clear();assert(md_domain_check(&md,!on)==-EBUSY && calls==6);
  for(unsigned n=1;n<=6;n++) {
   clear();fail=n;assert(md_domain_check(&md,on)==-EACCES && calls==n);
  }
  /* One bad protection/isolation bit must veto further OFF/ON actions. */
  const unsigned masks[]={1,1,4,1,2,0x80,0x400,0x200000,0x20000000,0x40,0x80};
  const unsigned regs[]={0x16c,0x300,0x300,0x398,0x398,0x228,0xb90,0xb90,0xb90,0xbc4,0xbc4};
  for(unsigned n=0;n<11;n++) {
   state(&md,on);struct regmap *m=n<5?&spm:&infra;
   m->words[regs[n]/4]^=masks[n];
   assert(md_domain_check(&md,on)==-EBUSY);
  }
 }
 /* Adjacent SRC CLK and SPM votes survive, and stale readback is rejected. */
 state(&md,false);infra.words[0xf0c/4]=0xa5a5ff00;
 assert(!md_srcclk(&md,true) && infra.words[0xf0c/4]==0xa5a5ff21);
 assert(op[0]==2 && reg[0]==0xf0c && value[0]==0x21 && op[1]==0);
 clear();assert(!md_srcclk(&md,false) && infra.words[0xf0c/4]==0xa5a5ff00);
 clear();stale=true;assert(md_srcclk(&md,true)==-EIO);
 for(unsigned n=1;n<=2;n++) {
  clear();fail=n;assert(md_srcclk(&md,true)==-EACCES && calls==n);
 }
 state(&md,false);spm.words[8/4]=0x55;
 assert(!md_srclken_o1(&md) && spm.words[8/4]==0x200055);
 assert(calls==3 && op[0]==1 && reg[0]==0 && value[0]==0xb160001);
 assert(op[1]==3 && reg[1]==8 && value[1]==0x200000 && op[2]==0);
 for(unsigned n=1;n<=3;n++) {
  clear();fail=n;assert(md_srclken_o1(&md)==-EACCES && calls==n);
 }
 clear();stale=true;spm.words[8/4]=0;assert(md_srclken_o1(&md)==-EIO);
 clear();assert(!md_flight(&md,false) && value[0]==0);
 clear();assert(!md_flight(&md,true) && value[0]==1);
 clear();smc_result=~0UL;assert(md_flight(&md,false)==-EOPNOTSUPP);
 clear();smc_result=2;assert(md_flight(&md,false)==-EIO);
 /* Successful runtime PM alone is not proof of actual domain state. */
 for(unsigned on=0;on<2;on++) {
  state(&md,on);assert(!md_domain(&md,on) && calls==7 && op[0]==6 && value[0]==on);
  state(&md,!on);assert(md_domain(&md,on)==-EBUSY && calls==7);
  clear();runtime_result=-ETIMEDOUT;
  assert(md_domain(&md,on)==-ETIMEDOUT && calls==1);
 }
 state(&md,true);assert(!md_handoff_check(&md) && calls==13);
 assert(op[6]==5 && reg[6]==6 && value[6]==3);
 clear();smc_result=1;assert(md_handoff_check(&md)==-ETIMEDOUT && sleeps==100);
 clear();smc_result=~0UL;assert(md_handoff_check(&md)==-EOPNOTSUPP && calls==7);
 state(&md,false);assert(md_handoff_check(&md)==-EBUSY && calls==6);
 state(&md,true);assert(!md_handoff_acquire(&md) && calls==8 && op[7]==7);
 clear();runtime_result=-EIO;assert(md_handoff_acquire(&md)==-EIO && calls==7);
 clear();allow_off_result=-EIO;assert(md_handoff_acquire(&md)==-EIO && calls==8);
 struct regulator rails[4];
 for(unsigned n=0;n<4;n++) {
  rails[n]=(struct regulator){1,600000+(int)n*10000};
  md.rails[n]=&rails[n];md.voltage[n]=rails[n].voltage;
 }
 state(&md,false);assert(!md_off_check(&md));clear();assert(!md_rails_check(&md));
 for(unsigned n=0;n<4;n++) {
  rails[n].voltage++;assert(md_rails_check(&md)==-ESTALE);rails[n].voltage--;
  rails[n].enabled=0;assert(md_rails_check(&md)==-ENODATA);
  rails[n].enabled=-EACCES;assert(md_rails_check(&md)==-EACCES);rails[n].enabled=1;
  int old=rails[n].voltage;rails[n].voltage=-EIO;
  assert(md_rails_check(&md)==-EIO);rails[n].voltage=old;
 }
 clear();assert(!md_clocks(&md,true) && op[0]==4 && value[0]==1);
 clear();assert(!md_clocks(&md,false) && op[0]==4 && value[0]==0);
 clear();fail=1;assert(md_clocks(&md,true)==-EACCES);
 puts("PASS: actual MD register callbacks: bounded state readback, adjacent bits,");
 puts("      exact SMC7 ABI, stale/error rejection, runtime-PM veto and cold rail checks");
}
'''

with tempfile.TemporaryDirectory(prefix='op6893-md-platform-') as temporary:
    root = Path(temporary)
    (root / 'linux').mkdir()
    (root / 'linux/types.h').write_text('#include <stdbool.h>\n')
    (root / 'linux/errno.h').write_text('#include <asm-generic/errno.h>\n')
    (root / 'test.c').write_text(HARNESS)
    subprocess.run(['cc', '-std=gnu11', '-Wall', '-Wextra', '-Werror',
                    '-fsanitize=address,undefined', '-fno-sanitize-recover=all',
                    '-I' + str(root), '-I' + str(K / 'drivers/misc/mediatek/ccci'),
                    str(root / 'test.c'), '-o', str(root / 'test')], check=True)
    subprocess.run([str(root / 'test')], check=True)
    source = (K / 'drivers/misc/mediatek/ccci/ccci-md-platform.c').read_text()
    callbacks = source[source.index('#define MD_FLIGHT_MODE'):
                       source.index('static const struct ccci_md_power_ops')]
    (root / 'backend.c').write_text(BACKEND + callbacks + BACKEND_TEST)
    subprocess.run(['cc', '-std=gnu11', '-Wall', '-Wextra', '-Werror',
                    '-Wno-unused-parameter', '-Wno-misleading-indentation',
                    '-fsanitize=address,undefined', '-fno-sanitize-recover=all',
                    '-I' + str(root), '-I' + str(K / 'drivers/misc/mediatek/ccci'),
                    str(root / 'backend.c'), '-o', str(root / 'backend')], check=True)
    subprocess.run([str(root / 'backend')], check=True)
