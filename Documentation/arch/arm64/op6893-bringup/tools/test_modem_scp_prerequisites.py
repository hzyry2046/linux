#!/usr/bin/env python3
# SPDX-License-Identifier: GPL-2.0-only
"""Compile AP-side observer boundary checks with failures; no device access."""
from pathlib import Path
import subprocess
import tempfile

KERNEL = Path(__file__).resolve().parents[5]
source = (KERNEL / 'drivers/misc/mediatek/ccci/ccci-scp-observe.c').read_text()


def function(declaration):
    start = source.index(declaration)
    return source[start:source.index('\n}', start) + 2]


code = r'''
#include <assert.h>
#include <errno.h>
#include <stdarg.h>
#include <stdint.h>
#include <stdio.h>
#include <string.h>
#include <stdbool.h>
#include <sys/types.h>
typedef uint64_t phys_addr_t;
#define U32_MAX UINT32_MAX
#define BIT(n) (1U<<(n))
#define GENMASK(h,l) (((~0U)>>(31-(h))) & ((~0U)<<(l)))
struct regmap { int unused; };
struct device_node { int unused; };
struct device_attribute { int unused; };
struct reserved_mem { uint64_t base,size; };
struct ccci_scp_observer {
 struct regmap *top; phys_addr_t firmware_base,firmware_size,share_base,share_size;
};
struct device { struct ccci_scp_observer *data; };
static struct device_node child,parent;
static struct reserved_mem rmem;
static bool has_node,has_parent,parent_name,available,nomap,reusable,has_rmem;
static unsigned ref_puts;
static struct device_node *of_parse_phandle(struct device_node *n,const char *p,unsigned i) {
 (void)n;assert(!strcmp(p,"memory-region") && i<2);return has_node?&child:NULL;
}
static struct device_node *of_get_parent(struct device_node *n) {
 assert(n==&child);return has_parent?&parent:NULL;
}
static bool of_node_name_eq(struct device_node *n,const char *s) {
 assert(n==&parent && !strcmp(s,"reserved-memory"));return parent_name;
}
static bool of_device_is_available(struct device_node *n) {assert(n==&child);return available;}
static bool of_property_present(struct device_node *n,const char *s) {
 assert(n==&child);if(!strcmp(s,"no-map"))return nomap;
 assert(!strcmp(s,"reusable"));return reusable;
}
static struct reserved_mem *of_reserved_mem_lookup(struct device_node *n) {
 assert(n==&child);return has_rmem?&rmem:NULL;
}
static void of_node_put(struct device_node *n) {if(n)ref_puts++;}
static void *dev_get_drvdata(struct device *d) {return d->data;}
static unsigned reads,fail_read;
static unsigned words[2];
static int regmap_read(struct regmap *m,unsigned offset,unsigned *out) {
 assert(m && offset==0x10 && reads<2);reads++;
 if(reads==fail_read)return -EIO;*out=words[reads-1];return 0;
}
static int sysfs_emit(char *buffer,const char *format,...) {
 va_list args;va_start(args,format);
 /* Avoid implementing kernel %pa in this userspace harness. */
 assert(strstr(format,"scp_access=0 ready_known=0"));
 unsigned sel=va_arg(args,unsigned),gate=va_arg(args,unsigned),equal=va_arg(args,unsigned);
 for(unsigned i=0;i<4;i++)assert(va_arg(args,phys_addr_t *));
 va_end(args);return snprintf(buffer,256,"selector=%u gated=%u samples_equal=%u",sel,gate,equal);
}
''' + function('static int ccci_scp_reservation(') + '\n' + function('static ssize_t state_show(') + r'''
static void reset(void) {
 has_node=has_parent=parent_name=available=nomap=has_rmem=true;
 reusable=false;ref_puts=0;rmem=(struct reserved_mem){0x8d000000,0x320000};
}
int main(void) {
 phys_addr_t base,size;
 reset();assert(!ccci_scp_reservation(&parent,1,&base,&size));
 assert(base==rmem.base && size==rmem.size && ref_puts==2);
 bool *flags[]={&has_node,&has_parent,&parent_name,&available,&nomap,&has_rmem};
 for(unsigned i=0;i<6;i++) {
  reset();*flags[i]=false;base=123;size=456;
  assert(ccci_scp_reservation(&parent,0,&base,&size)==-EINVAL);
  assert(base==123 && size==456);
  assert(ref_puts==(i==0?0:i==1?1:2));
 }
 reset();reusable=true;assert(ccci_scp_reservation(&parent,0,&base,&size)==-EINVAL);
 const struct reserved_mem bad[]={{0,4},{4,0},{0x100000000ULL,4},{0xfffffffc,8},{4,UINT64_MAX}};
 for(unsigned i=0;i<sizeof(bad)/sizeof(bad[0]);i++) {
  reset();rmem=bad[i];base=123;size=456;
  assert(ccci_scp_reservation(&parent,0,&base,&size)==-EINVAL);
  assert(base==123 && size==456 && ref_puts==2);
 }
 reset();rmem=(struct reserved_mem){0xfffffffc,4};
 assert(!ccci_scp_reservation(&parent,0,&base,&size));
 struct regmap m;struct ccci_scp_observer o={.top=&m};struct device d={.data=&o};
 char buf[256];
 for(unsigned failure=1;failure<=2;failure++) {
  reads=0;fail_read=failure;strcpy(buf,"unchanged");
  assert(state_show(&d,NULL,buf)==-EIO && reads==failure);
  assert(!strcmp(buf,"unchanged"));
 }
 fail_read=0;
 for(unsigned sel=0;sel<8;sel++)for(unsigned gate=0;gate<2;gate++) {
  reads=0;words[0]=words[1]=(sel<<16)|(gate<<23);
  assert(state_show(&d,NULL,buf)>0 && reads==2);
  char expected[100];snprintf(expected,sizeof(expected),"selector=%u gated=%u samples_equal=1",sel,gate);
  assert(!strcmp(buf,expected));
 }
 reads=0;words[0]=0;words[1]=BIT(16);
 assert(state_show(&d,NULL,buf)>0 && strstr(buf,"samples_equal=0"));
 reads=0;words[0]=0;words[1]=BIT(23);
 assert(state_show(&d,NULL,buf)>0 && strstr(buf,"samples_equal=0"));
 reads=0;words[0]=0;words[1]=BIT(1); /* Unrelated AXI changes not SCP changes. */
 assert(state_show(&d,NULL,buf)>0 && strstr(buf,"samples_equal=1"));
 printf("PASS: missing/disabled/reusable/unreserved/overflow regions refused; refs balanced\n");
 printf("PASS: both read failures propagated; selectors/gate/transitions; only TOPCK +0x10 reads\n");
 return 0;
}
'''
with tempfile.TemporaryDirectory(prefix='op6893-scp-prerequisites-') as directory:
    root = Path(directory)
    (root / 'test.c').write_text(code)
    subprocess.run(['cc', '-Wall', '-Wextra', '-Werror', '-Wno-unused-parameter',
                    '-Wno-misleading-indentation', '-fsanitize=address,undefined',
                    '-fno-sanitize-recover=all', '-no-pie', str(root / 'test.c'),
                    '-o', str(root / 'test')], check=True)
    subprocess.run([str(root / 'test')], check=True)
