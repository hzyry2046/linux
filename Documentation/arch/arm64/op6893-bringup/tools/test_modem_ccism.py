#!/usr/bin/env python3
# SPDX-License-Identifier: GPL-2.0-only
"""Actual CCISM protocol C with synthetic MD/SCP peers and fallible operations."""
from pathlib import Path
import runpy

base = runpy.run_path(str(Path(__file__).with_name('test_modem_handshake.py')))

TEST = r'''
#include "ccci-ccism.h"
static struct ccci_ccism cm;
static struct ccci_ccism_plan cp;
static struct ccci_smem_layout cs;
static unsigned calls[6], fail_op, fail_n, order[32], order_n;
static bool provider_ready;
static int op(unsigned n){assert(order_n<32);order[order_n++]=n;calls[n]++;return n==fail_op && calls[n]==fail_n?-EACCES:0;}
static int cm_check(void *ctx,u64 gen){assert(ctx==&cm && gen==1);return provider_ready?0:-ESHUTDOWN;}
static int cm_on(void *ctx){assert(ctx==&cm && cm.state==CCCI_CCISM_WAIT_MD_ACK);return op(0);}
static int cm_md(void *ctx,u32 msg){
 assert(ctx==&cm && ((msg==CCCI_CCISM_INIT && cm.state==CCCI_CCISM_WAIT_MD_ACK) ||
 (msg==CCCI_CCISM_DONE && cm.state==CCCI_CCISM_WAIT_MD_DONE)));return op(msg==CCCI_CCISM_INIT?1:4);
}
static int cm_clear(void *ctx,u32 ap,u32 size){assert(ctx==&cm && ap==0x80120000 && size==32768);return op(2);}
static int cm_send(void *ctx,u16 opc,u32 data){
 assert(ctx==&cm);
 if(opc==CCCI_SCP_OP_SHM_INIT){assert(data==cp.ap && cm.state==CCCI_CCISM_WAIT_RBREADY);return op(3);}
 assert(opc==CCCI_SCP_OP_MD_STATE);
 if(data==2){assert(cm.state==CCCI_CCISM_WAIT_MD_DONE);return op(5);}
 assert(!data && cm.state==CCCI_CCISM_WAIT_STOP);return op(3);
}
static int cm_off(void *ctx){assert(ctx==&cm && cm.state==CCCI_CCISM_WAIT_STOP && cm.stop_seen);return op(0);}
static const struct ccci_ccism_ops cm_ops={cm_check,cm_on,cm_md,cm_clear,cm_send,cm_off};
static void cm_setup(void){
 memset(&cm,0,sizeof(cm));memset(&cs,0,sizeof(cs));memset(calls,0,sizeof(calls));
 cs.noncached=(struct ccci_lk_region){0x80000000,0x1800000};
 cs.users[16]=(struct ccci_smem_region){.ap=0x80120000,.md=0x40120000,.size=32768,.present=true};
 assert(!ccci_ccism_plan(&cs,&cp));order_n=0;fail_op=99;fail_n=1;provider_ready=true;
 assert(!ccci_ccism_arm(&cm,&cm_ops,&cm,&cp,1,100));assert(!order_n && cm.state==CCCI_CCISM_ARMED);
}
static int cm_message(u32 msg,u32 queue,u16 chan,u32 size){
 u8 packet[20]={0};put_unaligned_le32(msg,packet+4);put_unaligned_le32(chan,packet+8);
 struct ccci_ccif_event e={.type=CCCI_CCIF_EVENT_RING,.data=packet,.size=size,.queue=queue};
 return ccci_ccism_md_event(&cm,&e,200);
}
static void cm_ack(void){assert(!cm_message(CCCI_CCISM_ACK,0,2,16));}
static void cm_rb(void){assert(!ccci_ccism_scp_state(&cm,1,CCCI_SCP_STATE_RBREADY,200));}
static void cm_running(void){
 cm_setup();assert(!ccci_ccism_md_ready(&cm,200));cm_ack();cm_rb();
 assert(!cm_message(CCCI_CCISM_DONE,0,2,16) && cm.state==CCCI_CCISM_RUNNING);
}
static void ccism_tests(void){
 cm_running();assert(cm.rbready_seen && cm.md_done_seen && cm.bridge_touched && !cm.stop_seen);
 assert(order_n==6);for(unsigned i=0;i<6;i++)assert(order[i]==i);
 assert(!ccci_ccism_tick(&cm,1000000));unsigned saved=order_n;
 assert(ccci_ccism_stop(&cm,false,1000001)==-EBUSY && order_n==saved);
 assert(!ccci_ccism_stop(&cm,true,1000001) && cm.state==CCCI_CCISM_WAIT_STOP && cm.bridge_touched);
 assert(ccci_ccism_stop(&cm,true,1000002)==-EALREADY);
 assert(!ccci_ccism_scp_state(&cm,1,CCCI_SCP_STATE_STOP,1000002));
 assert(cm.state==CCCI_CCISM_STOPPED && !cm.bridge_touched && cm.stop_seen);
 saved=order_n;assert(!ccci_ccism_stop(&cm,true,1000003) && order_n==saved);
 assert(ccci_ccism_scp_state(&cm,1,CCCI_SCP_STATE_STOP,1000004)==-ESHUTDOWN && cm.state==CCCI_CCISM_STOPPED);
 assert(ccci_ccism_arm(&cm,&cm_ops,&cm,&cp,1,1000004)==-EALREADY);
 /* All six forward side effects fail independently, with no later operation. */
 for(unsigned n=0;n<6;n++){
  cm_setup();fail_op=n;int r=ccci_ccism_md_ready(&cm,200);
  if(n>1){assert(!r);r=cm_message(CCCI_CCISM_ACK,0,2,16);}
  if(n>3){assert(!r);r=ccci_ccism_scp_state(&cm,1,CCCI_SCP_STATE_RBREADY,200);}
  if(n>4){assert(!r);r=cm_message(CCCI_CCISM_DONE,0,2,16);}
  assert(r==-EACCES && cm.state==CCCI_CCISM_FAILED && cm.bridge_touched && order_n==n+1);
  fail_op=99;assert(!ccci_ccism_stop(&cm,true,300));
  assert(!ccci_ccism_scp_state(&cm,1,CCCI_SCP_STATE_STOP,301));
  assert(cm.state==CCCI_CCISM_STOPPED && cm.error==-EACCES && !cm.cleanup_error);
 }
 /* No shared-memory clear before MD ACK; no synthetic RBREADY or retry. */
 cm_setup();assert(ccci_ccism_scp_state(&cm,1,CCCI_SCP_STATE_RBREADY,200)==-EPROTO && !order_n);
 cm_setup();assert(cm_message(CCCI_CCISM_ACK,0,2,16)==-EPROTO && !order_n);
 cm_setup();assert(!ccci_ccism_md_ready(&cm,200));
 assert(ccci_ccism_scp_state(&cm,2,CCCI_SCP_STATE_RBREADY,200)==-ESTALE && !calls[2]);
 cm_setup();assert(!ccci_ccism_md_ready(&cm,200));cm_ack();
 assert(cm_message(CCCI_CCISM_ACK,0,2,16)==-EPROTO && calls[2]==1);
 cm_setup();assert(!ccci_ccism_md_ready(&cm,200));assert(cm_message(CCCI_CCISM_ACK,1,2,16)==-EPROTO && !calls[2]);
 cm_setup();assert(!ccci_ccism_md_ready(&cm,200));assert(cm_message(CCCI_CCISM_ACK,0,0,16)==-EPROTO && !calls[2]);
 cm_setup();assert(!ccci_ccism_md_ready(&cm,200));assert(cm_message(CCCI_CCISM_ACK,0,2,20)==-EPROTO && !calls[2]);
 cm_setup();assert(cm_message(0x123,0,2,16)==-EOPNOTSUPP && cm.state==CCCI_CCISM_ARMED);
 for(unsigned phase=0;phase<3;phase++){
  cm_setup();assert(!ccci_ccism_md_ready(&cm,200));if(phase)cm_ack();if(phase==2)cm_rb();
  assert(ccci_ccism_tick(&cm,60200)==-ETIMEDOUT && cm.bridge_touched);
 }
 cm_setup();assert(ccci_ccism_tick(&cm,99)==-ERANGE && !order_n);
 cm_setup();assert(ccci_ccism_md_ready(&cm,UINT64_MAX-1)==-ERANGE && !order_n);
 cm_running();assert(!ccci_ccism_stop(&cm,true,300));
 assert(ccci_ccism_tick(&cm,3300)==-ETIMEDOUT && cm.cleanup_error==-ETIMEDOUT && cm.bridge_touched && !cm.stop_seen);
 saved=order_n;assert(ccci_ccism_stop(&cm,true,3400)==-EALREADY && order_n==saved);
 cm_running();fail_op=0;fail_n=2;assert(!ccci_ccism_stop(&cm,true,300));
 assert(ccci_ccism_scp_state(&cm,1,CCCI_SCP_STATE_STOP,301)==-EACCES && cm.cleanup_error==-EACCES && cm.bridge_touched);
 cm_setup();assert(!ccci_ccism_md_ready(&cm,200));cm_ack();cm_rb();
 assert(ccci_ccism_scp_state(&cm,1,CCCI_SCP_STATE_RBREADY,201)==-EPROTO && calls[4]==1);
 cm_setup();assert(!ccci_ccism_md_ready(&cm,200));cm_ack();
 assert(cm_message(CCCI_CCISM_DONE,0,2,16)==-EPROTO && !calls[5]);
 cm_running();assert(ccci_ccism_scp_state(&cm,1,CCCI_SCP_STATE_BOOTING,300)==-ECONNRESET && cm.bridge_touched && calls[0]==1);
 cm_running();assert(ccci_ccism_scp_state(&cm,1,CCCI_SCP_STATE_STOP,300)==-EPROTO && cm.bridge_touched && calls[0]==1);
 cm_running();provider_ready=false;assert(ccci_ccism_tick(&cm,300)==-ESHUTDOWN && cm.bridge_touched);
 cm_setup();assert(!ccci_ccism_stop(&cm,true,200) && !order_n);
 for(unsigned n=0;n<8;n++){
  cm_setup();switch(n){case 0:cs.users[16].cached=true;break;case 1:cs.users[16].no_map=true;break;
   case 2:cs.users[16].size=32764;break;case 3:cs.users[16].md++;break;
   case 4:cs.noncached.base+=UINT64_C(0x100000000);cs.users[16].ap+=UINT64_C(0x100000000);break;case 5:cs.users[16].ap++;break;
   case 6:cs.noncached.size=0x100;break;case 7:cs.users[16].present=false;break;}
  memset(&cp,0x5a,sizeof(cp));assert(ccci_ccism_plan(&cs,&cp)<0);assert_zero(&cp,sizeof(cp));
 }
 puts("PASS: actual post-HS2 CCISM INIT/ACK/clear/SHM_INIT/RBREADY/DONE, all side-effect failures,");
 puts("      source/order/generation/deadlines, STOP-before-clock-off and geometry under ASan/UBSan");
}
int main(void){handshake_tests();ccism_tests();}
'''

if __name__ == '__main__':
    base['main'](TEST, ['ccci-scp-protocol.c', 'ccci-ccism.c'])
