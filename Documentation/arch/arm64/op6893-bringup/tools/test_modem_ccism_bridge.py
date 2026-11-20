#!/usr/bin/env python3
# SPDX-License-Identifier: GPL-2.0-only
"""Actual dormant CCIF2 bridge C with fake resources, SCP lease and session.

Session scheduling is tested separately. This checks the hardware adapter and
its lifecycle boundaries; no device, firmware or private modem data is used.
"""
from pathlib import Path
import subprocess
import tempfile

K = Path(__file__).resolve().parents[5]
SRC = K / 'drivers/misc/mediatek/ccci'
MODEL = r'''
#include <assert.h>
#include <stdio.h>
#include <stdlib.h>
#include <string.h>
#include <stdint.h>
#include <linux/types.h>
#include <linux/errno.h>
#include <linux/unaligned.h>
#define __iomem
#define CONFIG_OP6893_CCCI_CCIF 1
#define CONFIG_OP6893_CCCI_CCISM 1
#define IS_ENABLED(x) (x)
#define ARRAY_SIZE(a) (sizeof(a)/sizeof((a)[0]))
#define GFP_KERNEL 0
#define IORESOURCE_MEM 1
#define ERR_PTR(n) ((void *)(intptr_t)(n))
#define IS_ERR(p) ((uintptr_t)(p)>=(uintptr_t)-4095)
#define ERR_CAST(p) ((void *)(p))
#define PTR_ERR(p) ((int)(intptr_t)(p))
#define MTK_SIP_KERNEL_CCCI_CONTROL 0xc2000505UL
#define SMCCC_RET_NOT_SUPPORTED (-1)
#define WARN_ON(x) assert(!(x))
#define sysfs_emit(b,...) snprintf(b,4096,__VA_ARGS__)
struct device {unsigned id;};
struct resource {u64 start,end;};
struct platform_device {struct device dev;struct resource resources[2];};
struct clk_bulk_data {const char *id;};
struct mutex {bool held;};
static void mutex_init(struct mutex *m){m->held=false;}
static void mutex_lock(struct mutex *m){assert(!m->held);m->held=true;}
static void mutex_unlock(struct mutex *m){assert(m->held);m->held=false;}
static u64 resource_size(const struct resource *r){return r->end-r->start+1;}
struct arm_smccc_res {unsigned long a0,a1,a2,a3;};
#define __CCCI_SCP_RUNTIME_H
struct ccci_scp_client {unsigned marker;};
typedef void (*ccci_scp_state_fn)(void *,u64,u32,int);
#include "ccci-ccif.h"
#include "ccci-ccism-session.h"
#include "ccci-smem.h"
struct ccci_ccif {unsigned marker;};
struct ccci_ccism_session {
 const struct ccci_ccism_ops *ops;void *context;struct ccci_ccism_plan plan;
 ccci_ccism_session_fault_fn fault;struct ccci_ccism_session_status snapshot;
};
static struct platform_device device;
static struct ccci_ccif ordinary;
static struct ccci_scp_client client;
static struct ccci_ccism_session session;
static ccci_scp_state_fn notify;
static void *notify_context;
static u8 shared[32768],ap_regs[4096],md_regs[4096];
static void *allocated[32];static unsigned allocations;
static unsigned requests,wc_maps,register_maps,clock_gets,session_creates,client_creates;
static unsigned checks,acquires,releases,arms,ready_events,md_events,scp_events,stops,quiesces;
static unsigned clk_on,clk_off,smcs,clears,barriers,acks,md_sends,scp_sends,aborts;
static int alloc_fail,request_fail,wc_fail,window_fail,clock_get_error,session_create_error,client_create_error;
static int action_error;static void (*cleanup_action)(void *);static void *cleanup_context;
static unsigned destroys;
static int acquire_error,arm_error,check_error,md_error,scp_error,quiesce_error,stop_error,clock_enable_error;
static unsigned long smc_result;
static unsigned trace[32],trace_count;
static u64 notified_generation;static u32 notified_state;static int notified_error;
static void record(unsigned id){assert(trace_count<32);trace[trace_count++]=id;}
static void *devm_kzalloc(struct device *d,size_t size,int flags){
 assert(d==&device.dev && !flags);if(alloc_fail)return NULL;
 assert(allocations<32);void *p=calloc(1,size);assert(p);allocated[allocations++]=p;return p;
}
static int devm_add_action_or_reset(struct device *d,void (*action)(void *),void *context){
 assert(d==&device.dev && action && context);if(action_error){action(context);return action_error;}
 cleanup_action=action;cleanup_context=context;return 0;
}
static const char *dev_name(struct device *d){assert(d==&device.dev);return "ccism-synthetic";}
static void *devm_request_mem_region(struct device *d,u64 start,u64 size,const char *name){
 assert(d==&device.dev && start==0x80120000 && size==sizeof(shared) && name);
 requests++;return request_fail?NULL:shared;
}
static void *devm_ioremap_wc(struct device *d,u64 start,u64 size){
 assert(d==&device.dev && start==0x80120000 && size==sizeof(shared));wc_maps++;return wc_fail?NULL:shared;
}
static struct resource *platform_get_resource_byname(struct platform_device *p,unsigned type,const char *name){
 assert(p==&device && type==IORESOURCE_MEM);
 if(!strcmp(name,"ccif2-ap"))return &p->resources[0];
 assert(!strcmp(name,"ccif2-md"));return &p->resources[1];
}
static void *devm_ioremap_resource(struct device *d,struct resource *r){
 assert(d==&device.dev);register_maps++;
 if(window_fail==(int)register_maps)return ERR_PTR(-EACCES);
 assert(r==&device.resources[0] || r==&device.resources[1]);
 return r==&device.resources[0]?ap_regs:md_regs;
}
static int devm_clk_bulk_get(struct device *d,unsigned count,struct clk_bulk_data *clocks){
 assert(d==&device.dev && count==2 && !strcmp(clocks[0].id,"ccif2-ap") && !strcmp(clocks[1].id,"ccif2-md"));
 clock_gets++;return clock_get_error;
}
static int clk_bulk_prepare_enable(unsigned count,struct clk_bulk_data *clocks){
 assert(count==2 && clocks);clk_on++;record(1);return clock_enable_error;
}
static void clk_bulk_disable_unprepare(unsigned count,struct clk_bulk_data *clocks){
 assert(count==2 && clocks && acks==2 && trace_count && trace[trace_count-1]==6);
 clk_off++;record(7);
}
static void arm_smccc_smc(unsigned long fn,unsigned long op,unsigned long a2,unsigned long a3,
 unsigned long a4,unsigned long a5,unsigned long a6,unsigned long a7,struct arm_smccc_res *r){
 assert(fn==MTK_SIP_KERNEL_CCCI_CONTROL && op==13 && !a2 && !a3 && !a4 && !a5 && !a6 && !a7);
 assert(clk_on && !clk_off);smcs++;record(2);r->a0=smc_result;
}
static void memset_io(void *p,int value,size_t count){
 assert(p==shared && !value && count==sizeof(shared) && clk_on && !clk_off);
 clears++;record(3);memset(p,value,count);
}
static void mb(void){barriers++;record(6);}
static void writel(u32 value,void *p){
 assert(value==0xffff && clk_on && !clk_off);
 assert((!acks && p==ap_regs+0x14) || (acks==1 && p==md_regs+0x14));
 acks++;record(acks==1?4:5);put_unaligned_le32(value,p);
}
int ccci_ccif_system_send(struct ccci_ccif *c,u32 message,u32 reserved){
 assert(c==&ordinary && (message==0x119 || message==0x11b) && !reserved);md_sends++;return md_error;
}
void ccci_ccif_abort(struct ccci_ccif *c,int error){assert(c==&ordinary && error<0);aborts++;}
static struct ccci_scp_client *ccci_scp_client_create(struct device *d,ccci_scp_state_fn fn,void *context){
 assert(d==&device.dev && fn && context);client_creates++;notify=fn;notify_context=context;
 return client_create_error?ERR_PTR(client_create_error):&client;
}
static int ccci_scp_client_acquire(struct ccci_scp_client *c,u64 *generation){
 assert(c==&client);acquires++;if(!acquire_error)*generation=27;return acquire_error;
}
static int ccci_scp_client_check(struct ccci_scp_client *c,u64 generation){assert(c==&client && generation==27);checks++;return check_error;}
static int ccci_scp_client_send(struct ccci_scp_client *c,u16 op,u32 data){
 assert(c==&client && op==CCCI_SCP_OP_SHM_INIT && data==0x80120000);scp_sends++;return scp_error;
}
static void ccci_scp_client_release(struct ccci_scp_client *c){assert(c==&client);releases++;}
struct ccci_ccism_session *ccci_ccism_session_create(struct device *d,const struct ccci_ccism_ops *ops,
 void *context,const struct ccci_ccism_plan *plan,ccci_ccism_session_fault_fn fault){
 assert(d==&device.dev && context && plan && fault);session_creates++;
 session.ops=ops;session.context=context;session.plan=*plan;session.fault=fault;
 return session_create_error?ERR_PTR(session_create_error):&session;
}
int ccci_ccism_session_arm(struct ccci_ccism_session *s,u64 generation){assert(s==&session && generation==27);arms++;return arm_error;}
int ccci_ccism_session_md_ready(struct ccci_ccism_session *s){assert(s==&session);ready_events++;return md_error;}
int ccci_ccism_session_md_event(struct ccci_ccism_session *s,const struct ccci_ccif_event *event){
 assert(s==&session && event);md_events++;return md_error;
}
void ccci_ccism_session_scp_notify(void *context,u64 generation,u32 state,int error){
 assert(context==&session);scp_events++;notified_generation=generation;notified_state=state;notified_error=error;
}
int ccci_ccism_session_stop(struct ccci_ccism_session *s,bool stopped){assert(s==&session && stopped);stops++;return stop_error;}
int ccci_ccism_session_rearm(struct ccci_ccism_session *s){assert(s==&session);return 0;}
int ccci_ccism_session_quiesce(struct ccci_ccism_session *s){assert(s==&session);quiesces++;return quiesce_error;}
void ccci_ccism_session_status(struct ccci_ccism_session *s,struct ccci_ccism_session_status *out){assert(s==&session);*out=s->snapshot;}
int ccci_ccism_session_destroy(struct ccci_ccism_session *s){assert(s==&session);destroys++;return 0;}
#include "ccci-ccism-bridge.c"
'''
TEST = r'''
static struct ccci_smem_layout smem;
static void reset(void){
 if(cleanup_action){cleanup_action(cleanup_context);cleanup_action=NULL;cleanup_context=NULL;}
 for(unsigned i=0;i<allocations;i++)free(allocated[i]);allocations=0;
 memset(&device,0,sizeof(device));device.resources[0]=(struct resource){0x1023c000,0x1023cfff};
 device.resources[1]=(struct resource){0x1023d000,0x1023dfff};
 memset(&smem,0,sizeof(smem));smem.noncached=(struct ccci_lk_region){0x80000000,0x1800000};
 smem.users[16]=(struct ccci_smem_region){.ap=0x80120000,.md=0x40120000,.size=32768,.present=true};
 memset(shared,0x5a,sizeof(shared));memset(ap_regs,0x5a,sizeof(ap_regs));memset(md_regs,0x5a,sizeof(md_regs));
 memset(&session,0,sizeof(session));notify=NULL;notify_context=NULL;
 requests=wc_maps=register_maps=clock_gets=session_creates=client_creates=0;
 checks=acquires=releases=arms=ready_events=md_events=scp_events=stops=quiesces=0;
 clk_on=clk_off=smcs=clears=barriers=acks=md_sends=scp_sends=aborts=trace_count=0;
 alloc_fail=request_fail=wc_fail=window_fail=clock_get_error=session_create_error=client_create_error=0;
 action_error=0;destroys=0;
 acquire_error=arm_error=check_error=md_error=scp_error=quiesce_error=stop_error=clock_enable_error=0;smc_result=0;
}
static void no_hardware(void){assert(!clk_on && !clk_off && !smcs && !clears && !barriers && !acks && !md_sends && !scp_sends);}
static struct ccci_ccism_bridge *create(void){
 struct ccci_ccism_bridge *b=ccci_ccism_bridge_create(&device,&ordinary,&smem);
 assert(!IS_ERR(b));no_hardware();assert(!acquires && !arms && !releases);
 assert(requests==1 && wc_maps==1 && register_maps==2 && clock_gets==1 && session_creates==1 && client_creates==1);
 return b;
}
static void constructor(void){
 struct ccci_ccism_bridge *b;
 reset();assert(PTR_ERR(ccci_ccism_bridge_create(&device,NULL,&smem))==-EINVAL);assert(!allocations);no_hardware();
 for(unsigned n=0;n<13;n++){
  reset();switch(n){case 0:smem.users[16].present=false;break;case 1:smem.users[16].cached=true;break;
   case 2:smem.users[16].no_map=true;break;case 3:smem.users[16].size=32764;break;
   case 4:smem.users[16].ap+=4;smem.users[16].md+=4;break;case 5:smem.users[16].size+=4;break;
   case 6:smem.users[16].md+=4;break;case 7:smem.noncached.size=0x100;break;
   case 8:alloc_fail=1;break;case 9:request_fail=1;break;case 10:wc_fail=1;break;
   case 11:device.resources[0].start++;break;case 12:device.resources[1].end--;break;}
  b=ccci_ccism_bridge_create(&device,&ordinary,&smem);assert(IS_ERR(b));no_hardware();assert(!acquires && !releases);
  if(n<8)assert(!requests && !wc_maps && !register_maps);
 }
 for(unsigned n=0;n<6;n++){
  reset();switch(n){case 0:window_fail=1;break;case 1:window_fail=2;break;
   case 2:clock_get_error=-EPROBE_DEFER;break;case 3:session_create_error=-ENOMEM;break;case 4:client_create_error=-ENODEV;break;case 5:action_error=-ENOMEM;break;}
  assert(IS_ERR(ccci_ccism_bridge_create(&device,&ordinary,&smem)));no_hardware();assert(!acquires && !releases);
 }
 reset();b=create();assert(!ccci_ccism_bridge_offline(b) && !quiesces);assert(!ccci_ccism_bridge_offline(NULL));
 puts("PASS: actual CCIF2 constructor dormant; invalid geometry, resources and provider failures perform no hardware I/O");
}
static void hardware(void){
 reset();struct ccci_ccism_bridge *b=create();
 assert(bridge_clear(b,b->plan.ap,b->plan.size)==-ERANGE && !clears);
 assert(bridge_off(b)==-EHOSTDOWN && !acks);
 assert(!bridge_check(b,27) && checks==1);check_error=-ESTALE;assert(bridge_check(b,27)==-ESTALE);
 assert(!bridge_on(b) && b->clocks_held && b->smc_attempted && clk_on==1 && smcs==1);
 assert(bridge_on(b)==-EALREADY && clk_on==1 && smcs==1);
 assert(bridge_clear(b,b->plan.ap+4,b->plan.size)==-ERANGE && !clears);
 assert(bridge_clear(b,b->plan.ap,b->plan.size-4)==-ERANGE && !clears);
 assert(!bridge_clear(b,b->plan.ap,b->plan.size) && clears==1);
 for(unsigned i=0;i<sizeof(shared);i++)assert(!shared[i]);
 assert(!bridge_md_send(b,CCCI_CCISM_INIT) && !bridge_md_send(b,CCCI_CCISM_DONE) && md_sends==2);
 md_error=-EBUSY;assert(bridge_md_send(b,CCCI_CCISM_INIT)==-EBUSY);
 assert(!bridge_scp_send(b,CCCI_SCP_OP_SHM_INIT,b->plan.ap));scp_error=-EIO;
 assert(bridge_scp_send(b,CCCI_SCP_OP_SHM_INIT,b->plan.ap)==-EIO);
 unsigned before=trace_count;assert(!bridge_off(b));
 assert(!b->clocks_held && clk_off==1 && acks==2 && trace_count==before+4);
 assert(trace[before]==4 && trace[before+1]==5 && trace[before+2]==6 && trace[before+3]==7);
 for(unsigned i=0;i<sizeof(ap_regs);i++)if(i<0x14 || i>=0x18)assert(ap_regs[i]==0x5a && md_regs[i]==0x5a);
 assert(bridge_off(b)==-EHOSTDOWN && acks==2 && clk_off==1);
 for(unsigned n=0;n<3;n++){
  reset();b=create();if(!n)clock_enable_error=-EACCES;else smc_result=n==1?(unsigned long)SMCCC_RET_NOT_SUPPORTED:1;
  assert(bridge_on(b)==(!n?-EACCES:n==1?-EOPNOTSUPP:-EIO));
  assert(!clk_off && !acks && !clears && !md_sends && !scp_sends);
  assert(b->clocks_held==(n!=0) && b->smc_attempted==(n!=0));
  if(n)assert(bridge_on(b)==-EALREADY && smcs==1 && clk_on==1);
 }
 puts("PASS: actual clock/SMC13 ABI, exact ID16 clear, both ACKs and barrier before clock-off; failures retain resources");
}
static void lifecycle(void){
 reset();struct ccci_ccism_bridge *b=create();assert(!ccci_ccism_bridge_arm(b));
 assert(b->attempted && b->leased && acquires==1 && arms==1);no_hardware();
 assert(ccci_ccism_bridge_arm(b)==-EALREADY && acquires==1);
 assert(ccci_ccism_bridge_stop(b,false)==-EBUSY && !stops);
 stop_error=-EIO;assert(ccci_ccism_bridge_stop(b,true)==-EIO && stops==1 && !releases);
 quiesce_error=-EBUSY;assert(ccci_ccism_bridge_offline(b)==-EBUSY && b->leased && !releases);
 quiesce_error=0;assert(!ccci_ccism_bridge_offline(b) && !b->leased && releases==1);
 assert(!ccci_ccism_bridge_offline(b) && releases==1);
 reset();b=create();acquire_error=-EHOSTDOWN;
 assert(ccci_ccism_bridge_arm(b)==-EHOSTDOWN && b->attempted && !b->leased && !arms);
 assert(ccci_ccism_bridge_arm(b)==-EALREADY && acquires==1);assert(!ccci_ccism_bridge_offline(b) && !releases);
 reset();b=create();arm_error=-ESTALE;
 assert(ccci_ccism_bridge_arm(b)==-ESTALE && b->leased && acquires==1 && arms==1 && !releases);
 quiesce_error=-EBUSY;assert(ccci_ccism_bridge_offline(b)==-EBUSY && !releases);
 quiesce_error=0;assert(!ccci_ccism_bridge_offline(b) && releases==1);
 session.fault(session.context,-ECONNRESET);assert(aborts==1);
 unsigned old_checks=checks;notify(notify_context,27,CCCI_SCP_STATE_STOP,-EIO);
 assert(scp_events==1 && notified_generation==27 && notified_state==CCCI_SCP_STATE_STOP && notified_error==-EIO && checks==old_checks);
 session.snapshot=(struct ccci_ccism_session_status){.state=CCCI_CCISM_FAILED,.generation=27,.error=-EIO,.bridge_touched=true};
 char status[4096];assert(ccci_ccism_bridge_status(b,status)>0);
 assert(strstr(status,"generation=27") && strstr(status,"cpu_release_issued=0"));
 no_hardware();puts("PASS: actual lease one-shot arm, failed-arm retention, stopped-MD guard, offline release only after quiesce and scalar notification routing");
}
static int port(struct ccci_ccism_bridge *b,u32 message,u32 channel,u32 reserved,u32 type,u32 queue,u32 size){
 u8 packet[20]={0};put_unaligned_le32(message,packet+4);put_unaligned_le32(channel,packet+8);put_unaligned_le32(reserved,packet+12);
 struct ccci_ccif_event event={.type=type,.queue=queue,.size=size,.data=packet};
 return ccci_ccism_bridge_port(b,&event);
}
static void ports(void){
 reset();struct ccci_ccism_bridge *b=create();assert(ccci_ccism_bridge_port(b,NULL)==-EOPNOTSUPP);
 assert(!port(b,0,0,0,CCCI_CCIF_EVENT_RING,0,16) && ready_events==1);
 assert(!port(b,CCCI_CCISM_ACK,2,0,CCCI_CCIF_EVENT_RING,0,16) && md_events==1);
 assert(!port(b,CCCI_CCISM_DONE,2,0,CCCI_CCIF_EVENT_RING,0,16) && md_events==2);
 md_error=-ENOBUFS;assert(port(b,0,0,0,CCCI_CCIF_EVENT_RING,0,16)==-ENOBUFS);
 assert(port(b,CCCI_CCISM_ACK,2,0,CCCI_CCIF_EVENT_RING,0,16)==-ENOBUFS);
 for(unsigned n=0;n<8;n++){
  u32 type=CCCI_CCIF_EVENT_RING,queue=0,size=16,chan=2,msg=CCCI_CCISM_ACK,reserved=0;
  switch(n){case 0:type=CCCI_CCIF_EVENT_SRAM;break;case 1:type=CCCI_CCIF_EVENT_NOTIFY;break;
   case 2:queue=1;break;case 3:size=20;break;case 4:chan=3;break;case 5:msg=CCCI_CCISM_INIT;break;
   case 6:chan=0;msg=0;reserved=CCCI_CCIF_INIT_CHECK;break;case 7:chan=0;msg=4;break;}
  assert(port(b,msg,chan,reserved,type,queue,size)==-EOPNOTSUPP);
 }
 struct ccci_ccif_event null_data={.type=CCCI_CCIF_EVENT_RING,.size=16};
 assert(ccci_ccism_bridge_port(b,&null_data)==-EINVAL);
 assert(ready_events==2 && md_events==3);no_hardware();
 puts("PASS: actual port routing accepts only q0 HS2/ACK/DONE and propagates admission errors");
}
int main(void){constructor();hardware();lifecycle();ports();reset();}
'''


def main():
    # Reuse the established scalar types/endian shims, while compiling only this adapter.
    base_source = Path(__file__).with_name('test_modem_ccif.py').read_text()
    files_section = base_source[base_source.index('        files = {'):
                               base_source.index('        for name, content in files.items():')]
    scope = {}
    exec(files_section.strip(), scope)
    with tempfile.TemporaryDirectory(prefix='op6893-ccism-bridge-') as directory:
        root = Path(directory)
        inc = root / 'linux'
        inc.mkdir()
        for name, content in scope['files'].items():
            if name == 'types.h':
                content = content.replace('typedef uint64_t u64;', 'typedef unsigned long long u64;')
            if name == 'limits.h':
                content += '#define U32_MAX UINT32_MAX\n'
            (inc / name).write_text(content)
        with (inc / 'errno.h').open('a') as output:
            output.write('#define EPROBE_DEFER 517\n')
        with (inc / 'unaligned.h').open('a') as output:
            output.write('static inline u16 get_unaligned_le16(const void *p){const u8 *b=p;return b[0]|(u16)b[1]<<8;}\n'
                         'static inline void put_unaligned_le16(u16 v,void *p){u8 *b=p;b[0]=v;b[1]=v>>8;}\n')
        for name in ('arm-smccc.h', 'clk.h', 'err.h', 'io.h', 'ioport.h', 'mutex.h',
                     'platform_device.h', 'slab.h', 'sysfs.h', 'kconfig.h'):
            (inc / name).write_text('/* Models supplied by the harness. */\n')
        (inc / 'soc/mediatek').mkdir(parents=True)
        (inc / 'soc/mediatek/mtk_sip_svc.h').write_text('/* Synthetic ABI constant. */\n')
        (root / 'test.c').write_text(MODEL + TEST)
        subprocess.run(['cc', '-O1', '-g', '-Wall', '-Wextra', '-Werror',
                        '-Wno-misleading-indentation', '-Wno-sign-compare', '-D__iomem=',
                        '-fsanitize=address,undefined',
                        '-fno-sanitize-recover=all', '-no-pie', '-I' + str(root),
                        '-I' + str(SRC), '-I' + str(K / 'include'),
                        str(SRC / 'ccci-ccif-protocol.c'), str(SRC / 'ccci-ccism.c'),
                        str(SRC / 'ccci-scp-protocol.c'), str(root / 'test.c'),
                        '-o', str(root / 'test')], check=True)
        subprocess.run([str(root / 'test')], check=True)


if __name__ == '__main__':
    main()
