#!/usr/bin/env python3
# SPDX-License-Identifier: GPL-2.0-only
"""Actual NO_AUTOEN IRQ owner with synthetic kernel/devres scheduling APIs."""
from pathlib import Path
import argparse
import subprocess
import tempfile

K = Path(__file__).resolve().parents[5]
D = K / 'drivers/misc/mediatek/ccci'
code = r'''
#include <assert.h>
#include <errno.h>
#include <stdbool.h>
#include <stddef.h>
#include <stdint.h>
#include <stdio.h>
#include <stdarg.h>
#include <stdlib.h>
#include <string.h>
#include <sys/types.h>
typedef uint32_t u32;typedef uint64_t u64;
#define CCCI_SCP_MAX_MBOXES 5
#define BIT(n) (1U<<(n))
#define GFP_KERNEL 0
#define IRQF_NO_AUTOEN 0x80000
#define IRQ_TYPE_LEVEL_HIGH 4
#define IRQCHIP_STATE_MASKED 2
#define EPROBE_DEFER 517
#define container_of(p,t,m) ((t *)((char *)(p)-offsetof(t,m)))
typedef int irqreturn_t;
#define IRQ_HANDLED 1
struct mutex {bool locked;};
typedef struct {bool locked;} raw_spinlock_t;
#define raw_spin_lock_init(p) ((p)->locked=false)
#define raw_spin_lock_irqsave(p,f) do {assert(!(p)->locked);(p)->locked=true;(f)=0;} while(0)
#define raw_spin_unlock_irqrestore(p,f) do {assert((p)->locked);(p)->locked=false;(void)(f);} while(0)
struct work_struct {void (*fn)(struct work_struct *);bool pending;};
#define INIT_WORK(p,f) do {(p)->fn=f;(p)->pending=false;} while(0)
struct device_node {bool controller;};
struct device {struct device_node *of_node;};
struct platform_device {struct device dev;};
struct of_phandle_args {struct device_node *np;unsigned args_count,args[3];};
struct irq_chip {void *irq_bus_lock,*irq_bus_sync_unlock;};
struct irq_data {unsigned hwirq;};
struct ccci_scp_queue {bool fault;unsigned char payload[64];};
static struct device_node controller,node;
static struct platform_device pdev={.dev={.of_node=&node}};
static struct mutex owner;
static struct irq_chip chip;
static struct irq_data irqdata;
static unsigned requested,lookups,parsed,puts_count,syncs,cancels,queued,invalidations;
static unsigned disables[5],depth[5],state_queries;
static irqreturn_t (*handlers[5])(int,void *);
static void *handler_data[5],*allocation,*stop_data;
static void (*stop_action)(void *);
static bool nomem,action_fail,inject_closing,gic_masks[5],compatible,available;
static int spec_bad,spec_kind,map_bad,request_bad,duplicate_bad,trigger_bad,data_bad,bus_bad,state_bad;
static int system_dfl_wq;
static void mutex_lock(struct mutex *m) {assert(!m->locked);m->locked=true;}
static void mutex_unlock(struct mutex *m) {assert(m->locked);m->locked=false;}
static void ccci_scp_queue_invalidate(struct ccci_scp_queue *q) {q->fault=true;memset(q->payload,0,sizeof(q->payload));invalidations++;}
static void *devm_kzalloc(struct device *d,size_t size,int flags) {
 assert(d==&pdev.dev && flags==GFP_KERNEL && !allocation);
 if(nomem)return NULL;allocation=calloc(1,size);assert(allocation);return allocation;
}
static int of_property_match_string(struct device_node *n,const char *property,const char *name) {
 assert(n==&node && !strcmp(property,"interrupt-names") && !strncmp(name,"mbox",4));
 unsigned i=name[4]-'0';assert(i<5);return (spec_bad==(int)i && spec_kind==0)?-ENOENT:(int)i;
}
static int of_irq_parse_one(struct device_node *n,int i,struct of_phandle_args *out) {
 assert(n==&node && i>=0 && i<5);parsed++;
 if(spec_bad==i && spec_kind==1)return -EINVAL;
 *out=(struct of_phandle_args){&controller,3,{0,436+i,4}};
 if(spec_bad==i) switch(spec_kind) {case 2:out->args_count=2;break;case 3:out->args[0]=1;break;
 case 4:out->args[1]++;break;case 5:out->args[2]=1;break;}
 return 0;
}
static bool of_device_is_compatible(struct device_node *n,const char *s) {assert(n==&controller && !strcmp(s,"arm,gic-v3"));return compatible;}
static bool of_device_is_available(struct device_node *n) {assert(n==&controller);return available;}
static void of_node_put(struct device_node *n) {assert(n==&controller);puts_count++;}
static int platform_get_irq_byname(struct platform_device *p,const char *name) {
 assert(p==&pdev && !strncmp(name,"mbox",4));unsigned i=name[4]-'0';assert(i<5);lookups++;
 if(map_bad==(int)i)return -EPROBE_DEFER;
 if(duplicate_bad==(int)i)return 100;return 100+i;
}
static unsigned irq_get_trigger_type(int n) {return trigger_bad==n-100?1:4;}
static struct irq_data *irq_get_irq_data(int n) {
 if(data_bad==n-100)return NULL;irqdata.hwirq=468+n-100;
 if(data_bad==n-100+10)irqdata.hwirq++;return &irqdata;
}
static unsigned irqd_to_hwirq(struct irq_data *d) {return d->hwirq;}
static struct irq_chip *irq_data_get_irq_chip(struct irq_data *d) {
 unsigned i=d->hwirq-468;chip=(struct irq_chip){0};
 if(bus_bad==(int)i)chip.irq_bus_lock=&chip;
 if(bus_bad==(int)i+10)chip.irq_bus_sync_unlock=&chip;return &chip;
}
static int devm_request_irq(struct device *d,int n,irqreturn_t (*fn)(int,void *),unsigned flags,const char *name,void *context) {
 assert(d==&pdev.dev && flags==IRQF_NO_AUTOEN && !strcmp(name,"op6893-scp-mbox"));
 unsigned i=n-100;assert(i==requested && i<5);
 if(request_bad==(int)i)return -EBUSY;
 handlers[i]=fn;handler_data[i]=context;requested++;depth[i]=1;gic_masks[i]=true;return 0;
}
static void disable_irq_nosync(int n) {
 unsigned i=n-100;assert(i<requested);disables[i]++;depth[i]++;gic_masks[i]=true;
}
static bool queue_work(int wq,struct work_struct *work) {
 assert(wq==system_dfl_wq);queued++;bool old=work->pending;work->pending=true;return !old;
}
static void synchronize_irq(int n) {
 assert(!owner.locked && n>=100 && n<100+(int)requested);syncs++;
 if(inject_closing)assert(handlers[n-100](n,handler_data[n-100])==IRQ_HANDLED);
}
static bool cancel_work_sync(struct work_struct *work) {
 assert(!owner.locked && syncs==requested);cancels++;bool old=work->pending;work->pending=false;return old;
}
static int devm_add_action_or_reset(struct device *d,void (*fn)(void *),void *arg) {
 assert(d==&pdev.dev);if(action_fail){fn(arg);return -ENOMEM;}stop_action=fn;stop_data=arg;return 0;
}
static int irq_get_irqchip_state(int n,int which,bool *out) {
 assert(n>=100 && n<100+(int)requested && which==IRQCHIP_STATE_MASKED);state_queries++;
 if(state_bad==n-100)return -EIO;*out=gic_masks[n-100];return 0;
}
static int sysfs_emit(char *buf,const char *fmt,...) {
 va_list args;va_start(args,fmt);int n=vsnprintf(buf,4096,fmt,args);va_end(args);return n;
}
'''
code += '\n'.join(line for line in (D / 'ccci-scp-irq.c').read_text().splitlines()
                  if not line.startswith('#include'))
code += r'''
static void setup(void) {
 free(allocation);allocation=NULL;stop_action=NULL;stop_data=NULL;
 owner=(struct mutex){0};requested=lookups=parsed=puts_count=syncs=cancels=queued=invalidations=state_queries=0;
 memset(disables,0,sizeof(disables));memset(depth,0,sizeof(depth));memset(gic_masks,0,sizeof(gic_masks));
 nomem=action_fail=inject_closing=false;compatible=available=true;
 spec_bad=map_bad=request_bad=duplicate_bad=trigger_bad=data_bad=bus_bad=state_bad=-1;spec_kind=0;
}
static void stopped(struct ccci_scp_irq *irq) {
 assert(irq->closing && irq->queue.fault && !irq->fault_work.pending && syncs==requested && cancels==1);
 for(unsigned i=0;i<requested;i++)assert(disables[i]==1 && depth[i]==2 && gic_masks[i]);
}
int main(void) {
 struct ccci_scp_irq *irq;char buf[4096];setup();
 assert(!ccci_scp_irq_reserve(&pdev,&owner,&irq));
 assert(irq && requested==5 && parsed==5 && puts_count==5 && !queued && !syncs && irq->queue.fault);
 for(unsigned i=0;i<5;i++)assert(!disables[i] && depth[i]==1);
 assert(ccci_scp_irq_status(irq,buf)>0 && strstr(buf,"requested=5 gic_masked=5") && strstr(buf,"unexpected=0 work_runs=0"));
 assert(ccci_scp_irq_status(NULL,buf)==-EOPNOTSUPP);
 gic_masks[2]=false;assert(ccci_scp_irq_status(irq,buf)>0 && strstr(buf,"gic_masked=4"));gic_masks[2]=true;
 state_bad=3;assert(ccci_scp_irq_status(irq,buf)==-EIO);state_bad=-1;
 assert(handlers[2](102,handler_data[2])==IRQ_HANDLED);
 assert(handlers[4](104,handler_data[4])==IRQ_HANDLED && irq->unexpected==2 && queued==2);
 for(unsigned i=0;i<5;i++)assert(disables[i]==1 && depth[i]==2);
 assert(irq->fault_work.pending);irq->fault_work.pending=false;irq->fault_work.fn(&irq->fault_work);
 assert(irq->work_runs==1 && !owner.locked);
 assert(ccci_scp_irq_status(irq,buf)>0 && strstr(buf,"unexpected=2 work_runs=1"));
 /* Cancel a queued worker and inject all five late hard handlers after closing. */
 assert(handlers[0](100,handler_data[0])==IRQ_HANDLED);unsigned before=queued;
 inject_closing=true;stop_action(stop_data);stopped(irq);assert(queued==before);
 /* Every partial map/request/trigger/data/chip failure stops before probe unwind. */
 for(unsigned i=0;i<5;i++)for(unsigned bad=0;bad<7;bad++) {
  setup();switch(bad){case 0:map_bad=i;break;case 1:request_bad=i;break;case 2:trigger_bad=i;break;
   case 3:data_bad=i;break;case 4:data_bad=i+10;break;case 5:bus_bad=i;break;case 6:bus_bad=i+10;break;}
  assert(ccci_scp_irq_reserve(&pdev,&owner,&irq)<0 && !irq && requested==i);
  stopped(allocation);assert(!queued && !owner.locked);
 }
 setup();duplicate_bad=3;assert(ccci_scp_irq_reserve(&pdev,&owner,&irq)==-EINVAL && requested==3);stopped(allocation);
 for(unsigned i=0;i<5;i++)for(unsigned bad=0;bad<6;bad++) {
  setup();spec_bad=i;spec_kind=bad;
  assert(ccci_scp_irq_reserve(&pdev,&owner,&irq)<0 && !irq && !lookups && !requested && !syncs);
 }
 setup();compatible=false;assert(ccci_scp_irq_reserve(&pdev,&owner,&irq)==-EINVAL && !requested);
 setup();available=false;assert(ccci_scp_irq_reserve(&pdev,&owner,&irq)==-EINVAL && !requested);
 setup();nomem=true;assert(ccci_scp_irq_reserve(&pdev,&owner,&irq)==-ENOMEM && !irq);
 setup();action_fail=true;assert(ccci_scp_irq_reserve(&pdev,&owner,&irq)==-ENOMEM && !irq && requested==5);stopped(allocation);
 setup();assert(ccci_scp_irq_reserve(&pdev,&owner,NULL)==-EINVAL);
 assert(ccci_scp_irq_reserve(NULL,&owner,&irq)==-EINVAL && !irq);
 assert(ccci_scp_irq_reserve(&pdev,NULL,&irq)==-EINVAL && !irq);
 free(allocation);allocation=NULL;
 puts("PASS: actual IRQ owner, five NO_AUTOEN claims, specs/mappings/hwirq/trigger/bus-lock guards, partial failure cleanup, bounded disable depth, unexpected-handler worker, closing gate and lock-free waits");
}
'''
parser = argparse.ArgumentParser(description=__doc__)
parser.add_argument('--dtb', type=Path, action='append', default=[])
args = parser.parse_args()
with tempfile.TemporaryDirectory(prefix='op6893-irq-') as directory:
    root = Path(directory)
    (root / 'test.c').write_text(code)
    subprocess.run(['cc', '-Wall', '-Wextra', '-Werror', '-Wno-unused-parameter',
                    '-Wno-sign-compare', '-Wno-misleading-indentation',
                    '-fsanitize=address,undefined', '-fno-sanitize-recover=all',
                    '-no-pie', str(root / 'test.c'), '-o', str(root / 'test')], check=True)
    subprocess.run([str(root / 'test')], check=True)
for dtb in args.dtb:
    node = '/scp-resource-hold@10724000'
    cells = subprocess.check_output(['fdtget', '-t', 'x', str(dtb), node, 'interrupts'], text=True).split()
    assert cells == [s for i in range(5) for s in ['0', format(436 + i, 'x'), '4']]
    names = subprocess.check_output(['fdtget', str(dtb), node, 'interrupt-names'], text=True).split()
    assert names == [f'mbox{i}' for i in range(5)]
    print('PASS: complete IRQ specs and names:', dtb.name)
