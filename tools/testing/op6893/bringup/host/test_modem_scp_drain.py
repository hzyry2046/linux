#!/usr/bin/env python3
# SPDX-License-Identifier: GPL-2.0-only
"""Actual RX/drain C with synthetic IRQ containment and reset generations."""
from pathlib import Path
import runpy
import subprocess
import tempfile

K = Path(__file__).resolve().parents[5]
D = K / 'drivers/misc/mediatek/ccci'
fixture = runpy.run_path(str(Path(__file__).with_name('test_modem_scp.py')))
tx, rx, _ = fixture['audited_fixture']()


def source(name):
    return '\n'.join(line for line in (D / name).read_text().splitlines()
                     if not line.startswith('#include'))


preamble = r'''
#include <assert.h>
#include <errno.h>
#include <stdbool.h>
#include <stdint.h>
#include <stdio.h>
#include <string.h>
typedef uint8_t u8;typedef uint16_t u16;typedef uint32_t u32;typedef uint64_t u64;
#define U32_MAX UINT32_MAX
#define BIT(n) (1U<<(n))
#define BIT_ULL(n) (1ULL<<(n))
#define ARRAY_SIZE(a) (sizeof(a)/sizeof((a)[0]))
static u16 get_unaligned_le16(const void *p) {const u8 *b=p;return (u16)b[0]|(u16)b[1]<<8;}
static u32 get_unaligned_le32(const void *p) {const u8 *b=p;return (u32)b[0]|(u32)b[1]<<8|(u32)b[2]<<16|(u32)b[3]<<24;}
static void put_unaligned_le16(u16 v,void *p) {u8 *b=p;for(unsigned i=0;i<2;i++)b[i]=v>>(8*i);}
static void put_unaligned_le32(u32 v,void *p) {u8 *b=p;for(unsigned i=0;i<4;i++)b[i]=v>>(8*i);}
'''
harness = r'''
static const u32 tx[]={@TX@},rt[]={@RX@};
static struct ccci_scp_layout layout;
static struct ccci_scp_drain drain;
static struct ccci_scp_rx receivers[5],*rx[5];
struct model {u32 known,mask;unsigned box,stage,reads,acks,posts,delivered,polls,busy_sweeps;u8 wire[256];};
static struct model models[5];
static unsigned operations,fail_at,mask_calls,unmask_calls,checks,polls;
static bool masked,fail_mask,fail_unmask,fail_remask,continuous,late;
static u64 expected_generation;
static int fail(void) {return ++operations==fail_at?-EIO:0;}
static int mask(void *context,bool value) {
 assert(context==&drain);
 if(value){mask_calls++;if(fail_mask || (fail_remask && unmask_calls)){return -EIO;}masked=true;}
 else {unmask_calls++;masked=false;if(fail_unmask)return -EREMOTEIO;
  /* New level-high work after the empty sweep must be visible on next run. */
  if(late)models[0].mask=models[0].known;
 }
 return 0;
}
static int check(void *context,u64 generation) {
 assert(context==&drain && masked && generation==expected_generation);checks++;return fail();
}
static int pending(void *context,u32 *out) {
 struct model *m=context;assert(masked && m->box==polls%5);polls++;m->polls++;m->stage=1;
 for(unsigned i=0;i<256;i++)m->wire[i]=(u8)(i+m->box);
 *out=(continuous || m->polls<=m->busy_sweeps)?m->known:m->mask;return fail();
}
static int read_words(void *context,u32 offset,u32 words,void *buffer) {
 struct model *m=context;assert(masked && m->stage==1 && offset+words<=64);
 m->reads++;if(fail())return -EIO;memcpy(buffer,m->wire+offset*4,words*4);return 0;
}
static int post(void *context) {
 struct model *m=context;assert(masked && m->stage==1);m->stage=2;m->posts++;return fail();
}
static int ack(void *context,u32 bits) {
 struct model *m=context;assert(masked && m->stage==2 && bits && !(bits&~m->known));
 m->stage=3;m->acks++;m->mask&=~bits;memset(m->wire,0xee,sizeof(m->wire));return fail();
}
static void deliver(void *context,const struct ccci_scp_pin *pin,const void *data,size_t size,u64 generation) {
 struct model *m=context;assert(masked && m->stage==3 && generation==expected_generation);
 assert(pin->mbox==m->box && size==pin->words*4);
 const u8 *bytes=data;for(unsigned i=0;i<size;i++)assert(bytes[i]==(u8)(pin->offset*4+i+m->box));m->delivered++;
}
static const struct ccci_scp_rx_ops rxops={pending,read_words,post,ack,deliver};
static const struct ccci_scp_drain_ops ops={mask,check};
static void reinit(u64 gen) {
 expected_generation=gen;
 for(unsigned i=0;i<5;i++) {
  models[i]=(struct model){.box=i};rx[i]=&receivers[i];
  for(unsigned j=0;j<layout.rx_count;j++)if(layout.rx[j].mbox==i)models[i].known|=BIT(layout.rx[j].irq);
  assert(!ccci_scp_rx_init(rx[i],&layout,i,models[i].known,gen,&rxops,&models[i]));
 }
 polls=0;
}
static void reset(void) {
 assert(!ccci_scp_build_layout(tx,ARRAY_SIZE(tx),rt,ARRAY_SIZE(rt),5,&layout));
 operations=fail_at=mask_calls=unmask_calls=checks=polls=0;
 masked=true;fail_mask=fail_unmask=fail_remask=continuous=late=false;
 assert(!ccci_scp_drain_init(&drain,&ops,&drain));reinit(17);
}
static void faulted(void) {
 assert(drain.state==CCCI_SCP_DRAIN_FAULT);
 for(unsigned i=0;i<5;i++)assert(rx[i]->fault);
 unsigned calls=operations,masks=mask_calls;
 assert(ccci_scp_drain_run(&drain,17)==-ESHUTDOWN && calls==operations && masks==mask_calls);
 assert(ccci_scp_drain_prepare(&drain,rx,18,4)==-EBUSY);
}
static void stop(void) {
 assert(!ccci_scp_drain_begin_stop(&drain) && masked);
 unsigned calls=operations,masks=mask_calls;
 assert(!ccci_scp_drain_begin_stop(&drain) && masks==mask_calls);
 assert(ccci_scp_drain_run(&drain,drain.generation)==-ESHUTDOWN);
 assert(ccci_scp_drain_prepare(&drain,rx,18,4)==-EBUSY);
 assert(!ccci_scp_drain_finish_stop(&drain) && calls==operations);
 assert(drain.state==CCCI_SCP_DRAIN_QUIESCED);
}
int main(void) {
 reset();assert(!operations && !mask_calls && !polls);
 assert(!ccci_scp_drain_prepare(&drain,rx,17,4) && masked && !polls);
 assert(!ccci_scp_drain_run(&drain,17) && !masked && polls==5 && drain.rounds==1);
 assert(drain.state==CCCI_SCP_DRAIN_ACTIVE && unmask_calls==1);
 stop();assert(ccci_scp_drain_prepare(&drain,rx,17,4)==-ESTALE);
 reinit(18);assert(!ccci_scp_drain_prepare(&drain,rx,18,4));
 unsigned n=operations,m=mask_calls;
 assert(ccci_scp_drain_run(&drain,17)==-ESTALE && n==operations && m==mask_calls);
 assert(!ccci_scp_drain_run(&drain,18));
 /* Bound is exact: budget-1 busy sweeps plus one quiet succeeds. */
 for(unsigned budget=1;budget<=32;budget++) {
  reset();for(unsigned i=0;i<5;i++)models[i].busy_sweeps=budget-1;
  assert(!ccci_scp_drain_prepare(&drain,rx,17,budget));
  assert(!ccci_scp_drain_run(&drain,17) && polls==5*budget && drain.rounds==budget);
  for(unsigned i=0;i<5;i++)assert(models[i].acks==budget-1);
  reset();continuous=true;assert(!ccci_scp_drain_prepare(&drain,rx,17,budget));
  assert(ccci_scp_drain_run(&drain,17)==-EOVERFLOW && masked && polls==5*budget && !unmask_calls);
  faulted();
 }
 /* Run every real check/pending/copy/post/ack failure in a full-board batch. */
 reset();for(unsigned i=0;i<5;i++)models[i].mask=models[i].known;
 assert(!ccci_scp_drain_prepare(&drain,rx,17,4));assert(!ccci_scp_drain_run(&drain,17));
 unsigned total=operations;
 for(unsigned failure=1;failure<=total;failure++) {
  reset();for(unsigned i=0;i<5;i++)models[i].mask=models[i].known;
  fail_at=failure;int ret=ccci_scp_drain_prepare(&drain,rx,17,4);
  if(!ret)ret=ccci_scp_drain_run(&drain,17);
  assert(ret==-EIO && masked && operations==failure && !unmask_calls);faulted();
 }
 /* Unknown pending in each mailbox must never be cleared or delivered. */
 for(unsigned i=0;i<5;i++) {
  reset();models[i].mask=BIT(31);assert(!ccci_scp_drain_prepare(&drain,rx,17,4));
  assert(ccci_scp_drain_run(&drain,17)==-EOPNOTSUPP && masked);
  assert(!models[i].reads && !models[i].acks && !models[i].posts && !models[i].delivered);faulted();
 }
 reset();fail_mask=true;
 assert(ccci_scp_drain_prepare(&drain,rx,17,4)==-EIO && !drain.masked && !polls);faulted();
 reset();assert(!ccci_scp_drain_prepare(&drain,rx,17,4));fail_mask=true;
 assert(ccci_scp_drain_run(&drain,17)==-EIO && !drain.masked && !polls);faulted();
 for(unsigned bad=0;bad<2;bad++) {
  reset();assert(!ccci_scp_drain_prepare(&drain,rx,17,4));fail_unmask=true;
  fail_remask=bad;
  assert(ccci_scp_drain_run(&drain,17)==-EREMOTEIO);
  assert(drain.masked==!bad && masked==!bad);
  assert(drain.containment_error==(bad?-EIO:0) && unmask_calls==1);faulted();
 }
 reset();assert(!ccci_scp_drain_prepare(&drain,rx,17,4));fail_mask=true;
 assert(ccci_scp_drain_begin_stop(&drain)==-EIO && !drain.masked);
 assert(ccci_scp_drain_finish_stop(&drain)==-EBUSY);fail_mask=false;stop();
 reset();assert(ccci_scp_drain_finish_stop(&drain)==-EBUSY);
 assert(!ccci_scp_drain_prepare(&drain,rx,17,4));late=true;
 assert(!ccci_scp_drain_run(&drain,17) && models[0].mask);
 late=false;assert(!ccci_scp_drain_run(&drain,17) && models[0].acks==1);
 /* No receiver may be omitted, only partially supported, stale or duplicated. */
 for(unsigned i=0;i<5;i++)for(unsigned bad=0;bad<8;bad++) {
  reset();switch(bad) {case 0:rx[i]=NULL;break;case 1:rx[i]->supported_mask^=BIT(31);break;
  case 2:rx[i]->generation=16;break;case 3:rx[i]->fault=true;break;case 4:rx[i]->mbox=5;break;case 5:rx[i]->layout=NULL;break;
  case 6:rx[i]->ops=NULL;break;case 7:rx[i]->known_mask=0;break;}
  assert(ccci_scp_drain_prepare(&drain,rx,17,4)==-EINVAL && !mask_calls && !operations);
 }
 for(unsigned missing=0;missing<5;missing++) {
  reset();struct ccci_scp_rx_ops broken=rxops;
  switch(missing){case 0:broken.pending=NULL;break;case 1:broken.read_words=NULL;break;
   case 2:broken.post_capture=NULL;break;case 3:broken.ack=NULL;break;case 4:broken.deliver=NULL;break;}
  rx[4]->ops=&broken;
  assert(ccci_scp_drain_prepare(&drain,rx,17,4)==-EINVAL && !mask_calls && !operations);
 }
 reset();struct ccci_scp_layout other=layout;rx[4]->layout=&other;
 assert(ccci_scp_drain_prepare(&drain,rx,17,4)==-EINVAL && !mask_calls);
 /* A prerequisite or receiver lost after prepare must never poll/unmask. */
 reset();assert(!ccci_scp_drain_prepare(&drain,rx,17,4));rx[4]->fault=true;
 assert(ccci_scp_drain_run(&drain,17)==-EINVAL && !polls && masked);faulted();
 reset();assert(ccci_scp_drain_prepare(&drain,rx,0,4)==-EINVAL);
 assert(ccci_scp_drain_prepare(&drain,rx,17,0)==-EINVAL);
 assert(ccci_scp_drain_prepare(&drain,rx,17,33)==-EINVAL);
 assert(ccci_scp_drain_run(&drain,0)==-ESTALE);
 assert(ccci_scp_drain_prepare(&drain,rx,UINT64_MAX,4)==-EINVAL);
 reinit(UINT64_MAX);assert(!ccci_scp_drain_prepare(&drain,rx,UINT64_MAX,4));stop();
 reinit(1);assert(ccci_scp_drain_prepare(&drain,rx,1,4)==-ESTALE);
 assert(ccci_scp_drain_init(NULL,&ops,NULL)==-EINVAL);
 assert(ccci_scp_drain_run(NULL,1)==-EINVAL);
 assert(ccci_scp_drain_begin_stop(NULL)==-EINVAL);
 assert(ccci_scp_drain_finish_stop(NULL)==-EINVAL);
 struct ccci_scp_drain_ops badops=ops;badops.check=NULL;
 assert(ccci_scp_drain_init(&drain,&badops,NULL)==-EINVAL);
 puts("PASS: actual five-mailbox RX/drain, all budgets 1..32, fault injection, sticky invalidation, unknown bits, stale queued generations, STOP barrier, late arrivals and generation exhaustion");
}
'''.replace('@TX@', ','.join(map(str, tx))).replace('@RX@', ','.join(map(str, rx)))
code = preamble + '\n'.join(source(n) for n in (
    'ccci-scp-protocol.h', 'ccci-scp-rx.h', 'ccci-scp-drain.h',
    'ccci-scp-protocol.c', 'ccci-scp-rx.c', 'ccci-scp-drain.c')) + harness
with tempfile.TemporaryDirectory(prefix='op6893-drain-') as directory:
    p = Path(directory)
    (p / 'test.c').write_text(code)
    subprocess.run(['cc', '-Wall', '-Wextra', '-Werror', '-Wno-misleading-indentation',
                    '-Wno-sign-compare', '-fsanitize=address,undefined',
                    '-fno-sanitize-recover=all', '-no-pie', str(p / 'test.c'),
                    '-o', str(p / 'test')], check=True)
    subprocess.run([str(p / 'test')], check=True)
