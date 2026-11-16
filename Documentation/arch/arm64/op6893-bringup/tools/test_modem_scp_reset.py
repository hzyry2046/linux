#!/usr/bin/env python3
# SPDX-License-Identifier: GPL-2.0-only
"""Focused test of actual forced SET sequence and owner STOP/locking wrapper."""
from pathlib import Path
import subprocess
import tempfile

K = Path(__file__).resolve().parents[5]
D = K / 'drivers/misc/mediatek/ccci'


def clean(name):
    return '\n'.join(line for line in (D / name).read_text().splitlines()
                     if not line.startswith('#include'))


def block(source, marker):
    start = source.index(marker)
    end = source.index('{', start) + 1
    depth = 1
    while depth:
        depth += (source[end] == '{') - (source[end] == '}')
        end += 1
    return source[start:end]


prefix = r'''
#include <assert.h>
#include <errno.h>
#include <stdint.h>
#include <stdbool.h>
#include <stdio.h>
#include <stdlib.h>
#include <string.h>
#include <sys/types.h>
typedef uint32_t u32;
#define __iomem
#define BIT(n) (1U<<(n))
struct mutex {bool held;};
struct ccci_scp_inspect {unsigned writes;};
struct ccci_scp_receive {int unused;};
struct device_attribute {int unused;};
struct device {void *data;};
static unsigned char cores[2][4096];
static unsigned calls,fail_at,writes,reads,barriers,stops;
static int error_at;
static unsigned released_mask;
static struct mutex *owner_lock;
static struct ccci_scp_inspect inspect;
static struct ccci_scp_receive receive;
static void mutex_lock(struct mutex *m){assert(!m->held);m->held=true;}
static void mutex_unlock(struct mutex *m){assert(m->held);m->held=false;}
static bool sysfs_streq(const char *a,const char *b){size_t n=strlen(b);return !strncmp(a,b,n) && (!a[n] || (a[n]=='\n' && !a[n+1]));}
static void *dev_get_drvdata(struct device *d){return d->data;}
static int ccci_scp_inspect_reset_check(void *ctx){assert(ctx==&inspect && owner_lock->held);calls++;return calls==fail_at?error_at:0;}
static void ccci_scp_inspect_record_reset(struct ccci_scp_inspect *i,u32 n){assert(i==&inspect && owner_lock->held);i->writes+=n;}
static void ccci_scp_receive_stop(struct ccci_scp_receive *r){assert(r==&receive && !owner_lock->held && !writes);stops++;}
static void writel(u32 value,void *ptr){assert(owner_lock->held && stops==1 && !barriers && writes<2 && ptr==cores[writes]+4 && value==1);writes++;}
static void mb(void){assert(writes==2 && !barriers && !reads);barriers++;}
static u32 readl(void *ptr){assert(owner_lock->held && writes==2 && barriers==1 && reads<2 && ptr==cores[reads]+4);return 0xff00 | ((released_mask>>reads++)&1);}
'''

tests = r'''
static void setup(struct ccci_scp_resource_owner *o){
 memset(o,0,sizeof(*o));inspect.writes=0;owner_lock=&o->lock;
 o->core_tcm[0]=cores[0];o->core_tcm[1]=cores[1];o->inspect=&inspect;o->receive=&receive;
 calls=fail_at=writes=reads=barriers=stops=0;error_at=-EAGAIN;released_mask=0;
}
int main(void){
 struct ccci_scp_resource_owner o;struct device d={&o};
 setup(&o);assert(reset_assert_store(&d,NULL,"release",7)==-EINVAL && !calls && !stops && !writes);
 setup(&o);fail_at=1;assert(reset_assert_store(&d,NULL,"assert",6)==-EAGAIN && !o.reset_requested && !stops && !writes);
 fail_at=0;assert(reset_assert_store(&d,NULL,"assert\n",7)==7);
 assert(o.reset_requested && o.reset.attempted && o.reset.latched && !o.reset.error);
 assert(o.reset.raw[0]==0xff00 && o.reset.raw[1]==0xff00 && !o.reset.set[0] && !o.reset.set[1]);
 assert(writes==2 && reads==2 && barriers==1 && stops==1 && calls==4 && inspect.writes==2 && !owner_lock->held);
 unsigned before=calls;assert(reset_assert_store(&d,NULL,"assert",6)==-EALREADY && calls==before && writes==2 && stops==1);
 for(unsigned phase=2;phase<=3;phase++){
  setup(&o);fail_at=phase;error_at=-EIO;
  assert(reset_assert_store(&d,NULL,"assert",6)==-EIO && o.reset_requested && !o.reset.latched && o.reset.error==-EIO);
  assert(stops==1 && writes==(phase==2?0:2) && inspect.writes==writes);
  before=calls;assert(reset_assert_store(&d,NULL,"assert",6)==-EALREADY && before==calls && stops==1);
 }
 for(unsigned mask=1;mask<4;mask++){
  setup(&o);released_mask=mask;
  assert(reset_assert_store(&d,NULL,"assert",6)==-EIO && o.reset.attempted && !o.reset.latched && writes==2 && reads==2 && stops==1);
 }
 setup(&o);mutex_lock(&o.lock);
 assert(ccci_scp_reset_assert(NULL,o.core_tcm,ccci_scp_inspect_reset_check,&inspect)==-EINVAL);
 assert(ccci_scp_reset_assert(&o.reset,NULL,ccci_scp_inspect_reset_check,&inspect)==-EINVAL);
 o.reset.attempted=true;
 assert(ccci_scp_reset_assert(&o.reset,o.core_tcm,ccci_scp_inspect_reset_check,&inspect)==-EALREADY);
 mutex_unlock(&o.lock);
 puts("PASS: actual owner + forced SET sequence; preconditions, STOP outside lock, exact two writes then DSB/readback, postcheck failure, latch mismatch, no retry/release");
}
'''


def main():
    source = (D / 'ccci-scp-resource-hold.c').read_text()
    owner = '''
struct ccci_scp_resource_owner {
 struct mutex lock;void *core_tcm[3];struct ccci_scp_inspect *inspect;
 struct ccci_scp_receive *receive;struct ccci_scp_reset reset;bool reset_requested;
};
'''
    code = (prefix + clean('ccci-scp-reset.h') + clean('ccci-scp-reset.c') +
            owner + block(source, 'static ssize_t reset_assert_store(') + tests)
    with tempfile.TemporaryDirectory(prefix='op6893-reset-') as directory:
        root = Path(directory)
        (root / 'test.c').write_text(code)
        subprocess.run(['cc', '-Wall', '-Wextra', '-Werror', '-Wno-unused-parameter',
                        '-fsanitize=address,undefined', '-fno-sanitize-recover=all',
                        '-no-pie', str(root / 'test.c'), '-o', str(root / 'test')], check=True)
        subprocess.run([str(root / 'test')], check=True)


if __name__ == '__main__':
    main()
