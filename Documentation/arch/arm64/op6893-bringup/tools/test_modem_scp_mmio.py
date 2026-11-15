#!/usr/bin/env python3
# SPDX-License-Identifier: GPL-2.0-only
"""Actual non-posted MMIO backend and queue/RX/drain with synthetic device I/O."""
from pathlib import Path
import ast
import runpy
import subprocess
import tempfile

K = Path(__file__).resolve().parents[5]
D = K / 'drivers/misc/mediatek/ccci'
tx, rx, _ = runpy.run_path(str(Path(__file__).with_name('test_modem_scp.py')))['audited_fixture']()
tree = ast.parse(Path(__file__).with_name('test_modem_scp_drain.py').read_text())
preamble = next(ast.literal_eval(n.value) for n in tree.body
                if isinstance(n, ast.Assign) and any(isinstance(t, ast.Name) and t.id == 'preamble'
                                                     for t in n.targets))


def source(name):
    return '\n'.join(line for line in (D / name).read_text().splitlines()
                     if not line.startswith('#include'))


preamble += r'''
#include <stdlib.h>
#include <stdarg.h>
#include <sys/types.h>
#define __iomem
#define GFP_KERNEL 0
#define IORESOURCE_MEM 0x200
#define IORESOURCE_MEM_NONPOSTED 0x8000
#define IS_ERR(p) ((uintptr_t)(p)>=(uintptr_t)-4095)
#define PTR_ERR(p) ((intptr_t)(p))
#define EPROBE_DEFER 517
struct resource {u64 start,end;unsigned flags;};
struct device_node {bool alternate,workaround;};
struct device {struct device_node *of_node;};
struct platform_device {struct device dev;};
static struct device_node node;
static struct platform_device pdev={.dev={.of_node=&node}};
static struct resource resources[6];
static unsigned char pages[6][4096];
static bool claimed[6],nomem,new_arrival,continuous;
static void *allocation;
static int missing,bad_map;
static unsigned lookups,maps,reads,writes,barriers,checks,fail_check;
static unsigned stage[5],copied[5],expected_words[5];
static u32 known[5];
static bool store_outstanding;
static unsigned current_box;
static int sysfs_emit(char *buf,const char *fmt,...) {
 va_list args;va_start(args,fmt);int n=vsnprintf(buf,4096,fmt,args);va_end(args);return n;
}
static unsigned hweight32(u32 x) {return __builtin_popcount(x);}
static void memzero_explicit(void *p,size_t n) {memset(p,0,n);}
static u64 resource_size(struct resource *r) {return r->end-r->start+1;}
static bool of_property_present(struct device_node *n,const char *s) {
 assert(n==&node);
 if(!strcmp(s,"scp-cfgreg-ap-en"))return n->alternate;
 assert(!strcmp(s,"scp-ipc-wa"));return n->workaround;
}
static struct resource *platform_get_resource_byname(struct platform_device *p,unsigned type,const char *s) {
 assert(p==&pdev && type==IORESOURCE_MEM);unsigned i;
 if(!strcmp(s,"scp-cfg"))i=0;else {assert(!strncmp(s,"mbox",4));i=1+s[4]-'0';assert(i>=1 && i<=5);}
 lookups++;return missing==(int)i?NULL:&resources[i];
}
static void *devm_kzalloc(struct device *d,size_t n,int flags) {
 assert(d==&pdev.dev && flags==GFP_KERNEL && !allocation);
 if(nomem)return NULL;allocation=calloc(1,n);assert(allocation);return allocation;
}
static void *devm_ioremap_resource(struct device *d,struct resource *r) {
 assert(d==&pdev.dev && (r->flags&IORESOURCE_MEM_NONPOSTED));unsigned i=maps++;
 assert(i<6 && r!=&resources[i] && r->start==resources[i].start && resource_size(r)==4096);
 if(bad_map==(int)i)return (void *)(intptr_t)-ENOMEM;
 if(claimed[i])return (void *)(intptr_t)-EBUSY;
 claimed[i]=true;return pages[i];
}
static unsigned page_index(const void *p,unsigned *offset) {
 for(unsigned i=0;i<6;i++) {
  uintptr_t addr=(uintptr_t)p,base=(uintptr_t)pages[i];
  if(addr>=base && addr<base+4096){*offset=addr-base;assert(!(*offset%4));return i;}
 }
 assert(0);return 0;
}
static u32 readl(const void *p) {
 unsigned offset,i=page_index(p,&offset);assert(i && !store_outstanding);reads++;
 unsigned b=i-1;u32 value=get_unaligned_le32(p);
 if(offset==0x10c) {
  current_box=b;stage[b]=1;copied[b]=0;
  if(continuous){value=known[b];put_unaligned_le32(value,pages[i]+0x10c);}
  expected_words[b]=0;
 } else {assert(offset<256 && stage[b]==1 && current_box==b);copied[b]++;}
 return value;
}
static void writel(u32 v,void *p) {
 unsigned offset,i=page_index(p,&offset);assert(!store_outstanding);writes++;
 if(!i) {
  assert(offset==0x94 && v==1 && stage[current_box]==1);
  assert(copied[current_box]==expected_words[current_box]);stage[current_box]=2;
 } else {
  unsigned b=i-1;assert(offset==0x10c && b==current_box && stage[b]==2);
  assert(v && !(v&~known[b]));stage[b]=3;
  u32 pending=get_unaligned_le32(p);assert((pending&v)==v);
  put_unaligned_le32(new_arrival?v:(pending&~v),p);
  memset(pages[i],0xed,256);
 }
 store_outstanding=true;
}
static void mb(void) {assert(store_outstanding);barriers++;store_outstanding=false;}
'''

harness = r'''
static const u32 tx[]={@TX@},rt[]={@RX@};
static struct ccci_scp_layout layout;
static struct ccci_scp_queue queue;
static struct ccci_scp_event event;
static struct ccci_scp_mmio *mmio;
static struct ccci_scp_drain drain;
static bool masked;
static u64 reset_generation;
static const struct ccci_scp_rx_ops *hardware[5];
static void *contexts[5];
static int prerequisite(void *context,u64 generation) {
 assert(context==&reset_generation && generation==reset_generation);
 if(++checks==fail_check)return -EIO;
 /* Count expected data words for this transaction before post writes. */
 for(unsigned b=0;b<5;b++) {
  u32 pending=get_unaligned_le32(pages[b+1]+0x10c);expected_words[b]=0;
  for(unsigned j=0;j<layout.rx_count;j++)if(layout.rx[j].mbox==b && (pending&BIT(layout.rx[j].irq)))
   expected_words[b]+=layout.rx[j].words;
 }
 return 0;
}
static void reset_model(void) {
 free(allocation);allocation=NULL;mmio=NULL;
 memset(pages,0,sizeof(pages));memset(claimed,0,sizeof(claimed));node=(struct device_node){0};
 for(unsigned i=0;i<6;i++) {
  u64 base=i?0x107fb000+(i-1)*4096:0x10724000;
  resources[i]=(struct resource){base,base+4095,IORESOURCE_MEM};
 }
 missing=bad_map=-1;nomem=new_arrival=continuous=false;
 lookups=maps=reads=writes=barriers=checks=fail_check=0;store_outstanding=false;
 memset(stage,0,sizeof(stage));memset(copied,0,sizeof(copied));memset(known,0,sizeof(known));
 assert(!ccci_scp_build_layout(tx,ARRAY_SIZE(tx),rt,ARRAY_SIZE(rt),5,&layout));
 for(unsigned j=0;j<layout.rx_count;j++)known[layout.rx[j].mbox]|=BIT(layout.rx[j].irq);
 reset_generation=17;masked=true;
}
static void setup(unsigned capacity) {
 reset_model();assert(!ccci_scp_mmio_reserve(&pdev,&mmio) && maps==6);
 for(unsigned i=0;i<6;i++)assert(resources[i].flags==IORESOURCE_MEM);
 assert(!ccci_scp_mmio_prepare(mmio,&layout,17,prerequisite,&reset_generation));
 for(unsigned i=0;i<5;i++) {hardware[i]=ccci_scp_mmio_ops();contexts[i]=ccci_scp_mmio_port(mmio,i);}
 assert(!ccci_scp_queue_init(&queue,&layout,17,capacity,hardware,contexts));
 assert(!reads && !writes && !barriers && !checks);
}
static void messages(void) {
 for(unsigned b=0;b<5;b++) {
  for(unsigned i=0;i<256;i++)pages[b+1][i]=(u8)(i+b+7);
  put_unaligned_le32(known[b],pages[b+1]+0x10c);
 }
}
static void verify_events(unsigned count) {
 for(unsigned n=0;n<count;n++) {
  assert(!store_outstanding && !ccci_scp_queue_pop(&queue,17,&event));
  assert(event.generation==17 && event.bytes==event.pin.words*4);
  for(unsigned j=0;j<event.bytes;j++)assert(event.data[j]==(u8)(event.pin.offset*4+j+event.pin.mbox+7));
 }
 assert(ccci_scp_queue_pop(&queue,17,&event)==-ENODATA);
}
static int set_masked(void *p,bool value) {assert(p==&drain);masked=value;return 0;}
static int drain_check(void *p,u64 generation) {assert(p==&drain && masked);return prerequisite(&reset_generation,generation);}
static const struct ccci_scp_drain_ops drainops={set_masked,drain_check};
int main(void) {
 struct ccci_scp_rx_result result;u32 mask;u8 buffer[259];char status[4096];
 /* Every resource is validated before mapping; original descriptors unchanged. */
 for(unsigned i=0;i<6;i++) {
  reset_model();missing=i;assert(ccci_scp_mmio_reserve(&pdev,&mmio)==-EINVAL && !maps && !mmio);
  for(unsigned bad=0;bad<4;bad++) {
   reset_model();switch(bad){case 0:resources[i].start+=4;break;case 1:resources[i].end--;break;
    case 2:resources[i].end++;break;case 3:resources[i].end=resources[i].start-1;break;}
   assert(ccci_scp_mmio_reserve(&pdev,&mmio)==-EINVAL && !maps && !mmio);
  }
  reset_model();bad_map=i;
  assert(ccci_scp_mmio_reserve(&pdev,&mmio)==-ENOMEM && maps==i+1 && !mmio);
  /* Caller aborts probe: synthetic devres rollback happens in reset_model. */
  reset_model();claimed[i]=true;
  assert(ccci_scp_mmio_reserve(&pdev,&mmio)==-EBUSY && maps==i+1 && !mmio);
 }
 for(unsigned i=1;i<4;i++) {
  reset_model();node.alternate=i&1;node.workaround=i&2;
  assert(ccci_scp_mmio_reserve(&pdev,&mmio)==-EOPNOTSUPP && !maps && !mmio);
 }
 reset_model();nomem=true;assert(ccci_scp_mmio_reserve(&pdev,&mmio)==-ENOMEM && !maps);
 assert(ccci_scp_mmio_reserve(NULL,&mmio)==-EINVAL && !mmio);
 assert(ccci_scp_mmio_reserve(&pdev,NULL)==-EINVAL);
 /* Unprepared mappings cannot perform any I/O; prepare itself has no I/O. */
 reset_model();assert(!ccci_scp_mmio_reserve(&pdev,&mmio));
 assert(ccci_scp_mmio_ops()->pending(ccci_scp_mmio_port(mmio,0),&mask)==-ESHUTDOWN);
 assert(!reads && !writes);
 setup(64);assert(ccci_scp_mmio_prepare(mmio,&layout,18,prerequisite,&reset_generation)==-EBUSY);
 assert(ccci_scp_mmio_status(mmio,status)>0 && strstr(status,"register_reads=0 register_writes=0 prepared=1 generation=17 fault=0"));
 assert(ccci_scp_mmio_cfg_status(mmio,status)>0 && strstr(status,"register_reads=0 register_writes=0 completion_enabled=1"));
 assert(ccci_scp_mmio_status(NULL,status)==-EOPNOTSUPP && ccci_scp_mmio_cfg_status(NULL,status)==-EOPNOTSUPP);
 for(unsigned b=0;b<5;b++)assert(!ccci_scp_rx_step(&queue.rx[b],&result) && !result.pending);
 assert(reads==5 && !writes && !barriers);
 /* Full board: only exact wire words read, snapshot survives destructive ACK. */
 setup(64);messages();
 for(unsigned b=0;b<5;b++)assert(!ccci_scp_rx_step(&queue.rx[b],&result));
 assert(queue.count==17 && writes==10 && barriers==10);verify_events(17);
 assert(mmio->register_reads==reads && mmio->register_writes==writes && mmio->cfg_writes==5);
 assert(ccci_scp_mmio_cfg_status(mmio,status)>0 && strstr(status,"register_writes=5 completion_enabled=1"));
 /* A new message at ACK is permitted; there is no clear-bit assertion/readback. */
 setup(64);messages();new_arrival=true;
 assert(!ccci_scp_rx_step(&queue.rx[0],&result));
 assert(get_unaligned_le32(pages[1]+0x10c)==known[0] && writes==2 && barriers==2);
 /* Every prerequisite failure before each operation stops I/O and all ports. */
 for(unsigned b=0;b<5;b++) {
  unsigned pins=0;for(unsigned j=0;j<layout.rx_count;j++)pins+=layout.rx[j].mbox==b;
  for(unsigned fail=1;fail<=pins+3;fail++) {
   setup(64);messages();fail_check=fail;
   assert(ccci_scp_rx_step(&queue.rx[b],&result)==-EIO && mmio->fault && !queue.count);
   unsigned r=reads,w=writes,c=checks;
   for(unsigned other=0;other<5;other++)assert(ccci_scp_mmio_ops()->pending(contexts[other],&mask)==-ESHUTDOWN);
   assert(reads==r && writes==w && checks==c && !store_outstanding);
  }
 }
 /* Unsupported pending and capacity reject before any completion/ACK write. */
 setup(64);put_unaligned_le32(BIT(31),pages[1]+0x10c);
 assert(ccci_scp_rx_step(&queue.rx[0],&result)==-EOPNOTSUPP && reads==1 && !writes);
 setup(1);messages();assert(ccci_scp_rx_step(&queue.rx[1],&result)==-ENOSPC && !writes);
 /* Direct hardware callback bounds and unaligned CPU output. */
 const u32 offsets[]={64,UINT32_MAX,0,0,63};
 const u32 words[]={1,1,0,65,2};
 for(unsigned i=0;i<5;i++) {
  setup(64);assert(ccci_scp_mmio_ops()->read_words(contexts[0],offsets[i],words[i],buffer)==-EINVAL);
  assert(!reads && !writes && mmio->fault);
 }
 setup(64);assert(ccci_scp_mmio_ops()->read_words(contexts[0],0,1,NULL)==-EINVAL && !reads);
 setup(64);pages[1][252]=0x12;pages[1][253]=0x34;pages[1][254]=0x56;pages[1][255]=0x78;
 stage[0]=1;current_box=0;
 assert(!ccci_scp_mmio_ops()->read_words(contexts[0],63,1,buffer+1));
 assert(get_unaligned_le32(buffer+1)==0x78563412 && reads==1);
 setup(64);stage[0]=1;current_box=0;
 for(unsigned i=0;i<256;i++)pages[1][i]=(u8)i;
 assert(!ccci_scp_mmio_ops()->read_words(contexts[0],0,64,buffer+1) && reads==64);
 for(unsigned i=0;i<256;i++)assert(buffer[i+1]==(u8)i);
 for(unsigned i=0;i<2;i++) {
  setup(64);assert(ccci_scp_mmio_ops()->ack(contexts[0],i?BIT(31):0)==-EINVAL && !writes && mmio->fault);
 }
 setup(64);assert(ccci_scp_mmio_ops()->pending(NULL,&mask)==-EINVAL);
 assert(ccci_scp_mmio_ops()->pending(contexts[0],NULL)==-EINVAL);
 assert(!ccci_scp_mmio_port(NULL,0) && !ccci_scp_mmio_port(mmio,5));
 /* Monotonic generations only after invalidation; no implicit fault retry. */
 setup(64);ccci_scp_mmio_invalidate(mmio);
 assert(ccci_scp_mmio_prepare(mmio,&layout,17,prerequisite,&reset_generation)==-ESTALE);
 assert(ccci_scp_mmio_prepare(mmio,&layout,16,prerequisite,&reset_generation)==-ESTALE);
 assert(ccci_scp_mmio_prepare(mmio,&layout,18,NULL,NULL)==-EINVAL);
 assert(ccci_scp_mmio_prepare(mmio,&layout,0,prerequisite,NULL)==-EINVAL);
 struct ccci_scp_layout broken=layout;broken.rx[0].mbox=5;
 assert(ccci_scp_mmio_prepare(mmio,&broken,18,prerequisite,NULL)==-EINVAL);
 broken=layout;broken.rx[0].irq=32;
 assert(ccci_scp_mmio_prepare(mmio,&broken,18,prerequisite,NULL)==-EINVAL);
 broken=layout;broken.rx[0].words=0;
 assert(ccci_scp_mmio_prepare(mmio,&broken,18,prerequisite,NULL)==-EINVAL);
 reset_generation=18;assert(!ccci_scp_mmio_prepare(mmio,&layout,18,prerequisite,&reset_generation));
 assert(!reads && !writes);ccci_scp_mmio_invalidate(NULL);
 /* Actual bounded drain: full empty sweep before unmask, finite busy fault. */
 setup(64);messages();struct ccci_scp_rx *receivers[5];
 for(unsigned i=0;i<5;i++)receivers[i]=&queue.rx[i];
 assert(!ccci_scp_drain_init(&drain,&drainops,&drain));
 assert(!ccci_scp_drain_prepare(&drain,receivers,17,4));
 assert(!ccci_scp_drain_run(&drain,17) && !masked && queue.count==17);
 verify_events(17);
 setup(64);messages();continuous=true;
 for(unsigned i=0;i<5;i++)receivers[i]=&queue.rx[i];
 assert(!ccci_scp_drain_init(&drain,&drainops,&drain));
 assert(!ccci_scp_drain_prepare(&drain,receivers,17,1));
 assert(ccci_scp_drain_run(&drain,17)==-EOVERFLOW && masked);
 ccci_scp_queue_invalidate(&queue);ccci_scp_mmio_invalidate(mmio);
 assert(queue.fault && !queue.count && mmio->fault);
 free(allocation);
 puts("PASS: actual MMIO/queue/RX/drain; six full-page non-posted claims, all resource/map failures, exact wire copies, completion/barrier/ACK/barrier, destructive ACK and new arrivals, prerequisite faults, bounds, generations and budget containment");
}
'''.replace('@TX@', ','.join(map(str, tx))).replace('@RX@', ','.join(map(str, rx)))
code = preamble + '\n'.join(source(n) for n in (
    'ccci-scp-protocol.h', 'ccci-scp-rx.h', 'ccci-scp-drain.h', 'ccci-scp-queue.h',
    'ccci-scp-mmio.h', 'ccci-scp-protocol.c', 'ccci-scp-rx.c', 'ccci-scp-drain.c',
    'ccci-scp-queue.c', 'ccci-scp-mmio.c')) + harness
with tempfile.TemporaryDirectory(prefix='op6893-mmio-') as directory:
    root = Path(directory)
    (root / 'test.c').write_text(code)
    subprocess.run(['cc', '-Wall', '-Wextra', '-Werror', '-Wno-unused-parameter',
                    '-Wno-misleading-indentation', '-Wno-sign-compare',
                    '-fsanitize=address,undefined', '-fno-sanitize-recover=all',
                    '-no-pie', str(root / 'test.c'), '-o', str(root / 'test')], check=True)
    subprocess.run([str(root / 'test')], check=True)
