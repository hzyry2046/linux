#!/usr/bin/env python3
# SPDX-License-Identifier: GPL-2.0-only
"""Actual header snapshot/decoder with synthetic MMIO, exact read boundaries."""
from pathlib import Path
import subprocess
import tempfile

K = Path(__file__).resolve().parents[5]
D = K / 'drivers/misc/mediatek/ccci'
src = (D / 'ccci-scp-observe.c').read_text()


def section(start, end):
    return src[src.index(start):src.index(end)]


def without_includes(path):
    return '\n'.join(line for line in path.read_text().splitlines()
                     if not line.startswith('#include'))


code = r'''
#include <assert.h>
#include <errno.h>
#include <stdint.h>
#include <stdbool.h>
#include <stdio.h>
#include <string.h>
typedef uint8_t u8;
typedef uint32_t u32;
typedef uint64_t u64;
#define __iomem
#define U32_MAX UINT32_MAX
#define U64_MAX UINT64_MAX
#define BIT(n) (1U<<(n))
#define GENMASK(h,l) (((~0U)>>(31-(h))) & ((~0U)<<(l)))
static u32 get_unaligned_le32(const void *p) {
 const u8 *b=p;return (u32)b[0]|(u32)b[1]<<8|(u32)b[2]<<16|(u32)b[3]<<24;
}
static void put_unaligned_le32(u32 v,void *p) {
 u8 *b=p;for(unsigned i=0;i<4;i++)b[i]=v>>(8*i);
}
struct ccci_scp_observer { void *top; unsigned char *core0,*header; };
static unsigned char core0[0x1000],*header;
static unsigned tcm_reads,core_reads,top_reads,fail_read,words[4],core_values[12];
static unsigned version,mutate_read,mutate_offset;
static int regmap_read(void *m,unsigned offset,unsigned *out) {
 assert(m && offset==0x10 && top_reads<4);
 top_reads++;if(top_reads==fail_read)return -EIO;
 *out=words[top_reads-1];return 0;
}
static u32 readl(void *p) {
 if(p==core0 || p==core0+4 || p==core0+0x70) {
  static const unsigned offsets[]={0,4,0x70,0,4,0x70};
  assert(core_reads<12 && p==core0+offsets[core_reads%6]);
  return core_values[core_reads++];
 }
 unsigned expected;
 if(!tcm_reads || tcm_reads==1+2*(version/4))expected=28;
 else expected=((tcm_reads-1)%(version/4))*4;
 assert(p==header+expected && expected+4<=version);
 if(tcm_reads==mutate_read)header[mutate_offset]^=4;
 tcm_reads++;return get_unaligned_le32(p);
}
''' + without_includes(D / 'ccci-scp-memory.h') + '\n' + without_includes(D / 'ccci-scp-memory.c') + '\n' + section('struct ccci_scp_core0_sample {', 'static ssize_t core0_show') + '\n' + section('static int ccci_scp_header_copy', 'static ssize_t header_show') + r'''
static void reset(unsigned bytes) {
 static u8 legacy[68],modern[72];
 assert(bytes==68 || bytes==72);version=bytes;header=bytes==68?legacy:modern;
 memset(header,0,bytes);put_unaligned_le32(bytes,header+28);
 put_unaligned_le32(0x9fa00000,header);put_unaligned_le32(8192,header+4);
 put_unaligned_le32(0x9fa02000,header+8);put_unaligned_le32(0x180000,header+12);
 put_unaligned_le32(0x9fc00000,header+16);put_unaligned_le32(305120,header+20);
 put_unaligned_le32(0x9fc95000,header+24);
 tcm_reads=core_reads=top_reads=fail_read=0;mutate_read=UINT32_MAX;mutate_offset=0;
 memset(words,0,sizeof(words));memset(core_values,0,sizeof(core_values));
}
static void cleared(const void *p,size_t n) {
 const u8 *b=p;for(size_t i=0;i<n;i++)assert(!b[i]);
}
int main(void) {
 struct ccci_scp_observer o={.top=&o,.core0=core0};
 struct ccci_scp_region region;size_t length;u8 buffer[72];
 for(unsigned bytes=68;bytes<=72;bytes+=4) {
  reset(bytes);o.header=header;
  assert(!ccci_scp_header_read(&o,&region,&length));
  assert(length==bytes && tcm_reads==2+2*(bytes/4) && core_reads==12 && top_reads==4);
  assert(region.loader.size==8192 && region.firmware.size==0x180000 && region.dram.size==305120);
  struct ccci_scp_span window={0x9fa00000,0x500000},mapping;
  assert(ccci_scp_span_allowed(&window,&region.loader));
  assert(!ccci_scp_dram_span(&region,&window,&mapping) && mapping.size==1220608);
  assert(!ccci_scp_spans_overlap(&region.loader,&region.firmware));
  struct ccci_scp_span overlap={0x9fa00004,4};assert(ccci_scp_spans_overlap(&region.loader,&overlap));
  for(unsigned failure=1;failure<=4;failure++) {
   reset(bytes);o.header=header;fail_read=failure;
   memset(&region,0xa5,sizeof(region));length=99;
   assert(ccci_scp_header_read(&o,&region,&length)==-EIO);
   assert(!length);cleared(&region,sizeof(region));
   assert(tcm_reads==(failure<=2?0:2+2*(bytes/4)));
  }
  for(unsigned phase=0;phase<4;phase++) {
   reset(bytes);o.header=header;words[phase]=BIT(23);length=99;
   assert(ccci_scp_header_read(&o,&region,&length)==-EAGAIN && !length);
   assert(tcm_reads==(phase<2?0:2+2*(bytes/4)));
  }
  for(unsigned field=0;field<3;field++) {
   reset(bytes);o.header=header;core_values[6+field]=core_values[9+field]=1;
   assert(ccci_scp_header_read(&o,&region,&length)==-EAGAIN && !length);
  }
  for(unsigned offset=0;offset<bytes;offset+=4) {
   reset(bytes);mutate_read=1+bytes/4;mutate_offset=offset;
   memset(buffer,0xa5,sizeof(buffer));length=99;
   assert(ccci_scp_header_copy(header,buffer,&length)==-EAGAIN && !length);
   cleared(buffer,sizeof(buffer));
  }
  reset(bytes);o.header=header;put_unaligned_le32(3,header);
  assert(ccci_scp_header_read(&o,&region,&length)==-ERANGE && !length);
  cleared(&region,sizeof(region));
 }
 const u32 bad[]={0,4,28,32,64,67,69,71,73,UINT32_MAX};
 for(unsigned i=0;i<sizeof(bad)/sizeof(bad[0]);i++) {
  reset(68);put_unaligned_le32(bad[i],header+28);length=99;
  assert(ccci_scp_header_copy(header,buffer,&length)==-EPROTONOSUPPORT);
  assert(!length && tcm_reads==1);cleared(buffer,sizeof(buffer));
 }
 reset(68);o.header=NULL;length=99;
 assert(ccci_scp_header_read(&o,&region,&length)==-EOPNOTSUPP);
 assert(!length && !tcm_reads && !core_reads && !top_reads);cleared(&region,sizeof(region));
 puts("PASS: exact 68/72-byte MMIO limits, two snapshots, every word mutation, unknown lengths, pre/post refusal, decoder errors, clear outputs");
}
'''
with tempfile.TemporaryDirectory(prefix='op6893-tcm-') as directory:
    p = Path(directory)
    (p / 'test.c').write_text(code)
    subprocess.run(['cc', '-Wall', '-Wextra', '-Werror', '-Wno-misleading-indentation',
                    '-fsanitize=address,undefined', '-fno-sanitize-recover=all',
                    '-no-pie', str(p / 'test.c'), '-o', str(p / 'test')], check=True)
    subprocess.run([str(p / 'test')], check=True)
