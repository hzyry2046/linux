#!/usr/bin/env python3
# SPDX-License-Identifier: GPL-2.0-only
"""Exercise actual FS/RPC CCIF sender, ring faults and STOP concurrency."""
from pathlib import Path
import runpy
import subprocess
import tempfile

K = Path(__file__).resolve().parents[5]
BASE = runpy.run_path(str(Path(__file__).with_name('test_modem_ccif_system_tx.py')))
MODEL = BASE['MODEL']
a = MODEL.index('static void writel(')
b = MODEL.index('static void mb(', a)
MODEL = MODEL[:a] + r'''
/* Header model: the AT/MUX transmit contract from ccci-ccif.h. */
#define CCCI_CCIF_HEADER 16
#define CCCI_CCIF_AT_CHANNEL 12
#define CCCI_CCIF_AT_QUEUE 5
#define CCCI_CCIF_AT_MAX 3456
#define CCCI_CCIF_NET_CHANNEL 22
#define CCCI_CCIF_NET_QUEUE 0
#define CCCI_CCIF_NET_MIN 14
#define CCCI_CCIF_NET_MAX (1500 + 128)
#define CCCI_CCIF_NET_INDEX_MAX 20
static unsigned expected_queue, allocations, frees;
static bool alloc_fail;
#define GFP_KERNEL 0
static void *kmemdup(const void *p,size_t n,int flags){
 (void)flags;allocations++;if(alloc_fail)return NULL;void *v=malloc(n);assert(v);memcpy(v,p,n);return v;
}
static void kfree_sensitive(void *p){assert(p);frees++;free(p);}
static void *kmalloc(size_t n,int flags){
 (void)flags;allocations++;if(alloc_fail)return NULL;void *v=malloc(n);assert(v);return v;
}
/* The sender reports deferred/failed transmit through printk; keep it silent. */
__attribute__((unused)) static int test_printk(const char *fmt,...){(void)fmt;return 0;}
#define pr_info(...) test_printk(__VA_ARGS__)
#define pr_err(...) test_printk(__VA_ARGS__)
#define pr_warn(...) test_printk(__VA_ARGS__)
#define pr_info_ratelimited(...) test_printk(__VA_ARGS__)
static void writel(u32 value,void *p){
 assert((p==ap_registers+4 && value==BIT(expected_queue)) ||
        (p==ap_registers+12 && value==expected_queue));
 if(p==ap_registers+4){assert(ap_writes%2==0);assert(get_unaligned_le32(memory+40));}
 else assert(ap_writes%2==1);
 ap_writes++;put_unaligned_le32(value,p);
}
''' + MODEL[b:]
TEST = r'''
static u8 packet[20+0xd80], original[sizeof(packet)];
static void init_sender(struct ccci_ccif *c,unsigned queue){
 memset(c,0,sizeof(*c));assert(!pthread_mutex_init(&c->tx_lock.lock,NULL));
 setup(&c->ring[0][queue]);c->ap=ap_registers;expected_queue=queue;
 memset(ap_registers,0,sizeof(ap_registers));ap_reads=ap_writes=aborts=0;receive_error=0;
 allocations=frees=0;alloc_fail=false;
 memset(packet,0,sizeof(packet));
 put_unaligned_le32(0x13579bdf,packet);put_unaligned_le32(40,packet+4);
 put_unaligned_le32(0x56780000|(queue==4?15:33),packet+8);
 put_unaligned_le32(queue==4?4:2,packet+12);put_unaligned_le32(0xffff400f,packet+16);
 for(unsigned i=20;i<40;i++)packet[i]=i^0x5a;
 memcpy(original,packet,sizeof(packet));ccif_tx_gate(c,true);
}
static void destroy_sender(struct ccci_ccif *c){
 assert(allocations==frees+(alloc_fail?1:0));assert(!pthread_mutex_destroy(&c->tx_lock.lock));
}
static int published_failure(void *c,u32 o,u32 v){
 int ret=wr(c,o,v);return ret?ret:(o==40?-EIO:0);
}
static const struct ccci_ccif_ring_ops published_failure_ops={rd,published_failure,from,to,zero,fence,NULL,NULL,NULL};
static void tx_tests(void){
 struct ccci_ccif c;unsigned steps[2];
 for(unsigned index=0;index<2;index++){
  unsigned queue=index?1:4;init_sender(&c,queue);
  assert(!ccci_ccif_service_send(&c,packet,40,false));steps[index]=calls;
  assert(!memcmp(packet,original,sizeof(packet)) && ap_writes==2);
  assert(c.service_sequence[index]==1 && !c.service_sequence[!index]);
  assert(get_unaligned_le32(memory+312)==0x13579bdf && get_unaligned_le32(memory+316)==40);
  assert(get_unaligned_le32(memory+320)==(0x80000000|(index?33:15)));
  assert(!memcmp(memory+324,original+12,28));
  unsigned old_calls=calls,old_reads=ap_reads;
  assert(ccci_ccif_service_send(&c,packet,40,true)==-EBUSY && calls==old_calls);
  assert(ap_reads==old_reads+1 && c.service_sequence[index]==1);
  put_unaligned_le32(0,ap_registers+4);
  assert(!ccci_ccif_service_send(&c,packet,40,true));
  assert(get_unaligned_le32(memory+376)==(0x10000|(index?33:15)));
  ccif_tx_gate(&c,false);old_calls=calls;old_reads=ap_reads;
  assert(ccci_ccif_service_send(&c,packet,40,true)==-ESHUTDOWN);
  assert(calls==old_calls && ap_reads==old_reads);destroy_sender(&c);
  for(unsigned i=1;i<=steps[index];i++){
   init_sender(&c,queue);fail=i;
   assert(ccci_ccif_service_send(&c,packet,40,true)==-EACCES && calls==i);
   assert(c.tx_error==-EACCES && !c.tx_active && !c.service_sequence[index] && aborts==1 && !ap_writes);
   old_calls=calls;old_reads=ap_reads;
   assert(ccci_ccif_service_send(&c,packet,40,true)==-EACCES);
   assert(calls==old_calls && ap_reads==old_reads);destroy_sender(&c);
  }
  init_sender(&c,queue);c.ring[0][queue].ops=&published_failure_ops;
  assert(ccci_ccif_service_send(&c,packet,40,true)==-EIO && get_unaligned_le32(memory+40)==56);
  assert(!ap_writes && c.tx_error==-EIO && !c.tx_active && aborts==1);
  ccif_tx_gate(&c,true);assert(!c.tx_active);destroy_sender(&c);
  init_sender(&c,queue);put_unaligned_le32(56,memory+36);
  assert(ccci_ccif_service_send(&c,packet,40,true)==-ENOSPC);
  assert(c.tx_active && !c.tx_error && !ap_writes && !c.service_sequence[index]);destroy_sender(&c);
  init_sender(&c,queue);c.service_sequence[index]=0x7fff;
  assert(!ccci_ccif_service_send(&c,packet,40,true) && !c.service_sequence[index]);
  assert(get_unaligned_le32(memory+320)==(0x7fff0000|(index?33:15)));destroy_sender(&c);
 }
 init_sender(&c,4);alloc_fail=true;
 assert(ccci_ccif_service_send(&c,packet,40,true)==-ENOMEM && !calls && !ap_reads);destroy_sender(&c);
 init_sender(&c,4);receive_error=-EPROTO;
 assert(ccci_ccif_service_send(&c,packet,40,true)==-EPROTO && !calls && !ap_reads);destroy_sender(&c);
 init_sender(&c,4);
 assert(ccci_ccif_service_send(NULL,packet,40,true)==-EINVAL);
 assert(ccci_ccif_service_send(&c,NULL,40,true)==-EINVAL);
 assert(ccci_ccif_service_send(&c,packet,23,true)==-EINVAL);
 assert(ccci_ccif_service_send(&c,packet,sizeof(packet)+1,true)==-EINVAL);
 put_unaligned_le32(7,packet+8);assert(ccci_ccif_service_send(&c,packet,40,true)==-EOPNOTSUPP);
 put_unaligned_le32(15,packet+8);put_unaligned_le32(5,packet+12);
 assert(ccci_ccif_service_send(&c,packet,40,true)==-ERANGE);
 put_unaligned_le32(33,packet+8);put_unaligned_le32(3,packet+12);
 assert(ccci_ccif_service_send(&c,packet,40,true)==-ERANGE);
 put_unaligned_le32(2,packet+12);put_unaligned_le32(2049,packet+4);
 assert(ccci_ccif_service_send(&c,packet,2049,true)==-ERANGE);
 assert(!calls && !ap_reads && !allocations);destroy_sender(&c);
 /* Short final FS fragments and the full per-fragment payload limit. */
 init_sender(&c,4);put_unaligned_le32(21,packet+4);
 assert(!ccci_ccif_service_send(&c,packet,21,true));
 assert(get_unaligned_le32(memory+308)==21 && get_unaligned_le32(memory+316)==21);
 destroy_sender(&c);
 init_sender(&c,1);put_unaligned_le32(21,packet+4);
 assert(ccci_ccif_service_send(&c,packet,21,true)==-ERANGE && !calls && !ap_reads);
 destroy_sender(&c);
 for(unsigned queue=1;queue<=4;queue+=3){
  init_sender(&c,queue);
  struct ccci_ccif_slot large={16,256,4096,4392};
  assert(!ccci_ccif_ring_init(&c.ring[0][queue],&ops,NULL,&large,sizeof(memory)));
  assert(!ccci_ccif_ring_format(&c.ring[0][queue]));clear();
  unsigned size=queue==4?sizeof(packet):2048;
  put_unaligned_le32(size,packet+4);
  for(unsigned i=20;i<size;i++)packet[i]=i^0xa5;
  assert(!ccci_ccif_service_send(&c,packet,size,true));
  assert(get_unaligned_le32(memory+308)==size);
  assert(!memcmp(memory+324,packet+12,size-12));
  destroy_sender(&c);
 }
 puts("PASS: actual FS/RPC sender exact payload, queues, phase/sequence/wrap, all callback faults");
}
static pthread_mutex_t pause_lock=PTHREAD_MUTEX_INITIALIZER;
static pthread_cond_t pause_cond=PTHREAD_COND_INITIALIZER;
static bool entered,release_sender,stop_attempted,stop_done;
static void blocking_fence(void *c,bool publish){
 fence(c,publish);if(!publish)return;
 assert(!pthread_mutex_lock(&pause_lock));entered=true;pthread_cond_broadcast(&pause_cond);
 while(!release_sender)pthread_cond_wait(&pause_cond,&pause_lock);
 assert(!pthread_mutex_unlock(&pause_lock));
}
static const struct ccci_ccif_ring_ops blocking_ops={rd,wr,from,to,zero,blocking_fence,NULL,NULL,NULL};
static void *sender_thread(void *p){assert(!ccci_ccif_service_send(p,packet,40,true));return NULL;}
static void *stop_thread(void *p){
 assert(!pthread_mutex_lock(&pause_lock));stop_attempted=true;pthread_cond_broadcast(&pause_cond);
 assert(!pthread_mutex_unlock(&pause_lock));ccif_tx_gate(p,false);
 assert(!pthread_mutex_lock(&pause_lock));stop_done=true;
 assert(!pthread_mutex_unlock(&pause_lock));return NULL;
}
static void stop_race(void){
 struct ccci_ccif c;pthread_t sender,stopper;
 init_sender(&c,4);c.ring[0][4].ops=&blocking_ops;
 assert(!pthread_create(&sender,NULL,sender_thread,&c));
 assert(!pthread_mutex_lock(&pause_lock));
 while(!entered)pthread_cond_wait(&pause_cond,&pause_lock);
 assert(!pthread_create(&stopper,NULL,stop_thread,&c));
 while(!stop_attempted)pthread_cond_wait(&pause_cond,&pause_lock);
 assert(!stop_done && !ap_writes);release_sender=true;pthread_cond_broadcast(&pause_cond);
 assert(!pthread_mutex_unlock(&pause_lock));
 assert(!pthread_join(sender,NULL) && !pthread_join(stopper,NULL));
 assert(stop_done && !c.tx_active && ap_writes==2);
 unsigned old_reads=ap_reads,old_calls=calls;
 assert(ccci_ccif_service_send(&c,packet,40,true)==-ESHUTDOWN && ap_reads==old_reads && calls==old_calls);
 destroy_sender(&c);puts("PASS: actual service sender/STOP concurrency drains before gate close");
 /* AT/MUX: the header is built here, on channel 12 queue 5, payload verbatim. */
 {
  static const u8 stream[]="\xf9\x03\x3f\x01\x1c\xf9";
  struct ccci_ccif c;
  init_sender(&c,CCCI_CCIF_AT_QUEUE);
  assert(ccci_ccif_at_send(&c,NULL,sizeof(stream),true)==-EINVAL);
  assert(ccci_ccif_at_send(&c,stream,0,true)==-EINVAL);
  assert(ccci_ccif_at_send(&c,stream,CCCI_CCIF_AT_MAX+1,true)==-EINVAL);
  assert(!ccci_ccif_at_send(&c,stream,sizeof(stream),true));
  assert(ap_writes==2);
  const u8 *sent=NULL;
  for(size_t i=0;i+sizeof(stream)+CCCI_CCIF_HEADER<=sizeof(memory);i++)
   if(!memcmp(memory+i,stream,sizeof(stream))){sent=memory+i-CCCI_CCIF_HEADER;break;}
  assert(sent);
  assert(!get_unaligned_le32(sent));
  assert(get_unaligned_le32(sent+4)==CCCI_CCIF_HEADER+sizeof(stream));
  assert((get_unaligned_le32(sent+8)&0xffff)==CCCI_CCIF_AT_CHANNEL);
  assert(!get_unaligned_le32(sent+12));
  destroy_sender(&c);
  puts("PASS: actual AT/MUX sender: header built here, channel 12 queue 5, payload verbatim");
 }
 /* CCMNI: index in data[0], total length in data[1], channel 22, MD's queue. */
 {
  static u8 frame[64];
  struct ccci_ccif c;
  init_sender(&c,CCCI_CCIF_NET_QUEUE);
  for(unsigned i=0;i<sizeof(frame);i++)frame[i]=(u8)(i*7+1);
  assert(ccci_ccif_net_send(&c,0,0,NULL,20)==-EINVAL);
  assert(ccci_ccif_net_send(&c,0,0,frame,CCCI_CCIF_NET_MIN-1)==-EINVAL);
  assert(ccci_ccif_net_send(&c,0,0,frame,CCCI_CCIF_NET_MAX+1)==-EINVAL);
  assert(ccci_ccif_net_send(&c,CCCI_CCIF_NET_INDEX_MAX+1,0,frame,20)==-EINVAL);
  assert(ccci_ccif_net_send(&c,0,CCCI_CCIF_QUEUES,frame,20)==-EINVAL);
  assert(!ccci_ccif_net_send(&c,3,CCCI_CCIF_NET_QUEUE,frame,sizeof(frame)));
  const u8 *sent=NULL;
  for(size_t i=0;i+sizeof(frame)+CCCI_CCIF_HEADER<=sizeof(memory);i++)
   if(!memcmp(memory+i,frame,sizeof(frame))){sent=memory+i-CCCI_CCIF_HEADER;break;}
  assert(sent);
  assert(get_unaligned_le32(sent)==3);
  assert(get_unaligned_le32(sent+4)==CCCI_CCIF_HEADER+sizeof(frame));
  assert((get_unaligned_le32(sent+8)&0xffff)==CCCI_CCIF_NET_CHANNEL);
  assert(!get_unaligned_le32(sent+12));
  destroy_sender(&c);
  /* A remapped uplink must reach the doorbell with that queue number. */
  init_sender(&c,3);
  assert(!ccci_ccif_net_send(&c,0,3,frame,sizeof(frame)));
  destroy_sender(&c);
  puts("PASS: actual CCMNI sender: index and total length in the header, channel 22, MD queue");
 }
}
int main(void){baseline_main();tx_tests();stop_race();}
'''


def main():
    source = K / 'drivers/misc/mediatek/ccci'
    owner = (source / 'ccci-ccif.c').read_text()
    structures = owner[owner.index('struct ccci_ccif_bank {'):
                       owner.index('static int ccif_bank_read(')]
    sender = owner[owner.index('static void ccif_tx_gate('):
                   owner.index('static bool ccci_ccif_faulted(')]
    transmit = owner[owner.index('static int ccif_transmit('):
                     owner.index('int ccci_ccif_service_send(')]
    service = owner[owner.index('int ccci_ccif_service_send('):
                    owner.index('ssize_t ccci_ccif_handshake_status(')]
    with tempfile.TemporaryDirectory(prefix='op6893-service-tx-') as directory:
        root = Path(directory)
        (root / 'linux').mkdir()
        base_source = Path(__file__).with_name('test_modem_ccif.py').read_text()
        section = base_source[base_source.index('        files = {'):
                              base_source.index('        for name, content in files.items():')]
        scope = {}
        exec(section.strip(), scope)
        for name, content in scope['files'].items():
            (root / 'linux' / name).write_text(content)
        harness = BASE['BASE']['HARNESS'].replace('int main(void){', 'static void baseline_main(void){')
        harness = harness.replace('static u8 memory[2048];', 'static u8 memory[8192];')
        (root / 'test.c').write_text(harness + MODEL + structures + sender + transmit + service + TEST)
        subprocess.run(['cc', '-O1', '-g', '-Wall', '-Wextra', '-Werror',
                        '-Wno-misleading-indentation', '-fsanitize=address,undefined',
                        '-fno-sanitize-recover=all', '-no-pie', '-pthread',
                        '-I' + str(root), '-I' + str(K / 'include'), '-I' + str(source),
                        str(source / 'ccci-ccif-ring.c'), str(source / 'ccci-ccif-hw.c'),
                        str(root / 'test.c'), '-o', str(root / 'test')], check=True)
        subprocess.run([str(root / 'test')], check=True)


if __name__ == '__main__':
    main()
