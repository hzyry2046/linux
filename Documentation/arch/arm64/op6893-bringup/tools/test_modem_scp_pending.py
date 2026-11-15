#!/usr/bin/env python3
# SPDX-License-Identifier: GPL-2.0-only
"""Actual pending reader and IRQ parser with synthetic operations; no device I/O."""
import argparse
from pathlib import Path
import runpy
import subprocess
import tempfile

K = Path(__file__).resolve().parents[5]
src = (K / 'drivers/misc/mediatek/ccci/ccci-scp-observe.c').read_text()


def section(start, end):
    return src[src.index(start):src.index(end)]


code = r'''
#include <assert.h>
#include <errno.h>
#include <stdbool.h>
#include <stdint.h>
#include <stdio.h>
#include <string.h>
typedef uint32_t u32;
#define __iomem
#define CCCI_SCP_MAX_MBOXES 5
#define BIT(n) (1U<<(n))
#define GENMASK(h,l) (((~0U)>>(31-(h))) & ((~0U)<<(l)))
struct ccci_scp_observer {void *top; unsigned char *core0,*pending[5];};
static unsigned char core0[0x1000],mmio[5][4];
static unsigned core_reads,pending_reads,top_reads,fail_top,values[12],pending_values[10],words[4];
static int regmap_read(void *m,unsigned offset,unsigned *out) {
 assert(m && offset==0x10 && top_reads<4);top_reads++;
 if(top_reads==fail_top)return -EIO;*out=words[top_reads-1];return 0;
}
static u32 readl(void *p) {
 if(p==core0 || p==core0+4 || p==core0+0x70) {
  static const unsigned offsets[]={0,4,0x70,0,4,0x70};
  assert(core_reads<12 && p==core0+offsets[core_reads%6]);return values[core_reads++];
 }
 assert(pending_reads<10 && p==mmio[pending_reads%5]);
 return pending_values[pending_reads++];
}
struct device_node {int unused;};
struct of_phandle_args {struct device_node *np;unsigned args_count,args[3];};
static struct device_node controller;
static int match_error,parse_error;
static bool compatible,available;
static unsigned puts_count,parse_count,argc,irq_type,spi,flags;
static int of_property_match_string(struct device_node *n,const char *key,const char *name) {
 assert(n && !strcmp(key,"interrupt-names") && !strncmp(name,"mbox",4));
 return match_error?match_error:name[4]-'0';
}
static int of_irq_parse_one(struct device_node *n,int index,struct of_phandle_args *out) {
 assert(n && index>=0 && index<5);parse_count++;
 if(parse_error)return parse_error;
 *out=(struct of_phandle_args){&controller,argc,{irq_type,spi,flags}};return 0;
}
static bool of_device_is_compatible(struct device_node *n,const char *name) {
 assert(n==&controller && !strcmp(name,"arm,gic-v3"));return compatible;
}
static bool of_device_is_available(struct device_node *n) {assert(n==&controller);return available;}
static void of_node_put(struct device_node *n) {assert(n==&controller);puts_count++;}
''' + section('struct ccci_scp_core0_sample {', 'static ssize_t core0_show') + section('static int ccci_scp_irq_spec', 'static int ccci_scp_table') + section('static int ccci_scp_pending_read', 'static ssize_t pending_show') + r'''
static void reset(struct ccci_scp_observer *o) {
 core_reads=pending_reads=top_reads=fail_top=0;
 memset(values,0,sizeof(values));memset(words,0,sizeof(words));
 for(unsigned i=0;i<10;i++)pending_values[i]=BIT(i%5);
 for(unsigned i=0;i<5;i++)o->pending[i]=mmio[i];
}
static void cleared(u32 *p) {for(unsigned i=0;i<5;i++)assert(!p[i]);}
int main(void) {
 struct ccci_scp_observer o={.top=&o,.core0=core0};u32 out[5];
 reset(&o);assert(!ccci_scp_pending_read(&o,out));
 for(unsigned i=0;i<5;i++)assert(out[i]==BIT(i));
 assert(pending_reads==10 && core_reads==12 && top_reads==4);
 for(unsigned missing=0;missing<5;missing++) {
  reset(&o);o.pending[missing]=NULL;memset(out,0xa5,sizeof(out));
  assert(ccci_scp_pending_read(&o,out)==-EOPNOTSUPP);
  cleared(out);assert(!pending_reads && !core_reads && !top_reads);
 }
 for(unsigned failure=1;failure<=4;failure++) {
  reset(&o);fail_top=failure;memset(out,0xa5,sizeof(out));
  assert(ccci_scp_pending_read(&o,out)==-EIO);cleared(out);
  assert(pending_reads==(failure<3?0:10));
 }
 for(unsigned phase=0;phase<4;phase++)for(unsigned bit=16;bit<=23;bit++) {
  if(bit>18 && bit!=23)continue;
  reset(&o);words[phase]=BIT(bit);memset(out,0xa5,sizeof(out));
  assert(ccci_scp_pending_read(&o,out)==-EAGAIN);cleared(out);
  assert(pending_reads==(phase<2?0:10));
 }
 for(unsigned box=0;box<5;box++) {
  reset(&o);pending_values[box+5]^=BIT(31);
  assert(ccci_scp_pending_read(&o,out)==-EAGAIN);cleared(out);
 }
 for(unsigned field=0;field<3;field++) {
  reset(&o);values[6+field]=values[9+field]=1;
  assert(ccci_scp_pending_read(&o,out)==-EAGAIN);cleared(out);
 }
 reset(&o);for(unsigned i=0;i<10;i++)pending_values[i]=UINT32_MAX;
 assert(!ccci_scp_pending_read(&o,out)); /* Report unknown bits, never clear. */
 for(unsigned i=0;i<5;i++)assert(out[i]==UINT32_MAX);
 struct device_node device;
 for(unsigned box=0;box<5;box++)for(unsigned bad=0;bad<9;bad++) {
  match_error=parse_error=0;compatible=available=true;argc=3;irq_type=0;spi=436+box;flags=4;
  puts_count=parse_count=0;char name[10];snprintf(name,sizeof(name),"mbox%u",box);
  switch(bad){case 1:match_error=-ENOENT;break;case 2:parse_error=-EINVAL;break;
  case 3:compatible=false;break;case 4:available=false;break;case 5:argc=2;break;
  case 6:irq_type=1;break;case 7:spi++;break;case 8:flags=1;break;}
  assert((ccci_scp_irq_spec(&device,name,box)==0)==(bad==0));
  assert(puts_count==((bad==1 || bad==2)?0:1));assert(parse_count==(bad==1?0:1));
 }
 puts("PASS: ten exact pending reads, missing maps, all pre/post errors/transitions, unknown bits preserved, IRQ spec validation/ref cleanup without mapping");
}
'''
with tempfile.TemporaryDirectory(prefix='op6893-pending-') as directory:
    p = Path(directory)
    (p / 'test.c').write_text(code)
    subprocess.run(['cc', '-Wall', '-Wextra', '-Werror', '-Wno-misleading-indentation',
                    '-fsanitize=address,undefined', '-fno-sanitize-recover=all',
                    '-no-pie', str(p / 'test.c'), '-o', str(p / 'test')], check=True)
    subprocess.run([str(p / 'test')], check=True)

parser = argparse.ArgumentParser()
parser.add_argument('--dtb', type=Path, action='append', default=[])
args = parser.parse_args()
fixture = runpy.run_path(str(Path(__file__).with_name('test_modem_scp.py')))['audited_fixture']()
for dtb in args.dtb:
    node = '/scp-observe@10730000'

    def get(name, kind='x'):
        return subprocess.check_output(['fdtget', '-t', kind, str(dtb), node, name], text=True).split()

    names = get('reg-names', 's')
    regs = [int(v, 16) for v in get('reg')]
    assert len(names) == 7 and len(regs) == 28
    for box in range(5):
        index = names.index(f'mbox{box}-clr')
        assert regs[index*4:index*4+4] == [0, 0x107fb10c+box*0x1000, 0, 4]
    assert get('interrupt-names', 's') == [f'mbox{i}' for i in range(5)]
    assert [int(v, 16) for v in get('interrupts')] == [v for i in range(5) for v in (0, 436+i, 4)]
    for name, expected in zip(('send-table', 'recv-table'), fixture[:2]):
        assert [int(v, 16) for v in get('mediatek,'+name)] == expected
    print('PASS: DTB exact pending resources, IRQ specs and complete TX/RX fixture:', dtb.name)
