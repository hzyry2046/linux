#!/usr/bin/env python3
# SPDX-License-Identifier: GPL-2.0-only
"""Actual receive/MMIO/queue/drain with deterministic IRQ/work/devres models.

This checks state transitions and operation ordering, not Linux SMP or GIC timing.
"""
from pathlib import Path
import subprocess
import tempfile

base = Path(__file__).with_name('test_modem_scp_mmio.py')
namespace = {'__file__': str(base)}
# Reuse the synthetic device I/O and the audited board layout, without its main.
exec(compile(base.read_text().split("harness = r" + chr(39)*3)[0], str(base), 'exec'), namespace)
preamble = namespace['preamble']
preamble = preamble.replace('static void *allocation;',
                           'static void *allocation, *allocations[2]; static unsigned allocations_count;')
preamble = preamble.replace('&& !allocation', '&& allocations_count<2')
preamble = preamble.replace('assert(allocation);return allocation;',
                           'assert(allocation);allocations[allocations_count++]=allocation;return allocation;')
preamble += r'''
#include <stddef.h>
#define IRQF_NO_AUTOEN 0x80000
#define IRQ_DISABLE_UNLAZY 1
static bool unlazy[5],hardware_masked[5];
#define IRQ_HANDLED 1
#define IRQCHIP_STATE_MASKED 1
#define container_of(p,t,m) ((t *)((char *)(p)-offsetof(t,m)))
typedef int irqreturn_t;
struct mutex {bool held;};
static struct mutex owner;
static void mutex_init(struct mutex *m){m->held=false;}
static void mutex_lock(struct mutex *m){assert(!m->held);m->held=true;}
static void mutex_unlock(struct mutex *m){assert(m->held);m->held=false;}
typedef struct {bool held;} raw_spinlock_t;
#define raw_spin_lock_init(g) ((g)->held=false)
#define raw_spin_lock_irqsave(g,f) do {(f)=0;assert(!(g)->held);(g)->held=true;}while(0)
static void (*unlock_hook)(void);
static void unlock(raw_spinlock_t *g){assert(g->held);g->held=false;if(unlock_hook){void (*h)(void)=unlock_hook;unlock_hook=NULL;h();}}
#define raw_spin_unlock_irqrestore(g,f) do {(void)(f);unlock(g);}while(0)
struct work_struct {void (*fn)(struct work_struct *);bool pending,running;};
#define INIT_WORK(w,f) (*(w)=(struct work_struct){.fn=(f)})
#define system_dfl_wq NULL
static bool fail_queue;
static bool queue_work(void *wq,struct work_struct *w){
 if(fail_queue || w->pending)return false;w->pending=true;return true;
}
static void run_work(struct work_struct *w){assert(w->pending && !w->running);w->pending=false;w->running=true;w->fn(w);w->running=false;}
static int depths[5],resolve_failure,request_failure,spec_failure;
static unsigned requested_irqs,syncs,cancels;
static bool action_failure;
static irqreturn_t (*handlers[5])(int,void *);
static void *handler_data[5];
static void (*release_action)(void *);
static void *release_data;
static void (*sync_hook)(void);
static int ccci_scp_irq_validate_specs(struct platform_device *p){assert(p==&pdev);return spec_failure;}
static int ccci_scp_irq_resolve(struct platform_device *p,u32 b){assert(p==&pdev && b<5);return resolve_failure==(int)b?-EPROBE_DEFER:100+b;}
static int devm_request_irq(struct device *d,int n,irqreturn_t (*fn)(int,void *),unsigned f,const char *name,void *data){
 unsigned b=n-100;assert(d==&pdev.dev && b<5 && f==IRQF_NO_AUTOEN);
 if(request_failure==(int)b)return -EBUSY;
 assert(!depths[b]);depths[b]=1;hardware_masked[b]=true;handlers[b]=fn;handler_data[b]=data;requested_irqs++;return 0;
}
static void irq_set_status_flags(int n,unsigned f){assert(f==IRQ_DISABLE_UNLAZY);unlazy[n-100]=true;}
static void irq_clear_status_flags(int n,unsigned f){assert(f==IRQ_DISABLE_UNLAZY);unlazy[n-100]=false;}
static void disable_irq_nosync(int n){unsigned b=n-100;assert(b<5 && !depths[b]);depths[b]++;if(unlazy[b])hardware_masked[b]=true;}
static void enable_irq(int n){unsigned b=n-100;assert(b<5 && depths[b]==1);depths[b]--;hardware_masked[b]=false;}
static void synchronize_irq(int n){assert(!owner.held && n>=100 && n<105);syncs++;if(sync_hook){void (*h)(void)=sync_hook;sync_hook=NULL;h();}}
static void cancel_work_sync(struct work_struct *w){assert(!owner.held && !w->running);cancels++;w->pending=false;}
static int devm_add_action_or_reset(struct device *d,void (*fn)(void *),void *data){
 assert(d==&pdev.dev);if(action_failure){fn(data);return -ENOMEM;}release_action=fn;release_data=data;return 0;
}
static int irq_get_irqchip_state(int n,int state,bool *v){assert(state==IRQCHIP_STATE_MASKED);*v=hardware_masked[n-100];return 0;}
'''
harness = r'''
static const u32 tx[]={@TX@},rt[]={@RX@};
static struct ccci_scp_layout layout;
static struct ccci_scp_mmio *mmio;
static struct ccci_scp_receive *receive;
static u64 reset_generation;
static int prerequisite(void *ctx,u64 gen){
 assert(ctx==&reset_generation && gen==reset_generation && owner.held);
 if(++checks==fail_check)return -EIO;
 for(unsigned b=0;b<5;b++){
  u32 pending=get_unaligned_le32(pages[b+1]+0x10c);expected_words[b]=0;
  for(unsigned j=0;j<layout.rx_count;j++)if(layout.rx[j].mbox==b && (pending&BIT(layout.rx[j].irq)))expected_words[b]+=layout.rx[j].words;
 }
 return 0;
}
static void trigger(unsigned b){assert(b<requested_irqs);unsigned r=reads,w=writes,c=checks;assert(handlers[b](100+b,handler_data[b])==IRQ_HANDLED);assert(reads==r && writes==w && checks==c);}
static void late_irq(void){trigger(0);run_work(&receive->work);}
static void reset_model(void){
 if(release_action){release_action(release_data);release_action=NULL;}
 for(unsigned i=0;i<allocations_count;i++)free(allocations[i]);allocations_count=0;allocation=NULL;
 mmio=NULL;receive=NULL;owner=(struct mutex){0};
 memset(pages,0,sizeof(pages));memset(claimed,0,sizeof(claimed));node=(struct device_node){0};
 for(unsigned i=0;i<6;i++){u64 base=i?0x107fb000+(i-1)*4096:0x10724000;resources[i]=(struct resource){base,base+4095,IORESOURCE_MEM};}
 missing=bad_map=resolve_failure=request_failure=-1;spec_failure=0;nomem=fail_queue=action_failure=new_arrival=continuous=false;
 lookups=maps=reads=writes=barriers=checks=fail_check=requested_irqs=syncs=cancels=0;store_outstanding=false;
 memset(unlazy,0,sizeof(unlazy));memset(hardware_masked,0,sizeof(hardware_masked));memset(depths,0,sizeof(depths));memset(stage,0,sizeof(stage));memset(copied,0,sizeof(copied));memset(known,0,sizeof(known));
 assert(!ccci_scp_build_layout(tx,ARRAY_SIZE(tx),rt,ARRAY_SIZE(rt),5,&layout));
 for(unsigned j=0;j<layout.rx_count;j++)known[layout.rx[j].mbox]|=BIT(layout.rx[j].irq);
 reset_generation=17;assert(!ccci_scp_mmio_reserve(&pdev,&mmio));
}
static int reserve(void){return ccci_scp_receive_reserve(&pdev,&owner,mmio,prerequisite,&reset_generation,&receive);}
static void setup(void){reset_model();assert(!reserve());assert(requested_irqs==5 && !checks && !reads && !writes);for(unsigned b=0;b<5;b++)assert(depths[b]==1 && hardware_masked[b]);}
static void messages(void){for(unsigned b=0;b<5;b++){for(unsigned i=0;i<256;i++)pages[b+1][i]=(u8)(i+b+7);put_unaligned_le32(known[b],pages[b+1]+0x10c);}}
static void contained(void){assert(receive->fault && !receive->armed && receive->queue.fault && !receive->queue.count && mmio->fault);for(unsigned b=0;b<5;b++)assert(depths[b]==1 && hardware_masked[b]);}
static void start(unsigned budget){assert(!ccci_scp_receive_start(receive,&layout,reset_generation,budget));assert(receive->work.pending);}
/* Inject at final unmask gate unlock while work still runs. */
static void irq_after_unmask(void){if(!depths[0])trigger(0);else unlock_hook=irq_after_unmask;}
static unsigned consumer_events,consumer_errors,consumer_fail;
static int consumer(void *context,const struct ccci_scp_event *event,int error){
 assert(context==&consumer_events && owner.held);
 if(error){assert(!event);consumer_errors++;return error;}
 assert(event && event->generation==17);consumer_events++;
 return consumer_events==consumer_fail?-EPROTO:0;
}
int main(void){
 struct ccci_scp_event event;char status[4096];
 setup();assert(ccci_scp_receive_status(receive,status)>0 && strstr(status,"requested=5 gic_masked=5 armed=0"));
 assert(ccci_scp_receive_reserve(&pdev,&owner,mmio,prerequisite,NULL,NULL)==-EINVAL);
 assert(ccci_scp_receive_start(NULL,&layout,17,4)==-EINVAL);
 /* Constructor partial failures leave every claimed line masked and quiesced. */
 for(unsigned i=0;i<5;i++)for(unsigned type=0;type<2;type++){
  reset_model();if(type)request_failure=i;else resolve_failure=i;
  assert(reserve()==(type?-EBUSY:-EPROBE_DEFER) && !receive);
  assert(requested_irqs==i && syncs==i && cancels==1);
  for(unsigned b=0;b<i;b++)assert(depths[b]==1 && hardware_masked[b]);
 }
 reset_model();spec_failure=-EINVAL;assert(reserve()==-EINVAL && !requested_irqs);
 reset_model();nomem=true;assert(reserve()==-ENOMEM && !requested_irqs);
 reset_model();action_failure=true;assert(reserve()==-ENOMEM && syncs==5 && cancels==1);
 /* Persistent consumer drains every destination in the RX worker. */
 setup();consumer_events=consumer_errors=consumer_fail=0;
 assert(!ccci_scp_receive_consumer(receive,consumer,&consumer_events));
 messages();start(4);run_work(&receive->work);
 assert(consumer_events==17 && !consumer_errors && !receive->queue.count);
 assert(ccci_scp_receive_pop(receive,17,&event)==-EBUSY);
 assert(ccci_scp_receive_consumer(receive,NULL,NULL)==-EBUSY);
 ccci_scp_receive_stop(receive);
 assert(!ccci_scp_receive_consumer(receive,NULL,NULL));
 setup();consumer_events=consumer_errors=0;consumer_fail=3;
 assert(!ccci_scp_receive_consumer(receive,consumer,&consumer_events));
 messages();start(4);run_work(&receive->work);contained();
 assert(consumer_events==3 && consumer_errors==1 && receive->error==-EPROTO);
 /* Unexpected pre-start IRQ forces STOP, never starts a generation implicitly. */
 setup();trigger(0);assert(ccci_scp_receive_start(receive,&layout,17,4)==-EBUSY);run_work(&receive->work);contained();assert(!reads && !checks);
 ccci_scp_receive_stop(receive);start(4);run_work(&receive->work);assert(!receive->fault);
 /* Initial full-board snapshot and empty sweep, wrong-generation pop harmless. */
 setup();messages();start(4);run_work(&receive->work);assert(!receive->fault && receive->queue.count==17 && writes==10 && barriers==10);
 for(unsigned b=0;b<5;b++)assert(!depths[b]);
 assert(ccci_scp_receive_pop(receive,16,&event)==-ESTALE && !receive->fault);
 for(unsigned n=0;n<17;n++){assert(!ccci_scp_receive_pop(receive,17,&event));assert(event.generation==17 && event.bytes==event.pin.words*4);for(unsigned j=0;j<event.bytes;j++)assert(event.data[j]==(u8)(event.pin.offset*4+j+event.pin.mbox+7));}
 assert(ccci_scp_receive_pop(receive,17,&event)==-ENODATA);
 /* Coalesced IRQs preserve token and a single owned disable depth. */
 trigger(0);u64 token=receive->queued_generation;for(unsigned b=0;b<5;b++)trigger(b);
 assert(receive->queued_generation==token && receive->work.pending);run_work(&receive->work);assert(!receive->fault);
 /* Requeue during the running work's final unmask; no lost notification. */
 trigger(0);unlock_hook=irq_after_unmask;run_work(&receive->work);assert(!unlock_hook && receive->work.pending && receive->queued);
 run_work(&receive->work);assert(!receive->fault && !receive->work.pending);
 /* STOP closes before synchronizing; late IRQ cannot queue, no owner-held wait. */
 trigger(0);sync_hook=late_irq;ccci_scp_receive_stop(receive);
 assert(!receive->fault && !receive->error && !receive->work.pending && receive->quiesced && !receive->generation && syncs==5 && cancels==1);
 for(unsigned b=0;b<5;b++)assert(depths[b]==1 && hardware_masked[b]);
 assert(ccci_scp_receive_start(receive,&layout,17,4)==-ESTALE);
 reset_generation=18;start(4);run_work(&receive->work);assert(!receive->fault);
 release_action(release_data);release_action=NULL;assert(receive->terminal);
 assert(ccci_scp_receive_start(receive,&layout,19,4)==-EBUSY);
 /* Stale queued token faults without touching registers. */
 setup();start(4);unsigned before=checks;receive->queued_generation=16;run_work(&receive->work);contained();assert(!reads && !writes && checks==before);
 /* Per-operation prerequisite failures: scrub both backends, keep IRQs masked. */
 setup();messages();start(4);run_work(&receive->work);unsigned total=checks;
 for(unsigned f=1;f<=total;f++){setup();messages();fail_check=f;int ret=ccci_scp_receive_start(receive,&layout,17,4);if(ret)assert(ret==-EIO && f==1);else run_work(&receive->work);contained();assert(checks==f && !store_outstanding);unsigned r=reads,w=writes;trigger(0);run_work(&receive->work);assert(reads==r && writes==w);}
 setup();start(4);run_work(&receive->work);fail_check=checks+1;assert(ccci_scp_receive_pop(receive,17,&event)==-EIO);contained();
 /* Unsupported bits, CPU queue exhaustion and bounded busy drain. */
 setup();put_unaligned_le32(BIT(31),pages[1]+0x10c);start(4);run_work(&receive->work);contained();assert(!writes);
 setup();messages();start(1);run_work(&receive->work);contained();assert(receive->error==-EOVERFLOW);
 setup();messages();continuous=true;start(32);run_work(&receive->work);contained();assert(receive->error==-ENOSPC);
 /* Scheduling mismatch has no implicit retry; STOP required before next gen. */
 setup();fail_queue=true;assert(ccci_scp_receive_start(receive,&layout,17,4)==-EIO);contained();
 assert(ccci_scp_receive_start(receive,&layout,18,4)==-EBUSY);
 fail_queue=false;ccci_scp_receive_stop(receive);reset_generation=18;start(4);run_work(&receive->work);
 assert(!receive->fault);reset_model();for(unsigned i=0;i<allocations_count;i++)free(allocations[i]);
 puts("PASS: actual receive/MMIO/queue/drain; NO_AUTOEN, constructor failures, IRQ coalescing/requeue, exact event snapshots, STOP barriers, monotonic generations, stale tokens, prerequisite/overflow/budget/scheduling faults and terminal teardown");
}
'''.replace('@TX@', ','.join(map(str, namespace['tx']))).replace('@RX@', ','.join(map(str, namespace['rx'])))
code = preamble + '\n'.join(namespace['source'](n) for n in (
    'ccci-scp-protocol.h', 'ccci-scp-rx.h', 'ccci-scp-drain.h', 'ccci-scp-queue.h',
    'ccci-scp-mmio.h', 'ccci-scp-receive.h', 'ccci-scp-protocol.c', 'ccci-scp-rx.c',
    'ccci-scp-drain.c', 'ccci-scp-queue.c', 'ccci-scp-mmio.c', 'ccci-scp-receive.c')) + harness
with tempfile.TemporaryDirectory(prefix='op6893-receive-') as directory:
    root = Path(directory)
    (root / 'test.c').write_text(code)
    subprocess.run(['cc', '-Wall', '-Wextra', '-Werror', '-Wno-unused-parameter',
                    '-Wno-misleading-indentation', '-Wno-sign-compare',
                    '-fsanitize=address,undefined', '-fno-sanitize-recover=all',
                    '-no-pie', str(root / 'test.c'), '-o', str(root / 'test')], check=True)
    subprocess.run([str(root / 'test')], check=True)
