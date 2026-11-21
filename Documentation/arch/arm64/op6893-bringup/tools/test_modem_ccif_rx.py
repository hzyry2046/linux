#!/usr/bin/env python3
# SPDX-License-Identifier: GPL-2.0-only
"""Actual CCIF RX/protocol/ring C with deterministic IRQ, work and peer models.

The interleaving model checks lifecycle ordering, not Linux SMP/GIC timing.
No firmware, device memory or persistent modem data is used.
"""
from pathlib import Path
import subprocess
import tempfile

K = Path(__file__).resolve().parents[5]
SRC = K / 'drivers/misc/mediatek/ccci'

SHIM = r'''
#include <assert.h>
#include <errno.h>
#include <stdbool.h>
#include <stddef.h>
#include <stdint.h>
#include <stdio.h>
#include <stdlib.h>
#include <string.h>
#include <linux/types.h>
#include <linux/unaligned.h>
#define __iomem
#define GFP_KERNEL 0
#define BIT(n) (1U << (n))
#define container_of(p,t,m) ((t *)((char *)(p)-offsetof(t,m)))
#define ERR_PTR(n) ((void *)(intptr_t)(n))
#define IS_ERR(p) ((uintptr_t)(p) > (uintptr_t)-4096)
struct device {int unused;};
static void *allocations[4];
static unsigned allocations_count,allocation_calls,fail_allocation;
static void *devm_kmalloc(struct device *d,size_t n,int flags){
 (void)d;(void)flags;if(++allocation_calls==fail_allocation)return NULL;
 void *p=calloc(1,n);assert(p && allocations_count<4);
 allocations[allocations_count++]=p;return p;
}
#define devm_kzalloc devm_kmalloc
struct spinlock {bool held;};
typedef struct spinlock spinlock_t;
static void (*unlock_hook)(void);
#define spin_lock_init(g) ((g)->held=false)
#define spin_lock_irqsave(g,f) do{(f)=0;assert(!(g)->held);(g)->held=true;}while(0)
static void gate_unlock(spinlock_t *g){
 assert(g->held);g->held=false;if(unlock_hook){void (*h)(void)=unlock_hook;unlock_hook=NULL;h();}
}
#define spin_unlock_irqrestore(g,f) do{(void)(f);gate_unlock(g);}while(0)
struct work_struct {void (*fn)(struct work_struct *);bool pending,running;};
#define INIT_WORK(w,f) (*(w)=(struct work_struct){.fn=(f)})
#define system_dfl_wq NULL
static bool fail_queue;
static unsigned queue_calls;
static bool queue_work(void *wq,struct work_struct *w){
 (void)wq;queue_calls++;if(fail_queue || w->pending)return false;w->pending=true;return true;
}
static void run_work(struct work_struct *w){
 assert(w->pending && !w->running);w->pending=false;w->running=true;w->fn(w);w->running=false;
}
static int depths[2];
static unsigned disables,enables,syncs,cancels;
static void (*rearm_hook)(void);
static void (*sync_hook)(void);
static void disable_irq_nosync(int irq){
 unsigned i=irq-100;assert(i<2 && !depths[i]);depths[i]++;disables++;
}
static void enable_irq(int irq){unsigned i=irq-100;assert(i<2 && depths[i]==1);depths[i]--;enables++;if(i==1 && rearm_hook){unlock_hook=rearm_hook;rearm_hook=NULL;}}
static void synchronize_irq(int irq){
 assert(irq>=100 && irq<102 && depths[irq-100]==1);syncs++;
 if(sync_hook){void (*h)(void)=sync_hook;sync_hook=NULL;h();}
}
static void cancel_work_sync(struct work_struct *w){assert(!w->running);w->pending=false;cancels++;}
static u8 page[4096];
static unsigned reads,writes,ack_count,sram_reads;
static bool mutate_sram_on_ack;
static u32 acks[8],arrival;
static u32 readl(const void *p){
 size_t off=(const u8 *)p-page;assert(off+4<=sizeof(page) && !(off&3));reads++;if(off>=0x100 && off<0x1f0)sram_reads++;
 return get_unaligned_le32(p);
}
static void writel(u32 value,void *p){
 size_t off=(u8 *)p-page;assert(off==0x14 && ack_count<8);writes++;
 acks[ack_count++]=value;
 if(value&BIT(15)){assert(sram_reads==60);if(mutate_sram_on_ack)memset(page+0x100,0xff,240);}
 put_unaligned_le32(get_unaligned_le32(page+0x10)&~value,page+0x10);
 if(arrival){put_unaligned_le32(get_unaligned_le32(page+0x10)|arrival,page+0x10);arrival=0;}
}
#include "ccci-ccif-rx.c"
'''

TEST = r'''
static struct ccci_ccif_rx *rx;
static struct device dev;
static struct ccci_ccif_ring rings[16];
static u8 banks[16][2048];
static unsigned consumed[16],sram_events,notify_events,callback_calls;
static u32 notified,last_data;
static int callback_error;
static bool inject_irq,stop_in_callback;
static int bank_read(void *c,u32 o,u32 *v){assert(o+4<=2048);*v=get_unaligned_le32((u8 *)c+o);return 0;}
static int bank_write(void *c,u32 o,u32 v){assert(o+4<=2048);put_unaligned_le32(v,(u8 *)c+o);return 0;}
static int bank_from(void *c,u32 o,void *v,u32 n){assert(o+n<=2048);memcpy(v,(u8 *)c+o,n);return 0;}
static int bank_to(void *c,u32 o,const void *v,u32 n){assert(o+n<=2048);memcpy((u8 *)c+o,v,n);return 0;}
static int bank_zero(void *c,u32 o,u32 n){assert(o+n<=2048);memset((u8 *)c+o,0,n);return 0;}
static void bank_fence(void *c,bool publish){(void)c;(void)publish;}
static const struct ccci_ccif_ring_ops ops={bank_read,bank_write,bank_from,bank_to,bank_zero,bank_fence,NULL,NULL,NULL};
static void interrupt0(void){ccci_ccif_rx_interrupt(rx,100);}
static void late_irq(void){assert(!rx->active);interrupt0();}
static void hs1(u8 *p){
 memset(p,0,240);put_unaligned_le32(0,p+4);put_unaligned_le32(0xfffe0000,p+8);
 put_unaligned_le32(0x5555ffff,p+12);put_unaligned_le32(0x49434343,p+16);
 for(unsigned i=0;i<64;i++)p[20+i]=(i<<4)|(i%5);
 put_unaligned_le32(0x49434343,p+84);memset(p+88,0xa5,152);
}
static int consume(void *ctx,const struct ccci_ccif_event *e){
 assert(ctx==&dev && rx->active && !rx->gate.held && depths[0]==1 && depths[1]==1);
 callback_calls++;
 if(e->type==CCCI_CCIF_EVENT_SRAM){
  assert(ack_count && e->size==240 && e->header.channel==0);
  assert(get_unaligned_le32((const u8 *)e->data+16)==0x49434343);
  assert(ccci_ccif_control_decode(&e->header)==CCCI_CCIF_CONTROL_HS1);sram_events++;
 }else if(e->type==CCCI_CCIF_EVENT_NOTIFY){
  assert(e->notifications && !e->data && !e->size);notify_events++;notified|=e->notifications;
 }else{
  assert(e->queue<16 && e->size>=16 && e->header.data[1]==0x12345678);
  consumed[e->queue]++;last_data=e->header.data[0];
  assert(e->header.channel==e->queue*2 && e->header.sequence==(last_data&0x7fff));
 }
 if(inject_irq){inject_irq=false;unsigned before=queue_calls;interrupt0();assert(queue_calls==before);}
 if(stop_in_callback){/* Model the gate half of STOP; its wait completes after worker return. */
  stop_in_callback=false;rx->active=false;
 }
 return callback_error;
}
static void cleanup(void){
 if(rx && !IS_ERR(rx))ccci_ccif_rx_stop(rx);
 for(unsigned i=0;i<allocations_count;i++)free(allocations[i]);allocations_count=0;rx=NULL;
}
static void setup(void){
 cleanup();memset(page,0,sizeof(page));memset(banks,0,sizeof(banks));
 allocation_calls=fail_allocation=reads=writes=ack_count=sram_reads=arrival=0;
 mutate_sram_on_ack=false;
 disables=enables=syncs=cancels=queue_calls=0;depths[0]=depths[1]=1;
 fail_queue=inject_irq=stop_in_callback=false;callback_error=0;unlock_hook=sync_hook=rearm_hook=NULL;
 memset(consumed,0,sizeof(consumed));sram_events=notify_events=callback_calls=notified=last_data=0;
 for(unsigned i=0;i<16;i++){
  struct ccci_ccif_slot slot={.rx=(i==0 || i==1 || i==6 || i==8)?1024:0,.tx=0};
  slot.span=40+slot.rx;assert(!ccci_ccif_ring_init(&rings[i],&ops,banks[i],&slot,2048));
  assert(!ccci_ccif_ring_format(&rings[i]));
 }
 int irqs[]={100,101};rx=ccci_ccif_rx_create(&dev,page,rings,irqs);assert(!IS_ERR(rx));
 assert(!reads && !writes && !queue_calls && !enables);
}
/* Independent peer producer writes complete packets into RX, including wrapping. */
static void peer_bytes(unsigned q,u32 pos,const void *src,u32 size){
 for(u32 i=0;i<size;i++)banks[q][32+(pos+i)%1024]=((const u8 *)src)[i];
}
static void peer_packet(unsigned q,u32 value){
 u8 packet[32]={0};u32 write=get_unaligned_le32(banks[q]+12),read=get_unaligned_le32(banks[q]+8);
 assert((write+32)%1024!=read);
 put_unaligned_le32(0xaabbaabb,packet);put_unaligned_le32(16,packet+4);
 put_unaligned_le32(value,packet+8);put_unaligned_le32(0x12345678,packet+12);
 put_unaligned_le32(q*2|((value&0x7fff)<<16),packet+16);
 put_unaligned_le32(0xccddeeff,packet+24);put_unaligned_le32(0xccddeeff,packet+28);
 peer_bytes(q,write,packet,32);put_unaligned_le32((write+32)%1024,banks[q]+12);
}
static void start(void){assert(!ccci_ccif_rx_start(rx,consume,&dev));assert(rx->work.pending && !rx->armed);}
static void contained(int error){
 assert(ccci_ccif_rx_error(rx)==error && !rx->active && !rx->armed);
 assert(depths[0]==1 && depths[1]==1);
}
static void allocation_failures(void){
 for(unsigned n=1;n<=2;n++){
  setup();cleanup();allocation_calls=0;fail_allocation=n;
  int irqs[]={100,101};rx=ccci_ccif_rx_create(&dev,page,rings,irqs);
  assert(IS_ERR(rx) && (intptr_t)rx==-ENOMEM && !reads && !writes && !enables);
 }
}
static void protocol(void){
 u8 storage[242],features[64];u8 *p=storage+1;struct ccci_ccif_header h;
 hs1(p);assert(!ccci_ccif_header_decode(p,240,&h));assert(h.sequence==0x7ffe && h.assert_sequence);
 assert(!ccci_ccif_hs1_decode(p,240,features));assert(!memcmp(features,p+20,64));
 for(unsigned n=0;n<242;n++)if(n!=240)assert(ccci_ccif_hs1_decode(p,n,features)==-EMSGSIZE);
 for(unsigned off=0;off<88;off+=4){
  if(off!=4 && off!=8 && off!=12 && off!=16 && off!=84)continue;
  u32 old=get_unaligned_le32(p+off);put_unaligned_le32(old^1,p+off);
  if(off!=8){assert(ccci_ccif_hs1_decode(p,240,features)==-EBADMSG);for(unsigned i=0;i<64;i++)assert(!features[i]);}
  put_unaligned_le32(old,p+off);
 }
 for(u32 n=0;n<65536;n++){
  put_unaligned_le32(n|0xffff0000,p+8);assert(!ccci_ccif_header_decode(p,16,&h));
  assert(h.channel==n && h.sequence==0x7fff && h.assert_sequence);
  assert(ccci_ccif_control_decode(&h)==(n?CCCI_CCIF_CONTROL_OTHER:CCCI_CCIF_CONTROL_HS1));
 }
 hs1(p);put_unaligned_le32(0,p+12);assert(!ccci_ccif_header_decode(p,16,&h));
 assert(ccci_ccif_control_decode(&h)==CCCI_CCIF_CONTROL_HS2);
 const unsigned ids[]={4,5,6,8,0x12345678};
 const enum ccci_ccif_control kinds[]={CCCI_CCIF_CONTROL_EXCEPTION,CCCI_CCIF_CONTROL_VERSION_ERROR,
  CCCI_CCIF_CONTROL_EXCEPTION_OK,CCCI_CCIF_CONTROL_EXCEPTION_PASS,CCCI_CCIF_CONTROL_OTHER};
 for(unsigned i=0;i<5;i++){put_unaligned_le32(ids[i],p+4);assert(!ccci_ccif_header_decode(p,16,&h));assert(ccci_ccif_control_decode(&h)==kinds[i]);}
 assert(ccci_ccif_header_decode(NULL,16,&h)==-EINVAL && !h.channel);
 assert(ccci_ccif_header_decode(p,15,&h)==-EINVAL);
 assert(ccci_ccif_header_decode(p,16,NULL)==-EINVAL);
 assert(ccci_ccif_hs1_decode(NULL,240,features)==-EINVAL);
 assert(ccci_ccif_hs1_decode(p,240,NULL)==-EINVAL);
}
static void lifecycle(void){
 setup();assert(ccci_ccif_rx_start(rx,NULL,NULL)==-EINVAL && !rx->attempted);
 start();run_work(&rx->work);assert(rx->armed && !rx->scheduled && enables==2);
 unsigned before=reads;interrupt0();assert(reads==before && disables==2 && rx->work.pending);
 ccci_ccif_rx_interrupt(rx,101);assert(disables==2);
 run_work(&rx->work);assert(rx->armed && enables==4);
 sync_hook=late_irq;ccci_ccif_rx_stop(rx);assert(!rx->active && !rx->armed && !rx->work.pending);
 assert(depths[0]==1 && depths[1]==1 && syncs==2 && cancels==1 && !rx->consume);
 assert(!ccci_ccif_rx_error(rx) && ccci_ccif_rx_start(rx,consume,&dev)==-EALREADY);
 ccci_ccif_rx_stop(rx);assert(disables==4 && syncs==4);
 setup();start();ccci_ccif_rx_stop(rx);assert(!reads && !enables && !rx->work.pending);
 setup();interrupt0();contained(-EIO);assert(!reads && !writes && ccci_ccif_rx_start(rx,consume,&dev)==-EIO);
 setup();fail_queue=true;assert(ccci_ccif_rx_start(rx,consume,&dev)==-EIO);contained(-EIO);
 setup();start();run_work(&rx->work);fail_queue=true;interrupt0();contained(-EIO);
 setup();start();run_work(&rx->work);ccci_ccif_rx_interrupt(rx,999);contained(-EINVAL);
}
static void notifications(void){
 setup();hs1(page+0x100);put_unaligned_le32(BIT(15)|BIT(7)|BIT(0)|BIT(16)|BIT(21),page+0x10);
 peer_packet(0,7);mutate_sram_on_ack=true;start();inject_irq=true;run_work(&rx->work);
 assert(sram_events==1 && notify_events==1 && consumed[0]==1 && rx->armed);
 assert(ack_count==2 && acks[0]==(BIT(15)|BIT(7)|BIT(0)) && acks[1]==(BIT(16)|BIT(21)));
 assert(notified==(BIT(7)|BIT(16)|BIT(21)));
 setup();hs1(page+0x100);page[0x100+84]^=1;put_unaligned_le32(BIT(15),page+0x10);
 start();run_work(&rx->work);contained(-EBADMSG);assert(!writes && !callback_calls);
 setup();hs1(page+0x100);put_unaligned_le32(BIT(15),page+0x10);callback_error=-ENOSPC;
 start();run_work(&rx->work);contained(-ENOSPC);assert(writes==1 && sram_events==1);
 setup();hs1(page+0x100);put_unaligned_le32(BIT(15)|BIT(16),page+0x10);callback_error=-EIO;
 start();run_work(&rx->work);contained(-EIO);
 assert(notify_events==1 && !sram_events && ack_count==2 && sram_reads==60);
 setup();put_unaligned_le32(BIT(24),page+0x10);start();run_work(&rx->work);contained(-EPROTO);assert(!writes);
 setup();put_unaligned_le32(BIT(7),page+0x10);callback_error=-ENODATA;
 start();run_work(&rx->work);contained(-ENODATA);assert(ack_count==1);
 setup();put_unaligned_le32(BIT(0),page+0x10);arrival=BIT(1);start();run_work(&rx->work);
 assert(acks[0]==BIT(0) && get_unaligned_le32(page+0x10)==BIT(1) && rx->armed);
 interrupt0();run_work(&rx->work);assert(acks[1]==BIT(1) && !get_unaligned_le32(page+0x10));
}
static void packets(void){
 setup();for(unsigned i=0;i<20;i++){peer_packet(0,i);peer_packet(1,i+100);peer_packet(6,i+200);peer_packet(8,i+300);}
 start();inject_irq=true;run_work(&rx->work);
 assert(consumed[0]==8 && consumed[1]==8 && consumed[6]==8 && consumed[8]==8);
 assert(rx->work.pending && !rx->armed && !enables && queue_calls==2);
 run_work(&rx->work);assert(rx->work.pending && consumed[0]==16 && consumed[1]==16);
 run_work(&rx->work);assert(rx->armed && !rx->work.pending);
 for(unsigned i=0;i<16;i++)assert(consumed[i]==((i==0 || i==1 || i==6 || i==8)?20:0));
 setup();peer_packet(0,12);callback_error=-ENODATA;start();run_work(&rx->work);contained(-ENODATA);
 assert(consumed[0]==1 && get_unaligned_le32(banks[0]+8)==32 && last_data==12);
 assert(get_unaligned_le32(rx->packet)==12);/* Durable CPU copy on consumer fault. */
 setup();peer_packet(0,13);callback_error=1;start();run_work(&rx->work);contained(-EPROTO);
 setup();peer_packet(0,14);banks[0][32]^=1;start();run_work(&rx->work);contained(-EBADMSG);
 assert(!callback_calls && !get_unaligned_le32(banks[0]+8));
 setup();put_unaligned_le32(8,banks[0]+12);start();run_work(&rx->work);contained(-EAGAIN);
 setup();peer_packet(0,1);peer_packet(1,2);stop_in_callback=true;start();run_work(&rx->work);
 assert(consumed[0]==1 && !consumed[1] && !rx->armed);ccci_ccif_rx_stop(rx);
 setup();for(unsigned i=0;i<20;i++){peer_packet(0,i);peer_packet(1,i);}
 start();fail_queue=true;run_work(&rx->work);contained(-EIO);
 setup();start();/* A stale IRQ while the worker owns the queue must coalesce. */
 unlock_hook=interrupt0;run_work(&rx->work);
 assert(rx->armed && !rx->work.pending && queue_calls==1);
 setup();start();/* IRQ on another CPU just after the final rearm gate. */
 rearm_hook=interrupt0;run_work(&rx->work);
 assert(!rx->armed && rx->work.pending && queue_calls==2 && depths[0]==1 && depths[1]==1);
 run_work(&rx->work);assert(rx->armed && !rx->work.pending && !depths[0] && !depths[1]);
}
int main(void){
 allocation_failures();protocol();lifecycle();notifications();packets();cleanup();
 puts("PASS: actual CCIF header/HS1, IRQ/work/STOP and ring drain under ASan/UBSan");
 puts("      65536 channels, separate ACKs, SRAM-before-ACK, coalescing, fairness,");
 puts("      consumer and malformed packet faults, one-shot and late IRQ gates");
}
'''


def main():
    with tempfile.TemporaryDirectory(prefix='op6893-ccif-rx-') as tmp:
        root = Path(tmp)
        inc = root / 'linux'
        inc.mkdir()
        (inc / 'types.h').write_text('#pragma once\n#include <stdint.h>\n#include <stdbool.h>\n'
                                   'typedef uint8_t u8;typedef uint16_t u16;'
                                   'typedef uint32_t u32;typedef uint64_t u64;\n')
        (inc / 'unaligned.h').write_text('#pragma once\n#include <linux/types.h>\n'
            'static inline u32 get_unaligned_le32(const void *p){const u8 *b=p;'
            'return (u32)b[0]|(u32)b[1]<<8|(u32)b[2]<<16|(u32)b[3]<<24;}\n'
            'static inline u64 get_unaligned_le64(const void *p){return get_unaligned_le32(p)|'
            '(u64)get_unaligned_le32((const u8 *)p+4)<<32;}\n'
            'static inline void put_unaligned_le32(u32 v,void *p){u8 *b=p;'
            'for(unsigned i=0;i<4;i++)b[i]=v>>(i*8);}\n')
        (inc / 'limits.h').write_text('#include <stdint.h>\n#define U64_MAX UINT64_MAX\n')
        (inc / 'errno.h').write_text('#include <asm-generic/errno.h>\n')
        (inc / 'string.h').write_text('#include <string.h>\n')
        (inc / 'kernel.h').write_text('#define ALIGN(n,a) (((n)+(a)-1)&~((a)-1))\n'
                                     '#define min(a,b) ((a)<(b)?(a):(b))\n')
        for name in ('bitops.h', 'device.h', 'err.h', 'interrupt.h', 'io.h', 'slab.h',
                     'spinlock.h', 'workqueue.h'):
            (inc / name).write_text('/* Models supplied by the harness. */\n')
        (root / 'test.c').write_text(SHIM + TEST)
        subprocess.run(['cc', '-O1', '-g', '-Wall', '-Wextra', '-Werror',
                        '-Wno-misleading-indentation', '-fsanitize=address,undefined',
                        '-fno-sanitize-recover=all', '-no-pie', '-I'+str(root),
                        '-I'+str(SRC), '-I'+str(K/'include'), str(SRC/'ccci-ccif-ring.c'),
                        str(SRC/'ccci-ccif-protocol.c'), str(root/'test.c'),
                        '-o', str(root/'test')], check=True)
        subprocess.run([str(root/'test')], check=True)


if __name__ == '__main__':
    main()
