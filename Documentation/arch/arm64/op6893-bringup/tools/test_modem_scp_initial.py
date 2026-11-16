#!/usr/bin/env python3
# SPDX-License-Identifier: GPL-2.0-only
"""Exercise actual initial boot owner with ordered hardware/RX fault injection."""
from pathlib import Path
import runpy
import subprocess
import tempfile

K = Path(__file__).resolve().parents[5]
D = K / 'drivers/misc/mediatek/ccci'
block = runpy.run_path(str(Path(__file__).with_name('test_modem_scp_reset.py')))['block']

prefix = r'''
#include <assert.h>
#include <errno.h>
#include <stdbool.h>
#include <stdint.h>
#include <stdio.h>
#include <string.h>
#include <sys/types.h>
typedef uint32_t u32;
typedef uint64_t u64;
#define __iomem
#define BIT(n) (1U<<(n))
struct mutex {bool held;};
struct device_attribute {int unused;};
struct device {void *data;};
struct ccci_scp_pin {u32 channel;};
struct ccci_scp_layout {int unused;};
struct ccci_scp_inspect {int unused;};
struct ccci_scp_mmio {int unused;};
struct ccci_scp_receive {int unused;};
struct ccci_scp_event {u64 generation;struct ccci_scp_pin pin;u32 bytes;unsigned char data[256];};
static unsigned char cores[2][4096];
static unsigned long jiffies;
static unsigned checks, fail_at, stops, resets, starts, events, writes, released;
static int start_error, pop_error;
static bool bad_ready, timeout, stale;
static unsigned channel;
static struct mutex *lock;
static void mutex_lock(struct mutex *m){assert(!m->held);m->held=true;}
static void mutex_unlock(struct mutex *m){assert(m->held);m->held=false;}
static bool sysfs_streq(const char *a,const char *b){return !strcmp(a,b);}
static void *dev_get_drvdata(struct device *d){return d->data;}
static void memzero_explicit(void *p,size_t n){memset(p,0,n);}
static unsigned long msecs_to_jiffies(unsigned long n){return n;}
static bool time_before(unsigned long a,unsigned long b){return a<b;}
static void usleep_range(unsigned a,unsigned b){assert(!lock->held && a==10000 && b==12000);jiffies+=10;}
static void mb(void){assert(lock->held);}
static u32 readl(void *p){assert(lock->held);u32 v;memcpy(&v,p,4);return v;}
static void writel(u32 v,void *p){
 assert(lock->held);writes++;
 if(p==cores[0]){assert(starts==1 && v==1);released++;memcpy(cores[0]+4,&v,4);}
 else if(p==cores[0]+4 || p==cores[1]+4){u32 raw=0xff00;assert(v==1);memcpy(p,&raw,4);}
 else {assert(p==cores[0]+0x44 || p==cores[0]+0x48);memcpy(p,&v,4);}
}
static int ccci_scp_inspect_reset_check(void *c){(void)c;assert(lock->held);return ++checks==fail_at?-EIO:0;}
static void ccci_scp_inspect_record_reset(void *c,u32 n){(void)c;(void)n;assert(lock->held);}
static int ccci_scp_inspect_boot(void *c,u32 *base,u32 *size){
 assert(resets==1 && stops==1 && lock->held);int ret=ccci_scp_inspect_reset_check(c);
 *base=0x8d000000;*size=0x320000;return ret;
}
static int ccci_scp_mmio_discard(void *m,const void *l,int(*check)(void*),void *c,u32 *n){
 (void)m;(void)l;assert(lock->held && !starts);int r=check(c);*n=2;return r;
}
static void ccci_scp_receive_stop(void *r){(void)r;assert(!lock->held);stops++;}
static int ccci_scp_receive_start(void *r,const void *l,u64 gen,u32 budget){
 (void)r;(void)l;assert(!lock->held && stops==1 && resets==1 && gen==1 && budget==16);starts++;return start_error;
}
static int ccci_scp_receive_pop(void *r,u64 gen,struct ccci_scp_event *e){
 (void)r;assert(!lock->held && gen==1 && released==1);if(pop_error)return pop_error;
 if(timeout)return -ENODATA;
 memset(e,0,sizeof(*e));e->generation=stale?2:1;e->bytes=4;
 e->pin.channel=events++?channel:21;return 0;
}
static int ccci_scp_decode_ready(const struct ccci_scp_pin *p,const void *b,size_t n,u32 size){
 (void)b;assert((p->channel==9 || p->channel==22) && n==4 && size==0x180000);return bad_ready?-EPROTO:0;
}
'''
owner = r'''
struct ccci_scp_resource_owner {
 struct mutex lock;void *core_tcm[3];struct ccci_scp_inspect *inspect;
 struct ccci_scp_receive *receive;struct ccci_scp_mmio *mmio;
 struct ccci_scp_reset reset;bool reset_requested;u64 reset_generation;
 struct ccci_scp_layout layout;bool boot_requested,boot_running;
 u32 boot_ready_channel,boot_discarded,boot_events;int boot_error,boot_cleanup_error;
};
'''
tests = r'''
static void setup(struct ccci_scp_resource_owner *o){
 memset(o,0,sizeof(*o));memset(cores,0,sizeof(cores));lock=&o->lock;
 o->core_tcm[0]=cores[0];o->core_tcm[1]=cores[1];
 u32 a=0x11223344,b=0x55667788;memcpy(cores[0]+0x44,&a,4);memcpy(cores[0]+0x48,&b,4);
 checks=fail_at=stops=resets=starts=events=writes=released=0;jiffies=0;
 start_error=pop_error=0;bad_ready=timeout=stale=false;channel=22;
}
int main(void){
 struct ccci_scp_resource_owner o;struct device dev={&o};
 setup(&o);assert(initial_boot_store(&dev,NULL,"wrong",5)==-EINVAL && !checks);
 setup(&o);fail_at=1;assert(initial_boot_store(&dev,NULL,"test",4)==-EIO && !o.boot_requested && !stops);
 for(unsigned c=9;c<=22;c+=13){
  setup(&o);channel=c;assert(initial_boot_store(&dev,NULL,"test",4)==4);
  assert(o.boot_ready_channel==c && o.boot_events==2 && o.boot_discarded==2);
  assert(stops==2 && resets==2 && starts==1 && released==1 && !o.reset_generation);
  assert(o.reset.latched && !o.boot_running && !o.boot_error && !o.boot_cleanup_error);
  assert(!memcmp(cores[0]+0x44,"\x44\x33\x22\x11\x88\x77\x66\x55",8));
  unsigned before=writes;assert(initial_boot_store(&dev,NULL,"test",4)==-EALREADY && writes==before);
 }
 for(unsigned f=0;f<5;f++){
  setup(&o);
  if(f==0)start_error=-ENOMEM;
  if(f==1)pop_error=-ESHUTDOWN;
  if(f==2)bad_ready=true;
  if(f==3)timeout=true;
  if(f==4)stale=true;
  assert(initial_boot_store(&dev,NULL,"test",4)<0);
  assert(o.boot_error && !o.boot_ready_channel && !o.reset_generation && !o.boot_running && o.reset.latched);
  assert(stops==2 && resets==2 && !o.boot_cleanup_error && !lock->held);
 }
 /* Every prerequisite phase fails independently; cleanup still runs. */
 for(unsigned f=2;f<=8;f++){
  setup(&o);fail_at=f;
  assert(initial_boot_store(&dev,NULL,"test",4)==-EIO);
  assert(o.boot_requested && !o.boot_running && !o.reset_generation && stops==2 && !lock->held);
 }
 puts("PASS: actual boot owner; both READY channels, old discard before RX/release, lock ordering, exact GPR restore, one-shot, timeout/stale/malformed/start/RX/prerequisite faults and cleanup");
}
'''


def test_discard():
    prefix = r"""
#include <assert.h>
#include <errno.h>
#include <stdbool.h>
#include <stdint.h>
#include <stdio.h>
#include <string.h>
typedef uint32_t u32;
#define CCCI_SCP_MAX_MBOXES 5
#define CCCI_SCP_MAX_CHANNELS 64
#define CCCI_SCP_MMIO_PENDING 0x10c
#define CCCI_SCP_MMIO_COMPLETE 0x94
#define BIT(n) (1U<<(n))
struct pin {unsigned mbox,irq;};
struct ccci_scp_layout {unsigned rx_count;struct pin rx[64];};
struct port {void *base;};
struct ccci_scp_mmio {bool prepared;struct port ports[5];void *cfg;unsigned register_reads,register_writes,cfg_writes;};
static unsigned char pages[6][4096];
static unsigned writes,barriers,checks,fail_at;
static bool retain;
static unsigned hweight32(u32 n){return __builtin_popcount(n);}
static int check(void *p){(void)p;return ++checks==fail_at?-EIO:0;}
static u32 readl(void *p){u32 v;memcpy(&v,p,4);return v;}
static void mb(void){barriers++;}
static void writel(u32 n,void *p){
 assert(writes==barriers);writes++;
 if(p==pages[5]+0x94){assert(n==1);return;}
 for(unsigned i=0;i<5;i++)if(p==pages[i]+0x10c){
  assert(n==1 && writes%2==0);if(!retain)memset(p,0,4);return;
 }
 assert(0);
}
"""
    tests = r"""
int main(void){
 struct ccci_scp_mmio m;struct ccci_scp_layout l;u32 discarded;
 for(unsigned test=0;test<5;test++){
  memset(&m,0,sizeof(m));memset(&l,0,sizeof(l));memset(pages,0,sizeof(pages));
  checks=writes=barriers=0;retain=test==4;fail_at=test==2?1:(test==3?2:0);
  m.cfg=pages[5];l.rx_count=5;
  for(unsigned i=0;i<5;i++){m.ports[i].base=pages[i];l.rx[i]=(struct pin){i,0};}
  u32 one=1;memcpy(pages[1]+0x10c,&one,4);memcpy(pages[3]+0x10c,&one,4);
  if(test==1){u32 bad=2;memcpy(pages[4]+0x10c,&bad,4);}
  int ret=ccci_scp_mmio_discard(&m,&l,check,NULL,&discarded);
  if(!test)assert(!ret && writes==4 && barriers==4 && discarded==2 && m.cfg_writes==2);
  if(test==1)assert(ret==-EPROTO && !writes);
  if(test==2 || test==3)assert(ret==-EIO && !writes);
  if(test==4)assert(ret==-EAGAIN && discarded==2 && writes==4);
 }
 puts("PASS: actual old-message discard; exact known W1C, completion/barrier ordering, no payload reads, unknown-source/precondition rejection and retained-pending containment");
}
"""
    source = (D / 'ccci-scp-mmio.c').read_text()
    code = prefix + block(source, 'int ccci_scp_mmio_discard(') + tests
    compile_run(code)


def compile_run(code):
    with tempfile.TemporaryDirectory(prefix='op6893-initial-') as path:
        p = Path(path)
        (p / 'test.c').write_text(code)
        subprocess.run(['cc', '-Wall', '-Wextra', '-Werror', '-Wno-unused-parameter',
                        '-fsanitize=address,undefined', '-fno-sanitize-recover=all',
                        '-no-pie', str(p / 'test.c'), '-o', str(p / 'test')], check=True)
        subprocess.run([str(p / 'test')], check=True)


def main():
    def clean(name):
        return '\n'.join(s for s in (D / name).read_text().splitlines()
                         if not s.startswith('#include'))
    source = (D / 'ccci-scp-resource-hold.c').read_text()
    reset = clean('ccci-scp-reset.c').replace('reset->attempted = true;',
                                             'reset->attempted = true; resets++;')
    code = prefix + clean('ccci-scp-reset.h') + reset + owner
    code += block(source, 'static int ccci_scp_initial_asserted(')
    code += block(source, 'static ssize_t initial_boot_store(') + tests
    compile_run(code)
    test_discard()


if __name__ == '__main__':
    main()
