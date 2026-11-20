#!/usr/bin/env python3
# SPDX-License-Identifier: GPL-2.0-only
"""Actual asynchronous CCISM session C with bounded queue/work/timer models.

Exercises deterministic lock interleavings; does not prove concurrent SMP use.
"""
from pathlib import Path
import runpy

base = runpy.run_path(str(Path(__file__).with_name('test_modem_handshake.py')))
# The session admits immediate wakeups and exact short cleanup deadlines.
base['main'].__globals__['GLUE'] = base['GLUE'].replace(
    'assert(delay==1000)', 'assert(delay<=1000)')

TEST = r'''
#define kzalloc_obj(obj) calloc(1,sizeof(obj))
#define kfree(p) free(p)
#define memzero_explicit(ptr, size) memset(ptr, 0, size)
#define min_t(type,a,b) ((type)(a)<(type)(b)?(type)(a):(type)(b))
struct completion { bool done; };
static void init_completion(struct completion *c) { c->done = false; }
static void reinit_completion(struct completion *c) { c->done = false; }
static void complete_all(struct completion *c) { c->done = true; }
static void (*during_wait)(void);
static unsigned long wait_for_completion_timeout(struct completion *c, unsigned long timeout);
#include "ccci-ccism-session.c"
static unsigned s_calls[6],s_faults;
static bool s_provider,s_in_notify;
static int s_context;
static struct ccci_ccism_session *sess;
static bool s_fault_during_check;
static int s_check(void *ctx,u64 gen){
 assert(!s_in_notify && ctx==&s_context && (gen==61 || gen==62));
 if(s_fault_during_check){s_fault_during_check=false;ccci_ccism_session_scp_notify(sess,gen,0,-EIO);}
 return s_provider?0:-ESHUTDOWN;
}
static int s_on(void *ctx){assert(!s_in_notify && ctx==&s_context);s_calls[0]++;return 0;}
static int s_md(void *ctx,u32 message){
 assert(!s_in_notify && ctx==&s_context);
 assert(message==CCCI_CCISM_INIT || message==CCCI_CCISM_DONE);s_calls[message==CCCI_CCISM_INIT?1:4]++;return 0;
}
static int s_clear(void *ctx,u32 ap,u32 size){
 assert(!s_in_notify && ctx==&s_context && ap==0x80120000 && size==32768);s_calls[2]++;return 0;
}
static int s_scp(void *ctx,u16 op,u32 data){
 assert(!s_in_notify && ctx==&s_context);
 assert((op==CCCI_SCP_OP_SHM_INIT && data==0x80120000) || (op==CCCI_SCP_OP_MD_STATE && (data==0 || data==2)));
 s_calls[3]++;return 0;
}
static int s_off(void *ctx){assert(!s_in_notify && ctx==&s_context);s_calls[5]++;return 0;}
static void s_fault(void *ctx,int error){assert(ctx==&s_context && error<0);s_faults++;}
static const struct ccci_ccism_ops s_ops={s_check,s_on,s_md,s_clear,s_scp,s_off};
static void s_create(void){
 struct ccci_ccism_plan p={.ap=0x80120000,.md=0x40120000,.size=32768};
 memset(s_calls,0,sizeof(s_calls));s_faults=0;s_provider=true;s_in_notify=false;s_fault_during_check=false;now_ms=100;
 sess=ccci_ccism_session_create(&dev,&s_ops,&s_context,&p,s_fault);assert(!IS_ERR(sess));
 assert(!sess->work.work.pending && !sess->armed);
}
static void s_new(void){s_create();assert(!ccci_ccism_session_arm(sess,61));}
static void s_run(void){assert(sess->work.work.pending);run_work(&sess->work.work);}
static void s_state(u64 generation,u32 state,int error){
 s_in_notify=true;ccci_ccism_session_scp_notify(sess,generation,state,error);s_in_notify=false;
}
static unsigned long wait_for_completion_timeout(struct completion *c, unsigned long timeout)
{
 assert(!sess->lock.held && timeout==CCCI_CCISM_STOP_MS);
 if (!c->done && during_wait)
  during_wait();
 return c->done;
}
static int s_begin_stop(void){
 mutex_lock(&sess->lock);
 int ret=ccism_session_begin_stop(sess);
 mutex_unlock(&sess->lock);
 return ret;
}
static void s_stop_reply(void){
 s_state(61,CCCI_SCP_STATE_STOP,0);s_run();
}
static void s_stop_stale(void){
 s_state(62,CCCI_SCP_STATE_STOP,0);s_run();
}
static void s_message(u32 message){
 u8 p[16]={0};put_unaligned_le32(message,p+4);put_unaligned_le32(2,p+8);
 struct ccci_ccif_event e={.type=CCCI_CCIF_EVENT_RING,.size=16,.data=p};
 assert(!ccci_ccism_session_md_event(sess,&e));memset(p,0x5a,sizeof(p));
}
static void s_running(void){
 s_new();assert(!ccci_ccism_session_md_ready(sess));assert(!s_calls[0]);s_run();assert(s_calls[0]==1 && s_calls[1]==1);
 s_message(CCCI_CCISM_ACK);assert(!s_calls[2]);s_run();assert(s_calls[2]==1 && s_calls[3]==1);
 s_state(61,CCCI_SCP_STATE_RBREADY,0);assert(!s_calls[4]);s_run();assert(s_calls[4]==1);
 s_message(CCCI_CCISM_DONE);s_run();assert(sess->core.state==CCCI_CCISM_RUNNING && s_calls[3]==2);
}
static void s_finish(void){
 assert(!s_begin_stop());assert(sess->core.state==CCCI_CCISM_WAIT_STOP);
 assert(ccci_ccism_session_quiesce(sess)==-EBUSY && sess->scp_open);
 during_wait=s_stop_reply;assert(!ccci_ccism_session_stop(sess,true));during_wait=NULL;
 assert(sess->core.state==CCCI_CCISM_STOPPED && s_calls[5]==1);
 assert(!ccci_ccism_session_quiesce(sess) && !sess->work.work.pending);
 assert(ccci_ccism_session_md_ready(sess)==-ESHUTDOWN || sess->queue_error);
 assert(!ccci_ccism_session_destroy(sess));
}
static void session_tests(void){
 struct ccci_ccism_session_status st;
 s_running();ccci_ccism_session_status(sess,&st);assert(st.state==CCCI_CCISM_RUNNING && st.bridge_touched && st.generation==61);
 unsigned before=s_calls[3];assert(ccci_ccism_session_stop(sess,false)==-EBUSY && sess->md_open && sess->scp_open && s_calls[3]==before);
 assert(ccci_ccism_session_destroy(sess)==-EBUSY);s_finish();assert(!s_faults);
 /* A normal stop waits for its asynchronous reply in a single call. */
 s_running();during_wait=s_stop_reply;
 assert(!ccci_ccism_session_stop(sess,true) && s_calls[3]==3 && s_calls[5]==1);
 during_wait=NULL;assert(!ccci_ccism_session_destroy(sess));
 /* Repeated STOP preserves an already-enqueued response and its timer. */
 s_running();assert(!s_begin_stop());
 s_state(61,CCCI_SCP_STATE_STOP,0);u64 deadline=sess->core.deadline_ms;
 assert(ccci_ccism_session_stop(sess,true)==-ETIMEDOUT);
 assert(sess->count==1 && sess->work.work.pending && sess->core.deadline_ms==deadline);
 s_run();assert(sess->core.state==CCCI_CCISM_STOPPED && s_calls[5]==1);
 assert(!ccci_ccism_session_stop(sess,true));assert(!ccci_ccism_session_destroy(sess));
 /* Hardware is never touched by the provider callback, even on failure. */
 s_running();s_state(61,0,-EIO);assert(!s_faults);s_run();assert(s_faults==1 && !sess->md_open && sess->core.error==-EIO);s_finish();assert(s_faults==1);
 /* Overflow loses history, faults once, and preserves the future STOP path. */
 s_new();for(unsigned i=0;i<CCISM_SESSION_EVENTS;i++)assert(!ccci_ccism_session_md_ready(sess));
 assert(ccci_ccism_session_md_ready(sess)==-ENOSPC && !s_calls[0]);s_run();
 assert(sess->core.state==CCCI_CCISM_FAILED && sess->core.error==-ENOSPC && s_faults==1 && !s_calls[0]);
 assert(!ccci_ccism_session_stop(sess,true) && sess->core.state==CCCI_CCISM_STOPPED);
 assert(!ccci_ccism_session_destroy(sess));
 s_running();for(unsigned i=0;i<CCISM_SESSION_EVENTS+1;i++)s_state(61,CCCI_SCP_STATE_RBREADY,0);
 s_run();assert(sess->core.error==-ENOSPC && s_faults==1);s_finish();
 /* Arrival before or during arm cannot disappear in the lease-check gap. */
 s_create();s_state(61,0,-EIO);assert(ccci_ccism_session_arm(sess,61)==-EIO);assert(!ccci_ccism_session_destroy(sess));
 s_create();s_state(61,CCCI_SCP_STATE_RBREADY,0);assert(ccci_ccism_session_arm(sess,61)==-EPROTO);assert(!ccci_ccism_session_destroy(sess));
 s_create();s_fault_during_check=true;assert(ccci_ccism_session_arm(sess,61)==-EIO && s_faults==1);assert(!ccci_ccism_session_destroy(sess));
 /* A provider generation mismatch and missing ACK are contained. */
 s_running();s_state(62,CCCI_SCP_STATE_RBREADY,0);s_run();assert(sess->core.error==-ESTALE);s_finish();
 s_new();assert(!ccci_ccism_session_md_ready(sess));s_run();now_ms+=CCCI_CCISM_TIMEOUT_MS;s_run();
 assert(sess->core.error==-ETIMEDOUT && !sess->md_open && s_faults==1);s_finish();
 /* WAIT_STOP has a real bounded timeout; retained clocks forbid freeing. */
 s_running();assert(ccci_ccism_session_stop(sess,true)==-ETIMEDOUT);now_ms+=CCCI_CCISM_STOP_MS;s_run();
 assert(sess->core.cleanup_error==-ETIMEDOUT && ccci_ccism_session_destroy(sess)==-EBUSY);
 assert(ccci_ccism_session_stop(sess,true)==-ETIMEDOUT && s_calls[3]==3);
 /* Test-only release after asserting the production refusal above. */
 sess->core.bridge_touched=false;assert(!ccci_ccism_session_destroy(sess));
 /* The synchronous caller must see a stale reply's cleanup error. */
 s_running();during_wait=s_stop_stale;
 assert(ccci_ccism_session_stop(sess,true)==-ESTALE && !s_calls[5]);
 during_wait=NULL;assert(ccci_ccism_session_stop(sess,true)==-ESTALE && s_calls[3]==3);
 assert(ccci_ccism_session_destroy(sess)==-EBUSY);
 sess->core.bridge_touched=false;assert(!ccci_ccism_session_destroy(sess));
 /* Stop cancels already-queued forward traffic without powering a bridge. */
 s_new();assert(!ccci_ccism_session_md_ready(sess));assert(!ccci_ccism_session_stop(sess,true));
 assert(sess->core.state==CCCI_CCISM_STOPPED && !s_calls[0]);assert(!ccci_ccism_session_destroy(sess));
 s_running();s_state(61,0,-EIO);assert(!s_begin_stop());
 assert(sess->core.error==-EIO && s_faults==1);s_state(61,CCCI_SCP_STATE_STOP,0);s_run();
 assert(sess->core.state==CCCI_CCISM_STOPPED);assert(!ccci_ccism_session_destroy(sess));
 /* Rearm consumes clean STOP only and cannot reuse the old SCP epoch. */
 s_running();assert(ccci_ccism_session_rearm(sess)==-EBUSY);
 during_wait=s_stop_reply;assert(!ccci_ccism_session_stop(sess,true));during_wait=NULL;
 assert(!ccci_ccism_session_quiesce(sess));assert(sess->stop_done.done);
 assert(!ccci_ccism_session_rearm(sess) && !sess->stop_done.done);
 assert(ccci_ccism_session_arm(sess,61)==-ESTALE);
 assert(!ccci_ccism_session_arm(sess,62));
 assert(!ccci_ccism_session_stop(sess,true));assert(!ccci_ccism_session_destroy(sess));
 /* Quiesce cancels armed work, closes all ingress, and cannot be rearmed. */
 s_new();assert(!ccci_ccism_session_quiesce(sess));assert(!sess->work.work.pending);
 s_provider=false;ccism_session_work(&sess->work.work);assert(!sess->core.error);
 s_state(61,0,-EIO);assert(!sess->work.work.pending && !sess->queue_error);
 assert(ccci_ccism_session_arm(sess,61)==-ESHUTDOWN);assert(!ccci_ccism_session_destroy(sess));
 puts("PASS: actual CCISM session bounded queues, copied packets, asynchronous provider callbacks,");
 puts("      lease/arm races, sticky overflow, worker deadlines, STOP admission and retained-resource teardown");
}
int main(void){handshake_tests();session_tests();}
'''

if __name__ == '__main__':
    base['main'](TEST, ['ccci-scp-protocol.c', 'ccci-ccism.c'])
