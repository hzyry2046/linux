#!/usr/bin/env python3
# SPDX-License-Identifier: GPL-2.0-only
"""Exercise the actual SCP awake backend with failure-injecting regmap stubs.

Synthetic register state only; does not contact a device or validate firmware.
The polling stub enforces an iteration budget, not real bus timeout behavior.
"""
from pathlib import Path
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
#include "ccci-scp-awake.h"
struct regmap { unsigned status, pending, reads; };
struct event { unsigned op, reg, value; };
static struct event events[100010];
static unsigned calls, fail_at, fail_also, ack_after, delays;
static bool no_ack, bad_magic;
static int event(unsigned op,unsigned reg,unsigned value) {
 assert(calls < 100010 && (reg==0xb14 || reg==0xb18));
 events[calls++]=(struct event){op,reg,value};
 return calls==fail_at ? -EACCES : calls==fail_also ? -EFAULT : 0;
}
static int regmap_read(struct regmap *map,unsigned reg,unsigned *value) {
 int ret=event(0,reg,0);assert(reg==0xb14);if(ret)return ret;
 if(map->pending && ++map->reads>=ack_after) {
  if(bad_magic)map->status&=~0xa0U;
  else if(!no_ack)map->status&=~map->pending;
 }
 *value=map->status;return 0;
}
static int regmap_write(struct regmap *map,unsigned reg,unsigned value) {
 int ret=event(1,reg,value);
 assert(value==0xa1 || value==0xa2);
 /* Also model writes that reached hardware despite an error return. */
 if(reg==0xb14) {map->status|=value;map->pending=value&3;map->reads=0;}
 else {map->status&=~value;map->pending=0;}
 return ret;
}
#define regmap_read_poll_timeout(m,r,v,cond,delay,budget) ({ \
 int result=-ETIMEDOUT; \
 assert((delay)==10 && (budget)==1000000); \
 for(unsigned j=0;j<=(budget)/(delay);j++) { \
  int err=regmap_read(m,r,&v);if(err){result=err;break;} \
  if(cond){result=0;break;}delays++; \
 } result; })
#include "ccci-scp-awake.c"
static void clear_events(void) {calls=fail_at=fail_also=delays=0;}
static void setup(struct ccci_scp_awake *a,struct regmap *m) {
 *m=(struct regmap){.status=0x5a00000c};
 clear_events();ack_after=1;no_ack=bad_magic=false;
 assert(!ccci_scp_awake_init(a,m) && !calls);
 assert(!a->users && !a->fault && !a->cleanup_error);
}
static void trace(unsigned bit,unsigned reads) {
 assert(calls==3+reads);
 assert(events[0].op==0 && events[0].reg==0xb14);
 assert(events[1].op==1 && events[1].reg==0xb14 && events[1].value==(0xa0|bit));
 for(unsigned j=0;j<reads;j++)assert(events[j+2].op==0 && events[j+2].reg==0xb14);
 assert(events[calls-1].op==1 && events[calls-1].reg==0xb18 &&
        events[calls-1].value==(0xa0|bit));
}
static void reject_faulted(struct ccci_scp_awake *a) {
 unsigned old=calls,users=a->users;
 assert(a->fault && ccci_scp_awake_get(a)==-EIO && ccci_scp_awake_put(a)==-EIO);
 assert(calls==old && a->users==users);
}
int main(void) {
 struct ccci_scp_awake a;struct regmap m;
 setup(&a,&m);assert(!ccci_scp_awake_get(&a));trace(1,1);
 assert(a.users==1 && !a.fault && m.status==0x5a00000c);
 clear_events();assert(!ccci_scp_awake_get(&a) && a.users==2 && !calls);
 assert(!ccci_scp_awake_put(&a) && a.users==1 && !calls);
 assert(!ccci_scp_awake_put(&a));trace(2,1);
 assert(!a.users && !a.fault && m.status==0x5a00000c);
 clear_events();assert(ccci_scp_awake_put(&a)==-EINVAL && !calls && !a.fault);
 a.users=UINT32_MAX;assert(ccci_scp_awake_get(&a)==-EOVERFLOW);
 assert(a.users==UINT32_MAX && !calls && !a.fault);
 puts("PASS: first/last AP lease, nested users, underflow/overflow, W1 masks and adjacent CONNSYS bits");
 for(unsigned unlock=0;unlock<2;unlock++) {
  for(unsigned failure=1;failure<=4;failure++) {
   setup(&a,&m);a.users=unlock;fail_at=failure;
   int ret=unlock?ccci_scp_awake_put(&a):ccci_scp_awake_get(&a);
   assert(ret==-EACCES && a.users==unlock);
   if(failure==1)assert(calls==1);
   else {
    assert(events[calls-1].reg==0xb18 && events[calls-1].op==1);
    assert(events[calls-1].value==(0xa0 | (unlock?2:1)));
   }
   assert(a.cleanup_error==(failure==4?-EACCES:0));reject_faulted(&a);
  }
  setup(&a,&m);a.users=unlock;fail_at=2;fail_also=3;
  assert((unlock?ccci_scp_awake_put(&a):ccci_scp_awake_get(&a))==-EACCES);
  assert(a.cleanup_error==-EFAULT && a.users==unlock);reject_faulted(&a);
  setup(&a,&m);a.users=unlock;no_ack=true;
  assert((unlock?ccci_scp_awake_put(&a):ccci_scp_awake_get(&a))==-ETIMEDOUT);
  trace(unlock?2:1,100001);assert(a.users==unlock);reject_faulted(&a);
  setup(&a,&m);a.users=unlock;bad_magic=true;
  assert((unlock?ccci_scp_awake_put(&a):ccci_scp_awake_get(&a))==-EPROTO);
  trace(unlock?2:1,1);assert(a.users==unlock);reject_faulted(&a);
  for(unsigned stale=1;stale<4;stale++) {
   setup(&a,&m);a.users=unlock;m.status|=stale;
   assert((unlock?ccci_scp_awake_put(&a):ccci_scp_awake_get(&a))==-EBUSY);
   assert(calls==1 && a.users==unlock && (m.status&3)==stale);reject_faulted(&a);
  }
 }
 puts("PASS: every lock/unlock I/O failure, ambiguous failed SET cleanup, primary+cleanup errors, sticky fault");
 puts("PASS: bounded timeout, missing marker rejection, pending AP requests never overwritten or cleared");
 for(unsigned delay=1;delay<=33;delay++) {
  setup(&a,&m);ack_after=delay;
  assert(!ccci_scp_awake_get(&a));trace(1,delay);assert(delays==delay-1);
  clear_events();assert(!ccci_scp_awake_put(&a));trace(2,delay);
 }
 setup(&a,&m);assert(!ccci_scp_awake_get(&a));clear_events();
 ccci_scp_awake_invalidate(&a);assert(a.users==1 && !calls);reject_faulted(&a);
 setup(&a,&m);ccci_scp_awake_invalidate(&a);reject_faulted(&a);
 assert(ccci_scp_awake_get(NULL)==-EINVAL && ccci_scp_awake_put(NULL)==-EINVAL);
 assert(ccci_scp_awake_init(NULL,&m)==-EINVAL);
 assert(ccci_scp_awake_init(&a,NULL)==-EINVAL && a.fault && !a.infra);
 assert(ccci_scp_awake_init(&a,(void *)(intptr_t)-EIO)==-EINVAL && a.fault);
 assert(ccci_scp_awake_get(&a)==-EINVAL && ccci_scp_awake_put(&a)==-EINVAL);
 ccci_scp_awake_invalidate(NULL);
 puts("PASS: delayed ACK, STOP invalidation without I/O, null/error regmaps and init without I/O");
 return 0;
}
'''


def main():
    with tempfile.TemporaryDirectory(prefix='op6893-scp-awake-') as tmp:
        root = Path(tmp)
        linux = root / 'linux'
        linux.mkdir()
        (linux / 'types.h').write_text(
            '#include <stdbool.h>\n#include <stdint.h>\ntypedef uint32_t u32;\n')
        (linux / 'errno.h').write_text('#include_next <linux/errno.h>\n')
        (linux / 'limits.h').write_text('#define U32_MAX UINT32_MAX\n')
        (linux / 'bitops.h').write_text('#define BIT(n) (1U << (n))\n')
        (linux / 'regmap.h').write_text('/* Provided by the failure-injecting harness. */\n')
        (linux / 'err.h').write_text(
            '#define IS_ERR_OR_NULL(p) (!(p) || (uintptr_t)(p) >= (uintptr_t)-4095)\n')
        source = root / 'test.c'
        binary = root / 'test'
        source.write_text(HARNESS)
        subprocess.run(['cc', '-std=gnu11', '-Wall', '-Wextra', '-Werror', '-g',
                        '-fsanitize=address,undefined', '-fno-omit-frame-pointer',
                        '-no-pie', '-I', str(root), '-I', str(DRIVER),
                        str(source), '-o', str(binary)], check=True)
        subprocess.run([str(binary)], check=True)


if __name__ == '__main__':
    main()
