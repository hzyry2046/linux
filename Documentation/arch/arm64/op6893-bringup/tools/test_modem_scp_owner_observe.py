#!/usr/bin/env python3
# SPDX-License-Identifier: GPL-2.0-only
"""Actual unique-owner observation code with bounded synthetic MMIO and OF."""
from pathlib import Path
import subprocess
import tempfile

K = Path(__file__).resolve().parents[5]
D = K / 'drivers/misc/mediatek/ccci'


def without_includes(path):
    return '\n'.join(line for line in path.read_text().splitlines()
                     if not line.startswith('#include'))


prefix = r'''
#include <assert.h>
#include <errno.h>
#include <stdint.h>
#include <stdbool.h>
#include <stdio.h>
#include <stdlib.h>
#include <stdarg.h>
#include <string.h>
#include <sys/types.h>
typedef uint8_t u8;
typedef uint32_t u32;
typedef unsigned long long u64;
#define __iomem
#define U32_MAX UINT32_MAX
#define U64_MAX UINT64_MAX
#define BIT(n) (1U<<(n))
#define GENMASK(h,l) (((~0U)>>(31-(h))) & ((~0U)<<(l)))
#define GFP_KERNEL 0
#define IS_ERR(p) ((uintptr_t)(p)>=(uintptr_t)-4095)
#define PTR_ERR(p) ((intptr_t)(p))
struct mutex {bool held;};
struct regmap {int unused;};
struct device_node {unsigned index;};
struct reserved_mem {u64 base,size;};
struct device {struct device_node *of_node;};
struct platform_device {struct device dev;};
static struct mutex lock={true};
static struct regmap top;
static struct device_node nodes[3]={{0},{1},{2}},parent={3};
static struct platform_device pdev={{&nodes[0]}};
static struct reserved_mem rmem[2];
static unsigned char core[2][4096],header[72];
static unsigned reads,tcm_reads,top_reads,checks,puts_count,gets_count;
static unsigned fail_check,fail_top,mutate_core_at,mutate_header_at,mutate_offset;
static unsigned version,mux[4];
static int missing_node,invalid_node,absent_rmem;
static bool bad_parent,reusable,nomem,bad_names;
static int lookup_error;
static void *allocation;
static void lockdep_assert_held(struct mutex *m){assert(m==&lock && m->held);}
static void memzero_explicit(void *p,size_t n){memset(p,0,n);}
static u32 get_unaligned_le32(const void *p){const u8 *b=p;return (u32)b[0]|(u32)b[1]<<8|(u32)b[2]<<16|(u32)b[3]<<24;}
static void put_unaligned_le32(u32 v,void *p){u8 *b=p;for(unsigned i=0;i<4;i++)b[i]=v>>(8*i);}
static int check(void *context){assert(context==&pdev && lock.held);checks++;return checks==fail_check?-EIO:0;}
static int regmap_read(struct regmap *m,unsigned offset,unsigned *out){
 assert(m==&top && offset==0x10 && top_reads<4 && lock.held);
 top_reads++;if(top_reads==fail_top)return -EIO;*out=mux[top_reads-1];return 0;
}
static u32 readl(void *p){
 static const unsigned offsets[]={0,4,0x70};
 unsigned lane=(reads/3)%2,field=reads%3;
 if(p==core[lane]+offsets[field]){
  u32 value=get_unaligned_le32(p);if(reads>=mutate_core_at)value^=1;
  reads++;return value;
 }
 unsigned offset=0;
 if(!tcm_reads || tcm_reads==1+2*(version/4))offset=28;
 else offset=((tcm_reads-1)%(version/4))*4;
 assert(p==header+offset && offset+4<=version && reads==12 && lock.held);
 if(tcm_reads==mutate_header_at)header[mutate_offset]^=4;
 tcm_reads++;return get_unaligned_le32(p);
}
static int sysfs_emit(char *buf,const char *format,...){
 assert(lock.held);va_list ap;va_start(ap,format);int n=vsnprintf(buf,4096,format,ap);va_end(ap);return n;
}
static struct device_node *of_parse_phandle(struct device_node *np,const char *name,unsigned index){
 assert(np==&nodes[0] && !strcmp(name,"memory-region") && index<2);
 if((int)index==missing_node)return NULL;gets_count++;return &nodes[index+1];
}
static struct device_node *of_get_parent(struct device_node *np){assert(np==&nodes[1] || np==&nodes[2]);gets_count++;return &parent;}
static bool of_node_name_eq(struct device_node *np,const char *s){assert(np==&parent && !strcmp(s,"reserved-memory"));return !bad_parent;}
static bool of_device_is_available(struct device_node *np){return (int)np->index!=invalid_node;}
static bool of_property_present(struct device_node *np,const char *s){
 assert(np==&nodes[1] || np==&nodes[2]);if(!strcmp(s,"no-map"))return true;
 assert(!strcmp(s,"reusable"));return reusable;
}
static struct reserved_mem *of_reserved_mem_lookup(struct device_node *np){assert(np->index==1 || np->index==2);return (int)np->index==absent_rmem?NULL:&rmem[np->index-1];}
static void of_node_put(struct device_node *np){if(np)puts_count++;}
static int of_property_match_string(struct device_node *np,const char *property,const char *name){
 assert(np==&nodes[0] && !strcmp(property,"memory-region-names"));return bad_names?-EINVAL:(!strcmp(name,"firmware")?0:1);
}
static void *devm_kzalloc(struct device *dev,size_t n,int flag){assert(dev==&pdev.dev && flag==GFP_KERNEL && !allocation);if(nomem)return NULL;allocation=calloc(1,n);assert(allocation);return allocation;}
static struct regmap *syscon_regmap_lookup_by_phandle(struct device_node *np,const char *name){assert(np==&nodes[0] && !strcmp(name,"mediatek,topckgen"));return lookup_error?(void *)(intptr_t)lookup_error:&top;}
'''

checks = r'''
static void reset(unsigned bytes){
 free(allocation);allocation=NULL;
 version=bytes;reads=tcm_reads=top_reads=checks=puts_count=gets_count=0;
 fail_check=fail_top=0;mutate_core_at=mutate_header_at=UINT32_MAX;mutate_offset=0;
 missing_node=invalid_node=absent_rmem=-1;bad_parent=reusable=nomem=bad_names=false;lookup_error=0;
 memset(core,0,sizeof(core));memset(header,0,sizeof(header));memset(mux,0,sizeof(mux));
 put_unaligned_le32(bytes,header+28);
 put_unaligned_le32(0x9fa00000,header);put_unaligned_le32(8192,header+4);
 put_unaligned_le32(0x9fa02000,header+8);put_unaligned_le32(0x180000,header+12);
 put_unaligned_le32(0x9fc00000,header+16);put_unaligned_le32(305120,header+20);
 put_unaligned_le32(0x9fc95000,header+24);
 rmem[0]=(struct reserved_mem){0x9fa00000,0x500000};rmem[1]=(struct reserved_mem){0x8d000000,0x320000};
}
static struct ccci_scp_inspect *create(void){
 struct ccci_scp_inspect *out=(void *)1;
 void *maps[]={core[0],core[1],header-4};
 assert(!ccci_scp_inspect_create(&pdev,maps,&lock,check,&pdev,&out));
 assert(out==allocation && !reads && !tcm_reads && !checks && !top_reads && gets_count==puts_count);
 return out;
}
static int create_error(void){
 struct ccci_scp_inspect *out=(void *)1;void *maps[]={core[0],core[1],header-4};
 int ret=ccci_scp_inspect_create(&pdev,maps,&lock,check,&pdev,&out);
 assert(ret && !out && !reads && !tcm_reads && !checks && !top_reads && gets_count==puts_count);return ret;
}
int main(void){
 char buf[4096];struct ccci_scp_inspect *o;
 for(unsigned bytes=68;bytes<=72;bytes+=4){
  reset(bytes);o=create();assert(ccci_scp_inspect_status(o,buf)>0 && strstr(buf,"register_reads=0"));
  assert(!reads && !tcm_reads && !checks && !top_reads);
  assert(ccci_scp_inspect_cores(o,buf)>0 && reads==12 && !tcm_reads && checks==2 && top_reads==2);
  assert(strstr(buf,"core1_clr=0") && strstr(buf,"stopped_known=0 ready_known=0"));
  reset(bytes);o=create();assert(ccci_scp_inspect_header(o,buf)>0);
  assert(reads==24 && tcm_reads==2+2*(bytes/4) && checks==4 && top_reads==4);
  assert(o->core_reads==reads && o->header_reads==tcm_reads);
  assert(strstr(buf,"restore_geometry_valid=1 geometry_error=0") && !strstr(buf,"9fa"));
  unsigned n=reads,h=tcm_reads,c=checks,t=top_reads;
  assert(ccci_scp_inspect_status(o,buf)>0 && reads==n && tcm_reads==h && checks==c && top_reads==t);
  for(unsigned phase=1;phase<=4;phase++){
   reset(bytes);o=create();fail_check=phase;strcpy(buf,"unchanged");
   assert(ccci_scp_inspect_header(o,buf)==-EIO && !strcmp(buf,"unchanged"));
   assert(tcm_reads==(phase<3?0:2+2*(bytes/4)));
   reset(bytes);o=create();fail_top=phase;
   assert(ccci_scp_inspect_header(o,buf)==-EIO);
   for(unsigned selector=0;selector<8;selector++)for(unsigned gate=0;gate<2;gate++){
    if(!selector && !gate)continue;
    reset(bytes);o=create();mux[phase-1]=(selector<<16)|(gate<<23);
    assert(ccci_scp_inspect_header(o,buf)==-EAGAIN);
    assert(tcm_reads==(phase<3?0:2+2*(bytes/4)));
   }
  }
  reset(bytes);o=create();mutate_core_at=6;assert(ccci_scp_inspect_cores(o,buf)==-EAGAIN && !tcm_reads);
  reset(bytes);o=create();mutate_core_at=12;strcpy(buf,"unchanged");
  assert(ccci_scp_inspect_header(o,buf)==-EAGAIN && !strcmp(buf,"unchanged"));
  for(unsigned offset=0;offset<bytes;offset+=4){
   reset(bytes);o=create();mutate_header_at=1+bytes/4;mutate_offset=offset;strcpy(buf,"unchanged");
   assert(ccci_scp_inspect_header(o,buf)==-EAGAIN && !strcmp(buf,"unchanged") && reads==24);
  }
  reset(bytes);o=create();put_unaligned_le32(3,header);
  assert(ccci_scp_inspect_header(o,buf)==-ERANGE && reads==24);
  reset(bytes);o=create();put_unaligned_le32(0x9fc94000,header+24);
  assert(ccci_scp_inspect_header(o,buf)>0 && strstr(buf,"restore_geometry_valid=0"));
 }
 const unsigned unsupported[]={0,4,60,64,67,69,71,73,UINT32_MAX};
 for(unsigned i=0;i<sizeof(unsupported)/sizeof(*unsupported);i++){
  reset(68);o=create();put_unaligned_le32(unsupported[i],header+28);strcpy(buf,"unchanged");
  assert(ccci_scp_inspect_header(o,buf)==-EPROTONOSUPPORT && !strcmp(buf,"unchanged"));
  assert(tcm_reads==1 && reads==24 && checks==4);
 }
 for(int i=0;i<2;i++){
  reset(68);missing_node=i;assert(create_error()==-EINVAL);
  reset(68);invalid_node=i+1;assert(create_error()==-EINVAL);
  reset(68);absent_rmem=i+1;assert(create_error()==-EINVAL);
  reset(68);rmem[i].base=0;assert(create_error()==-EINVAL);
  reset(68);rmem[i].size=0;assert(create_error()==-EINVAL);
  reset(68);rmem[i].base=0xfffffffc;assert(create_error()==-EINVAL);
  reset(68);rmem[i].size|=1;assert(create_error()==-EINVAL);
  reset(68);rmem[i].base=0x10500000;assert(create_error()==-ERANGE);
 }
 reset(68);bad_parent=true;assert(create_error()==-EINVAL);
 reset(68);reusable=true;assert(create_error()==-EINVAL);
 reset(68);bad_names=true;assert(create_error()==-EINVAL);
 reset(68);nomem=true;assert(create_error()==-ENOMEM);
 reset(68);lookup_error=-EIO;assert(create_error()==-EIO);
 reset(68);rmem[1]=rmem[0];assert(create_error()==-ERANGE);
 reset(68);puts("PASS: actual constructor and core/header readers; no probe I/O, exact dual-core allowlist, pre/post prerequisites and mux, exact68/72 bounds, instability and decode rejection, geometry-only report, reservation failures and counters");
}
'''


def main():
    source = (D / 'ccci-scp-inspect.c').read_text()
    for forbidden in ('writel(', 'memcpy_toio(', 'memcpy_fromio(', 'memset_io('):
        assert forbidden not in source
    code = prefix
    for name in ('ccci-scp-memory.h', 'ccci-scp-restore.h', 'ccci-scp-memory.c',
                 'ccci-scp-restore.c', 'ccci-scp-inspect.c'):
        code += '\n' + without_includes(D / name)
    # A real TCM+4 pointer without forming an out-of-object pointer in the model.
    code = code.replace('static unsigned char core[2][4096],header[72];',
                        'static unsigned char core[2][4096],tcm[76];\nstatic unsigned char *const header=tcm+4;')
    code += checks.replace('memset(header,0,sizeof(header));', 'memset(header,0,72);')
    with tempfile.TemporaryDirectory(prefix='op6893-owner-observe-') as directory:
        root = Path(directory)
        (root / 'test.c').write_text(code)
        subprocess.run(['cc', '-Wall', '-Wextra', '-Werror', '-Wno-unused-function',
                        '-Wno-misleading-indentation', '-fsanitize=address,undefined',
                        '-fno-sanitize-recover=all', '-no-pie', str(root / 'test.c'),
                        '-o', str(root / 'test')], check=True)
        subprocess.run([str(root / 'test')], check=True)


if __name__ == '__main__':
    main()
