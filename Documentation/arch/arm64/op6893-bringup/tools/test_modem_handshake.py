#!/usr/bin/env python3
# SPDX-License-Identifier: GPL-2.0-only
"""Actual runtime/FSM/TX/controller and RX C with synthetic peer/IRQ/work models.

No firmware or private modem data. Deterministic interleavings do not prove SMP.
"""
from pathlib import Path
import runpy
import subprocess
import tempfile

K = Path(__file__).resolve().parents[5]
SRC = K / 'drivers/misc/mediatek/ccci'
base = runpy.run_path(str(Path(__file__).with_name('test_modem_ccif_rx.py')))
shim = base['SHIM']
a = shim.index('static u32 readl(')
b = shim.index('#include "ccci-ccif-rx.c"', a)
shim = shim[:a] + r'''
static u8 rt_pages[8192];
static unsigned rt_writes,rt_zeros,fences,doorbells;
static u32 readl(const void *p){
 uintptr_t address=(uintptr_t)p,base=(uintptr_t)page;
 if(address>=(uintptr_t)rt_pages && address+4<=(uintptr_t)rt_pages+8192)return get_unaligned_le32(p);
 assert(address>=base && address+4<=base+4096 && !((address-base)&3));
 size_t off=address-base;reads++;if(off>=0x100 && off<0x1f0)sram_reads++;
 return get_unaligned_le32(p);
}
static void writel(u32 value,void *p){
 uintptr_t address=(uintptr_t)p,base=(uintptr_t)page;
 if(address>=(uintptr_t)rt_pages && address+4<=(uintptr_t)rt_pages+8192){
  assert(address>=(uintptr_t)rt_pages+0x800 && address<(uintptr_t)rt_pages+0x1000);
  rt_writes++;put_unaligned_le32(value,p);return;
 }
 assert(address>=base && address+4<=base+4096 && !((address-base)&3));
 size_t off=address-base;writes++;
 if(off==0x14){
  assert(ack_count<8);acks[ack_count++]=value;
  if(value&BIT(15)){assert(sram_reads && !(sram_reads%60));if(mutate_sram_on_ack)memset(page+0x100,0xff,240);}
  put_unaligned_le32(get_unaligned_le32(page+0x10)&~value,page+0x10);
  if(arrival){put_unaligned_le32(get_unaligned_le32(page+0x10)|arrival,page+0x10);arrival=0;}
 }else{
  assert(off==4 || off==0xc || (off>=0x1f0 && off<0x29c));
  if(off==4)assert(value==BIT(15) && fences && rt_writes==512);
  if(off==0xc){assert(value==15 && get_unaligned_le32(page+4)==BIT(15));doorbells++;}
  put_unaligned_le32(value,p);
 }
}
''' + shim[b:]

# The complete original receiver suite remains part of this integration test.
baseline = base['TEST'].replace('int main(void){', 'static void baseline_tests(void){')

GLUE = r'''
#define CONFIG_OP6893_CCCI_HANDSHAKE 1
#define IS_ENABLED(x) (x)
struct mutex {bool held;};
static void mutex_init(struct mutex *m){m->held=false;}
static void mutex_lock(struct mutex *m){assert(!m->held);m->held=true;}
static void mutex_unlock(struct mutex *m){assert(m->held);m->held=false;}
struct delayed_work {struct work_struct work;};
#define INIT_DELAYED_WORK(w,f) INIT_WORK(&(w)->work,f)
#define to_delayed_work(w) container_of(w,struct delayed_work,work)
static unsigned timer_cancels,timer_queues;
static bool mod_delayed_work(void *q,struct delayed_work *w,unsigned long delay){
 (void)q;assert(delay==1000);bool old=w->work.pending;w->work.pending=true;timer_queues++;return old;
}
static void cancel_delayed_work_sync(struct delayed_work *w){assert(!w->work.running);w->work.pending=false;timer_cancels++;}
#define msecs_to_jiffies(n) (n)
static u64 now_ms;
static u64 ktime_get_boottime(void){return now_ms;}
#define ktime_to_ms(n) (n)
#define sysfs_emit(b,...) snprintf(b,4096,__VA_ARGS__)
#include <linux/time.h>
struct timezone sys_tz = { 0, 0 };
static void mb(void){fences++;}
static void memset_io(void *p,int v,size_t n){
 assert(p==rt_pages+0x800 && !v && n==4096);memset(p,v,n);rt_zeros++;
}
static bool claim_fail,map_fail;
static unsigned claims,maps;
static int claimed;
static void *devm_request_mem_region(struct device *d,u64 start,u64 size,const char *name){
 assert(d==&dev && start==0x8011e000 && size==8192 && name);claims++;return claim_fail?NULL:&claimed;
}
static void *devm_ioremap_wc(struct device *d,u64 start,u64 size){
 assert(d==&dev && start==0x8011e000 && size==8192);maps++;return map_fail?NULL:rt_pages;
}
static const char *dev_name(struct device *d){assert(d==&dev);return "ccci-synthetic";}
#define dev_err(d,fmt,...) ((void)0)
#define dev_info(d,fmt,...) ((void)0)
#include "ccci-ccif-control.c"
'''

TEST = r'''
static struct ccci_ccif_controller *controller;
static struct ccci_runtime_offer offers[64];
static struct ccci_runtime_plan plan;
static struct ccci_smem_layout smem;
static u8 blob[2048],upload[172],negotiated[64],query[64];
static u32 used,rejected;
static unsigned port_calls,accepted_hs1,accepted_hs2;
static struct ccci_handshake *port_machine;
static int port_error;
static void profile(void){
 memset(offers,0,sizeof(offers));offers[0].supported=true;offers[0].length=16;
 put_unaligned_le32(2,offers[0].data+8);offers[27].supported=true;
 memset(query,3,45);memset(query+45,0,19);query[0]=2;query[40]=1;
}
static void geometry(void){
 memset(&smem,0,sizeof(smem));smem.noncached=(struct ccci_lk_region){0x80000000,0x1800000};
 smem.cached=(struct ccci_lk_region){0xa0000000,0x4960000};smem.cache_md_base=0x48000000;
 smem.users[14]=(struct ccci_smem_region){.ap=0x8011e800,.md=0x4011e800,.size=4096,.present=true};
 assert(!ccci_runtime_plan(&smem,&plan));
}
static void assert_zero(const void *p,unsigned n){for(unsigned i=0;i<n;i++)assert(!((const u8 *)p)[i]);}
static void codec(void){
 geometry();profile();assert(!ccci_runtime_encode(query,offers,blob,2048,&used,negotiated,&rejected));
 assert(used==528 && rejected==64 && negotiated[0]==2 && negotiated[27]==2 && negotiated[40]==1);
 u32 pos=0;for(unsigned id=0;id<64;id++){
  u32 len=get_unaligned_le32(blob+pos+4);assert(blob[pos]==id && !blob[pos+2] && !blob[pos+3]);
  assert(len==(id==0?16:0));pos+=8+len;
 }assert(pos==used);assert_zero(blob+used,2048-used);
 /* Every legal capacity: canaries and failure output clearing. */
 u8 out[2050];for(unsigned cap=0;cap<=2048;cap++){
  memset(out,0x5a,sizeof(out));int ret=ccci_runtime_encode(query,offers,out+1,cap,&used,negotiated,&rejected);
  assert(out[0]==0x5a && out[cap+1]==0x5a);
  if(cap<528){assert(ret==-ENOSPC && !used);assert_zero(out+1,cap);assert_zero(negotiated,64);}
  else assert(!ret && used==528);
 }
 /* Exhaustive MD masks/versions against both available and missing AP capability. */
 for(unsigned supported=0;supported<2;supported++)for(unsigned mask=0;mask<16;mask++)for(unsigned ver=0;ver<16;ver++){
  profile();offers[0].supported=supported;query[0]=mask|(ver<<4);
  int ret=ccci_runtime_encode(query,offers,blob,2048,&used,negotiated,&rejected);
  int want=mask>4?-EPROTO:mask==2&&!supported?-EOPNOTSUPP:mask==2&&ver?-EPROTONOSUPPORT:0;
  assert(ret==want);
  if(ret){assert_zero(blob,2048);assert_zero(negotiated,64);assert(!used && rejected==0);}
  else assert(negotiated[0]==(!mask?query[0]:supported&&(mask==2 || (mask==3&&!ver) || mask==4)?2:1));
 }
 profile();offers[27].length=1;assert(ccci_runtime_validate(offers)==-EMSGSIZE);
 profile();offers[0].version=1;assert(ccci_runtime_validate(offers)==-EOPNOTSUPP);
 profile();offers[45].supported=true;assert(ccci_runtime_validate(offers)==-EOPNOTSUPP);
 profile();offers[38].supported=true;offers[38].length=48;assert(!ccci_runtime_validate(offers));
 offers[38].length=64;assert(ccci_runtime_validate(offers)==-EMSGSIZE);
 assert(!ccci_runtime_upload(&plan,upload,172));
 assert(get_unaligned_le32(upload+4)==0xac && get_unaligned_le32(upload+8)==1);
 assert(get_unaligned_le32(upload+16)==0x43434349 && upload[21]==0x10);
 assert(get_unaligned_le32(upload+84)==2 && get_unaligned_le32(upload+88)==0x4011e800);
 assert(get_unaligned_le32(upload+96)==0x4011f000 && get_unaligned_le32(upload+108)==0x1800000);
 assert(get_unaligned_le32(upload+112)==0x48000000 && get_unaligned_le32(upload+116)==0x4960000);
 assert_zero(upload+120,48);assert(get_unaligned_le32(upload+168)==0x43434349);
 for(unsigned i=0;i<12;i++){
  geometry();switch(i){case 0:smem.users[14].cached=true;break;case 1:smem.users[14].md++;break;
   case 2:smem.users[14].ap++;break;case 3:smem.users[14].size=4092;break;
   case 4:smem.cache_md_base=0xfffffff0;break;case 5:smem.cache_md_base=0x40000000;break;
   case 6:smem.noncached.size=0x100;break;case 7:smem.users[14].no_map=true;break;
   case 8:smem.cached.base=UINT64_MAX-3;break;case 9:smem.cached.base=smem.noncached.base;break;
   case 10:smem.cached.base++;break;case 11:smem.noncached.size++;break;}
  memset(&plan,0x5a,sizeof(plan));assert(ccci_runtime_plan(&smem,&plan)<0);assert_zero(&plan,sizeof(plan));
 }
 geometry();plan.cache_md=0xfffffff0;assert(ccci_runtime_upload(&plan,upload,172)==-ERANGE);assert_zero(upload,172);
 geometry();plan.md=0xfffffff0;assert(ccci_runtime_upload(&plan,upload,172)==-ERANGE);
}
static u8 tx_rt[4096],tx_ap[4096];
static unsigned tx_calls,tx_fail,tx_fences,tx_doorbells;
static bool tx_corrupt;
static int tx_step(void){return ++tx_calls==tx_fail?-EACCES:0;}
static int tx_runtime(void *ctx,u32 o,u32 v){assert(ctx==&dev && o<2048 && !(o&3));int r=tx_step();if(!r)put_unaligned_le32(v,tx_rt+o);return r;}
static int tx_read(void *ctx,u32 o,u32 *v){
 assert(ctx==&dev && (o==4 || (o>=0x1f0 && o<0x29c && !(o&3))));int r=tx_step();if(r)return r;
 *v=get_unaligned_le32(tx_ap+o);if(o!=4){assert(tx_fences==1);if(tx_corrupt)*v^=1;}return 0;
}
static int tx_write(void *ctx,u32 o,u32 v){
 assert(ctx==&dev && (o==4 || o==0xc || (o>=0x1f0 && o<0x29c && !(o&3))));
 int r=tx_step();if(r)return r;
 if(o==4){assert(v==BIT(15) && tx_calls==600 && tx_fences==1);}
 if(o==0xc){assert(v==15 && tx_calls==601 && get_unaligned_le32(tx_ap+4)==BIT(15));tx_doorbells++;}
 put_unaligned_le32(v,tx_ap+o);return 0;
}
static void tx_fence(void *ctx){assert(ctx==&dev && tx_calls==556);tx_fences++;}
static const struct ccci_ccif_tx_ops tx_ops={tx_runtime,tx_read,tx_write,tx_fence};
static void tx_reset(void){
 memset(tx_rt,0x5a,sizeof(tx_rt));memset(tx_ap,0xa5,sizeof(tx_ap));put_unaligned_le32(0,tx_ap+4);
 tx_calls=tx_fail=tx_fences=tx_doorbells=0;tx_corrupt=false;
}
static void transmit(void){
 geometry();profile();assert(!ccci_runtime_encode(query,offers,blob,2048,&used,negotiated,&rejected));
 assert(!ccci_runtime_upload(&plan,upload,172));tx_reset();
 assert(!ccci_ccif_runtime_send(&tx_ops,&dev,blob,used,upload) && tx_calls==601 && tx_doorbells==1);
 assert(!memcmp(tx_rt,blob,2048) && !memcmp(tx_ap+0x1f0,upload,172));
 for(unsigned i=2048;i<4096;i++)assert(tx_rt[i]==0x5a);
 for(unsigned i=0x100;i<0x1f0;i++)assert(tx_ap[i]==0xa5);
 for(unsigned i=0x29c;i<4096;i++)assert(tx_ap[i]==0xa5);
 for(unsigned n=1;n<=601;n++){
  tx_reset();tx_fail=n;assert(ccci_ccif_runtime_send(&tx_ops,&dev,blob,used,upload)==-EACCES);
  assert(tx_calls==n && !tx_doorbells);
 }
 tx_reset();put_unaligned_le32(BIT(15),tx_ap+4);
 assert(ccci_ccif_runtime_send(&tx_ops,&dev,blob,used,upload)==-EBUSY && tx_calls==1);
 tx_reset();tx_corrupt=true;assert(ccci_ccif_runtime_send(&tx_ops,&dev,blob,used,upload)==-EIO && tx_calls==557 && !tx_doorbells);
 tx_reset();upload[168]^=1;assert(ccci_ccif_runtime_send(&tx_ops,&dev,blob,used,upload)==-EINVAL && !tx_calls);
}
static struct ccci_handshake machine;
static unsigned publishes;
static int publish_error;
static int publish(void *ctx,const void *rt,u32 n,const void *up){
 assert(ctx==&dev && machine.state==CCCI_HANDSHAKE_PUBLISH && n>=512);
 assert(get_unaligned_le32((const u8 *)rt+4)==16 && get_unaligned_le32((const u8 *)up+4)==172);
 publishes++;return publish_error;
}
static int ports(void *ctx,const struct ccci_ccif_event *e){
 assert(ctx==&dev && e);port_calls++;
 if(e->type==CCCI_CCIF_EVENT_SRAM){
  assert(port_machine && e->size==240 && port_machine->hs1_seen);
  assert(port_machine->state==CCCI_HANDSHAKE_WAIT_HS2 && !port_machine->hs2_seen);
  assert(port_machine->deadline_ms==port_machine->last_ms+60000);
  assert(port_machine->used>=512 && (!controller || controller->hs.state!=CCCI_HANDSHAKE_PUBLISH));
  assert(get_unaligned_le32((const u8 *)e->data+12)==CCCI_CCIF_INIT_CHECK);
  assert(!memcmp((const u8 *)e->data+20,query,64));accepted_hs1++;
 }else if(e->type==CCCI_CCIF_EVENT_RING && e->size==16 &&
          !(get_unaligned_le32((const u8 *)e->data+8)&0xffff) &&
          !get_unaligned_le32((const u8 *)e->data+4)){
  assert(port_machine && port_machine->state==CCCI_HANDSHAKE_HS2_SEEN && port_machine->hs2_seen);
  assert(accepted_hs1==1);accepted_hs2++;
 }
 return port_error;
}
static const struct ccci_handshake_ops hops={publish,ports};
static u8 packet[240];
static struct ccci_ccif_event ev;
static void state_setup(void){
 geometry();profile();memset(&machine,0,sizeof(machine));publishes=port_calls=accepted_hs1=accepted_hs2=0;publish_error=port_error=0;port_machine=&machine;
 assert(!ccci_handshake_begin(&machine,&hops,&dev,&plan,offers,100));
 hs1(packet);memcpy(packet+20,query,64);
 ev=(struct ccci_ccif_event){.type=CCCI_CCIF_EVENT_SRAM,.data=packet,.size=240};
}
static void hs2_event(void){memset(packet,0,16);ev=(struct ccci_ccif_event){.type=CCCI_CCIF_EVENT_RING,.data=packet,.size=16};}
static void failed(int error){assert(machine.state==CCCI_HANDSHAKE_FAILED && machine.error==error && !machine.hs2_seen);}
static void state_machine(void){
 state_setup();assert(!ccci_handshake_consume(&machine,&ev,200) && publishes==1 && machine.hs1_seen && port_calls==1 && accepted_hs1==1);
 assert(machine.state==CCCI_HANDSHAKE_WAIT_HS2);hs2_event();
 assert(!ccci_handshake_consume(&machine,&ev,201) && machine.state==CCCI_HANDSHAKE_HS2_SEEN && machine.hs2_seen);
 assert(!ccci_handshake_tick(&machine,1000000));ccci_handshake_stop(&machine);
 assert(machine.state==CCCI_HANDSHAKE_STOPPED && machine.hs1_seen && machine.hs2_seen);
 assert(port_calls==2 && accepted_hs1==1 && accepted_hs2==1);
 assert(ccci_handshake_consume(&machine,&ev,1000001)==-ESHUTDOWN);
 assert(ccci_handshake_begin(&machine,&hops,&dev,&plan,offers,100)==-EALREADY);
 state_setup();assert(!ccci_handshake_consume(&machine,&ev,200));hs2_event();port_error=-ENOSPC;
 assert(ccci_handshake_consume(&machine,&ev,201)==-ENOSPC && machine.hs2_seen && port_calls==2);
 assert(machine.state==CCCI_HANDSHAKE_FAILED && machine.error==-ENOSPC);
 state_setup();hs2_event();assert(ccci_handshake_consume(&machine,&ev,200)==-EPROTO && !port_calls);failed(-EPROTO);
 state_setup();ev.type=CCCI_CCIF_EVENT_RING;assert(ccci_handshake_consume(&machine,&ev,200)==-EPROTO);assert(!publishes);
 state_setup();assert(!ccci_handshake_consume(&machine,&ev,200));assert(ccci_handshake_consume(&machine,&ev,201)==-EPROTO);assert(publishes==1 && port_calls==1 && accepted_hs1==1);
 state_setup();query[44]=2;memcpy(packet+20,query,64);
 assert(ccci_handshake_consume(&machine,&ev,200)==-EOPNOTSUPP && !publishes && machine.rejected==44);
 state_setup();packet[20+27]=1;assert(ccci_handshake_consume(&machine,&ev,200)==-EOPNOTSUPP && !publishes);
 state_setup();publish_error=-EBUSY;assert(ccci_handshake_consume(&machine,&ev,200)==-EBUSY && !port_calls);failed(-EBUSY);
 assert(ccci_handshake_consume(&machine,&ev,201)==-EBUSY && publishes==1 && !port_calls);
 state_setup();port_error=-ENXIO;
 assert(ccci_handshake_consume(&machine,&ev,200)==-ENXIO && publishes==1 && accepted_hs1==1);
 failed(-ENXIO);assert(machine.deadline_ms==60200);hs2_event();
 assert(ccci_handshake_consume(&machine,&ev,201)==-ENXIO && !accepted_hs2 && port_calls==1);
 state_setup();assert(ccci_handshake_abort(&machine,-EPIPE)==-EPIPE);
 assert(ccci_handshake_consume(&machine,&ev,200)==-EPIPE && !port_calls && !publishes);
 state_setup();assert(!ccci_handshake_tick(&machine,60099));assert(ccci_handshake_tick(&machine,60100)==-ETIMEDOUT);failed(-ETIMEDOUT);
 state_setup();assert(!ccci_handshake_consume(&machine,&ev,200));assert(ccci_handshake_tick(&machine,60200)==-ETIMEDOUT);failed(-ETIMEDOUT);
 state_setup();assert(ccci_handshake_tick(&machine,99)==-ERANGE);failed(-ERANGE);
 state_setup();ev.type=CCCI_CCIF_EVENT_NOTIFY;ev.notifications=BIT(16)|BIT(7);
 assert(!ccci_handshake_consume(&machine,&ev,200) && port_calls==1);
 state_setup();ev.type=CCCI_CCIF_EVENT_NOTIFY;ev.notifications=BIT(4);
 assert(ccci_handshake_consume(&machine,&ev,200)==-EREMOTEIO && !port_calls && !publishes);
 state_setup();assert(!ccci_handshake_consume(&machine,&ev,200));hs2_event();ev.queue=1;
 assert(ccci_handshake_consume(&machine,&ev,201)==-EPROTO);
 state_setup();ev.type=CCCI_CCIF_EVENT_NOTIFY;ev.notifications=BIT(7);port_error=-ENODATA;
 assert(ccci_handshake_consume(&machine,&ev,200)==-ENODATA && port_calls==1);failed(-ENODATA);
 state_setup();memset(&machine,0,sizeof(machine));
 assert(!ccci_handshake_begin(&machine,&hops,&dev,&plan,offers,UINT64_MAX-60000));
 assert(ccci_handshake_consume(&machine,&ev,UINT64_MAX-1)==-ERANGE && !publishes);
}
static unsigned control_fault_calls;
static int control_fault_error;
static void control_fault(void *context,int error){
 assert(context==&dev && controller->lock.held && error<0);
 assert(controller->hs.state==CCCI_HANDSHAKE_FAILED && !controller->active);
 control_fault_calls++;control_fault_error=error;
}
static void control_cleanup(void){if(controller && !IS_ERR(controller))ccci_ccif_control_quiesce(controller);controller=NULL;cleanup();}
static void control_setup(void){
 control_cleanup();setup();geometry();profile();memset(rt_pages,0x5a,sizeof(rt_pages));
 rt_writes=rt_zeros=fences=doorbells=claims=maps=timer_cancels=timer_queues=port_calls=0;
 claim_fail=map_fail=false;now_ms=100;port_error=0;control_fault_calls=0;control_fault_error=0;accepted_hs1=accepted_hs2=0;
 controller=ccci_ccif_control_create(&dev,page,rx,&smem);assert(!IS_ERR(controller));port_machine=&controller->hs;
 assert(!ccci_ccif_control_set_fault(controller,control_fault,&dev));
 assert(claims==1 && maps==1 && !reads && !writes && !rt_zeros && !timer_queues && !rt_writes);
}
static void controller_tests(void){
 /* Constructor failures cannot schedule work or access runtime/MMIO. */
 for(unsigned n=0;n<3;n++){
  control_cleanup();setup();geometry();profile();claims=maps=0;
  claim_fail=n==1;map_fail=n==2;fail_allocation=n==0?allocation_calls+1:0;
  controller=ccci_ccif_control_create(&dev,page,rx,&smem);
  assert(IS_ERR(controller) && !reads && !writes && !rx->work.pending);
  assert(claims==(n!=0) && maps==(n==2));fail_allocation=0;
 }
 control_setup();assert(!ccci_ccif_control_start(controller,offers,ports,&dev));
 assert(rt_zeros==1 && rx->work.pending && controller->timer.work.pending && controller->active);
 assert_zero(rt_pages+0x800,4096);
 for(unsigned i=0;i<0x800;i++)assert(rt_pages[i]==0x5a && rt_pages[i+0x1800]==0x5a);
 hs1(page+0x100);memcpy(page+0x100+20,query,64);put_unaligned_le32(BIT(15),page+0x10);
 run_work(&rx->work);assert(controller->hs.state==CCCI_HANDSHAKE_WAIT_HS2 && doorbells==1 && rx->armed);
 assert(port_calls==1 && accepted_hs1==1 && !accepted_hs2);
 assert(rt_writes==512 && ack_count==1 && sram_reads==60 && !ccci_ccif_control_error(controller));
 for(unsigned i=0x1000;i<0x1800;i++)assert(!rt_pages[i]);/* MD half stayed untouched after initial clear. */
 peer_packet(0,17);put_unaligned_le32(0,banks[0]+32+12);/* CCCI data[1]=message0. */
 now_ms=200;put_unaligned_le32(BIT(0),page+0x10);interrupt0();run_work(&rx->work);
 assert(controller->hs.hs2_seen && controller->hs.state==CCCI_HANDSHAKE_HS2_SEEN && doorbells==1);
 now_ms=1000000;run_work(&controller->timer.work);assert(controller->timer.work.pending && !ccci_ccif_control_error(controller));
 char status[4096];assert(ccci_ccif_control_status(controller,status)>0 && strstr(status,"hs2_seen=1"));
 assert(!control_fault_calls && accepted_hs1==1 && accepted_hs2==1);
 assert(ccci_ccif_rx_rearm(rx)==-EBUSY && ccci_ccif_control_rearm(controller)==-EBUSY);

 assert(ccci_ccif_control_set_fault(controller,control_fault,&dev)==-EBUSY);
 /* Raw RX faults never call the control consumer; the timer must observe them. */
 ccci_ccif_rx_abort(rx,-EPIPE);assert(!control_fault_calls);
 run_work(&controller->timer.work);
 assert(control_fault_calls==1 && control_fault_error==-EPIPE && !controller->active);
 assert(ccci_ccif_control_error(controller)==-EPIPE && controller->hs.hs2_seen);
 ccci_ccif_control_quiesce(controller);ccci_ccif_rx_stop(rx);assert(!rx->armed && !controller->active && !controller->timer.work.pending);
 assert(controller->hs.state==CCCI_HANDSHAKE_FAILED && controller->hs.hs2_seen);
 assert(ccci_ccif_control_start(controller,offers,ports,&dev)==-EIO && rt_zeros==1);
 assert(ccci_ccif_rx_rearm(rx)==-EBUSY && ccci_ccif_control_rearm(controller)==-EBUSY);
 control_setup();assert(!ccci_ccif_control_start(controller,offers,ports,&dev));
 run_work(&rx->work);assert(rx->armed);
 ccci_ccif_control_quiesce(controller);ccci_ccif_rx_stop(rx);
 assert(!ccci_ccif_rx_rearm(rx) && !ccci_ccif_control_rearm(controller));
 assert(!rx->attempted && !rx->next_queue && !controller->attempted &&
        !controller->fault && !controller->port && controller->hs.state==CCCI_HANDSHAKE_IDLE);
 assert(!ccci_ccif_control_set_fault(controller,control_fault,&dev));
 assert(!ccci_ccif_control_start(controller,offers,ports,&dev));
 hs1(page+0x100);memcpy(page+0x100+20,query,64);put_unaligned_le32(BIT(15),page+0x10);
 run_work(&rx->work);
 assert(rt_zeros==2 && accepted_hs1==1 && controller->hs.state==CCCI_HANDSHAKE_WAIT_HS2);

 control_setup();assert(!ccci_ccif_control_start(controller,offers,ports,&dev));run_work(&rx->work);
 now_ms=60100;run_work(&controller->timer.work);
 assert(ccci_ccif_control_error(controller)==-ETIMEDOUT && ccci_ccif_rx_error(rx)==-ETIMEDOUT);
 assert(!rx->armed && !rx->active && depths[0]==1 && depths[1]==1);
 assert(control_fault_calls==1 && control_fault_error==-ETIMEDOUT);
 control_timeout(&controller->timer.work);assert(control_fault_calls==1);
 control_setup();assert(!ccci_ccif_control_start(controller,offers,ports,&dev));
 hs1(page+0x100);memcpy(page+0x100+20,query,64);
 put_unaligned_le32(BIT(15),page+0x10);put_unaligned_le32(BIT(15),page+4);
 run_work(&rx->work);
 assert(ccci_ccif_control_error(controller)==-EBUSY && ccci_ccif_rx_error(rx)==-EBUSY);
 assert(!controller->active && !rx->armed && !doorbells && !rt_writes && !port_calls);
 assert(control_fault_calls==1 && control_fault_error==-EBUSY);
 /* Accepted HS1 callback failure contains RX after publication, with one fault notice. */
 control_setup();assert(!ccci_ccif_control_start(controller,offers,ports,&dev));
 port_error=-EHOSTDOWN;hs1(page+0x100);memcpy(page+0x100+20,query,64);
 put_unaligned_le32(BIT(15),page+0x10);run_work(&rx->work);
 assert(port_calls==1 && accepted_hs1==1 && !accepted_hs2 && doorbells==1);
 assert(ccci_ccif_control_error(controller)==-EHOSTDOWN && ccci_ccif_rx_error(rx)==-EHOSTDOWN);
 assert(control_fault_calls==1 && control_fault_error==-EHOSTDOWN && !controller->active);
 control_timeout(&controller->timer.work);assert(control_fault_calls==1);
 /* A receive fault before any control event must also reach the fault subscriber. */
 control_setup();assert(!ccci_ccif_control_start(controller,offers,ports,&dev));
 ccci_ccif_rx_abort(rx,-EILSEQ);assert(!control_fault_calls && !port_calls);
 run_work(&controller->timer.work);
 assert(control_fault_calls==1 && control_fault_error==-EILSEQ && !port_calls);
 control_setup();start();unsigned before=rt_zeros;
 assert(ccci_ccif_control_start(controller,offers,ports,&dev)==-EALREADY && rt_zeros==before);
 control_setup();offers[0].length=0;
 assert(ccci_ccif_control_start(controller,offers,ports,&dev)==-EMSGSIZE && !rt_zeros && !controller->attempted);
 control_setup();interrupt0();assert(ccci_ccif_control_start(controller,offers,ports,&dev)==-EIO && !rt_zeros);
 control_setup();assert(!ccci_ccif_control_start(controller,offers,ports,&dev));
 ccci_ccif_control_quiesce(controller);ccci_ccif_rx_stop(rx);unsigned count=reads;
 control_timeout(&controller->timer.work);assert(reads==count && !controller->active && !controller->timer.work.pending);
 control_cleanup();
}
int main(void){
 baseline_tests();codec();transmit();state_machine();controller_tests();
 puts("PASS: actual 64-slot runtime negotiation/geometry/v2.1 codec, 601 TX failure positions,");
 puts("      accepted HS1/HS2 callback ordering/failure, timeout and persistent RX fault reporting");
}
'''


def main(extra_test='', extra_units=()):
    with tempfile.TemporaryDirectory(prefix='op6893-handshake-') as tmp:
        root = Path(tmp)
        inc = root / 'linux'
        inc.mkdir()
        (inc/'types.h').write_text('#pragma once\n#include <stdint.h>\n#include <stdbool.h>\n'
            'typedef uint8_t u8;typedef uint16_t u16;typedef uint32_t u32;typedef uint64_t u64;\n')
        (inc/'unaligned.h').write_text('#pragma once\n#include <linux/types.h>\n'
            'static inline u16 get_unaligned_le16(const void *p){const u8 *b=p;return b[0]|(u16)b[1]<<8;}\n'
            'static inline void put_unaligned_le16(u16 v,void *p){u8 *b=p;b[0]=v;b[1]=v>>8;}\n'
            'static inline u32 get_unaligned_le32(const void *p){const u8 *b=p;'
            'return (u32)b[0]|(u32)b[1]<<8|(u32)b[2]<<16|(u32)b[3]<<24;}\n'
            'static inline u64 get_unaligned_le64(const void *p){return get_unaligned_le32(p)|'
            '(u64)get_unaligned_le32((const u8 *)p+4)<<32;}\n'
            'static inline void put_unaligned_le32(u32 v,void *p){u8 *b=p;for(unsigned i=0;i<4;i++)b[i]=v>>(8*i);}\n')
        (inc/'limits.h').write_text('#include <stdint.h>\n#define U64_MAX UINT64_MAX\n#define U32_MAX UINT32_MAX\n')
        (inc/'errno.h').write_text('#include <asm-generic/errno.h>\n')
        (inc/'string.h').write_text('#include <string.h>\n')
        (inc/'kernel.h').write_text('#define ARRAY_SIZE(a) (sizeof(a)/sizeof((a)[0]))\n'
                                  '#define ALIGN(n,a) (((n)+(a)-1)&~((a)-1))\n'
                                  '#define min(a,b) ((a)<(b)?(a):(b))\n'
                                  '#define lower_32_bits(n) ((u32)((n) & 0xffffffffULL))\n'
                                  '#define upper_32_bits(n) ((u32)(((n) >> 32) & 0xffffffffULL))\n')
        (inc/'bitops.h').write_text('#ifndef BIT\n#define BIT(n) (1U<<(n))\n#endif\n')
        (inc/'random.h').write_text('#pragma once\n#include <linux/types.h>\n'
                                  '/* Harness model: a fixed seed keeps record bytes comparable. */\n'
                                  'static inline u32 get_random_u32(void) { return 0x5a5a1234U; }\n')
        (inc/'time.h').write_text('#pragma once\n'
                                'struct timezone { int tz_minuteswest; int tz_dsttime; };\n'
                                'extern struct timezone sys_tz;\n')
        (inc/'timekeeping.h').write_text('#pragma once\n'
                                       'struct timespec64 { long long tv_sec; long tv_nsec; };\n'
                                       'static inline void ktime_get_real_ts64(struct timespec64 *ts)\n'
                                       '{ ts->tv_sec = 1700000000LL; ts->tv_nsec = 0; }\n')
        for name in ('device.h', 'err.h', 'interrupt.h', 'io.h', 'slab.h', 'spinlock.h',
                     'workqueue.h', 'completion.h', 'kconfig.h', 'ioport.h', 'jiffies.h', 'ktime.h', 'mutex.h', 'sysfs.h'):
            (inc/name).write_text('/* Models supplied by the harness. */\n')
        test = TEST if not extra_test else TEST.replace('int main(void){', 'static void handshake_tests(void){') + extra_test
        (root/'test.c').write_text(shim+baseline+GLUE+test)
        units = ['ccci-ccif-ring.c', 'ccci-ccif-protocol.c', 'ccci-runtime.c',
                 'ccci-ccif-tx.c', 'ccci-handshake.c', *extra_units]
        subprocess.run(['cc', '-O1', '-g', '-Wall', '-Wextra', '-Werror',
            '-Wno-misleading-indentation', '-Wno-sign-compare', '-fsanitize=address,undefined',
            '-fno-sanitize-recover=all', '-no-pie', '-D__iomem=', '-I'+str(root),
            '-I'+str(SRC), '-I'+str(K/'include'),
            *[str(SRC/n) for n in units], str(root/'test.c'), '-o', str(root/'test')], check=True)
        subprocess.run([str(root/'test')], check=True)


if __name__ == '__main__':
    main()
