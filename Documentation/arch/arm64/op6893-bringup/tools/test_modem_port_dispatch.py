#!/usr/bin/env python3
# SPDX-License-Identifier: GPL-2.0-only
"""Exercise full actual dispatcher and wire decoder with deterministic dependencies.

The model checks callback deferral and lifecycle call order, not SMP scheduling
or hardware. Endpoint, bridge and controller have their own actual C tests.
"""
from pathlib import Path
import subprocess
import tempfile

K = Path(__file__).resolve().parents[5]
SRC = K / 'drivers/misc/mediatek/ccci'
TEST = r'''
#include <assert.h>
#include <errno.h>
#include <stdarg.h>
#include <stdio.h>
#include <stdlib.h>
#include <string.h>
#include <stddef.h>
#include <linux/types.h>
#include <linux/unaligned.h>
#include "ccci-ccif-rx.h"
#define __CCCI_CCIF_H
#define __CCCI_CCISM_H
#define __CCCI_CCISM_BRIDGE_H
#define __CCCI_SERVICE_ENDPOINT_H
#define CCCI_FS_RX 14
#define CCCI_RPC_RX 32
#define BIT(x) (1U<<(x))
#define READ_ONCE(x) (x)
#define container_of(p,t,m) ((t *)((char *)(p)-offsetof(t,m)))
#define ERR_PTR(e) ((void *)(intptr_t)(e))
#define IS_ERR(p) ((uintptr_t)(p) >= (uintptr_t)-4095)
#define WARN_ON(x) (!!(x))
struct mutex { bool held; };
static unsigned spin_depth;
static void mutex_init(struct mutex *m){m->held=false;}
static void mutex_lock(struct mutex *m){assert(!m->held);assert(!spin_depth);m->held=true;}
static void mutex_unlock(struct mutex *m){assert(m->held);m->held=false;}
typedef unsigned spinlock_t;
#define spin_lock_init(p) (*(p)=0)
#define spin_lock_irqsave(p,f) do {(void)(p);(f)=0;spin_depth++;}while(0)
#define spin_unlock_irqrestore(p,f) do {(void)(p);(void)(f);assert(spin_depth);spin_depth--;}while(0)
struct work_struct {void (*fn)(struct work_struct *);bool pending;};
#define INIT_WORK(w,f) do {(w)->fn=f;(w)->pending=false;}while(0)
static void schedule_work(struct work_struct *w){w->pending=true;}
static void cancel_work_sync(struct work_struct *w){assert(!spin_depth);w->pending=false;}
static void run_work(struct work_struct *w){if(w->pending){w->pending=false;w->fn(w);}}
static bool alloc_fail,action_fail;
static void *alloc(size_t n){return alloc_fail?NULL:calloc(1,n);}
#define kzalloc_obj(x) alloc(sizeof(x))
#define kfree(p) free(p)
struct device {void (*cleanup)(void *);void *context;};
static int devm_add_action_or_reset(struct device *d,void (*fn)(void *),void *p){
 if(action_fail){fn(p);return -ENOMEM;}d->cleanup=fn;d->context=p;return 0;
}
static int sysfs_emit(char *b,const char *fmt,...){va_list a;va_start(a,fmt);int r=vsnprintf(b,4096,fmt,a);va_end(a);return r;}
struct ccci_ccif {int unused;};
struct ccci_ccism_bridge {int unused;};
struct ccci_service_endpoint {int unused;};
struct ccci_runtime_offer {int unused;};
static unsigned logn;static char logbuf[256];
static int fail_reserve,fail_bridge,fail_set,fail_start,fail_ccif_stop,fail_ep_stop,fail_bridge_stop,fail_offline;
static bool runtime_published,hs2_notified,rx_joined,synchronous_hs1;
static int fail_arm,fail_hs2,fail_receive,fail_port;
static ccci_ccif_consume_fn consumer;static void *consumer_ctx;
static void (*fault_cb)(void *,int);static void *fault_ctx;
static struct ccci_ccif_event hs1_event;
static void note(char c){assert(!spin_depth);assert(logn+1<sizeof(logbuf));logbuf[logn++]=c;logbuf[logn]=0;}
static int ccci_service_endpoint_reserve(struct ccci_service_endpoint *p,u64 g){(void)p;assert(g==77);note('R');return fail_reserve;}
static int ccci_ccism_bridge_arm(struct ccci_ccism_bridge *p){(void)p;note('B');return fail_bridge;}
static int ccci_ccif_set_fault(struct ccci_ccif *p,void (*f)(void *,int),void *ctx){(void)p;note('F');fault_cb=f;fault_ctx=ctx;return fail_set;}
static int ccci_ccif_handshake_start(struct ccci_ccif *p,const struct ccci_runtime_offer *o,ccci_ccif_consume_fn f,void *ctx){
 (void)p;assert(o);note('S');consumer=f;consumer_ctx=ctx;
 if(synchronous_hs1){runtime_published=true;assert(!f(ctx,&hs1_event));}return fail_start;
}
static int ccci_service_endpoint_arm(struct ccci_service_endpoint *p,u64 g){(void)p;assert(g==77&&runtime_published);note('A');return fail_arm;}
static int ccci_service_endpoint_hs2(struct ccci_service_endpoint *p,u64 g){(void)p;assert(g==77);note('H');hs2_notified=true;return fail_hs2;}
static int ccci_ccism_bridge_port(struct ccci_ccism_bridge *p,const struct ccci_ccif_event *e){
 (void)p;assert(hs2_notified);note(e->header.channel==2?'D':'I');return fail_port;
}
static int ccci_service_endpoint_receive(struct ccci_service_endpoint *p,u64 g,const struct ccci_ccif_event *e){
 (void)p;assert(g==77);note(e->header.channel==14?'f':'r');return fail_receive;
}
static void ccci_service_endpoint_abort(struct ccci_service_endpoint *p,u64 g,int e){(void)p;assert(g==77&&e<0);note('E');}
static void ccci_ccif_abort(struct ccci_ccif *p,int e){(void)p;assert(e<0);note('C');}
static int ccci_ccif_stop(struct ccci_ccif *p){(void)p;note('J');if(!fail_ccif_stop)rx_joined=true;return fail_ccif_stop;}
static int ccci_service_endpoint_stop(struct ccci_service_endpoint *p,bool stopped){(void)p;assert(stopped&&rx_joined);note('e');return fail_ep_stop;}
static int ccci_ccism_bridge_stop(struct ccci_ccism_bridge *p,bool stopped){(void)p;assert(stopped&&rx_joined);note('b');return fail_bridge_stop;}
static int ccci_ccism_bridge_offline(struct ccci_ccism_bridge *p){(void)p;note('o');return fail_offline;}
#include "ccci-port-dispatch.c"
static struct device dev;static struct ccci_ccif ccif;static struct ccci_ccism_bridge bridge;static struct ccci_service_endpoint endpoint;
static void clearlog(void){logn=0;logbuf[0]=0;}
static struct ccci_port_dispatch *fresh(void){
 memset(&dev,0,sizeof(dev));clearlog();runtime_published=hs2_notified=rx_joined=synchronous_hs1=false;
 fail_reserve=fail_bridge=fail_set=fail_start=fail_ccif_stop=fail_ep_stop=fail_bridge_stop=fail_offline=0;
 fail_arm=fail_hs2=fail_receive=fail_port=0;consumer=NULL;fault_cb=NULL;return ccci_port_dispatch_create(&dev,&ccif,&bridge,&endpoint);
}
static void dispose(struct ccci_port_dispatch *d){assert(!ccci_port_dispatch_stop(d,true));assert(!ccci_port_dispatch_offline(d));dev.cleanup(dev.context);}
static struct ccci_ccif_event packet(u8 *buf,u32 size,unsigned ch,bool hs1){
 memset(buf,0,size);put_unaligned_le32(ch,buf+8);if(hs1)put_unaligned_le32(CCCI_CCIF_INIT_CHECK,buf+12);
 struct ccci_ccif_event e={.type=hs1?CCCI_CCIF_EVENT_SRAM:CCCI_CCIF_EVENT_RING,.data=buf,.size=size,.queue=ch==14?4:ch==32?1:0};
 assert(!ccci_ccif_header_decode(buf,size,&e.header));return e;
}
static struct ccci_port_dispatch *running(void){struct ccci_port_dispatch *d=fresh();assert(!IS_ERR(d));assert(!ccci_port_dispatch_prepare(d,77));struct ccci_runtime_offer o={0};assert(!ccci_port_dispatch_start(d,&o));return d;}
int main(void){
 u8 hs1[240],hs2[16],fs[24],rpc[24],other[16];struct ccci_runtime_offer offer={0};char status[4096];
 hs1_event=packet(hs1,sizeof(hs1),0,true);
 struct ccci_ccif_event he=packet(hs2,sizeof(hs2),0,false),fe=packet(fs,sizeof(fs),14,false),re=packet(rpc,sizeof(rpc),32,false),oe=packet(other,sizeof(other),2,false);
 assert(IS_ERR(ccci_port_dispatch_create(NULL,&ccif,&bridge,&endpoint)));
 assert(IS_ERR(ccci_port_dispatch_create(&dev,NULL,&bridge,&endpoint)));
 assert(IS_ERR(ccci_port_dispatch_create(&dev,&ccif,NULL,&endpoint)));
 assert(IS_ERR(ccci_port_dispatch_create(&dev,&ccif,&bridge,NULL)));
 alloc_fail=true;assert(IS_ERR(ccci_port_dispatch_create(&dev,&ccif,&bridge,&endpoint)));alloc_fail=false;
 action_fail=true;assert(IS_ERR(ccci_port_dispatch_create(&dev,&ccif,&bridge,&endpoint)));action_fail=false;
 struct ccci_port_dispatch *d=fresh();assert(!IS_ERR(d));assert(!logn&&!ccci_port_dispatch_offline(d));
 assert(ccci_port_dispatch_prepare(d,0)==-EINVAL);assert(!logn);
 assert(ccci_port_dispatch_start(d,&offer)==-EAGAIN);assert(!logn);
 assert(!ccci_port_dispatch_prepare(d,77));assert(!strcmp(logbuf,"RB"));
 assert(ccci_port_dispatch_prepare(d,77)==-EALREADY);assert(!strcmp(logbuf,"RB"));
 synchronous_hs1=true;assert(!ccci_port_dispatch_start(d,&offer));assert(!strcmp(logbuf,"RBFSA"));
 assert(d->state==DISPATCH_WAIT_HS2);assert(ccci_port_dispatch_status(d,status)>0);assert(strstr(status,"cpu_release_issued=0 service_ready=0"));
 assert(!consumer(consumer_ctx,&fe));assert(!consumer(consumer_ctx,&re));assert(!consumer(consumer_ctx,&he));
 assert(!strcmp(logbuf,"RBFSAfrHI"));assert(d->state==DISPATCH_HS2);
 assert(!consumer(consumer_ctx,&oe));assert(logbuf[logn-1]=='D');
 unsigned before=logn;assert(ccci_port_dispatch_stop(d,false)==-EBUSY&&logn==before);
 clearlog();assert(!ccci_port_dispatch_stop(d,true));assert(!strcmp(logbuf,"Jebo"));dev.cleanup(dev.context);
 /* FS before runtime/HS1 is terminal, with no synchronous abort I/O. */
 d=running();clearlog();assert(consumer(consumer_ctx,&fe)==-EPROTO);assert(!logn&&d->fault_work.pending);
 run_work(&d->fault_work);assert(!strcmp(logbuf,"EC")&&d->state==DISPATCH_FAILED);dispose(d);
 /* Unsupported channel must neither disappear nor produce fake replies. */
 d=running();runtime_published=true;assert(!consumer(consumer_ctx,&hs1_event));assert(!consumer(consumer_ctx,&he));
 oe=packet(other,sizeof(other),99,false);clearlog();assert(consumer(consumer_ctx,&oe)==-EOPNOTSUPP);assert(!logn);
 run_work(&d->fault_work);assert(!strcmp(logbuf,"EC"));dispose(d);
 /* Failed admission never advances dispatcher state or calls the next owner. */
 for(unsigned stage=0;stage<4;stage++){
  d=running();runtime_published=true;
  if(stage==0){fail_arm=-ENODEV;clearlog();assert(consumer(consumer_ctx,&hs1_event)==-ENODEV);assert(!strcmp(logbuf,"A"));assert(d->state==DISPATCH_WAIT_HS1);}
  else {
   assert(!consumer(consumer_ctx,&hs1_event));clearlog();
   if(stage==1){fail_hs2=-ENOSPC;assert(consumer(consumer_ctx,&he)==-ENOSPC);assert(!strcmp(logbuf,"H"));}
   if(stage==2){fail_port=-EIO;assert(consumer(consumer_ctx,&he)==-EIO);assert(!strcmp(logbuf,"HI"));}
   if(stage==3){fail_receive=-EOPNOTSUPP;assert(consumer(consumer_ctx,&fe)==-EOPNOTSUPP);assert(!strcmp(logbuf,"f"));}
   assert(d->state==DISPATCH_WAIT_HS2);
  }
  assert(d->fault_work.pending);run_work(&d->fault_work);assert(d->state==DISPATCH_FAILED);dispose(d);
 }
 /* Boundary packets have no provider or bridge effects before containment. */
 for(unsigned stage=0;stage<6;stage++){
  d=running();runtime_published=true;struct ccci_ccif_event bad=hs1_event;
  if(stage==0)bad.size--;
  if(stage==1)bad.type=CCCI_CCIF_EVENT_RING;
  if(stage==2)bad=he;
  if(stage==3){bad=fe;bad.size=15;}
  if(stage==4)bad.type=99;
  clearlog();assert(consumer(consumer_ctx,stage==5?NULL:&bad)<0);assert(!logn&&d->fault_work.pending);dispose(d);
 }
 /* Controller faults are enqueue-only, first error wins and close once. */
 d=running();clearlog();fault_cb(fault_ctx,1);fault_cb(fault_ctx,-ENOMEM);assert(!logn&&d->error==-EIO);
 run_work(&d->fault_work);assert(!strcmp(logbuf,"EC"));fault_cb(fault_ctx,-ENOMEM);run_work(&d->fault_work);assert(!strcmp(logbuf,"EC"));dispose(d);
 /* Fault pending when stopping cannot close already stopped dependencies. */
 d=running();fault_cb(fault_ctx,-EIO);clearlog();assert(!ccci_port_dispatch_stop(d,true));run_work(&d->fault_work);assert(!strcmp(logbuf,"Jebo"));dev.cleanup(dev.context);
 /* Every lifecycle failure retains removal veto and original storage. */
 for(unsigned stage=0;stage<4;stage++){
  d=running();clearlog();int *fail=stage==0?&fail_ccif_stop:stage==1?&fail_ep_stop:stage==2?&fail_bridge_stop:&fail_offline;*fail=-EIO;
  assert(ccci_port_dispatch_stop(d,true)==-EIO);assert(ccci_port_dispatch_offline(d)==-EBUSY);
  const char *expected[]={"J","Je","Jeb","Jebo"};assert(!strcmp(logbuf,expected[stage]));
  *fail=0;dispose(d);
 }
 /* Failed prepare/start is one attempted generation, never a retry shortcut. */
 for(unsigned stage=0;stage<4;stage++){
  d=fresh();int *fail=stage==0?&fail_reserve:stage==1?&fail_bridge:stage==2?&fail_set:&fail_start;*fail=-EIO;
  if(stage<2)assert(ccci_port_dispatch_prepare(d,77)==-EIO);
  else {assert(!ccci_port_dispatch_prepare(d,77));assert(ccci_port_dispatch_start(d,&offer)==-EIO);}
  assert(ccci_port_dispatch_prepare(d,77)==-EALREADY);assert(ccci_port_dispatch_offline(d)==-EBUSY);
  run_work(&d->fault_work);assert(d->state==DISPATCH_FAILED);*fail=0;dispose(d);
 }
 /* Notifications accept only validated peer wake (bit 7). */
 d=running();struct ccci_ccif_event notify={.type=CCCI_CCIF_EVENT_NOTIFY,.notifications=BIT(7)};
 clearlog();assert(!consumer(consumer_ctx,&notify));notify.notifications|=BIT(4);assert(consumer(consumer_ctx,&notify)==-EREMOTEIO);assert(!logn);dispose(d);
 assert(ccci_port_dispatch_offline(NULL)==0);
 puts("PASS: actual dispatcher, runtime/HS2 ordering, fault deferral, lifecycle veto and dormant construction");
 return 0;
}
'''


def main():
    with tempfile.TemporaryDirectory(prefix='op6893-port-dispatch-') as directory:
        tmp = Path(directory)
        inc = tmp / 'linux'
        inc.mkdir()
        for name in ('bitops', 'device', 'err', 'mutex', 'slab', 'spinlock',
                     'sysfs', 'workqueue'):
            (inc / (name + '.h')).write_text('/* supplied by test translation unit */\n')
        (inc / 'types.h').write_text('''#pragma once
#include <stdint.h>
#include <stddef.h>
#include <stdbool.h>
#include <sys/types.h>
typedef uint8_t u8; typedef uint16_t u16; typedef uint32_t u32;
typedef unsigned long long u64;
#define __iomem
''')
        (inc / 'errno.h').write_text('#include <asm-generic/errno.h>\n')
        (inc / 'kconfig.h').write_text('#define IS_ENABLED(x) 1\n')
        (inc / 'string.h').write_text('#include <string.h>\n')
        (inc / 'unaligned.h').write_text('''#pragma once
#include <linux/types.h>
static inline u32 get_unaligned_le32(const void *p) {
 const u8 *b=p; return (u32)b[0]|(u32)b[1]<<8|(u32)b[2]<<16|(u32)b[3]<<24;
}
static inline void put_unaligned_le32(u32 v,void *p) {
 u8 *b=p;for(unsigned i=0;i<4;i++)b[i]=v>>(8*i);
}
''')
        (tmp / 'test.c').write_text(TEST)
        subprocess.run(['cc', '-O1', '-g', '-Wall', '-Wextra', '-Werror',
                        '-fsanitize=address,undefined', '-fno-sanitize-recover=all',
                        '-no-pie', '-I' + str(tmp), '-I' + str(SRC),
                        str(SRC / 'ccci-ccif-protocol.c'), str(tmp / 'test.c'),
                        '-o', str(tmp / 'test')], check=True)
        subprocess.run([str(tmp / 'test')], check=True)


if __name__ == '__main__':
    main()
