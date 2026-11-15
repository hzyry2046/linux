#!/usr/bin/env python3
# SPDX-License-Identifier: GPL-2.0-only
"""Exercise the actual cfg reservation and status callback without device I/O."""
from pathlib import Path
import argparse
import subprocess
import tempfile

K = Path(__file__).resolve().parents[5]
SOURCE = K / 'drivers/misc/mediatek/ccci/ccci-scp-resource-hold.c'


def function(source, marker):
    start = source.index(marker)
    end = source.index('{', start) + 1
    depth = 1
    while depth:
        depth += (source[end] == '{') - (source[end] == '}')
        end += 1
    return source[start:end]


PREFIX = r'''
#include <assert.h>
#include <errno.h>
#include <stdbool.h>
#include <stdint.h>
#include <stdarg.h>
#include <stdio.h>
#include <string.h>
#include <sys/types.h>
#define __iomem
#define IS_ENABLED(x) 0
#define IORESOURCE_MEM 0x200
#define IS_ERR(p) ((uintptr_t)(p) >= (uintptr_t)-4095)
#define PTR_ERR(p) ((intptr_t)(p))
struct resource {uint64_t start,end;};
struct device_node {bool alternate,workaround;};
struct device {struct device_node *of_node;void *data;};
struct platform_device {struct device dev;};
struct device_attribute {int unused;};
struct ccci_scp_resource_owner {void *cfg;};
static struct resource resource;
static bool missing,claimed;
static unsigned lookups,maps,properties;
static int map_error;
static char mapping[4096];
static uint64_t resource_size(struct resource *r) {return r->end-r->start+1;}
static struct resource *platform_get_resource_byname(struct platform_device *p,
 unsigned type,const char *name) {
 assert(p && type==IORESOURCE_MEM && !strcmp(name,"scp-cfg"));lookups++;
 return missing?NULL:&resource;
}
static bool of_property_present(struct device_node *n,const char *name) {
 assert(n);properties++;
 if(!strcmp(name,"scp-cfgreg-ap-en"))return n->alternate;
 assert(!strcmp(name,"scp-ipc-wa"));return n->workaround;
}
static void *devm_ioremap_resource(struct device *dev,struct resource *r) {
 assert(dev && r==&resource && r->start==0x10724000 && r->end==0x10724fff);maps++;
 if(map_error)return (void *)(intptr_t)map_error;
 if(claimed)return (void *)(intptr_t)-EBUSY;
 claimed=true;return mapping;
}
static void *dev_get_drvdata(struct device *dev) {return dev->data;}
static int sysfs_emit(char *buf,const char *fmt,...) {
 va_list args;va_start(args,fmt);int n=vsnprintf(buf,4096,fmt,args);va_end(args);return n;
}
'''
TESTS = r'''
static void reset(struct ccci_scp_resource_owner *o,struct device_node *node) {
 *o=(struct ccci_scp_resource_owner){0};*node=(struct device_node){0};
 resource=(struct resource){0x10724000,0x10724fff};
 missing=claimed=false;lookups=maps=properties=0;map_error=0;
 memset(mapping,0xa5,sizeof(mapping));
}
static void untouched(void) {
 for(unsigned i=0;i<sizeof(mapping);i++)assert((unsigned char)mapping[i]==0xa5);
}
int main(void) {
 struct ccci_scp_resource_owner o,other={0};struct device_node node;
 struct platform_device p={.dev={.of_node=&node,.data=&o}};char buf[4096];
 reset(&o,&node);assert(cfg_show(&p.dev,NULL,buf)==-EOPNOTSUPP && !maps && !lookups);
 assert(!ccci_scp_cfg_reserve(&p,&o) && o.cfg==mapping && maps==1 && lookups==1);
 for(unsigned i=0;i<5;i++)assert(cfg_show(&p.dev,NULL,buf)>0 &&
  !strcmp(buf,"reserved=1 bytes=4096 register_reads=0 register_writes=0 completion_enabled=0 ready_known=0\n"));
 assert(maps==1 && lookups==1);untouched();
 assert(ccci_scp_cfg_reserve(&p,&other)==-EBUSY && !other.cfg);
 assert(maps==2 && o.cfg==mapping);untouched();
 reset(&o,&node);missing=true;
 assert(ccci_scp_cfg_reserve(&p,&o)==-EINVAL && !maps && !properties && !o.cfg);
 /* Reject shifted, shortened, enlarged, wrapped and reversed windows before mapping. */
 const uint64_t starts[]={0x10724004,0x10723000,0,UINT64_MAX,0x10724000,0x10724000,0x10724000,0x10724000};
 const uint64_t ends[]={0x10725003,0x10724fff,0xfff,0xffe,0x10724ffe,0x10725000,0x10723fff,UINT64_MAX};
 for(unsigned i=0;i<sizeof(starts)/sizeof(starts[0]);i++) {
  reset(&o,&node);resource=(struct resource){starts[i],ends[i]};
  assert(ccci_scp_cfg_reserve(&p,&o)==-EINVAL && !maps && !properties && !o.cfg);
 }
 for(unsigned i=1;i<4;i++) {
  reset(&o,&node);node.alternate=i&1;node.workaround=i&2;
  assert(ccci_scp_cfg_reserve(&p,&o)==-EOPNOTSUPP && !maps && !o.cfg);untouched();
 }
 const int errors[]={-EBUSY,-ENOMEM,-EINVAL,-EPROBE_DEFER};
 for(unsigned i=0;i<sizeof(errors)/sizeof(errors[0]);i++) {
  reset(&o,&node);map_error=errors[i];
  assert(ccci_scp_cfg_reserve(&p,&o)==errors[i] && maps==1 && !o.cfg);untouched();
 }
 puts("PASS: actual cfg reservation/status, exact window, conflicting claim, missing/malformed resources, alternate protocols, mapping errors and untouched MMIO model");
}
'''


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--dtb', type=Path, action='append', default=[])
    args = parser.parse_args()
    source = SOURCE.read_text()
    code = (PREFIX + '\n#define EPROBE_DEFER 517\n' +
            function(source, 'static int ccci_scp_cfg_reserve(') + '\n' +
            function(source, 'static ssize_t cfg_show(') + '\n' + TESTS)
    with tempfile.TemporaryDirectory(prefix='op6893-scp-cfg-') as directory:
        root = Path(directory)
        (root / 'test.c').write_text(code)
        subprocess.run(['cc', '-std=gnu11', '-Wall', '-Wextra', '-Werror',
                        '-Wno-unused-parameter', '-fsanitize=address,undefined',
                        '-fno-sanitize-recover=all', '-no-pie', str(root / 'test.c'),
                        '-o', str(root / 'test')], check=True)
        subprocess.run([str(root / 'test')], check=True)
    for dtb in args.dtb:
        node = '/scp-resource-hold@10724000'
        reg = subprocess.check_output(['fdtget', '-t', 'x', str(dtb), node, 'reg'], text=True)
        cells = reg.split()
        assert cells[:4] == ['0', '10724000', '0', '1000']
        assert len(cells) in (4, 24)
        name = subprocess.check_output(['fdtget', str(dtb), node, 'reg-names'], text=True)
        names = name.split()
        assert names[0] == 'scp-cfg' and len(names) == len(cells) // 4
        print('PASS: complete cfg resource preserved in DTB:', dtb.name)


if __name__ == '__main__':
    main()
