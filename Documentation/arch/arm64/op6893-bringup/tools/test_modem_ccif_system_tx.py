#!/usr/bin/env python3
# SPDX-License-Identifier: GPL-2.0-only
"""Compile the actual CCIF system sender and ring C under ASan/UBSan."""
from pathlib import Path
import runpy
import subprocess
import tempfile

K = Path(__file__).resolve().parents[5]
BASE = runpy.run_path(str(Path(__file__).with_name('test_modem_ccif.py')))
MODEL = r'''
#include <pthread.h>
#include <stdatomic.h>
#include <linux/bitops.h>
#define __iomem
#define READ_ONCE(x) (x)
#define WRITE_ONCE(x,v) ((x)=(v))
#include "ccci-ccif-rx.h"
struct regmap;
struct ccci_ccif_controller;
struct mutex { pthread_mutex_t lock; };
static void mutex_lock(struct mutex *m){assert(!pthread_mutex_lock(&m->lock));}
static void mutex_unlock(struct mutex *m){assert(!pthread_mutex_unlock(&m->lock));}
static unsigned ap_reads,ap_writes,aborts;
static int receive_error;
static u8 ap_registers[4096];
static u32 readl(const void *p){assert(p==ap_registers+4);ap_reads++;return get_unaligned_le32(p);}
static void writel(u32 value,void *p){
 assert((p==ap_registers+4 && value==1) || (p==ap_registers+12 && value==0));
 if(p==ap_registers+4){assert(ap_writes%2==0);assert(get_unaligned_le32(memory+40));}
 else assert(ap_writes%2==1);
 ap_writes++;put_unaligned_le32(value,p);
}
static void mb(void){atomic_thread_fence(memory_order_seq_cst);}
int ccci_ccif_rx_error(struct ccci_ccif_rx *rx){(void)rx;return receive_error;}
void ccci_ccif_rx_abort(struct ccci_ccif_rx *rx,int error){(void)rx;assert(error<0);aborts++;receive_error=error;}
'''
TEST = r'''
static void init_sender(struct ccci_ccif *c){
 memset(c,0,sizeof(*c));assert(!pthread_mutex_init(&c->tx_lock.lock,NULL));
 setup(&c->ring[0][0]);c->ap=ap_registers;
 memset(ap_registers,0,sizeof(ap_registers));ap_reads=ap_writes=aborts=0;receive_error=0;
}
static void destroy_sender(struct ccci_ccif *c){assert(!pthread_mutex_destroy(&c->tx_lock.lock));}
static int published_failure(void *c,u32 o,u32 v){
 int ret=wr(c,o,v);return ret?ret:(o==40?-EIO:0);
}
static const struct ccci_ccif_ring_ops published_failure_ops={rd,published_failure,from,to,zero,fence};
static void tx_tests(void){
 struct ccci_ccif c;unsigned steps;
 init_sender(&c);
 assert(ccci_ccif_system_send(NULL,0x119,0)==-EINVAL);
 assert(ccci_ccif_system_send(&c,0x120,0)==-EINVAL && !calls && !ap_reads);
 assert(ccci_ccif_system_send(&c,0x119,0)==-ESHUTDOWN && !calls && !ap_reads);
 ccif_tx_gate(&c,true);receive_error=-EPROTO;
 assert(ccci_ccif_system_send(&c,0x119,0)==-EPROTO && !calls && !ap_reads);
 receive_error=0;put_unaligned_le32(1,ap_registers+4);
 assert(ccci_ccif_system_send(&c,0x119,0)==-EBUSY && !calls && !ap_writes && !c.tx_sequence);
 put_unaligned_le32(0,ap_registers+4);
 assert(!ccci_ccif_system_send(&c,0x119,0x11223344));steps=calls;
 assert(get_unaligned_le32(memory+40)==32 && c.tx_sequence==1 && ap_writes==2);
 assert(get_unaligned_le32(memory+312)==0xffffffff);
 assert(get_unaligned_le32(memory+316)==0x119);
 assert(get_unaligned_le32(memory+320)==0x80000003);
 assert(get_unaligned_le32(memory+324)==0x11223344);
 /* BUSY carries an outstanding notification: retry never duplicates the packet. */
 unsigned old_calls=calls;
 assert(ccci_ccif_system_send(&c,0x11b,0)==-EBUSY && calls==old_calls && c.tx_sequence==1);
 put_unaligned_le32(0,ap_registers+4);
 assert(!ccci_ccif_system_send(&c,0x11b,0));
 assert(get_unaligned_le32(memory+348)==0x11b);
 assert(get_unaligned_le32(memory+352)==0x80010003);
 ccif_tx_gate(&c,false);old_calls=calls;unsigned old_reads=ap_reads;
 assert(ccci_ccif_system_send(&c,0x119,0)==-ESHUTDOWN && calls==old_calls && ap_reads==old_reads);
 destroy_sender(&c);
 /* Every ring callback failure, including final producer publication, poisons TX. */
 for(unsigned i=1;i<=steps;i++){
  init_sender(&c);ccif_tx_gate(&c,true);fail=i;
  assert(ccci_ccif_system_send(&c,0x119,0)==-EACCES && calls==i);
  assert(c.tx_error==-EACCES && !c.tx_active && !c.tx_sequence && aborts==1 && !ap_writes);
  old_calls=calls;old_reads=ap_reads;
  assert(ccci_ccif_system_send(&c,0x119,0)==-EACCES && calls==old_calls && ap_reads==old_reads);
  destroy_sender(&c);
 }
 init_sender(&c);ccif_tx_gate(&c,true);c.ring[0][0].ops=&published_failure_ops;
 assert(ccci_ccif_system_send(&c,0x119,0)==-EIO && get_unaligned_le32(memory+40)==32);
 assert(!ap_writes && c.tx_error==-EIO && !c.tx_active && aborts==1);
 old_calls=calls;old_reads=ap_reads;
 assert(ccci_ccif_system_send(&c,0x119,0)==-EIO && calls==old_calls && ap_reads==old_reads);
 ccif_tx_gate(&c,true);assert(!c.tx_active);destroy_sender(&c);
 init_sender(&c);ccif_tx_gate(&c,true);
 put_unaligned_le32(32,memory+36); /* Only 31 bytes available; requires strict gap. */
 assert(ccci_ccif_system_send(&c,0x119,0)==-ENOSPC && !c.tx_error && c.tx_active && !ap_writes);
 put_unaligned_le32(0,memory+36);clear();
 c.tx_sequence=0x7fff;
 assert(!ccci_ccif_system_send(&c,0x119,0) && !c.tx_sequence);
 assert(get_unaligned_le32(memory+320)==0xffff0003);
 destroy_sender(&c);
 init_sender(&c);ccif_tx_gate(&c,true);ccci_ccif_abort(&c,-ETIMEDOUT);
 assert(c.tx_error==-ETIMEDOUT && !c.tx_active && aborts==1 && !ap_reads && !calls);
 ccci_ccif_abort(&c,-EPROTO);
 assert(c.tx_error==-ETIMEDOUT && receive_error==-ETIMEDOUT && aborts==2);
 assert(ccci_ccif_system_send(&c,0x119,0)==-ETIMEDOUT && !ap_reads && !calls);
 destroy_sender(&c);
 init_sender(&c);ccci_ccif_abort(&c,1);assert(c.tx_error==-EIO);destroy_sender(&c);
 ccci_ccif_abort(NULL,-EIO);
 puts("PASS: actual system q0 TX: exact wire header, sequence/assert/wrap, BUSY/full");
 puts("      no publication, all ring failure positions poison owner, STOP rejects I/O");
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
static const struct ccci_ccif_ring_ops blocking_ops={rd,wr,from,to,zero,blocking_fence};
static void *sender_thread(void *p){assert(!ccci_ccif_system_send(p,0x119,0));return NULL;}
static void *stop_thread(void *p){
 assert(!pthread_mutex_lock(&pause_lock));stop_attempted=true;pthread_cond_broadcast(&pause_cond);
 assert(!pthread_mutex_unlock(&pause_lock));ccif_tx_gate(p,false);
 assert(!pthread_mutex_lock(&pause_lock));stop_done=true;
 assert(!pthread_mutex_unlock(&pause_lock));return NULL;
}
static void stop_race(void){
 struct ccci_ccif c;pthread_t sender,stopper;
 init_sender(&c);ccif_tx_gate(&c,true);c.ring[0][0].ops=&blocking_ops;
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
 assert(ccci_ccif_system_send(&c,0x11b,0)==-ESHUTDOWN && ap_reads==old_reads && calls==old_calls);
 destroy_sender(&c);puts("PASS: actual sender/STOP gate concurrency drains publication before closing");
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
    stop = owner[owner.index('int ccci_ccif_stop('):owner.index('ssize_t ccci_ccif_status(')]
    assert stop.index('ccif_tx_gate(ccif, false)') < stop.index('ccci_ccif_control_quiesce')
    with tempfile.TemporaryDirectory(prefix='op6893-system-tx-') as directory:
        root = Path(directory)
        (root / 'linux').mkdir()
        # Reuse the established shim declarations without running its driver tests twice.
        base_source = Path(__file__).with_name('test_modem_ccif.py').read_text()
        files_section = base_source[base_source.index('        files = {'):
                                   base_source.index('        for name, content in files.items():')]
        scope = {}
        exec(files_section.strip(), scope)
        for name, content in scope['files'].items():
            (root / 'linux' / name).write_text(content)
        harness = BASE['HARNESS'].replace('int main(void){', 'static void baseline_main(void){')
        (root / 'test.c').write_text(harness + MODEL + structures + sender + TEST)
        subprocess.run(['cc', '-O1', '-g', '-Wall', '-Wextra', '-Werror',
                        '-Wno-misleading-indentation', '-fsanitize=address,undefined',
                        '-fno-sanitize-recover=all', '-no-pie', '-pthread',
                        '-I' + str(root), '-I' + str(K / 'include'), '-I' + str(source),
                        str(source / 'ccci-ccif-ring.c'), str(source / 'ccci-ccif-hw.c'),
                        str(root / 'test.c'), '-o', str(root / 'test')], check=True)
        subprocess.run([str(root / 'test')], check=True)


if __name__ == '__main__':
    main()
