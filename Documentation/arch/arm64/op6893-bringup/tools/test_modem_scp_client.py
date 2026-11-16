#!/usr/bin/env python3
# SPDX-License-Identifier: GPL-2.0-only
"""Actual SCP client lease/send/revoke with the actual runtime consumer/STOP."""
from pathlib import Path
import runpy

base = runpy.run_path(str(Path(__file__).with_name('test_modem_scp_runtime.py')))
D, block, compile_run = base['D'], base['block'], base['compile_run']

EXTRA = r'''
static unsigned notices,fault_notices;
static u32 last_state;
static void client_notice(void *ctx,u64 gen,u32 state,int error){
 assert(ctx==&notices && gen==1 && lock->held);notices++;last_state=state;
 if(error)fault_notices++;
}
static struct ccci_scp_client client;
static void client_setup(struct ccci_scp_resource_owner *o){
 setup(o);assert(!start(o));memset(&client,0,sizeof(client));
 client.owner=o;client.notify=client_notice;client.context=&notices;
 notices=fault_notices=last_state=0;
}
static void lease(struct ccci_scp_resource_owner *o){u64 gen=99;assert(!ccci_scp_client_acquire(&client,&gen) && gen==1 && o->runtime.client==&client);}
static void test_client(void){
 struct ccci_scp_resource_owner o;u64 gen=99;
 setup(&o);client=(struct ccci_scp_client){.owner=&o,.notify=client_notice,.context=&notices};
 assert(ccci_scp_client_acquire(&client,&gen)==-ESHUTDOWN && !gen && !o.runtime.client_attempted && !gets);
 client_setup(&o);lease(&o);assert(ccci_scp_client_acquire(&client,&gen)==-EBUSY && !gen);
 assert(!ccci_scp_client_check(&client,1) && ccci_scp_client_check(&client,2)==-ESTALE);
 struct device dev={&o};unsigned old=stops;
 assert(runtime_store(&dev,NULL,"stop",4)==-EBUSY && stops==old && o.runtime.ready);
 assert(runtime_store(&dev,NULL,"md-invalid",10)==-EBUSY && !tx_calls && o.runtime.ready);
 unsigned g=gets,p=put_calls,t=tx_calls;
 assert(ccci_scp_client_send(&client,CCCI_SCP_OP_SHM_INIT,0x80120000)==0);
 assert(last_op==2 && last_data==0x80120000 && gets==g+1 && put_calls==p+1 && tx_calls==t+1);
 assert(client.tx_completed==1 && !o.runtime.tx_completed && !o.runtime.awake.users);
 assert(!ccci_scp_client_send(&client,CCCI_SCP_OP_MD_STATE,2) && client.tx_completed==2);
 g=gets;t=tx_calls;assert(ccci_scp_client_send(&client,2,3)==-EINVAL && gets==g && tx_calls==t);
 assert(ccci_scp_client_send(&client,0,0)==-EOPNOTSUPP && gets==g && tx_calls==t);
 struct ccci_scp_event ev={.generation=1,.pin={.channel=7},.bytes=8,.data={2}};
 mutex_lock(lock);assert(!ccci_scp_runtime_consume(&o,&ev,0));mutex_unlock(lock);
 assert(notices==1 && last_state==2 && !fault_notices && o.runtime.ready);
 ev.generation=2;mutex_lock(lock);assert(ccci_scp_runtime_consume(&o,&ev,0)==-ESTALE);mutex_unlock(lock);
 assert(notices==2 && fault_notices==1 && client.faulted && !o.runtime.ready);
 assert(ccci_scp_client_send(&client,1,0)==-ESHUTDOWN);
 mutex_lock(&o.runtime.control);assert(!ccci_scp_runtime_stop(&o));mutex_unlock(&o.runtime.control);
 assert(notices==2);ccci_scp_client_release(&client);
 assert(!o.runtime.client && !client.attached && ccci_scp_client_check(&client,1)==-ESTALE);
 assert(ccci_scp_client_acquire(&client,&gen)==-EALREADY);
 /* Detach joins callbacks under owner lock; later events cannot call old context. */
 client_setup(&o);lease(&o);ccci_scp_client_release(&client);ev.generation=1;
 mutex_lock(lock);assert(!ccci_scp_runtime_consume(&o,&ev,0));mutex_unlock(lock);assert(!notices);
 assert(ccci_scp_client_acquire(&client,&gen)==-EALREADY);stop(&o);
 /* RBREADY from before the lease is never replayed as a fresh SHM_INIT reply. */
 client_setup(&o);o.runtime.apccci_events=1;o.runtime.apccci_state=2;
 assert(ccci_scp_client_acquire(&client,&gen)==-EPROTO && !o.runtime.client_attempted);stop(&o);
 /* Every hardware failure revokes once; a failed TX still pairs awake put. */
 for(unsigned n=0;n<5;n++){
  client_setup(&o);lease(&o);g=gets;p=put_calls;t=tx_calls;
  if(n==0)get_error=-EIO;
  if(n==1)tx_error=-ETIMEDOUT;
  if(n==2)put_error=-EBUSY;
  if(n==3)fail_at=checks+1;
  if(n==4)fail_at=checks+2;
  assert(ccci_scp_client_send(&client,1,0)<0 && client.faulted && fault_notices==1 && !o.runtime.ready);
  assert(o.runtime.fault_work.pending && !client.tx_completed);
  if(n==1)assert(gets==g+1 && put_calls==p+1 && tx_calls==t+1 && !o.runtime.awake.users);
  if(n==0)assert(put_calls==p && tx_calls==t);
  old=notices;mutex_lock(&o.runtime.control);ccci_scp_runtime_stop(&o);mutex_unlock(&o.runtime.control);
  assert(notices==old);ccci_scp_client_release(&client);
 }
 client_setup(&o);lease(&o);get_error=-EBUSY;struct device failed_dev={&o};
 assert(runtime_store(&failed_dev,NULL,"awake",5)==-EBUSY && !o.runtime.active && !o.runtime.ready && fault_notices==1);
 ccci_scp_client_release(&client);
 puts("PASS: actual SCP client READY/generation lease, shared awake, bounded APCCCI send, STOP veto,");
 puts("      stale rejection, scalar notifications, fault revocation, detach and one-shot under ASan/UBSan");
}
int main(void){runtime_tests();test_client();}
'''


def clean(name):
    return '\n'.join(line for line in (D / name).read_text().splitlines()
                     if not line.startswith('#include'))


def main():
    prefix = base['prefix'] + r'''
typedef uint8_t u8;
#define CCCI_SCP_STATE_RBREADY 2
#define CCCI_SCP_OP_MD_STATE 1
#define CCCI_SCP_OP_SHM_INIT 2
static u16 last_op;
static u32 last_data;
static void put_unaligned_le16(u16 v,void *p){memcpy(p,&v,2);}
static void put_unaligned_le32(u32 v,void *p){memcpy(p,&v,4);}
static int ccci_scp_mmio_apccci(void *m,const void *l,u64 gen,u16 op,u32 data){
 (void)m;(void)l;assert(lock->held && gen==1 && gets>put_calls);tx_calls++;last_op=op;last_data=data;return tx_error;
}
'''
    codec = block((D/'ccci-scp-protocol.c').read_text(), 'int ccci_scp_encode(')
    reset = clean('ccci-scp-reset.c').replace('reset->attempted = true;',
                                             'reset->attempted = true; resets++;')
    code = prefix.replace('static ', 'static __attribute__((unused)) ') + codec
    code += clean('ccci-scp-awake.h') + base['awake_stubs']
    code += clean('ccci-scp-runtime.h') + clean('ccci-scp-reset.h') + reset + base['owner']
    source = (D/'ccci-scp-runtime.c').read_text()
    for name in ('notify', 'stop', 'fault_work', 'consume', 'asserted', 'awake', 'start'):
        kind = 'void' if name in ('notify', 'fault_work') else 'int'
        code += block(source, f'static {kind} ccci_scp_runtime_{name}(')
    code += block(source, 'static ssize_t runtime_store(')
    source = (D/'ccci-scp-client.c').read_text()
    for signature in ('static int scp_client_check(', 'int ccci_scp_client_acquire(',
                      'int ccci_scp_client_check(', 'static void scp_client_fault(',
                      'int ccci_scp_client_send(', 'void ccci_scp_client_release('):
        code += block(source, signature)
    compile_run(code + base['tests'].replace('int main(void){', 'static void runtime_tests(void){') + EXTRA)


if __name__ == '__main__':
    main()
