#!/usr/bin/env python3
# SPDX-License-Identifier: GPL-2.0-only
"""Actual queue/RX/drain integration with destructive ACKs and capacity faults."""
from pathlib import Path
import runpy
import ast
import subprocess
import tempfile

K = Path(__file__).resolve().parents[5]
D = K / 'drivers/misc/mediatek/ccci'
tx, rx, _ = runpy.run_path(str(Path(__file__).with_name('test_modem_scp.py')))['audited_fixture']()
# Reuse C scalar/unaligned definitions, without executing the other test harness.
tree = ast.parse(Path(__file__).with_name('test_modem_scp_drain.py').read_text())
preamble = next(ast.literal_eval(n.value) for n in tree.body
                if isinstance(n, ast.Assign) and any(isinstance(t, ast.Name) and t.id == 'preamble'
                                                     for t in n.targets))
preamble += r'''
static unsigned hweight32(u32 x) {return __builtin_popcount(x);}
static void memzero_explicit(void *p,size_t n) {memset(p,0,n);}
'''


def source(name):
    return '\n'.join(line for line in (D / name).read_text().splitlines()
                     if not line.startswith('#include'))


harness = r'''
static const u32 tx[]={@TX@},rt[]={@RX@};
static struct ccci_scp_layout layout;
static struct ccci_scp_queue queue;
static struct ccci_scp_event event;
static struct ccci_scp_rx_result result;
struct device_model {unsigned mbox,stage,reads,posts,acks,sequence;u32 known,pending;u8 wire[256];};
static struct device_model models[5];
static unsigned operations,fail_at,total_posts,total_acks;
static bool continuous;
static const struct ccci_scp_rx_ops *hardware[5];
static void *contexts[5];
static struct ccci_scp_drain drain;
static bool masked;
static unsigned masks,unmasks;
static u64 generation;
static int fails(void) {return ++operations==fail_at?-EIO:0;}
static int pending(void *context,u32 *bits) {
 struct device_model *m=context;m->stage=1;
 *bits=continuous?m->known:m->pending;
 for(unsigned i=0;i<256;i++)m->wire[i]=(u8)(i+m->mbox+m->sequence);
 return fails();
}
static int read_words(void *context,u32 offset,u32 words,void *buffer) {
 struct device_model *m=context;assert(m->stage==1 && offset+words<=64);m->reads++;
 if(fails())return -EIO;memcpy(buffer,m->wire+offset*4,words*4);return 0;
}
static int post(void *context) {
 struct device_model *m=context;assert(m->stage==1);
 struct ccci_scp_queue_port *p=&queue.ports[m->mbox];
 assert(p->reserved==hweight32(p->pending) && queue.count+p->reserved<=queue.capacity);
 m->posts++;total_posts++;m->stage=2;return fails();
}
static int ack(void *context,u32 bits) {
 struct device_model *m=context;assert(m->stage==2 && bits && !(bits&~m->known));
 assert(queue.ports[m->mbox].reserved==hweight32(bits));
 m->acks++;total_acks++;m->stage=3;m->pending&=~bits;
 memset(m->wire,0xed,sizeof(m->wire));return fails();
}
static void forbidden_delivery(void *context,const struct ccci_scp_pin *p,const void *b,size_t n,u64 g) {
 (void)context;(void)p;(void)b;(void)n;(void)g;assert(0);
}
static const struct ccci_scp_rx_ops hwops={pending,read_words,post,ack,forbidden_delivery};
static int set_masked(void *context,bool value) {assert(context==&drain);masked=value;if(value)masks++;else unmasks++;return 0;}
static int check(void *context,u64 gen) {assert(context==&drain && gen==generation && masked);return 0;}
static const struct ccci_scp_drain_ops drainops={set_masked,check};
static void setup(unsigned capacity) {
 assert(!ccci_scp_build_layout(tx,ARRAY_SIZE(tx),rt,ARRAY_SIZE(rt),5,&layout));
 operations=fail_at=total_posts=total_acks=0;continuous=false;generation=17;masks=unmasks=0;masked=true;
 for(unsigned i=0;i<5;i++) {
  models[i]=(struct device_model){.mbox=i};hardware[i]=&hwops;contexts[i]=&models[i];
  for(unsigned j=0;j<layout.rx_count;j++)if(layout.rx[j].mbox==i)models[i].known|=BIT(layout.rx[j].irq);
 }
 assert(!ccci_scp_queue_init(&queue,&layout,generation,capacity,hardware,contexts) && !operations);
}
static void scrubbed(void) {
 const u8 *p=(const u8 *)queue.events;
 for(unsigned i=0;i<sizeof(queue.events);i++)assert(!p[i]);
}
static void unavailable(void) {
 assert(queue.fault && !queue.count);scrubbed();
 for(unsigned i=0;i<5;i++)assert(queue.rx[i].fault && !queue.ports[i].reserved);
 unsigned n=operations;
 for(unsigned i=0;i<5;i++)assert(ccci_scp_rx_step(&queue.rx[i],&result)==-ESHUTDOWN);
 memset(&event,0xa5,sizeof(event));
 assert(ccci_scp_queue_pop(&queue,17,&event)==-ESHUTDOWN && operations==n);
 const u8 *p=(const u8 *)&event;for(unsigned i=0;i<sizeof(event);i++)assert(!p[i]);
}
static void verify(const struct ccci_scp_pin *pin,unsigned sequence) {
 assert(!ccci_scp_queue_pop(&queue,17,&event));
 assert(event.generation==17 && event.pin.channel==pin->channel && event.pin.response==pin->response);
 assert(event.pin.mbox==pin->mbox && event.pin.irq==pin->irq && event.bytes==pin->words*4);
 for(unsigned i=0;i<event.bytes;i++)assert(event.data[i]==(u8)(pin->offset*4+i+pin->mbox+sequence));
 for(unsigned i=event.bytes;i<sizeof(event.data);i++)assert(!event.data[i]);
}
int main(void) {
 setup(64);
 for(unsigned i=0;i<5;i++) {
  models[i].pending=models[i].known;
  assert(!ccci_scp_rx_step(&queue.rx[i],&result) && result.acknowledged==models[i].known);
 }
 assert(queue.count==layout.rx_count && layout.rx_count==17);
 for(unsigned i=0;i<layout.rx_count;i++)verify(&layout.rx[i],0);
 assert(!queue.count);scrubbed();
 assert(ccci_scp_queue_pop(&queue,17,&event)==-ENODATA);
 /* 1000 wraps exercise consumed-slot scrubbing and reused variable sizes. */
 for(unsigned n=0;n<1000;n++) {
  const struct ccci_scp_pin *p=&layout.rx[n%layout.rx_count];
  models[p->mbox].pending=BIT(p->irq);models[p->mbox].sequence=n;
  assert(!ccci_scp_rx_step(&queue.rx[p->mbox],&result));verify(p,n);scrubbed();
 }
 /* Whole pending batches either fit or have no completion/ACK side effects. */
 for(unsigned capacity=1;capacity<=64;capacity++)for(unsigned box=0;box<5;box++) {
  setup(capacity);models[box].pending=models[box].known;
  int ret=ccci_scp_rx_step(&queue.rx[box],&result);
  if(hweight32(models[box].known)>capacity) {
   assert(ret==-ENOSPC && !total_posts && !total_acks && models[box].pending==models[box].known);
   assert(result.post_attempted && !result.ack_attempted);unavailable();
  } else {
   assert(!ret && queue.count==hweight32(models[box].known));
   for(unsigned i=0;i<layout.rx_count;i++)if(layout.rx[i].mbox==box)verify(&layout.rx[i],0);
   scrubbed();
  }
 }
 /* Exact-full queues must reject the next event before completion or ACK. */
 for(unsigned capacity=1;capacity<=64;capacity++) {
  setup(capacity);const struct ccci_scp_pin *p=&layout.rx[0];
  for(unsigned n=0;n<capacity;n++) {
   models[0].pending=BIT(p->irq);models[0].sequence=n;
   assert(!ccci_scp_rx_step(&queue.rx[0],&result) && queue.count==n+1);
  }
  unsigned posts=total_posts,acks=total_acks;models[0].pending=BIT(p->irq);
  assert(ccci_scp_rx_step(&queue.rx[0],&result)==-ENOSPC);
  assert(posts==total_posts && acks==total_acks && models[0].pending==BIT(p->irq));unavailable();
 }
 /* Existing queued event + fewer free slots than an entire multi-pin batch. */
 setup(8);const struct ccci_scp_pin *first=&layout.rx[0];
 models[0].pending=BIT(first->irq);assert(!ccci_scp_rx_step(&queue.rx[0],&result));
 models[1].pending=models[1].known;unsigned posts=total_posts,acks=total_acks;
 assert(hweight32(models[1].known)>7);
 assert(ccci_scp_rx_step(&queue.rx[1],&result)==-ENOSPC && posts==total_posts && acks==total_acks);
 unavailable();
 /* Every hardware callback failure, including ACK that already destroys wire. */
 for(unsigned box=0;box<5;box++) {
  setup(64);models[box].pending=models[box].known;
  assert(!ccci_scp_rx_step(&queue.rx[box],&result));unsigned total=operations;
  for(unsigned bad=1;bad<=total;bad++) {
   setup(64);models[box].pending=models[box].known;fail_at=bad;
   assert(ccci_scp_rx_step(&queue.rx[box],&result)==-EIO && operations==bad);unavailable();
  }
  setup(64);models[box].pending=BIT(31);
  assert(ccci_scp_rx_step(&queue.rx[box],&result)==-EOPNOTSUPP && !total_posts && !total_acks);
  unavailable();
 }
 /* Integrate all five queue-backed RXs with the actual bounded drain. */
 setup(64);struct ccci_scp_rx *receivers[5];for(unsigned i=0;i<5;i++)receivers[i]=&queue.rx[i];
 assert(!ccci_scp_drain_init(&drain,&drainops,&drain));
 assert(!ccci_scp_drain_prepare(&drain,receivers,17,4));
 for(unsigned i=0;i<5;i++)models[i].pending=models[i].known;
 assert(!ccci_scp_drain_run(&drain,17) && !masked && queue.count==17 && unmasks==1);
 for(unsigned i=0;i<layout.rx_count;i++)verify(&layout.rx[i],0);
 continuous=true;assert(ccci_scp_drain_run(&drain,17)==-ENOSPC && masked);
 assert(drain.state==CCCI_SCP_DRAIN_FAULT);unavailable();
 setup(64);assert(ccci_scp_queue_pop(&queue,16,&event)==-ESTALE && !operations);
 ccci_scp_queue_invalidate(&queue);unavailable();ccci_scp_queue_invalidate(&queue);scrubbed();
 assert(ccci_scp_queue_pop(NULL,17,&event)==-EINVAL);
 assert(ccci_scp_queue_pop(&queue,17,NULL)==-EINVAL);
 ccci_scp_queue_invalidate(NULL);
 /* Every missing hardware callback in every mailbox rejects initialization. */
 for(unsigned box=0;box<5;box++)for(unsigned bad=0;bad<5;bad++) {
  setup(64);struct ccci_scp_rx_ops broken=hwops;hardware[box]=&broken;
  switch(bad){case 0:hardware[box]=NULL;break;case 1:broken.pending=NULL;break;
   case 2:broken.read_words=NULL;break;case 3:broken.post_capture=NULL;break;case 4:broken.ack=NULL;break;}
  assert(ccci_scp_queue_init(&queue,&layout,17,64,hardware,contexts)==-EINVAL && !operations);
  unavailable();
 }
 setup(64);struct ccci_scp_rx_ops no_deliver=hwops;no_deliver.deliver=NULL;
 for(unsigned i=0;i<5;i++)hardware[i]=&no_deliver;
 assert(!ccci_scp_queue_init(&queue,&layout,17,64,hardware,contexts));
 models[0].pending=models[0].known;assert(!ccci_scp_rx_step(&queue.rx[0],&result));
 for(unsigned i=0;i<layout.rx_count;i++)if(layout.rx[i].mbox==0)verify(&layout.rx[i],0);
 setup(64);layout.rx[2].words=0;
 assert(ccci_scp_queue_init(&queue,&layout,17,64,hardware,contexts)==-EINVAL);unavailable();
 setup(64);assert(ccci_scp_queue_init(&queue,&layout,17,0,hardware,contexts)==-EINVAL);unavailable();
 assert(ccci_scp_queue_init(&queue,&layout,17,65,hardware,contexts)==-EINVAL);
 assert(ccci_scp_queue_init(&queue,&layout,0,64,hardware,contexts)==-EINVAL);
 assert(ccci_scp_queue_init(&queue,NULL,17,64,hardware,contexts)==-EINVAL);
 assert(ccci_scp_queue_init(&queue,&layout,17,64,NULL,contexts)==-EINVAL);
 assert(ccci_scp_queue_init(&queue,&layout,17,64,hardware,NULL)==-EINVAL);
 assert(ccci_scp_queue_init(NULL,&layout,17,64,hardware,contexts)==-EINVAL);
 puts("PASS: actual queue/RX/drain integration, all 17 pins, 320 capacity/mailbox combinations, 1000 wraps, pre-ACK whole-batch reservation, every hardware failure, destructive ACKs, full scrubbing, stale generation and invalidation");
}
'''.replace('@TX@', ','.join(map(str, tx))).replace('@RX@', ','.join(map(str, rx)))
code = preamble + '\n'.join(source(n) for n in (
    'ccci-scp-protocol.h', 'ccci-scp-rx.h', 'ccci-scp-drain.h', 'ccci-scp-queue.h',
    'ccci-scp-protocol.c', 'ccci-scp-rx.c', 'ccci-scp-drain.c', 'ccci-scp-queue.c')) + harness
with tempfile.TemporaryDirectory(prefix='op6893-queue-') as directory:
    root = Path(directory)
    (root / 'test.c').write_text(code)
    subprocess.run(['cc', '-Wall', '-Wextra', '-Werror', '-Wno-misleading-indentation',
                    '-Wno-sign-compare', '-fsanitize=address,undefined',
                    '-fno-sanitize-recover=all', '-no-pie', str(root / 'test.c'),
                    '-o', str(root / 'test')], check=True)
    subprocess.run([str(root / 'test')], check=True)
