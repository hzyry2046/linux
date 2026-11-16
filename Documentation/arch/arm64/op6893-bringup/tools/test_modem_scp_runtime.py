#!/usr/bin/env python3
# SPDX-License-Identifier: GPL-2.0-only
"""Actual runtime lifecycle/consumer with hardware, completion and awake faults."""
from pathlib import Path
import runpy

K = Path(__file__).resolve().parents[5]
D = K / 'drivers/misc/mediatek/ccci'
initial = runpy.run_path(str(Path(__file__).with_name('test_modem_scp_initial.py')))
block, compile_run = initial['block'], initial['compile_run']
prefix = initial['prefix'].replace('struct ccci_scp_pin {u32 channel;};',
                                  'struct ccci_scp_pin {u32 channel;bool response;};')
prefix += r'''
#include <stddef.h>
#define container_of(p,t,m) ((t *)((char *)(p)-offsetof(t,m)))
#define lockdep_assert_held(m) assert((m)->held)
#define CCCI_SCP_APCCCI_RX 7
struct regmap {int unused;};
struct work_struct {bool pending;};
struct completion {bool done;};
static int (*consume_fn)(void *,const struct ccci_scp_event *,int);
static void *consume_ctx;
static unsigned gets,put_calls,tx_calls;
static int get_error,put_error,tx_error;
static bool inject_fault;
static void complete_all(struct completion *c){assert(lock->held);c->done=true;}
static bool schedule_work(struct work_struct *w){w->pending=true;return true;}
static int ccci_scp_receive_consumer(void *r,int (*fn)(void *,const struct ccci_scp_event *,int),void *ctx){
 (void)r;assert(!lock->held);consume_fn=fn;consume_ctx=ctx;return 0;
}
static unsigned long wait_for_completion_timeout(struct completion *c,unsigned long ticks){
 assert(!lock->held && ticks==3000 && consume_fn);if(timeout)return 0;
 struct ccci_scp_event e={.generation=stale?2:1,.pin={.channel=21},.bytes=24};
 mutex_lock(lock);consume_fn(consume_ctx,&e,0);
 e.pin.channel=channel;e.bytes=4;consume_fn(consume_ctx,&e,0);
 if(inject_fault)consume_fn(consume_ctx,NULL,-EIO);
 mutex_unlock(lock);assert(c->done);return 1;
}
static int ccci_scp_decode_state(const void *p,size_t n,u32 *state){
 if(n!=8)return -EMSGSIZE;
 *state=*(const unsigned char *)p;return *state>=1 && *state<=3?0:-EPROTO;
}
'''
awake_stubs = r'''
int ccci_scp_awake_get(struct ccci_scp_awake *a){assert(lock->held);gets++;if(get_error){a->fault=true;return get_error;}a->users++;return 0;}
int ccci_scp_awake_put(struct ccci_scp_awake *a){assert(lock->held && a->users);put_calls++;if(put_error){a->fault=true;return put_error;}a->users--;return 0;}
void ccci_scp_awake_invalidate(struct ccci_scp_awake *a){assert(lock->held);a->fault=true;}
static int ccci_scp_mmio_md_invalid(void *m,const void *l,u64 gen){(void)m;(void)l;assert(lock->held && gen==1 && gets>put_calls);tx_calls++;return tx_error;}
'''
owner = initial['owner'].replace('int boot_error,boot_cleanup_error;',
                               'int boot_error,boot_cleanup_error;struct ccci_scp_runtime runtime;')
tests = r'''
static void setup(struct ccci_scp_resource_owner *o){
 memset(o,0,sizeof(*o));memset(cores,0,sizeof(cores));lock=&o->lock;
 o->core_tcm[0]=cores[0];o->core_tcm[1]=cores[1];o->runtime.owner=o;
 u32 a=0x11223344,b=0x55667788;memcpy(cores[0]+0x44,&a,4);memcpy(cores[0]+0x48,&b,4);
 checks=fail_at=stops=resets=starts=events=writes=released=0;jiffies=0;
 gets=put_calls=tx_calls=0;get_error=put_error=tx_error=0;
 start_error=pop_error=0;bad_ready=timeout=stale=inject_fault=false;channel=22;
}
static int start(struct ccci_scp_resource_owner *o){mutex_lock(&o->runtime.control);int ret=ccci_scp_runtime_start(o);mutex_unlock(&o->runtime.control);return ret;}
static void stop(struct ccci_scp_resource_owner *o){mutex_lock(&o->runtime.control);assert(!ccci_scp_runtime_stop(o));mutex_unlock(&o->runtime.control);}
static void failed(struct ccci_scp_resource_owner *o){
 assert(o->runtime.error && !o->runtime.active && !o->runtime.ready && !o->reset_generation && !o->boot_running && o->reset.latched);
 assert(!lock->held && !o->runtime.control.held && !consume_fn);
}
int main(void){
 struct ccci_scp_resource_owner o;
 setup(&o);assert(!start(&o));assert(o.runtime.active && o.runtime.ready && o.reset_generation==1);
 assert(o.runtime.logger_events==1 && o.boot_events==2 && gets==1 && put_calls==1 && o.runtime.awake_pairs==1);
 unsigned old=writes;assert(start(&o)==-EALREADY && writes==old);
 mutex_lock(lock);assert(!ccci_scp_runtime_awake(&o,true));mutex_unlock(lock);
 assert(tx_calls==1 && o.runtime.tx_completed==1 && gets==2 && put_calls==2);
 struct ccci_scp_event e={.generation=1,.pin={.channel=7},.bytes=8,.data={3}};
 mutex_lock(lock);assert(!ccci_scp_runtime_consume(&o,&e,0));mutex_unlock(lock);
 assert(o.runtime.apccci_events==1 && o.runtime.apccci_state==3);
 stop(&o);assert(!o.runtime.active && o.reset.latched && !o.reset_generation && !consume_fn);
 assert(!memcmp(cores[0]+0x44,"\x44\x33\x22\x11\x88\x77\x66\x55",8));
 old=writes;stop(&o);assert(writes==old);
 for(unsigned f=0;f<6;f++){
  setup(&o);if(f==0)timeout=true;if(f==1)stale=true;if(f==2)bad_ready=true;
  if(f==3)get_error=-ETIMEDOUT;
  if(f==4)put_error=-EIO;
  if(f==5)inject_fault=true;
  assert(start(&o)<0);failed(&o);
 }
 for(unsigned f=0;f<3;f++){
  setup(&o);assert(!start(&o));
  if(f==0)e.generation=2;
  if(f==1){e.generation=1;e.bytes=4;}
  if(f==2){e.generation=1;e.bytes=8;e.data[0]=4;}
  mutex_lock(lock);assert(ccci_scp_runtime_consume(&o,&e,0)<0);mutex_unlock(lock);
  assert(o.runtime.fault_work.pending && !o.runtime.ready);
  ccci_scp_runtime_fault_work(&o.runtime.fault_work);failed(&o);
 }
 setup(&o);assert(!start(&o));tx_error=-ETIMEDOUT;
 mutex_lock(lock);assert(ccci_scp_runtime_awake(&o,true)==-ETIMEDOUT);mutex_unlock(lock);
 assert(put_calls==2 && !o.runtime.awake.users && !o.runtime.tx_completed);stop(&o);
 puts("PASS: actual runtime start/READY/awake/TX/stop; continuous logger/APCCCI consume, shared one-shot, GPR restore, timeout/stale/malformed/awake/RX faults, deferred cleanup and TX failure put");
}
'''


def test_tx():
    prefix = r"""
#include <assert.h>
#include <errno.h>
#include <stdbool.h>
#include <stdint.h>
#include <stdio.h>
#include <string.h>
typedef uint8_t u8;typedef uint16_t u16;typedef uint32_t u32;typedef uint64_t u64;
#define CCCI_SCP_OP_MD_STATE 1
#define CCCI_SCP_OP_SHM_INIT 2
struct ccci_scp_pin {unsigned mbox,offset,irq,words;};
struct ccci_scp_layout {struct ccci_scp_pin tx,rx;};
struct ccci_scp_mmio_port {void *base;};
struct ccci_scp_mmio {u64 generation;struct ccci_scp_mmio_port ports[5];unsigned register_reads,register_writes;};
static unsigned char page[4096];
static unsigned writes,barriers,polls,checks,fail_check;
static bool busy,retain;
static void put_unaligned_le16(u16 n,void *p){memcpy(p,&n,2);}
static void put_unaligned_le32(u32 n,void *p){memcpy(p,&n,4);}
static u32 get_unaligned_le32(const void *p){u32 n;memcpy(&n,p,4);return n;}
static void memzero_explicit(void *p,size_t n){memset(p,0,n);}
static int ccci_scp_apccci_pins(const struct ccci_scp_layout *l,const struct ccci_scp_pin **tx,const struct ccci_scp_pin **rx){*tx=&l->tx;*rx=&l->rx;return 0;}
static int ccci_scp_mmio_check(struct ccci_scp_mmio_port *p){assert(p->base==page);return ++checks==fail_check?-EIO:0;}
static u32 readl(void *p){assert(p==page+0x100);polls++;return 0x80 | (busy || (writes && (retain || polls<4)));}
static void writel(u32 v,void *p){
 if(writes==0)assert(p==page && v==0x10000 && !barriers);
 if(writes==1)assert(p==page+4 && !v && !barriers);
 if(writes==2)assert(p==page+0x100 && v==1 && barriers==1);
 assert(writes<3);writes++;
}
static void mb(void){assert((writes==2 && !barriers) || (writes==3 && barriers==1));barriers++;}
static void usleep_range(unsigned a,unsigned b){assert(a==1000 && b==1200);}
"""
    tests = r"""
int main(void){
 for(unsigned f=0;f<7;f++){
  struct ccci_scp_mmio m={.generation=1};m.ports[1].base=page;
  struct ccci_scp_layout l={.tx={.mbox=1,.words=2}};
  writes=barriers=polls=checks=fail_check=0;busy=retain=false;
  if(f==1)busy=true;
  if(f==2)retain=true;
  if(f==3)l.tx.offset=2;
  if(f==4)fail_check=1;
  if(f==5)fail_check=2;
  int r=ccci_scp_mmio_md_invalid(&m,&l,f==6?2:1);
  if(!f)assert(!r && writes==3 && barriers==2 && checks==2 && polls==4);
  if(f==1)assert(r==-EBUSY && !writes);
  if(f==2)assert(r==-ETIMEDOUT && writes==3 && polls==101);
  if(f==3)assert(r==-EPROTO && !writes && !polls);
  if(f==4)assert(r==-EIO && !writes && !polls);
  if(f==5)assert(r==-EIO && writes==3);
  if(f==6)assert(r==-ESTALE && !writes && !polls);
 }
 puts("PASS: actual MD-invalid TX and codec; exact two words/barriers/SET, busy/stale/geometry/prerequisite rejection, bounded timeout without retry/ACK");
}
"""
    source = (D / 'ccci-scp-mmio.c').read_text()
    codec = block((D / 'ccci-scp-protocol.c').read_text(), 'int ccci_scp_encode(')
    compile_run(prefix + codec + block(source, 'int ccci_scp_mmio_md_invalid(') + tests)


def main():
    def clean(name):
        return '\n'.join(line for line in (D / name).read_text().splitlines()
                         if not line.startswith('#include'))
    reset = clean('ccci-scp-reset.c').replace('reset->attempted = true;',
                                             'reset->attempted = true; resets++;')
    code = prefix.replace('static ', 'static __attribute__((unused)) ') + clean('ccci-scp-awake.h') + awake_stubs
    code += clean('ccci-scp-runtime.h') + clean('ccci-scp-reset.h') + reset + owner
    source = (D / 'ccci-scp-runtime.c').read_text()
    for name in ('stop', 'fault_work', 'consume', 'asserted', 'awake', 'start'):
        kind = 'void' if name == 'fault_work' else 'int'
        code += block(source, f'static {kind} ccci_scp_runtime_{name}(')
    compile_run(code + tests)
    test_tx()


if __name__ == '__main__':
    main()
