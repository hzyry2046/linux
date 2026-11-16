#!/usr/bin/env python3
# SPDX-License-Identifier: GPL-2.0-only
"""Actual session, router and codecs under ASan/UBSan with modeled work/locks.

Deterministic producer/worker/stop interleavings; not a proof of SMP scheduling.
All bytes are synthetic; no real file, modem or calibration contents are used.
"""
from pathlib import Path
import subprocess
import tempfile

K = Path(__file__).resolve().parents[5]
TEST = r'''
#include <assert.h>
#include <stdio.h>
#include <stdlib.h>
#include <string.h>
#include <stdint.h>
#include <stdbool.h>
#include <stddef.h>
#include <linux/types.h>
#include <linux/errno.h>
#define __CCCI_CCIF_H
#define __iomem
struct device {int unused;};struct ccci_ccif {int unused;};
static int ccci_ccif_service_send(struct ccci_ccif *,const void *,u32,bool);
static void ccci_ccif_abort(struct ccci_ccif *,int);
static u64 now_ms;
static unsigned spin_depth;
struct mutex {bool held;};
static void mutex_init(struct mutex *m){m->held=false;}
static void mutex_lock(struct mutex *m){assert(!spin_depth&&!m->held);m->held=true;}
static void mutex_unlock(struct mutex *m){assert(!spin_depth&&m->held);m->held=false;}
typedef struct {bool held;} spinlock_t;
#define spin_lock_init(l) ((l)->held=false)
#define spin_lock_irqsave(l,f) do{(f)=0;assert(!(l)->held);(l)->held=true;spin_depth++;}while(0)
#define spin_unlock_irqrestore(l,f) do{(void)(f);assert((l)->held&&spin_depth);(l)->held=false;spin_depth--;}while(0)
struct work_struct {void(*fn)(struct work_struct *);bool pending;bool running;unsigned delay;};
struct delayed_work {struct work_struct work;};
struct workqueue_struct {bool live;};
#define WQ_MEM_RECLAIM 1
#define GFP_KERNEL 0
#define container_of(p,t,m) ((t *)((char *)(p)-offsetof(t,m)))
#define to_delayed_work(w) container_of(w,struct delayed_work,work)
#define INIT_DELAYED_WORK(w,f) do{(w)->work.fn=(f);}while(0)
static bool fail_workqueue;
static struct workqueue_struct *alloc_ordered_workqueue(const char *name,int flags){
 assert(name&&flags==WQ_MEM_RECLAIM);if(fail_workqueue)return NULL;
 struct workqueue_struct *q=calloc(1,sizeof(*q));assert(q);q->live=true;return q;
}
static void destroy_workqueue(struct workqueue_struct *q){assert(q&&q->live);free(q);}
static bool mod_delayed_work(struct workqueue_struct *q,struct delayed_work *w,unsigned delay){
 assert(q->live);bool prev=w->work.pending;w->work.pending=true;w->work.delay=delay;return prev;
}
static bool cancel_delayed_work_sync(struct delayed_work *w){
 assert(!spin_depth&&!w->work.running);bool p=w->work.pending;w->work.pending=false;return p;
}
#define msecs_to_jiffies(ms) (ms)
static u64 shim_clock_now(void);
#define ktime_get_boottime() shim_clock_now()
#define ktime_to_ms(ms) (ms)
#define kvzalloc_obj(obj) calloc(1,sizeof(obj))
#define kvfree(p) free(p)
static void kvfree_sensitive(void *p,size_t n){memset(p,0,n);free(p);}
#define ERR_PTR(e) ((void *)(intptr_t)(e))
#define IS_ERR(p) ((uintptr_t)(p)>(uintptr_t)-4096)
#define current get_current()
#include "ccci-service-session.c"
static struct ccci_service_session *session;
static void (*clock_hook)(void);
static u64 shim_clock_now(void){
 void (*hook)(void)=clock_hook;clock_hook=NULL;if(hook)hook();return now_ms;
}
static void abort_during_clock(void){assert(ccci_service_session_abort(session,41,-EPIPE)==-EPIPE);}
static struct device dev;static struct ccci_ccif ccif;
static unsigned submits,sends,aborts,faults,closed;
static u64 last_token;static int busy,backend_error,transport_error;
static bool expected_hs2,advance_send_time;static u8 request_copy[CCCI_FS_MESSAGE_MAX];
static size_t request_size;static u8 packet[CCCI_FS_MESSAGE_MAX],reply[CCCI_FS_MESSAGE_MAX];
static unsigned sent_payload;static u8 seen[10008],value[10000];
static int backend_submit(void *ctx,u64 gen,u64 token,enum ccci_service_kind kind,u32 slot,const void *p,size_t n){
 assert(ctx==&dev&&session->lock.held&&!spin_depth&&gen==41&&token);
 assert(kind==CCCI_SERVICE_FS&&slot==0);assert(n<=sizeof(request_copy));
 memcpy(request_copy,p,n);request_size=n;last_token=token;submits++;return backend_error;
}
static void backend_fault(void *ctx,u64 gen,int error){
 assert(ctx==&dev&&gen==41&&error<0&&!spin_depth&&session->lock.held);faults++;
}
static void backend_closing(void *ctx,u64 gen){
 assert(ctx==&dev&&gen==41&&!spin_depth&&!session->lock.held&&!session->accepting);
 assert(!session->work.work.pending);closed++;
 assert(ccci_service_session_reply(session,gen,last_token,CCCI_SERVICE_FS,0,reply,24)<0);
}
static const struct ccci_service_backend_ops backend={backend_submit,backend_fault,backend_closing};
static int ccci_ccif_service_send(struct ccci_ccif *c,const void *p,u32 n,bool hs2){
 assert(c==&ccif&&session->lock.held&&!spin_depth&&hs2==expected_hs2);sends++;
 if(busy){busy--;return -EBUSY;}
 if(transport_error)return transport_error;
 struct ccci_fs_fragment f;assert(!ccci_fs_fragment_decode(p,n,15,&f));
 assert(sent_payload+f.length<=sizeof(seen));memcpy(seen+sent_payload,f.data,f.length);
 sent_payload+=f.length;if(advance_send_time)now_ms+=60000;return 0;
}
static void ccci_ccif_abort(struct ccci_ccif *c,int error){assert(c==&ccif&&!spin_depth&&error<0);aborts++;}
static void run(void){
 struct work_struct *w=&session->work.work;assert(w->pending&&!w->running);
 w->pending=false;w->running=true;w->fn(w);w->running=false;
}
static size_t fs(u8 *p,u32 channel,unsigned n){
 struct ccci_fs_arg arg={value,n};int size=ccci_fs_encode(p+16,sizeof(packet)-16,0xffff1003U,&arg,1);
 assert(size>0);memset(p,0,16);put_unaligned_le32(16+size,p+4);put_unaligned_le32(channel,p+8);return 16+size;
}
static void create(bool arm){
 now_ms=100;submits=sends=aborts=faults=closed=0;last_token=0;backend_error=transport_error=busy=0;
 clock_hook=NULL;expected_hs2=advance_send_time=false;sent_payload=request_size=0;memset(seen,0,sizeof(seen));
 session=ccci_service_session_create(&dev,&ccif,&backend,&dev);assert(!IS_ERR(session));
 assert(!session->work.work.pending&&!submits&&!sends&&!aborts&&!faults&&!closed);
 assert(!ccci_service_session_offline(session));
 if(arm){assert(!ccci_service_session_arm(session,41));assert(ccci_service_session_offline(session)==-EBUSY);}
}
static void receive(void){
 size_t n=fs(packet,14,4);
 struct ccci_ccif_event e={.type=CCCI_CCIF_EVENT_RING,.queue=4,.size=n,.data=packet};
 assert(!ccci_service_session_receive(session,41,&e));memset(packet,0x5a,n);
}
static void stop_destroy(void){
 unsigned calls=sends+submits+aborts+closed;
 assert(ccci_service_session_stop(session,false)==-EBUSY);
 assert(sends+submits+aborts+closed==calls);
 assert(ccci_service_session_destroy(session)==-EBUSY);
 assert(!ccci_service_session_stop(session,true));assert(closed==1);
 assert(!session->work.work.pending&&!session->count&&!session->accepting);
 for(unsigned i=0;i<sizeof(session->queue);i++)assert(!((u8 *)session->queue)[i]);
 for(unsigned i=0;i<sizeof(session->request);i++)assert(!((u8 *)session->request)[i]);
 for(unsigned i=0;i<sizeof(session->reply);i++)assert(!((u8 *)session->reply)[i]);
 for(unsigned i=0;i<sizeof(session->tx);i++)assert(!session->tx[i]);
 assert(!ccci_service_session_offline(session));
 assert(!ccci_service_session_stop(session,true)&&closed==1);
 assert(ccci_service_session_arm(session,42)==-ESHUTDOWN);
 assert(!ccci_service_session_destroy(session));session=NULL;
}
static void sessions(void){
 struct ccci_service_session_status status;
 for(unsigned i=0;i<sizeof(value);i++)value[i]=i;
 create(false);assert(!ccci_service_session_destroy(session));
 create(true);receive();assert(!submits);run();assert(submits==1&&request_size==32);
 assert(get_unaligned_le32(request_copy+8)==14);
 size_t n=fs(reply,15,10000);u8 expected[10008];memcpy(expected,reply+20,sizeof(expected));
 assert(ccci_service_session_reply(session,40,last_token,CCCI_SERVICE_FS,0,reply,n)==-ESTALE);
 assert(!ccci_service_session_reply(session,41,last_token,CCCI_SERVICE_FS,0,reply,n));
 memset(reply,0x5a,n);busy=2;run();assert(sends==1&&!sent_payload&&session->work.work.delay==10);
 run();assert(sends==2&&!sent_payload);assert(!ccci_service_session_hs2(session,41));expected_hs2=true;
 run();assert(sends==5&&sent_payload==10008&&!memcmp(seen,expected,sizeof(expected)));
 ccci_service_session_status(session,&status);assert(status.armed&&status.accepting&&status.hs2_seen&&!status.error);
 stop_destroy();
 puts("PASS: actual async session copies RX/reply, ordered HS2, backend submit, retry work and full FS fragmentation");
 /* An accepted slow fragment must not allow the next fragment past deadline. */
 create(true);receive();run();n=fs(reply,15,10000);
 assert(!ccci_service_session_reply(session,41,last_token,CCCI_SERVICE_FS,0,reply,n));
 advance_send_time=true;run();assert(sends==1&&sent_payload==0xd80&&aborts==1&&faults==1);stop_destroy();
 /* An asynchronously closed queue must reject imminent backend callbacks. */
 create(true);n=fs(packet,14,4);
 assert(ccci_service_session_abort(session,41,-EPIPE)==-EPIPE);
 mutex_lock(&session->lock);
 assert(service_submit(session,41,1,CCCI_SERVICE_FS,0,packet,n)==-EPIPE&&!submits);
 mutex_unlock(&session->lock);
 run();assert(aborts==1&&faults==1);stop_destroy();
 /* A producer abort between the initial gate and final callback gate. */
 for(unsigned send_path=0;send_path<2;send_path++){
  create(true);n=fs(packet,send_path?15:14,4);clock_hook=abort_during_clock;
  mutex_lock(&session->lock);
  int ret=send_path?service_send(session,packet,n,false):
   service_submit(session,41,1,CCCI_SERVICE_FS,0,packet,n);
  mutex_unlock(&session->lock);
  assert(ret==-EPIPE&&!submits&&!sends);run();assert(aborts==1&&faults==1);stop_destroy();
 }
 create(true);receive();run();now_ms=60100;run();assert(aborts==1&&faults==1);
 ccci_service_session_status(session,&status);assert(status.error==-ETIMEDOUT&&!status.accepting);
 assert(ccci_service_session_abort(session,41,-EIO)==-ETIMEDOUT);stop_destroy();
 for(unsigned mode=0;mode<3;mode++){
  create(true);if(mode==0)backend_error=-EIO;receive();run();
  if(mode==1){assert(ccci_service_session_abort(session,41,-EPIPE)==-EPIPE);assert(!aborts);run();}
  if(mode==2){n=fs(reply,15,10000);assert(!ccci_service_session_reply(session,41,last_token,CCCI_SERVICE_FS,0,reply,n));transport_error=-EIO;run();}
  assert(aborts==1&&faults==1&&!session->accepting);unsigned previous=sends;
  assert(ccci_service_session_reply(session,41,last_token,CCCI_SERVICE_FS,0,reply,24)<0);
  assert(sends==previous);stop_destroy();
 }
 puts("PASS: deadlines, backend and transport faults abort CCIF asynchronously once; stopped-only private buffer erasure");
 create(true);for(unsigned i=0;i<SERVICE_SESSION_EVENTS;i++)assert(!ccci_service_session_hs2(session,41));
 assert(ccci_service_session_hs2(session,41)==-ENOSPC&&!aborts&&!faults&&!submits);
 run();assert(aborts==1&&faults==1&&!submits);stop_destroy();
 create(true);receive();run();n=fs(reply,15,4);
 assert(!ccci_service_session_reply(session,41,last_token+1,CCCI_SERVICE_FS,0,reply,n));run();
 assert(aborts==1&&faults==1&&!sends);stop_destroy();
 /* A request that expired while queued must not reach the backend. */
 create(true);receive();now_ms=60100;run();assert(!submits&&aborts==1&&faults==1);stop_destroy();
 create(true);receive();assert(!ccci_service_session_stop(session,true));
 assert(!submits&&!session->work.work.pending&&closed==1);assert(!ccci_service_session_destroy(session));
 fail_workqueue=true;session=ccci_service_session_create(&dev,&ccif,&backend,&dev);assert(IS_ERR(session));fail_workqueue=false;
 assert(IS_ERR(ccci_service_session_create(NULL,&ccif,&backend,&dev)));
 puts("PASS: queue overflow, stale reply token, stop-before-drain, allocation failure; no producer callback hardware access");
}
int main(void){sessions();return 0;}
'''


def main():
    with tempfile.TemporaryDirectory(prefix='op6893-session-') as directory:
        root = Path(directory)
        inc = root / 'linux'
        inc.mkdir()
        files = {
            'types.h': '#pragma once\n#include <stdint.h>\n#include <stdbool.h>\n'
                       '#include <stddef.h>\ntypedef uint8_t u8;typedef uint16_t u16;'
                       'typedef uint32_t u32;typedef uint64_t u64;\n',
            'errno.h': '#include <asm-generic/errno.h>\n',
            'string.h': '#pragma once\n#include <string.h>\n'
                        'static inline void memzero_explicit(void *p,size_t n){'
                        'volatile unsigned char *b=p;while(n--)*b++=0;}\n',
            'unaligned.h': '#pragma once\n#include <linux/types.h>\n'
                           'static inline u32 get_unaligned_le32(const void *p){'
                           'const u8 *b=p;return (u32)b[0]|(u32)b[1]<<8|(u32)b[2]<<16|(u32)b[3]<<24;}\n'
                           'static inline void put_unaligned_le32(u32 v,void *p){'
                           'u8 *b=p;for(unsigned i=0;i<4;i++)b[i]=v>>(8*i);}\n',
        }
        for name in ('err.h', 'ktime.h', 'mutex.h', 'slab.h', 'spinlock.h',
                     'vmalloc.h', 'workqueue.h'):
            files[name] = ''
        for name, data in files.items():
            (inc / name).write_text(data)
        (root / 'test.c').write_text(TEST)
        source = K / 'drivers/misc/mediatek/ccci'
        subprocess.run(['cc', '-O1', '-g', '-Wall', '-Wextra', '-Werror',
                        '-Wno-misleading-indentation', '-fsanitize=address,undefined',
                        '-fno-sanitize-recover=all', '-no-pie', '-I'+str(root),
                        '-I'+str(source), str(source/'ccci-fs-protocol.c'),
                        str(source/'ccci-rpc-protocol.c'), str(source/'ccci-service-router.c'),
                        str(root/'test.c'), '-o', str(root/'test')], check=True)
        subprocess.run([str(root/'test')], check=True)


if __name__ == '__main__':
    main()
