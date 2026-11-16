#!/usr/bin/env python3
# SPDX-License-Identifier: GPL-2.0-only
"""Actual misc fops plus session/router/codecs with synthetic user memory.

Models locks/work deterministically; not an SMP or Linux misc-core proof.
No device, firmware, file-service or private bytes are accessed.
"""
from pathlib import Path
import runpy
import subprocess
import tempfile
import textwrap

K = Path(__file__).resolve().parents[5]
BASE = runpy.run_path(str(Path(__file__).with_name('test_modem_service_session.py')))
PREFIX = BASE['TEST'].split('#include "ccci-service-session.c"')[0]
SHIM = r'''
#include <stdarg.h>
static u64 shim_clock_now(void){return now_ms;}
#include <sys/types.h>
#define CONFIG_OP6893_CCCI_SERVICES 1
#define IS_ENABLED(x) (x)
#define __user
#define THIS_MODULE NULL
#define CAP_SYS_RAWIO 17
#define O_NONBLOCK 2048
#define EPOLLERR 8
#define EPOLLHUP 16
#define EPOLLIN 1
#define EPOLLRDNORM 64
#define MISC_DYNAMIC_MINOR 255
#define PTR_ERR(p) ((int)(intptr_t)(p))
#define READ_ONCE(x) (x)
typedef unsigned __poll_t;
typedef int poll_table;
typedef int wait_queue_head_t;
struct inode {int unused;};
struct file {void *private_data;int f_flags;};
struct file_operations {
 void *owner;
 int (*open)(struct inode *,struct file *);
 int (*release)(struct inode *,struct file *);
 ssize_t (*read)(struct file *,char *,size_t,loff_t *);
 ssize_t (*write)(struct file *,const char *,size_t,loff_t *);
 __poll_t (*poll)(struct file *,poll_table *);
 void *llseek;
};
#define noop_llseek NULL
struct miscdevice {char *name;unsigned minor,mode;struct device *parent;const struct file_operations *fops;};
static bool rawio,copy_read_fault,copy_write_fault;
static unsigned wakeups,registered,deregistered,free_calls,reply_sends,ccif_aborts;
static int fail_misc,fail_action;
static u32 last_reply_length;
static int capable(int cap){assert(cap==CAP_SYS_RAWIO);return rawio;}
#define init_waitqueue_head(p) (*(p)=0)
static void wake_up_interruptible(wait_queue_head_t *w){(void)w;wakeups++;}
#define wait_event_interruptible(w,condition) ((void)(w),(void)(condition),-EINTR)
static void poll_wait(struct file *f,wait_queue_head_t *w,poll_table *p){(void)f;(void)w;(void)p;}
struct kref {unsigned count;};
static void kref_init(struct kref *r){r->count=1;}
static void kref_get(struct kref *r){assert(r->count);r->count++;}
static void kref_put(struct kref *r,void (*fn)(struct kref *)){assert(r->count);if(!--r->count)fn(r);}
static void *kvmalloc(size_t n,int flags){(void)flags;return malloc(n);}
static void kfree_sensitive(void *p){free(p);}
#define kfree(p) free(p)
static int copy_to_user(void *to,const void *from,size_t n){
 assert(!spin_depth);if(copy_read_fault)return 1;memcpy(to,from,n);return 0;
}
static void *memdup_user(const void *from,size_t n){
 assert(!spin_depth);if(copy_write_fault)return ERR_PTR(-EFAULT);
 void *p=malloc(n);assert(p);memcpy(p,from,n);return p;
}
static char *kasprintf(int flags,const char *format,...){
 (void)flags;char buffer[128];va_list ap;va_start(ap,format);vsnprintf(buffer,sizeof(buffer),format,ap);va_end(ap);
 size_t n=strlen(buffer)+1;char *out=malloc(n);assert(out);memcpy(out,buffer,n);return out;
}
static int sysfs_emit(char *out,const char *format,...){va_list ap;va_start(ap,format);int n=vsnprintf(out,4096,format,ap);va_end(ap);return n;}
static const char *dev_name(struct device *d){assert(d);return "synthetic";}
static int misc_register(struct miscdevice *m){assert(m->mode==0600&&m->fops);if(fail_misc)return fail_misc;registered++;return 0;}
static void misc_deregister(struct miscdevice *m){assert(m->name);deregistered++;}
static int devm_add_action_or_reset(struct device *d,void (*fn)(void *),void *p){assert(d);if(fail_action){fn(p);return fail_action;}return 0;}
static u64 get_unaligned_le64(const void *p){const u8 *b=p;u64 n=0;for(unsigned i=0;i<8;i++)n|=(u64)b[i]<<(8*i);return n;}
static void put_unaligned_le64(u64 v,void *p){u8 *b=p;for(unsigned i=0;i<8;i++)b[i]=v>>(8*i);}
#include "ccci-service-session.c"
#include "ccci-service-endpoint.c"
static u8 last_reply[CCCI_FS_MESSAGE_MAX];
static struct device dev;
static struct ccci_ccif ccif;
static int ccci_ccif_service_send(struct ccci_ccif *c,const void *p,u32 n,bool hs2){
 (void)hs2;assert(c==&ccif&&p&&n>=21&&n<=sizeof(last_reply)&&!spin_depth);
 memcpy(last_reply,p,n);last_reply_length=n;reply_sends++;return 0;
}
static void ccci_ccif_abort(struct ccci_ccif *c,int error){assert(c==&ccif&&error<0&&!spin_depth);ccif_aborts++;}
'''
TEST = r'''
static struct ccci_service_endpoint *endpoint;
static struct file file;
static u8 request[CCCI_FS_MESSAGE_MAX],record[CCCI_FS_MESSAGE_MAX+32];
static loff_t offset;
static size_t fs_packet(u8 *p,u32 channel,u32 slot){
 u8 scalar[4]={1,2,3,4};struct ccci_fs_arg a={scalar,4};
 int n=ccci_fs_encode(p+16,CCCI_FS_MESSAGE_MAX-16,0xffff1005,&a,1);assert(n>0);
 memset(p,0,16);put_unaligned_le32(n+16,p+4);put_unaligned_le32(channel,p+8);put_unaligned_le32(slot,p+12);return n+16;
}
static void run(void){
 struct work_struct *w=&endpoint->session->work.work;assert(w->pending&&!w->running);
 w->pending=false;w->running=true;w->fn(w);w->running=false;
}
static void create(bool arm){
 now_ms=100;rawio=true;copy_read_fault=copy_write_fault=false;reply_sends=ccif_aborts=last_reply_length=0;
 endpoint=ccci_service_endpoint_create(&dev,&ccif);assert(!IS_ERR(endpoint));
 assert(endpoint->refs.count==1&&!endpoint->connected&&!endpoint->armed);
 file=(struct file){.private_data=&endpoint->misc,.f_flags=O_NONBLOCK};
 assert(!endpoint_open(NULL,&file));assert(file.private_data==endpoint&&endpoint->refs.count==2);
 if(arm)assert(!ccci_service_endpoint_arm(endpoint,41));
}
static void destroy(void){
 assert(!ccci_service_endpoint_stop(endpoint,true));
 assert(!endpoint->armed&&!endpoint->reserved&&!endpoint->pending&&endpoint->error);
 for(unsigned i=0;i<sizeof(endpoint->requests);i++)assert(!((u8 *)endpoint->requests)[i]);
 for(unsigned i=0;i<sizeof(endpoint->rpc_reply);i++)assert(!endpoint->rpc_reply[i]);
 endpoint_remove(endpoint);assert(endpoint->removed&&endpoint->refs.count==1);
 assert(!endpoint_release(NULL,&file));endpoint=NULL;
}
static void receive_fs(u32 slot){
 size_t n=fs_packet(request,14,slot);struct ccci_ccif_event event={.type=CCCI_CCIF_EVENT_RING,.queue=4,.data=request,.size=n};
 assert(!ccci_service_endpoint_receive(endpoint,41,&event));run();
}
static size_t read_one(void){
 ssize_t n=endpoint_read(&file,(void *)record,sizeof(record),&offset);assert(n>32);
 assert(get_unaligned_le32(record)==1&&get_unaligned_le64(record+8)==41);
 assert(get_unaligned_le32(record+28)==n-32);return n;
}
static void access_and_lifetime(void){
 rawio=false;endpoint=ccci_service_endpoint_create(&dev,&ccif);assert(!IS_ERR(endpoint));
 file=(struct file){.private_data=&endpoint->misc,.f_flags=O_NONBLOCK};
 assert(endpoint_open(NULL,&file)==-EPERM&&!endpoint->connected&&endpoint->refs.count==1);
 rawio=true;assert(!endpoint_open(NULL,&file));
 struct file second={.private_data=&endpoint->misc};
 assert(endpoint_open(NULL,&second)==-EBUSY&&endpoint->refs.count==2);
 assert(!endpoint_poll(&file,NULL));
 assert(endpoint_read(&file,(void *)record,sizeof(record),&offset)==-EAGAIN);
 file.f_flags=0;assert(endpoint_read(&file,(void *)record,sizeof(record),&offset)==-EINTR);file.f_flags=O_NONBLOCK;
 /* Dormant disconnect allows a new exclusive provider; open refs survive remove. */
 assert(!endpoint_release(NULL,&file)&&endpoint->refs.count==1);
 file.private_data=&endpoint->misc;assert(!endpoint_open(NULL,&file));
 endpoint_remove(endpoint);assert(endpoint->removed&&endpoint->refs.count==1);
 assert(endpoint_read(&file,(void *)record,sizeof(record),&offset)==-ENODEV);
 assert(endpoint_poll(&file,NULL)==(EPOLLERR|EPOLLHUP));
 assert(endpoint_open(NULL,&second)==-ENODEV);
 assert(!endpoint_release(NULL,&file));endpoint=NULL;
 fail_misc=-EIO;assert(IS_ERR(ccci_service_endpoint_create(&dev,&ccif)));fail_misc=0;
 fail_action=-ENOMEM;assert(IS_ERR(ccci_service_endpoint_create(&dev,&ccif)));fail_action=0;
 puts("PASS: actual endpoint capability, exclusive open, nonblock/interrupted read and remove/open lifetime");
}
static void roundtrip_and_validation(void){
 create(true);receive_fs(0);assert(endpoint->pending==1&&endpoint->requests[0].pending);
 assert(endpoint_poll(&file,NULL)==(EPOLLIN|EPOLLRDNORM));
 assert(endpoint_read(&file,(void *)record,32,&offset)==-EMSGSIZE&&endpoint->pending==1&&!endpoint->requests[0].delivered);
 copy_read_fault=true;assert(endpoint_read(&file,(void *)record,sizeof(record),&offset)==-EFAULT);
 assert(endpoint->pending==1&&!endpoint->requests[0].delivered);copy_read_fault=false;
 size_t n=read_one();assert(!endpoint->pending&&endpoint->requests[0].delivered);
 put_unaligned_le32(15,record+40);
 unsigned queued=endpoint->session->count;
 copy_write_fault=true;assert(endpoint_write(&file,(void *)record,n,&offset)==-EFAULT);copy_write_fault=false;
 assert(endpoint->session->count==queued&&!endpoint->requests[0].replied);
 put_unaligned_le64(40,record+8);assert(endpoint_write(&file,(void *)record,n,&offset)==-ESTALE);put_unaligned_le64(41,record+8);
 u64 token=get_unaligned_le64(record+16);put_unaligned_le64(token+1,record+16);
 assert(endpoint_write(&file,(void *)record,n,&offset)==-ESTALE);put_unaligned_le64(token,record+16);
 for(unsigned where=0;where<6;where++){
  const unsigned offsets[]={0,4,24,28,40,48};unsigned at=offsets[where];u32 before=get_unaligned_le32(record+at);
  put_unaligned_le32(0x7777,record+at);assert(endpoint_write(&file,(void *)record,n,&offset)<0);
  assert(!endpoint->requests[0].replied&&endpoint->session->count==queued);put_unaligned_le32(before,record+at);
 }
 assert(endpoint_write(&file,(void *)record,n-1,&offset)==-EINVAL);
 assert(endpoint_write(&file,(void *)record,55,&offset)==-EMSGSIZE);
 assert(endpoint_write(&file,(void *)record,sizeof(record)+1,&offset)==-EMSGSIZE);
 assert(endpoint_write(&file,(void *)record,n,&offset)==n);
 assert(endpoint->requests[0].replied&&endpoint->session->count==queued+1&&!reply_sends);
 assert(endpoint_write(&file,(void *)record,n,&offset)==-EALREADY&&endpoint->session->count==queued+1);
 memset(record,0xa5,n);run();assert(reply_sends==1&&!endpoint->session->router.error);
 /* Fresh transaction reuses slot only after prior reply consumed by session. */
 receive_fs(0);assert(endpoint->pending==1&&!endpoint->requests[0].replied);n=read_one();
 assert(get_unaligned_le64(record+16)!=token);
 put_unaligned_le32(15,record+40);put_unaligned_le64(token,record+16);
 assert(endpoint_write(&file,(void *)record,n,&offset)==-ESTALE);destroy();
 puts("PASS: actual fops short/EFAULT reads preserve request; stale/token/frame/duplicate replies never enqueue");
}
static void rpc_and_failed_enqueue(void){
 create(true);
 memset(request,0,24);put_unaligned_le32(0x12345678,request);put_unaligned_le32(24,request+4);
 put_unaligned_le32(32,request+8);put_unaligned_le32(2,request+12);put_unaligned_le32(0x400f,request+16);
 struct ccci_ccif_event event={.type=CCCI_CCIF_EVENT_RING,.queue=1,.data=request,.size=24};
 assert(!ccci_service_endpoint_receive(endpoint,41,&event));run();size_t n=read_one();
 assert(get_unaligned_le32(record+4)==CCCI_SERVICE_RPC&&get_unaligned_le32(record+24)==2);
 put_unaligned_le32(33,record+40);put_unaligned_le32(0xffff4010,record+48);
 assert(endpoint_write(&file,(void *)record,n,&offset)==-EPROTO&&!endpoint->requests[7].replied);
 put_unaligned_le32(0xffff400f,record+48);put_unaligned_le32(0x12345679,record+32);
 assert(endpoint_write(&file,(void *)record,n,&offset)==-EPROTO&&!endpoint->requests[7].replied);
 put_unaligned_le32(0x12345678,record+32);put_unaligned_le32(7,record+52);
 assert(endpoint_write(&file,(void *)record,n,&offset)==-EPROTO&&!endpoint->requests[7].replied);
 put_unaligned_le32(0,record+52);assert(endpoint_write(&file,(void *)record,n,&offset)==n);run();
 assert(reply_sends==1);destroy();
 create(true);receive_fs(0);n=read_one();put_unaligned_le32(15,record+40);
 for(unsigned i=0;i<SERVICE_SESSION_EVENTS;i++)assert(!ccci_service_endpoint_hs2(endpoint,41));
 assert(endpoint_write(&file,(void *)record,n,&offset)==-ENOSPC&&endpoint->requests[0].replied);
 assert(!reply_sends);run();assert(ccif_aborts==1&&endpoint->error==-ENOSPC);
 assert(endpoint_poll(&file,NULL)==(EPOLLERR|EPOLLHUP));destroy();
 puts("PASS: actual RPC reply identity/codec and accepted-lease enqueue failure fault without publication");
}
static void active_remove_refusal(void){
 create(true);receive_fs(0);endpoint_remove(endpoint);
 assert(endpoint->removed&&endpoint->refs.count==2&&endpoint->armed);
 assert(endpoint_read(&file,(void *)record,sizeof(record),&offset)==-ENODEV);
 assert(endpoint_poll(&file,NULL)==(EPOLLERR|EPOLLHUP));
 assert(!ccci_service_endpoint_stop(endpoint,true));
 assert(!endpoint_release(NULL,&file)&&endpoint->refs.count==1);
 /* Production deliberately retains active-remove storage. Reclaim it explicitly
  * only in this stopped synthetic fixture to keep ASan leak checks meaningful. */
 assert(!ccci_service_session_destroy(endpoint->session));kref_put(&endpoint->refs,endpoint_free);endpoint=NULL;
 puts("PASS: active remove refusal retains callback/open storage; stopped fixture teardown is safe");
}
static void ordering_faults(void){
 create(true);size_t n=fs_packet(request,14,4);
 for(int slot=4;slot>=0;slot--){fs_packet(request,14,slot);assert(!endpoint_submit(endpoint,41,100+slot,CCCI_SERVICE_FS,slot,request,n));}
 assert(endpoint->pending==5);
 for(unsigned slot=0;slot<5;slot++){read_one();assert(get_unaligned_le32(record+24)==slot);}
 assert(!endpoint->pending);
 assert(endpoint_submit(endpoint,41,999,CCCI_SERVICE_FS,0,request,n)==-EBUSY);
 assert(endpoint_submit(endpoint,40,999,CCCI_SERVICE_FS,1,request,n)==-ESTALE);
 assert(endpoint_submit(endpoint,41,999,CCCI_SERVICE_FS,5,request,n)==-EINVAL);
 endpoint_fault(endpoint,40,-EIO);assert(!endpoint->error);
 endpoint_fault(endpoint,41,-EIO);assert(endpoint->error==-EIO);
 endpoint_fault(endpoint,41,-ETIMEDOUT);assert(endpoint->error==-EIO);
 assert(endpoint_poll(&file,NULL)==(EPOLLERR|EPOLLHUP));
 assert(endpoint_read(&file,(void *)record,sizeof(record),&offset)==-EIO);destroy();
 /* Active backend loss faults session asynchronously, keeping storage until stopped. */
 create(true);receive_fs(0);assert(!endpoint_release(NULL,&file));assert(endpoint->refs.count==1&&endpoint->error==-EPIPE);
 run();assert(ccif_aborts==1&&endpoint->session->router.error==-EPIPE);
 assert(endpoint_open(NULL,&(struct file){.private_data=&endpoint->misc})==-EBUSY);
 assert(ccci_service_endpoint_stop(endpoint,false)==-EBUSY&&endpoint->armed);
 assert(!ccci_service_endpoint_stop(endpoint,true));
 for(unsigned i=0;i<sizeof(endpoint->requests);i++)assert(!((u8 *)endpoint->requests)[i]);endpoint_remove(endpoint);endpoint=NULL;
 puts("PASS: actual pending-slot ordering, sticky poll faults, active disconnect abort and stopped-only request wipe");
}
static size_t rpc_packet(u32 operation,const struct ccci_rpc_arg *args,u32 argc){
 size_t n=24;memset(request,0,sizeof(request));put_unaligned_le32(0x12345678,request);
 put_unaligned_le32(32,request+8);put_unaligned_le32(2,request+12);
 put_unaligned_le32(operation,request+16);put_unaligned_le32(argc,request+20);
 for(unsigned i=0;i<argc;i++){
  put_unaligned_le32(args[i].size,request+n);n+=4;
  if(args[i].size)memcpy(request+n,args[i].data,args[i].size);n+=(args[i].size+3)&~3U;
 }
 put_unaligned_le32(n,request+4);return n;
}
static void receive_rpc(size_t n){
 struct ccci_ccif_event event={.type=CCCI_CCIF_EVENT_RING,.queue=1,.data=request,.size=n};
 assert(!ccci_service_endpoint_receive(endpoint,41,&event));run();
}
static void kernel_rpc_ownership(void){
 /* Unknown kernel operations receive the real vendor NO_OP without a user lease. */
 create(true);size_t n=rpc_packet(0x4018,NULL,0);receive_rpc(n);
 assert(reply_sends==1&&!ccif_aborts&&!endpoint->pending&&!endpoint->error);
 assert(endpoint_read(&file,(void *)record,sizeof(record),&offset)==-EAGAIN);
 struct ccci_rpc_message rpc;assert(!ccci_rpc_decode_request(request,n,&rpc));
 assert(!ccci_rpc_validate_reply(&rpc,last_reply,last_reply_length));
 assert(last_reply_length==32&&get_unaligned_le32(last_reply+20)==1);
 assert(get_unaligned_le32(last_reply+28)==0xffffffff);destroy();
 /* Declared kernel operations with missing providers fault, never reach userspace. */
 create(true);n=rpc_packet(0x4002,NULL,0);receive_rpc(n);
 assert(!reply_sends&&ccif_aborts==1&&!endpoint->pending&&endpoint->error==-EOPNOTSUPP);
 assert(endpoint_read(&file,(void *)record,sizeof(record),&offset)==-EOPNOTSUPP);
 assert(!endpoint->requests[7].pending&&!endpoint->requests[7].delivered);destroy();
 /* A complete audited snapshot is immutable after reserve; typed bytes reach TX. */
 static const struct ccci_rpc_named_fact gpio[]={{{'p','i','n',0},513}};
 static const struct ccci_rpc_provider facts={.gpio=gpio,.gpio_count=1,.gpio_present=true};
 create(false);assert(ccci_service_endpoint_set_rpc(NULL,&facts)==-EINVAL);
 struct ccci_rpc_provider invalid=facts;invalid.gpio_count=33;
 assert(ccci_service_endpoint_set_rpc(endpoint,&invalid)==-EINVAL&&!endpoint->rpc_provider);
 assert(!ccci_service_endpoint_set_rpc(endpoint,&facts)&&endpoint->rpc_provider==&facts);
 assert(!ccci_service_endpoint_reserve(endpoint,41));
 assert(ccci_service_endpoint_set_rpc(endpoint,NULL)==-EBUSY&&endpoint->rpc_provider==&facts);
 assert(!ccci_service_endpoint_arm(endpoint,41));
 assert(ccci_service_endpoint_set_rpc(endpoint,NULL)==-EBUSY&&endpoint->rpc_provider==&facts);
 struct ccci_rpc_arg args[]={{(const u8 *)"pin",4},{NULL,0}};
 n=rpc_packet(0x4002,args,2);receive_rpc(n);
 assert(reply_sends==1&&!ccif_aborts&&!endpoint->pending&&!endpoint->error);
 assert(!ccci_rpc_decode_request(request,n,&rpc));
 assert(!ccci_rpc_validate_reply(&rpc,last_reply,last_reply_length));
 assert(last_reply_length==40&&get_unaligned_le32(last_reply+20)==2);
 assert(get_unaligned_le32(last_reply+28)==513&&get_unaligned_le32(last_reply+36)==513);
 assert(endpoint_read(&file,(void *)record,sizeof(record),&offset)==-EAGAIN);
 /* Same session retains the explicit userspace-owned 0x4010 path. */
 n=rpc_packet(0x4010,NULL,0);receive_rpc(n);
 assert(endpoint->pending==1&&reply_sends==1&&!endpoint->error);read_one();
 assert(get_unaligned_le32(record+48)==0x4010);destroy();
 puts("PASS: kernel RPC never falls back to userspace; unknown NO_OP, unavailable fault and immutable typed provider TX");
}
static void reservation_lifecycle(void){
 create(false);assert(!ccci_service_endpoint_offline(endpoint));
 assert(ccci_service_endpoint_reserve(NULL,41)==-EINVAL);
 assert(ccci_service_endpoint_reserve(endpoint,0)==-EINVAL&&!endpoint->generation);
 assert(!endpoint_release(NULL,&file)&&endpoint->refs.count==1);
 assert(ccci_service_endpoint_reserve(endpoint,41)==-EBUSY&&!endpoint->generation);
 file.private_data=&endpoint->misc;assert(!endpoint_open(NULL,&file));
 assert(!ccci_service_endpoint_reserve(endpoint,41));
 assert(endpoint->reserved&&endpoint->generation==41&&!endpoint->armed&&!endpoint->session->armed);
 assert(!endpoint->session->work.work.pending&&!reply_sends&&!ccif_aborts);
 assert(ccci_service_endpoint_offline(endpoint)==-EBUSY);
 assert(ccci_service_endpoint_reserve(endpoint,41)==-EBUSY);
 assert(ccci_service_endpoint_reserve(endpoint,42)==-EBUSY&&endpoint->generation==41);
 assert(ccci_service_endpoint_arm(endpoint,42)==-ESTALE&&!endpoint->armed);
 assert(!ccci_service_endpoint_arm(endpoint,41)&&endpoint->armed&&endpoint->session->armed);
 destroy();
 /* A pre-HS1 lease still retains private data until MD is actually stopped. */
 create(false);assert(!ccci_service_endpoint_reserve(endpoint,41));
 endpoint->requests[0].packet[0]=0xa5;
 unsigned wakes=wakeups;struct ccci_service_session *session=endpoint->session;
 assert(ccci_service_endpoint_stop(endpoint,false)==-EBUSY);
 assert(endpoint->reserved&&endpoint->generation==41&&!endpoint->armed&&!endpoint->error);
 assert(endpoint->requests[0].packet[0]==0xa5&&endpoint->session==session);
 assert(!session->armed&&!session->work.work.pending&&!session->count);
 assert(!reply_sends&&!ccif_aborts&&wakeups==wakes);
 assert(!ccci_service_endpoint_stop(endpoint,true));
 assert(!endpoint->reserved&&!endpoint->armed&&endpoint->error==-ESHUTDOWN);
 assert(!ccci_service_endpoint_offline(endpoint)&&!endpoint->requests[0].packet[0]);
 assert(ccci_service_endpoint_arm(endpoint,41)==-ESHUTDOWN);destroy();
 /* Losing the reserved backend before HS1 aborts CCIF synchronously exactly once. */
 create(false);assert(!ccci_service_endpoint_reserve(endpoint,41));
 assert(!endpoint_release(NULL,&file));
 assert(endpoint->refs.count==1&&!endpoint->connected&&endpoint->reserved);
 assert(endpoint->error==-EPIPE&&ccif_aborts==1&&!reply_sends);
 assert(!endpoint->session->armed&&!endpoint->session->work.work.pending);
 assert(ccci_service_endpoint_offline(endpoint)==-EBUSY);
 assert(endpoint_open(NULL,&(struct file){.private_data=&endpoint->misc})==-EBUSY);
 assert(ccci_service_endpoint_abort(endpoint,42,-EIO)==-ESTALE&&ccif_aborts==1);
 assert(!ccci_service_endpoint_stop(endpoint,true)&&!endpoint->reserved);
 assert(!ccci_service_endpoint_offline(endpoint));endpoint_remove(endpoint);endpoint=NULL;
 /* Dispatcher faults latch before session arm, without a second CCIF action. */
 create(false);assert(!ccci_service_endpoint_reserve(endpoint,41));
 assert(ccci_service_endpoint_abort(endpoint,40,-EIO)==-ESTALE&&!endpoint->error);
 assert(ccci_service_endpoint_abort(endpoint,41,-EIO)==-EIO);
 assert(ccci_service_endpoint_abort(endpoint,41,-ETIMEDOUT)==-EIO);
 assert(endpoint->error==-EIO&&!endpoint->session->armed&&!endpoint->session->work.work.pending);
 assert(!reply_sends&&!ccif_aborts&&ccci_service_endpoint_offline(endpoint)==-EBUSY);destroy();
 /* Removal cannot destroy the session behind an unarmed reservation either. */
 create(false);assert(!ccci_service_endpoint_reserve(endpoint,41));endpoint_remove(endpoint);
 assert(endpoint->removed&&endpoint->refs.count==2&&endpoint->reserved&&!endpoint->armed);
 assert(ccci_service_endpoint_offline(endpoint)==-EBUSY);
 assert(endpoint_read(&file,(void *)record,sizeof(record),&offset)==-ENODEV);
 assert(endpoint_poll(&file,NULL)==(EPOLLERR|EPOLLHUP));
 assert(!ccci_service_endpoint_stop(endpoint,true)&&!endpoint->reserved);
 assert(!endpoint_release(NULL,&file)&&endpoint->refs.count==1);
 assert(!ccci_service_session_destroy(endpoint->session));kref_put(&endpoint->refs,endpoint_free);endpoint=NULL;
 puts("PASS: reservation freezes generation/backend, pre-HS1 disconnect aborts, stop requires MD stopped, active remove retains storage");
}
int main(void){kernel_rpc_ownership();reservation_lifecycle();access_and_lifetime();roundtrip_and_validation();rpc_and_failed_enqueue();ordering_faults();active_remove_refusal();return 0;}
'''


def main():
    with tempfile.TemporaryDirectory(prefix='op6893-endpoint-') as directory:
        root = Path(directory)
        inc = root / 'linux'
        inc.mkdir()
        script = Path(__file__).with_name('test_modem_service_session.py').read_text()
        section = script[script.index('        files = {'):script.index('        for name, data in files.items():')]
        scope = {}
        exec(textwrap.dedent(section), scope)
        for name, content in scope['files'].items():
            (inc / name).write_text(content + ('\ntypedef int32_t s32;\n' if name == 'types.h' else ''))
        for name in ('capability.h', 'device.h', 'fs.h', 'kref.h', 'miscdevice.h',
                     'poll.h', 'uaccess.h', 'kconfig.h', 'sysfs.h'):
            (inc / name).write_text('')
        # Header supplies portable little-endian 32-bit helpers before shim 64-bit helpers.
        (root / 'test.c').write_text(PREFIX + '\n#include <linux/unaligned.h>\n' + SHIM + TEST)
        source = K / 'drivers/misc/mediatek/ccci'
        subprocess.run(['cc', '-O1', '-g', '-Wall', '-Wextra', '-Werror',
                        '-Wno-unused-parameter', '-Wno-unused-function', '-Wno-unused-variable',
                        '-Wno-misleading-indentation', '-Wno-sign-compare',
                        '-fsanitize=address,undefined', '-fno-sanitize-recover=all', '-no-pie',
                        '-I'+str(root), '-I'+str(source),
                        str(source/'ccci-fs-protocol.c'), str(source/'ccci-rpc-protocol.c'),
                        str(source/'ccci-service-router.c'), str(source/'ccci-rpc-provider.c'),
                        str(root/'test.c'),
                        '-o', str(root/'test')], check=True)
        subprocess.run([str(root/'test')], check=True)


if __name__ == '__main__':
    main()
