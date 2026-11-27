#!/usr/bin/env python3
# SPDX-License-Identifier: GPL-2.0-only
"""Exercise actual SMC packing/resource pin code with a bounded firmware model."""
from pathlib import Path
import argparse
import subprocess
import tempfile

KERNEL = Path(__file__).resolve().parents[5]
DRIVER = KERNEL / 'drivers/misc/mediatek/ccci'
HARNESS = r'''
#include <assert.h>
#include <errno.h>
#include <stdbool.h>
#include <stdint.h>
#include <stdio.h>
#include <string.h>
#include <linux/arm-smccc.h>
#include "ccci-scp-resource.h"
static unsigned calls, queries, requests, fail_at, mode, mutate_at, request_at;
static unsigned resources, users, valid, names[32], usage[6];
static unsigned long request_a0,request_a1;
static void setup(bool present,unsigned id) {
 calls=queries=requests=fail_at=mode=mutate_at=0;
 request_a0=request_a1=request_at=0;resources=6;users=present?id+1:3;
 valid=users==32?UINT32_MAX:(1U<<users)-1;
 for(unsigned i=0;i<32;i++)names[i]=0x41414141+i;
 memset(usage,0,sizeof(usage));
 if(present)names[id]=0x504353;
}
static void fake_smc(unsigned long fid,unsigned long x1,unsigned long x2,
 unsigned long x3,unsigned long x4,unsigned long x5,unsigned long x6,
 unsigned long x7,struct arm_smccc_res *res) {
 assert(!x4 && !x5 && !x6 && !x7);assert(calls++<256);
 *res=(struct arm_smccc_res){0};
 if(fid==0xc2000232) {
  assert(x1==1 && x2==1 && !x3);requests++;request_at=calls;
  res->a0=request_a0;res->a1=request_a1;
  if(mode==1)return; /* Silent success without installing a resource vote. */
  unsigned id;
  for(id=0;id<users;id++)if(names[id]==0x504353)break;
  if(id==users) {assert(users<32);names[users++]=0x504353;valid|=1U<<id;}
  if(mode==2)for(unsigned i=0;i<6;i++)usage[i]&=~(1U<<id);
  usage[1]|=1U<<id;
  if(mode==3)valid&=~(1U<<id);
  if(mode==4) {assert(id+1<users);names[id]=0;names[id+1]=0x504353;}
  return;
 }
 assert(fid==0xc2000507 && x2==4 && (x1&0xffff0000)==0xda010000);
 queries++;
 if(calls==fail_at){res->a0=~0UL;return;}
 switch(x1&0xffff) {
 case 11:assert(!x3);res->a0=resources;break;
 case 14:assert(!x3);res->a0=users;break;
 case 15:assert(!x3);res->a0=valid;break;
 case 16:assert(x3<users && x3<32);res->a0=names[x3];break;
 case 13:assert(x3<6);res->a0=usage[x3];break;
 default:assert(0);
 }
 if(calls==mutate_at)usage[1]^=1U;
}
#include "ccci-scp-resource.c"
static void fault_stays(struct ccci_scp_resource *r) {
 unsigned n=calls;
 assert(r->fault && !r->pinned);
 assert(ccci_scp_resource_pin(r)==-EIO && calls==n);
 ccci_scp_resource_invalidate(r);assert(calls==n);
}
int main(void) {
 struct ccci_scp_resource_sample s;
 struct ccci_scp_resource r;
 assert(ccci_scp_resource_read(NULL)==-EINVAL);
 assert(ccci_scp_resource_pin(NULL)==-EINVAL);
 ccci_scp_resource_invalidate(NULL);
 setup(false,0);assert(!ccci_scp_resource_read(&s));
 assert(s.resources==6 && s.users==3 && !s.scp_present && s.scp_user==UINT32_MAX);
 assert(!requests && calls<=88);
 /* Every inherited SCP combination and all 32 possible user bits. */
 for(unsigned id=0;id<32;id++)for(unsigned mask=0;mask<64;mask++) {
  setup(true,id);r=(struct ccci_scp_resource){0};
  for(unsigned i=0;i<6;i++)usage[i]=(mask&(1U<<i))?(1U<<id):0;
  assert(!ccci_scp_resource_pin(&r));
  assert(r.attempted && r.accepted && r.pinned && !r.fault && requests==1);
  assert(r.before.scp_resources==mask && r.after.scp_resources==(mask|2));
  unsigned n=calls;assert(!ccci_scp_resource_pin(&r) && calls==n);
  ccci_scp_resource_invalidate(&r);assert(r.pinned && r.fault && calls==n);
  assert(ccci_scp_resource_pin(&r)==-EIO && calls==n);
 }
 setup(false,0);r=(struct ccci_scp_resource){0};
 assert(!ccci_scp_resource_pin(&r) && r.pinned && requests==1);
 assert(!r.before.scp_present && r.after.scp_present && r.after.scp_valid);
 /* Every read failure before or after the one mutation: no rollback/retry. */
 setup(true,1);r=(struct ccci_scp_resource){0};
 assert(!ccci_scp_resource_pin(&r));unsigned total=calls,mutation=request_at;
 for(unsigned failure=1;failure<=total;failure++) {
  setup(true,1);r=(struct ccci_scp_resource){0};fail_at=failure;
  /* A mutation has a distinct result contract, tested below. */
  if(failure==mutation)continue;
  int ret=ccci_scp_resource_pin(&r);
  assert(ret==-EOPNOTSUPP && calls==failure && requests<=1);
  assert(r.attempted==(requests==1));fault_stays(&r);
 }
 for(unsigned variant=0;variant<6;variant++) {
  setup(true,0);r=(struct ccci_scp_resource){0};
  if(variant<4)request_a0=(unsigned long)-(long)(variant+1);
  else if(variant==4)request_a1=UINT32_MAX;
  else request_a0=1;
  assert(ccci_scp_resource_pin(&r)==-EIO && requests==1 && !r.accepted);
  fault_stays(&r);
 }
 setup(false,0);mode=1;r=(struct ccci_scp_resource){0};
 assert(ccci_scp_resource_pin(&r)==-EPROTO && r.accepted);fault_stays(&r);
 for(unsigned m=2;m<=4;m++) {
  setup(true,0);users=2;valid=3;names[1]=0x42424242;usage[3]=1;mode=m;
  r=(struct ccci_scp_resource){0};
  assert(ccci_scp_resource_pin(&r)==-EPROTO && r.accepted);fault_stays(&r);
 }
 setup(true,0);valid=0;r=(struct ccci_scp_resource){0};
 assert(ccci_scp_resource_pin(&r)==-EACCES && !requests && !r.attempted);
 fault_stays(&r);
 setup(true,1);names[0]=0x504353;r=(struct ccci_scp_resource){0};
 assert(ccci_scp_resource_pin(&r)==-EPROTO && !requests);fault_stays(&r);
 for(unsigned n=0;n<40;n++) {
  setup(false,0);resources=n;s=(struct ccci_scp_resource_sample){.users=123};
  if(n==6)continue;
  assert(ccci_scp_resource_read(&s)==-EPROTO && !s.users && !requests);
 }
 setup(false,0);users=33;
 assert(ccci_scp_resource_read(&s)==-EOVERFLOW && !requests && queries==2);
 setup(true,0);valid=2;
 assert(ccci_scp_resource_read(&s)==-EPROTO && !requests);
 setup(true,0);mutate_at=12;
 assert(ccci_scp_resource_read(&s)==-EAGAIN && !s.users && !requests);

 /* Read-only receive prerequisite: no implicit pin, release or retry. */
 setup(true,1);r=(struct ccci_scp_resource){0};
 assert(ccci_scp_resource_check(NULL,26000000)==-EINVAL && !calls);
 assert(ccci_scp_resource_check(&r,26000000)==-EAGAIN && !calls);
 r.fault=true;assert(ccci_scp_resource_check(&r,26000000)==-ESHUTDOWN && !calls);
 setup(true,1);r=(struct ccci_scp_resource){0};assert(!ccci_scp_resource_pin(&r));
 calls=queries=0;
 assert(!ccci_scp_resource_check(&r,26000000) && !r.fault && requests==1 && calls<=88);
 unsigned check_total=calls;
 for(unsigned failure=1;failure<=check_total;failure++) {
  setup(true,1);r=(struct ccci_scp_resource){0};assert(!ccci_scp_resource_pin(&r));
  calls=queries=0;fail_at=failure;
  assert(ccci_scp_resource_check(&r,26000000)==-EOPNOTSUPP && r.fault && requests==1 && calls==failure);
  unsigned n=calls;assert(ccci_scp_resource_check(&r,26000000)==-ESHUTDOWN && calls==n);
 }
 for(unsigned variant=0;variant<7;variant++) {
  setup(true,variant==6?0:1);r=(struct ccci_scp_resource){0};assert(!ccci_scp_resource_pin(&r));
  calls=queries=0;
  switch(variant) {
   case 0:break; /* rate alone must fail without an SMC */
   case 1:usage[1]=0;break;
   case 2:usage[3]|=2;break;
   case 3:names[1]=0;break;
   case 4:names[1]=0;names[0]=0x504353;usage[1]=1;break;
   case 5:valid&=~2U;break;
   case 6:mutate_at=13;break;
  }
  int ret=ccci_scp_resource_check(&r,variant?26000000:24000000);
  assert(ret<0 && r.fault && r.error==ret && requests==1);
  if(!variant)assert(ret==-EBUSY && !calls);
  unsigned n=calls;assert(ccci_scp_resource_check(&r,26000000)==-ESHUTDOWN && calls==n);
 }
 puts("PASS: exact GET/request SMC ABI, 2048 inherited masks/user bits, lazy registration, bounded snapshots, every read/return failure, silent no-op, identity/validity changes, receive prerequisite checks and no release/retry");
}
'''



def owner_harness():
    source = (DRIVER / 'ccci-scp-resource-hold.c').read_text()

    def block(marker):
        start = source.index(marker)
        end = source.index('{', start)
        depth = 1
        end += 1
        while depth:
            depth += (source[end] == '{') - (source[end] == '}')
            end += 1
        return source[start:end]

    stubs = r"""
#include <stdarg.h>
#include <sys/types.h>
struct clk { unsigned long rate; bool changed; unsigned reads; };
struct mutex { bool locked; };
struct device { void *data; };
struct device_attribute { int unused; };
struct ccci_scp_resource_owner {
 struct clk *clock;struct mutex lock;struct ccci_scp_resource resource;uint64_t reset_generation;
};
static void *dev_get_drvdata(struct device *dev) {return dev->data;}
#define lockdep_assert_held(m) assert((m)->locked)
static void mutex_lock(struct mutex *m){assert(!m->locked);m->locked=true;}
static void mutex_unlock(struct mutex *m){assert(m->locked);m->locked=false;}
static bool sysfs_streq(const char *a,const char *b){return !strcmp(a,b);}
static unsigned long clk_get_rate(struct clk *c) {
 c->reads++;return c->changed && c->reads>1 ? 24000000 : c->rate;
}
static int sysfs_emit(char *buf,const char *fmt,...) {
 va_list args;va_start(args,fmt);int n=vsnprintf(buf,4096,fmt,args);va_end(args);return n;
}
"""
    tests = r"""
int main(void) {
 struct clk clk={.rate=26000000};
 struct ccci_scp_resource_owner o={.clock=&clk};
 struct device dev={.data=&o};char buf[4096];
 setup(true,0);
 assert(pin_store(&dev,NULL,"release",7)==-EINVAL && !calls);
 clk.rate=24000000;
 assert(pin_store(&dev,NULL,"26m",3)==-EBUSY && !calls && !o.lock.locked);
 clk.rate=26000000;
 assert(state_show(&dev,NULL,buf)>0 && !requests && strstr(buf,"attempted=0"));
 assert(pin_store(&dev,NULL,"26m",3)==3 && requests==1);
 assert(state_show(&dev,NULL,buf)>0 && strstr(buf,"pin_verified=1 fault=0"));
 unsigned old=requests;
 assert(pin_store(&dev,NULL,"26m",3)==3 && requests==old);
 /* A later lost vote becomes sticky and must not reissue the request. */
 usage[1]=0;
 assert(state_show(&dev,NULL,buf)>0 && strstr(buf,"pin_verified=0 fault=1"));
 assert(pin_store(&dev,NULL,"26m",3)==-EIO && requests==old);
 setup(true,0);o.resource=(struct ccci_scp_resource){0};
 assert(pin_store(&dev,NULL,"26m",3)==3);fail_at=calls+1;
 assert(state_show(&dev,NULL,buf)==-EOPNOTSUPP && o.resource.fault);
 assert(pin_store(&dev,NULL,"26m",3)==-EIO && requests==1);
 setup(true,0);o.resource=(struct ccci_scp_resource){0};clk.changed=true;clk.reads=0;
 assert(pin_store(&dev,NULL,"26m",3)==-EAGAIN);
 assert(o.resource.pinned && o.resource.fault && requests==1 && !o.lock.locked);
 clk.changed=false;

 /* Production reset generation stays zero; nonzero values below are model-only. */
 setup(true,0);o.resource=(struct ccci_scp_resource){0};clk.rate=26000000;
 mutex_lock(&o.lock);unsigned before=calls;
 assert(ccci_scp_resource_receive_check(&o,0)==-ESTALE && calls==before);
 assert(ccci_scp_resource_receive_check(&o,17)==-ESTALE && calls==before);
 o.reset_generation=17;
 assert(ccci_scp_resource_receive_check(&o,16)==-ESTALE && calls==before);
 assert(ccci_scp_resource_receive_check(&o,17)==-EAGAIN && calls==before);
 assert(!ccci_scp_resource_pin(&o.resource));calls=queries=0;clk.reads=0;
 assert(!ccci_scp_resource_receive_check(&o,17) && requests==1);
 assert(calls>0 && calls<=88 && clk.reads==2);
 clk.rate=24000000;before=calls;
 assert(ccci_scp_resource_receive_check(&o,17)==-EBUSY && calls==before && o.resource.fault);
 setup(true,0);o.resource=(struct ccci_scp_resource){0};clk.rate=26000000;
 assert(!ccci_scp_resource_pin(&o.resource));calls=queries=0;clk.changed=true;clk.reads=0;
 assert(ccci_scp_resource_receive_check(&o,17)==-EAGAIN && o.resource.fault && o.resource.error==-EAGAIN && requests==1);
 clk.changed=false;before=calls;
 assert(ccci_scp_resource_receive_check(&o,17)==-ESHUTDOWN && calls==before);
 mutex_unlock(&o.lock);
 puts("PASS: actual sysfs guard/hold callbacks and owner receive prerequisite, reset gate, pre/post clocks, read-only queries, no release, sticky lost vote/query fault and post-pin clock change");
}
"""
    return (HARNESS[:HARNESS.index('static void fault_stays(')] + stubs +
            block('static int ccci_scp_resource_receive_check(') + '\n' +
            block('static ssize_t state_show(') + '\n' +
            block('static ssize_t pin_store(') + '\n' + tests)


def run(harness, headers):
    with tempfile.TemporaryDirectory(prefix='op6893-scp-resource-') as directory:
        root = Path(directory)
        for name, content in headers.items():
            p = root / 'linux' / name
            p.parent.mkdir(parents=True, exist_ok=True)
            p.write_text(content)
        (root / 'test.c').write_text(harness)
        subprocess.run(['cc', '-std=gnu11', '-Wall', '-Wextra', '-Werror',
                        '-DCONFIG_ARM64', '-Wno-unused-parameter', '-fsanitize=address,undefined',
                        '-fno-sanitize-recover=all', '-no-pie', '-I', str(root),
                        '-I', str(DRIVER), '-I', str(KERNEL / 'include'),
                        str(root / 'test.c'), '-o', str(root / 'test')], check=True)
        subprocess.run([str(root / 'test')], check=True)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.parse_args()
    headers = {
        'types.h': '#include <stdint.h>\n#include <stdbool.h>\ntypedef uint32_t u32;typedef uint64_t u64;\n',
        'errno.h': '#include_next <linux/errno.h>\n',
        'limits.h': '#define U32_MAX UINT32_MAX\n',
        'bits.h': '#pragma once\n#define BIT(n) (1UL << (n))\n',
        'bitops.h': '#include <linux/bits.h>\n',
        'arm-smccc.h': '''#pragma once
struct arm_smccc_res { unsigned long a0,a1,a2,a3; };
#define ARM_SMCCC_SMC_64 1
#define ARM_SMCCC_SMC_32 0
#define ARM_SMCCC_FAST_CALL 1
#define ARM_SMCCC_OWNER_SIP 2
#define ARM_SMCCC_CALL_VAL(t,c,o,n) (((unsigned)(t)<<31)|((unsigned)(c)<<30)|((unsigned)(o)<<24)|(n))
#define arm_smccc_smc fake_smc
''',
    }
    run(HARNESS, headers)
    run(owner_harness(), headers)


if __name__ == '__main__':
    main()
