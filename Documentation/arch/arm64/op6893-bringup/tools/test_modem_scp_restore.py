#!/usr/bin/env python3
# SPDX-License-Identifier: GPL-2.0-only
"""Actual CPU-only non-secure restore planner; synthetic metadata, ASan/UBSan."""
from pathlib import Path
import subprocess
import tempfile

K = Path(__file__).resolve().parents[5]
D = K / 'drivers/misc/mediatek/ccci'
HARNESS = r'''
#include <assert.h>
#include <linux/errno.h>
#include <stdint.h>
#include <stdio.h>
#include <string.h>
#include "ccci-scp-restore.h"
static unsigned char header[72];
static struct ccci_scp_span fw,share,tcm;
static struct ccci_scp_restore_plan plan;
static void put32(unsigned offset,u32 v) {for(unsigned i=0;i<4;i++)header[offset+i]=v>>(8*i);}
static void setup(unsigned length,u32 bytes) {
 memset(header,0,sizeof(header));
 fw=(struct ccci_scp_span){0x9fa00000,0x500000};
 share=(struct ccci_scp_span){0x8d000000,0x320000};
 tcm=(struct ccci_scp_span){0x10500000,0x180000};
 put32(0,0x9fa00000);put32(4,8192);put32(8,0x9fa10000);put32(12,0x180000);
 put32(16,0x9fc00000);put32(20,bytes);
 put32(24,0x9fc00000+((bytes+1023ULL)&~1023ULL)*2);put32(28,length);
 /* regdump is not a recovery source: it can be outside these windows. */
 put32(44,0x20000000);put32(48,0x100000);
}
static int run(const void *p,size_t n,u32 cores) {return ccci_scp_plan_restore(p,n,cores,&fw,&share,&tcm,&plan);}
static void cleared(void) {const unsigned char *p=(void *)&plan;for(unsigned i=0;i<sizeof(plan);i++)assert(!p[i]);}
static void bad(const void *p,size_t n,u32 cores) {memset(&plan,0xa5,sizeof(plan));assert(run(p,n,cores)<0);cleared();}
static void verify(unsigned length,u32 bytes) {
 assert(!run(header,length,2));u64 rounded=((u64)bytes-1)/1024*1024+1024;
 assert(plan.loader_source.base==0x9fa00000 && plan.loader_source.size==8192);
 assert(plan.firmware.base==0x9fa10000 && plan.firmware.size==0x180000);
 assert(plan.tcm_clear.base==0x10500000 && plan.tcm_clear.size==0x180000);
 assert(plan.loader_target.base==0x10500000 && plan.loader_target.size==8192);
 assert(plan.header_target.base==0x10500004 && plan.header_target.size==length);
 assert(plan.dram_mapping.base==0x9fc00000 && plan.dram_mapping.size==4*rounded);
 assert(plan.dram_clear.base==0x9fc00000 && plan.dram_clear.size==2*rounded);
 assert(plan.dram_source.base==0x9fc00000+2*rounded && plan.dram_source.size==bytes);
 assert(plan.dram_target.base==0x9fc00000 && plan.dram_target.size==bytes);
 assert(plan.dram_clear.base+plan.dram_clear.size==plan.dram_source.base);
 assert(plan.dram_target.size<=plan.dram_clear.size);
 assert(plan.dram_source.base+plan.dram_source.size<=plan.dram_mapping.base+plan.dram_mapping.size);
}
static u32 seed=0x68935219;
static u32 random32(void) {seed^=seed<<13;seed^=seed>>17;seed^=seed<<5;return seed;}
int main(void) {
 for(unsigned length=68;length<=72;length+=4) {
  setup(length,305120);verify(length,305120);
  assert(plan.dram_mapping.size==1220608 && plan.dram_clear.size==610304);
  unsigned char legacy[68];memcpy(legacy,header,68);
  if(length==68){assert(!run(legacy,sizeof(legacy),2));assert(plan.header_target.size==68);}
  unsigned char unaligned[74];memcpy(unaligned+1,header,length);assert(!run(unaligned+1,length,2));
  assert(ccci_scp_plan_restore(header,length,2,&fw,&share,&tcm,NULL)==-EINVAL);
  for(unsigned n=0;n<=76;n++)if(n!=length)bad(header,n,2);
  bad(header,SIZE_MAX,2);bad(NULL,length,2);
  const u32 cores[]={0,1,3,UINT32_MAX};for(unsigned i=0;i<4;i++)bad(header,length,cores[i]);
  for(unsigned i=0;i<3;i++) {
   struct ccci_scp_span *windows[]={&fw,&share,&tcm};
   const struct ccci_scp_span invalid[]={{0,4},{4,0},{5,4},{4,5},{UINT64_MAX-3,4},{0xfffffffc,8},{0x100000000ULL,4}};
   for(unsigned j=0;j<7;j++){setup(length,305120);*windows[i]=invalid[j];bad(header,length,2);}
   setup(length,305120);memset(&plan,0xa5,sizeof(plan));
   assert(ccci_scp_plan_restore(header,length,2,i==0?NULL:&fw,i==1?NULL:&share,i==2?NULL:&tcm,&plan)==-EINVAL);cleared();
  }
  setup(length,305120);share=fw;bad(header,length,2);
  setup(length,305120);fw=tcm;bad(header,length,2);
  setup(length,305120);share=tcm;bad(header,length,2);
  setup(length,305120);tcm.size-=4;bad(header,length,2);
  setup(length,305120);tcm.base+=4;bad(header,length,2);
  const unsigned pairs[]={0,8,16};
  for(unsigned i=0;i<3;i++)for(unsigned field=0;field<3;field++) {
   setup(length,305120);unsigned offset=pairs[i];
   if(field==0)put32(offset+4,0);else if(field==1){put32(offset,0);put32(offset+4,0);}else put32(offset,0x9ff00000);
   bad(header,length,2);
  }
  setup(length,305120);put32(8,0x9fa00000);bad(header,length,2); /* loader vs firmware */
  setup(length,305120);put32(0,0x9fc00000);bad(header,length,2); /* loader vs live DRAM */
  setup(length,305120);put32(0,0x9fd00000);bad(header,length,2); /* loader vs backup tail */
  setup(length,305120);put32(8,0x9fc00000);bad(header,length,2);
  setup(length,305120);put32(4,length);bad(header,length,2); /* header is at TCM+4 */
  setup(length,305120);put32(4,length+4);assert(!run(header,length,2));
  for(unsigned variant=0;variant<3;variant++) {
   setup(length,305120);put32(24,variant?0x9fc00000+610304+4*variant:0);bad(header,length,2);
  }
  setup(length,0xfffffffc);bad(header,length,2); /* u64 round/multiply, no wrap */
  setup(length,305120);put32(16,0xfffff000);put32(20,4096);bad(header,length,2);
  setup(length,305120);fw.size=0x2000000;put32(8,0x9fc00000);put32(16,0x9fe00000);put32(24,0x9fe00000+610304);
  put32(4,0x180000);assert(!run(header,length,2));put32(4,0x180004);bad(header,length,2);
 }
 setup(60,305120);bad(header,60,2); /* Q header is not this board ABI. */
 const u32 sizes[]={4,1020,1024,1028,2044,2048,2052,305120};
 for(unsigned i=0;i<8;i++){setup(68,sizes[i]);verify(68,sizes[i]);}
 /* Random aligned sizes up to 512 KiB; independent quotient-based oracle. */
 for(unsigned trial=0;trial<10000;trial++) {
  unsigned length=(trial&1)?68:72;u32 bytes=4*(1+random32()%0x20000);
  setup(length,bytes);verify(length,bytes);
 }
 /* Fuzz the whole CPU snapshot; accepted outputs must remain bounded. */
 for(unsigned trial=0;trial<20000;trial++) {
  setup(68,305120);unsigned offset=4*(random32()%18);put32(offset,random32());
  memset(&plan,0xa5,sizeof(plan));int ret=run(header,68,2);
  if(ret)cleared();else {
   assert(ccci_scp_span_allowed(&fw,&plan.loader_source));
   assert(ccci_scp_span_allowed(&fw,&plan.firmware));
   assert(ccci_scp_span_allowed(&fw,&plan.dram_mapping));
   assert(ccci_scp_span_allowed(&tcm,&plan.loader_target));
   assert(ccci_scp_span_allowed(&tcm,&plan.header_target));
   assert(plan.header_target.size==68);
  }
 }
 puts("PASS: actual CPU restore planner; exact LE68/LE72 snapshots, trusted disjoint windows, required images, TCM/header capacity, two-core live/backup geometry, backup mismatch rejection, u32 overflow and cleared failures; 10000 valid layouts and 20000 mutations");
}
'''
with tempfile.TemporaryDirectory(prefix='op6893-scp-restore-') as directory:
    root = Path(directory)
    headers = {
        'types.h': '#pragma once\n#include <stdint.h>\n#include <stddef.h>\n#include <stdbool.h>\ntypedef uint64_t u64; typedef uint32_t u32; typedef uint8_t u8;\n',
        'errno.h': '#include <asm-generic/errno.h>\n',
        'limits.h': '#include <stdint.h>\n#define U32_MAX UINT32_MAX\n#define U64_MAX UINT64_MAX\n',
        'string.h': '#include <string.h>\n',
        'unaligned.h': '#include <linux/types.h>\nstatic inline u32 get_unaligned_le32(const void *p) {const u8 *b=p;return (u32)b[0]|(u32)b[1]<<8|(u32)b[2]<<16|(u32)b[3]<<24;}\n',
    }
    for name, text in headers.items():
        p = root / 'linux' / name
        p.parent.mkdir(exist_ok=True)
        p.write_text(text)
    (root / 'test.c').write_text(HARNESS)
    subprocess.run(['cc', '-O1', '-g', '-Wall', '-Wextra', '-Werror',
                    '-fsanitize=address,undefined', '-fno-sanitize-recover=all',
                    '-no-pie', '-I' + str(root), '-I' + str(D),
                    str(D / 'ccci-scp-memory.c'), str(D / 'ccci-scp-restore.c'),
                    str(root / 'test.c'), '-o', str(root / 'test')], check=True)
    subprocess.run([str(root / 'test')], check=True)
