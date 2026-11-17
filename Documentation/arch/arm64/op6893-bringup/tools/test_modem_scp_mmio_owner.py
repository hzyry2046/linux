#!/usr/bin/env python3
# SPDX-License-Identifier: GPL-2.0-only
"""Actual owner probe/status: legacy cfg, mapped MMIO and dormant receive paths."""
from pathlib import Path
import argparse
import re
import subprocess
import tempfile

K = Path(__file__).resolve().parents[5]
SOURCE = K / 'drivers/misc/mediatek/ccci/ccci-scp-resource-hold.c'


def extract(source, marker):
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
#include <stdbool.h>
#include <stdint.h>
#include <stdio.h>
#include <stdlib.h>
#include <string.h>
#include <sys/types.h>
#define __iomem
typedef uint64_t u64;
#define IS_ENABLED(x) (x)
#define CONFIG_OP6893_CCCI_SCP_CFG_RESERVE 1
#define CONFIG_OP6893_CCCI_SCP_IRQ_RESERVE 1
#define GFP_KERNEL 0
#define IS_ERR(p) ((uintptr_t)(p)>=(uintptr_t)-4095)
#define PTR_ERR(p) ((intptr_t)(p))
struct clk {unsigned rate;};
struct mutex {bool locked;};
struct ccci_scp_resource {int unused;};
struct ccci_scp_irq {int unused;};
struct ccci_scp_mmio {int unused;};
struct ccci_scp_receive {int unused;};
struct ccci_scp_inspect {int unused;};
struct device {void *data;};
struct platform_device {struct device dev;};
struct device_attribute {int unused;};
#define DEFINE_MUTEX(n) struct mutex n
static struct clk clock_model;
static struct ccci_scp_irq irq_model;
static struct ccci_scp_mmio mmio_model;
static struct ccci_scp_receive receive_model;
static struct ccci_scp_inspect inspect_model;
static unsigned inspect_calls;
static int inspect_error;
static struct platform_device pdev;
static bool board,nomem,action_fail;
static int clock_error,mmio_error,irq_error,legacy_error;
#define ARRAY_SIZE(a) (sizeof(a)/sizeof((a)[0]))
#define IORESOURCE_MEM 0x200
#define IORESOURCE_MEM_NONPOSTED 0x100000
 typedef uint64_t resource_size_t;
struct resource {resource_size_t start,end;unsigned long flags;};
static struct resource core_resources[3];
static unsigned core_lookups,core_maps;
static int core_missing,core_map_fail,core_map_error;
static resource_size_t resource_size(struct resource *r) {return r->end-r->start+1;}
static struct resource *platform_get_resource_byname(struct platform_device *p,unsigned type,const char *name) {
 const char *names[]={"core0","core1","tcm"};
 assert(p==&pdev && type==IORESOURCE_MEM);
 for(unsigned i=0;i<3;i++)if(!strcmp(name,names[i])){core_lookups++;return core_missing==(int)i?NULL:&core_resources[i];}
 assert(0);return NULL;
}
static void *devm_ioremap_resource(struct device *d,struct resource *r) {
 unsigned i=core_maps++;
 assert(d==&pdev.dev && core_lookups==3 && i<3 && r!=&core_resources[i]);
 assert(r->start==core_resources[i].start && r->end==core_resources[i].end);
 assert(r->flags==(IORESOURCE_MEM|IORESOURCE_MEM_NONPOSTED));
 assert(core_resources[i].flags==IORESOURCE_MEM);
 if(core_map_fail==(int)i)return (void *)(intptr_t)core_map_error;
 return (void *)(uintptr_t)(0x1000*(i+1));
}
static unsigned mmio_calls,irq_calls,legacy_calls,reports;
static unsigned stage,receive_calls,receive_reports;
static void *allocation;
static void (*unclaim)(void *);
static void *unclaim_data;
static void mutex_init(struct mutex *m) {m->locked=false;}
static void mutex_lock(struct mutex *m) {assert(!m->locked);m->locked=true;}
static void mutex_unlock(struct mutex *m) {assert(m->locked);m->locked=false;}
static bool of_machine_is_compatible(const char *s) {assert(!strcmp(s,"realme,op6893"));return board;}
static void *devm_kzalloc(struct device *d,size_t n,int flags) {
 assert(d==&pdev.dev && flags==GFP_KERNEL && !allocation);
 if(nomem)return NULL;allocation=calloc(1,n);assert(allocation);return allocation;
}
static struct clk *devm_clk_get_enabled(struct device *d,const char *s) {
 assert(d==&pdev.dev && !strcmp(s,"scp"));
 if(clock_error)return (void *)(intptr_t)clock_error;return &clock_model;
}
static unsigned clk_get_rate(struct clk *c) {assert(c==&clock_model);return c->rate;}
static int devm_add_action_or_reset(struct device *d,void (*fn)(void *),void *data) {
 assert(d==&pdev.dev && !unclaim);
 if(action_fail){fn(data);return -ENOMEM;}
 unclaim=fn;unclaim_data=data;return 0;
}
static int dev_err_probe(struct device *d,int error,const char *s) {assert(d==&pdev.dev && s);return error;}
static void platform_set_drvdata(struct platform_device *p,void *data) {assert(p==&pdev);p->dev.data=data;}
static void *dev_get_drvdata(struct device *d) {assert(d==&pdev.dev);return d->data;}
static void dev_info(struct device *d,const char *s) {assert(d==&pdev.dev && s);}
'''

dependencies = r'''
static int ccci_scp_resource_inspect_check(void *context){assert(0);return -EIO;}
static int ccci_scp_inspect_create(struct platform_device *p,void *const maps[3],struct mutex *lock,int (*check)(void *),void *context,struct ccci_scp_inspect **out){
 struct ccci_scp_resource_owner *o=context;
 assert(p==&pdev && stage==1 && core_maps==3 && lock==&o->lock && !lock->locked);
 assert(check==ccci_scp_resource_inspect_check && maps==o->core_tcm);
 inspect_calls++;*out=inspect_error?NULL:&inspect_model;return inspect_error;
}
static ssize_t ccci_scp_inspect_status(struct ccci_scp_inspect *i,char *buf){
 struct ccci_scp_resource_owner *o=pdev.dev.data;
 assert(i==&inspect_model && o->lock.locked);
 strcpy(buf,"mapped=3 bytes=1581056 nonposted=1 register_reads=0 register_writes=0 tcm_reads=0 tcm_writes=0");return strlen(buf);
}

static int ccci_scp_resource_receive_check(void *context,u64 generation) {assert(0);return -ESTALE;}
static int ccci_scp_receive_reserve(struct platform_device *p,struct mutex *lock,struct ccci_scp_mmio *mmio,int (*check)(void *,u64),void *ctx,struct ccci_scp_receive **out) {
 struct ccci_scp_resource_owner *o=ctx;
 assert(p==&pdev && stage==1 && !lock->locked && lock==&o->lock && mmio==&mmio_model);
 assert(check==ccci_scp_resource_receive_check && !o->reset_generation);
 stage=2;receive_calls++;*out=irq_error?NULL:&receive_model;return irq_error;
}
static ssize_t ccci_scp_receive_status(struct ccci_scp_receive *r,char *buf) {
 assert(r==&receive_model);receive_reports++;strcpy(buf,"receive");return 7;
}
static ssize_t ccci_scp_irq_status(struct ccci_scp_irq *r,char *buf) {
 assert(r==&irq_model);strcpy(buf,"legacy");return 6;
}

static int ccci_scp_mmio_reserve(struct platform_device *p,struct ccci_scp_mmio **out) {
 assert(p==&pdev && !stage);stage=1;mmio_calls++;
 *out=mmio_error?NULL:&mmio_model;return mmio_error;
}
static int ccci_scp_cfg_reserve(struct platform_device *p,struct ccci_scp_resource_owner *o) {
 assert(p==&pdev && !stage);stage=1;legacy_calls++;
 o->cfg=legacy_error?NULL:&mmio_model;return legacy_error;
}
static int ccci_scp_irq_reserve(struct platform_device *p,struct mutex *lock,struct ccci_scp_irq **out) {
 assert(p==&pdev && stage==1 && !lock->locked);stage=2;irq_calls++;
 *out=irq_error?NULL:&irq_model;return irq_error;
}
static ssize_t ccci_scp_mmio_status(struct ccci_scp_mmio *m,char *buf) {
 struct ccci_scp_resource_owner *o=pdev.dev.data;
 assert(m==&mmio_model && o->lock.locked);reports++;strcpy(buf,"mapped=6");return 8;
}
static ssize_t ccci_scp_mmio_cfg_status(struct ccci_scp_mmio *m,char *buf) {
 struct ccci_scp_resource_owner *o=pdev.dev.data;
 assert(m==&mmio_model && o->lock.locked);reports++;strcpy(buf,"reserved=1");return 10;
}
static int sysfs_emit(char *buf,const char *s) {strcpy(buf,s);return strlen(s);}
'''

tests = r'''
static void cleanup(void) {
 if(unclaim){void (*fn)(void *)=unclaim;unclaim=NULL;fn(unclaim_data);}
 free(allocation);allocation=NULL;pdev.dev.data=NULL;
}
static void setup(void) {
 cleanup();assert(!ccci_scp_resource_claimed);
 clock_model.rate=26000000;board=true;nomem=action_fail=false;
 clock_error=mmio_error=irq_error=legacy_error=0;
 inspect_calls=0;inspect_error=0;
 core_missing=core_map_fail=-1;core_map_error=-ENOMEM;core_lookups=core_maps=0;
 const resource_size_t bases[]={0x10730000,0x10740000,0x10500000};
 const resource_size_t sizes[]={0x1000,0x1000,0x180000};
 for(unsigned i=0;i<3;i++)core_resources[i]=(struct resource){bases[i],bases[i]+sizes[i]-1,IORESOURCE_MEM};
 mmio_calls=irq_calls=legacy_calls=reports=stage=receive_calls=receive_reports=0;
}
int main(void) {
 char buf[4096];setup();assert(!ccci_scp_resource_probe(&pdev));
 struct ccci_scp_resource_owner *o=pdev.dev.data;
 assert(o && o==allocation && ccci_scp_resource_claimed && stage==2 && irq_calls+receive_calls==1);
 assert(inspect_calls==CONFIG_OP6893_CCCI_SCP_OWNER_OBSERVE);
 if(CONFIG_OP6893_CCCI_SCP_RECEIVE_RESERVE) {
  assert(receive_calls==1 && !irq_calls && !o->irq && o->receive==&receive_model);
  assert(irq_show(&pdev.dev,NULL,buf)==7 && !strcmp(buf,"receive") && receive_reports==1);
 } else {assert(!receive_calls && irq_calls==1 && !o->receive);assert(irq_show(&pdev.dev,NULL,buf)==6 && !strcmp(buf,"legacy"));}
 if(CONFIG_OP6893_CCCI_SCP_MMIO_RESERVE) {
  assert(mmio_calls==1 && !legacy_calls && !o->cfg && o->mmio==&mmio_model);
  assert(mmio_show(&pdev.dev,NULL,buf)==8 && !strcmp(buf,"mapped=6"));
  assert(cfg_show(&pdev.dev,NULL,buf)==10 && !strcmp(buf,"reserved=1"));assert(reports==2);
 } else {
  assert(!mmio_calls && legacy_calls==1 && o->cfg && !o->mmio);
  assert(mmio_show(&pdev.dev,NULL,buf)==-EOPNOTSUPP);
  assert(cfg_show(&pdev.dev,NULL,buf)>0 && strstr(buf,"register_reads=0 register_writes=0"));
 }
 if(CONFIG_OP6893_CCCI_SCP_CORE_TCM_RESERVE) {
  assert(core_maps==3 && core_lookups==3);
  assert(core_tcm_show(&pdev.dev,NULL,buf)>0 && strstr(buf,"mapped=3 bytes=1581056 nonposted=1"));
  assert(strstr(buf,"register_reads=0 register_writes=0 tcm_reads=0 tcm_writes=0"));
 } else {assert(!core_maps && !core_lookups);assert(core_tcm_show(&pdev.dev,NULL,buf)==-EOPNOTSUPP);}
 assert(!o->lock.locked);cleanup();assert(!ccci_scp_resource_claimed);
 setup();board=false;assert(ccci_scp_resource_probe(&pdev)==-ENODEV && !allocation);
 setup();nomem=true;assert(ccci_scp_resource_probe(&pdev)==-ENOMEM && !allocation);
 setup();clock_error=-EIO;assert(ccci_scp_resource_probe(&pdev)==-EIO && !stage);
 setup();clock_model.rate=13000000;assert(ccci_scp_resource_probe(&pdev)==-EBUSY && !stage);
 setup();ccci_scp_resource_claimed=true;assert(ccci_scp_resource_probe(&pdev)==-EBUSY && !stage);
 ccci_scp_resource_claimed=false;
 setup();action_fail=true;assert(ccci_scp_resource_probe(&pdev)==-ENOMEM && !stage && !ccci_scp_resource_claimed);
 const int errors[]={-ENOMEM,-EBUSY,-EINVAL,-EIO};
 for(unsigned i=0;i<4;i++) {
  setup();mmio_error=legacy_error=errors[i];
  assert(ccci_scp_resource_probe(&pdev)==errors[i] && !irq_calls && !receive_calls && !pdev.dev.data);
  assert(ccci_scp_resource_claimed);cleanup();assert(!ccci_scp_resource_claimed);
  setup();irq_error=errors[i];
  assert(ccci_scp_resource_probe(&pdev)==errors[i] && irq_calls+receive_calls==1 && !pdev.dev.data);
  cleanup();assert(!ccci_scp_resource_claimed);
 }
 if(CONFIG_OP6893_CCCI_SCP_OWNER_OBSERVE){
  for(unsigned i=0;i<4;i++){
   setup();inspect_error=errors[i];assert(ccci_scp_resource_probe(&pdev)==errors[i] && inspect_calls==1 && !receive_calls && !pdev.dev.data);
  }
 }
 if(CONFIG_OP6893_CCCI_SCP_CORE_TCM_RESERVE) {
  for(int i=0;i<3;i++) {
   setup();core_missing=i;assert(ccci_scp_resource_probe(&pdev)==-EINVAL && !core_maps && !receive_calls && !pdev.dev.data);
   setup();core_resources[i].start+=4;assert(ccci_scp_resource_probe(&pdev)==-EINVAL && !core_maps);
   setup();core_resources[i].end+=4;assert(ccci_scp_resource_probe(&pdev)==-EINVAL && !core_maps);
   for(unsigned j=0;j<4;j++) {
    setup();core_map_fail=i;core_map_error=errors[j];
    assert(ccci_scp_resource_probe(&pdev)==errors[j] && core_maps==(unsigned)i+1 && !receive_calls && !pdev.dev.data);
    o=allocation;assert(!o->core_tcm[0] && !o->core_tcm[1] && !o->core_tcm[2]);
   }
  }
 }
 cleanup();puts("PASS: actual owner probe/status, exclusive cfg/MMIO/receive branches, no double IRQ ownership, mapping before IRQ, failure propagation, devres claim release, and status serialization");
}
'''


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--dtb', type=Path, action='append', default=[])
    args = parser.parse_args()
    source = SOURCE.read_text()
    # RX start and the reset generation are owned by the one-shot initial boot
    # path only: the probe and the cfg/MMIO/IRQ branches exercised below must
    # never start reception or arm a generation.
    boot = extract(source, 'static ssize_t initial_boot_store(')
    assert source.count("ccci_scp_receive_start(") == 1
    assert boot.count("ccci_scp_receive_start(") == 1
    assert source.count("owner->reset_generation = ") == 2
    assert boot.count("owner->reset_generation = ") == 2
    assert "owner->reset_generation = 1" in boot
    assert "owner->reset_generation = 0" in boot
    helper = extract(source, 'static int ccci_scp_core_tcm_reserve(')
    assert not re.search(r'\b(readl|writel|memcpy_fromio|memcpy_toio|memset_io)\s*\(', helper)
    # The owner structure moved to its own header; keep the same shape check.
    owner_header = (K / 'drivers/misc/mediatek/ccci/ccci-scp-owner.h').read_text()
    code = (prefix + extract(owner_header, 'struct ccci_scp_resource_owner {') + ';\n' +
            'static DEFINE_MUTEX(ccci_scp_resource_owner_lock);\n' +
            'static bool ccci_scp_resource_claimed;\n' + dependencies +
            extract(source, 'static void ccci_scp_resource_unclaim(') + '\n' +
            extract(source, 'static ssize_t cfg_show(') + '\n' +
            extract(source, 'static ssize_t mmio_show(') + '\n' +
            extract(source, 'static ssize_t irq_show(') + '\n' +
            extract(source, 'static int ccci_scp_core_tcm_reserve(') + '\n' +
            extract(source, 'static ssize_t core_tcm_show(') + '\n' +
            extract(source, 'static int ccci_scp_resource_probe(') + '\n' + tests)
    with tempfile.TemporaryDirectory(prefix='op6893-mmio-owner-') as directory:
        root = Path(directory)
        (root / 'test.c').write_text(code)
        for enabled, receive, core, observe in ((0, 0, 0, 0), (1, 0, 0, 0),
                                                 (1, 1, 0, 0), (1, 1, 1, 0),
                                                 (1, 1, 1, 1)):
            subprocess.run(['cc', '-Wall', '-Wextra', '-Werror', '-Wno-unused-parameter',
                            '-Wno-unused-function', '-Wno-misleading-indentation',
                            '-fsanitize=address,undefined', '-fno-sanitize-recover=all',
                            '-no-pie', f'-DCONFIG_OP6893_CCCI_SCP_MMIO_RESERVE={enabled}',
                            f'-DCONFIG_OP6893_CCCI_SCP_RECEIVE_RESERVE={receive}',
                            f'-DCONFIG_OP6893_CCCI_SCP_CORE_TCM_RESERVE={core}',
                            f'-DCONFIG_OP6893_CCCI_SCP_OWNER_OBSERVE={observe}',
                            str(root / 'test.c'), '-o', str(root / 'test')], check=True)
            subprocess.run([str(root / 'test')], check=True)
    for dtb in args.dtb:
        node = '/scp-resource-hold@10724000'
        names = subprocess.check_output(['fdtget', str(dtb), node, 'reg-names'], text=True).split()
        assert names in (['scp-cfg', 'mbox0', 'mbox1', 'mbox2', 'mbox3', 'mbox4'],
                         ['scp-cfg', 'mbox0', 'mbox1', 'mbox2', 'mbox3', 'mbox4',
                          'core0', 'core1', 'tcm'])
        cells = subprocess.check_output(['fdtget', '-t', 'x', str(dtb), node, 'reg'], text=True).split()
        expected = []
        for base in (0x10724000, 0x107fb000, 0x107fc000, 0x107fd000, 0x107fe000, 0x107ff000):
            expected.extend(['0', f'{base:x}', '0', '1000'])
        if len(names) == 9:
            for base, size in ((0x10730000, 0x1000), (0x10740000, 0x1000),
                               (0x10500000, 0x180000)):
                expected.extend(['0', f'{base:x}', '0', f'{size:x}'])
        assert cells == expected
        print('PASS: exact named owner resources:', dtb.name)


if __name__ == '__main__':
    main()
