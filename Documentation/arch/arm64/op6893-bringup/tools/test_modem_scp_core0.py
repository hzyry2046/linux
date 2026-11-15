#!/usr/bin/env python3
# SPDX-License-Identifier: GPL-2.0-only
"""Exercise the actual bounded core0 reader; does not model bus completion."""
from pathlib import Path
import subprocess
import tempfile

K = Path(__file__).resolve().parents[5]
src = (K / 'drivers/misc/mediatek/ccci/ccci-scp-observe.c').read_text()
start = src.index('struct ccci_scp_core0_sample {')
end = src.index('static ssize_t core0_show', start)
code = r'''
#include <assert.h>
#include <errno.h>
#include <stdint.h>
#include <stdio.h>
#include <string.h>
typedef uint32_t u32;
#define BIT(n) (1U<<(n))
#define GENMASK(h,l) (((~0U)>>(31-(h))) & ((~0U)<<(l)))
struct ccci_scp_observer { void *top; unsigned char *core0; };
static unsigned char mmio[0x1000];
static unsigned reads,top_reads,fail_read,words[2],values[6];
static int regmap_read(void *m,unsigned offset,unsigned *out) {
 assert(m && offset==0x10 && top_reads<2);
 top_reads++;if(top_reads==fail_read)return -EIO;
 *out=words[top_reads-1];return 0;
}
static u32 readl(void *p) {
 static const unsigned offsets[]={0,4,0x70,0,4,0x70};
 assert(reads<6 && p==mmio+offsets[reads]);return values[reads++];
}
''' + src[start:end] + r'''
static void reset(void) {
 reads=top_reads=fail_read=0;memset(words,0,sizeof(words));memset(values,0,sizeof(values));
}
int main(void) {
 struct ccci_scp_observer o={.top=&o,.core0=mmio};
 struct ccci_scp_core0_sample s;
 reset();o.core0=NULL;assert(ccci_scp_core0_read(&o,&s)==-EOPNOTSUPP);
 assert(!reads && !top_reads);o.core0=mmio;
 for(unsigned i=1;i<=2;i++) {
  reset();fail_read=i;s=(struct ccci_scp_core0_sample){9,9,9};
  assert(ccci_scp_core0_read(&o,&s)==-EIO);
  assert(s.clr==9 && s.set==9 && s.status==9 && reads==(i==1?0:6));
 }
 for(unsigned selector=0;selector<8;selector++)for(unsigned gate=0;gate<2;gate++) {
  if(!selector && !gate)continue;
  for(unsigned phase=0;phase<2;phase++) {
   reset();words[phase]=(selector<<16)|(gate<<23);s.clr=9;
   assert(ccci_scp_core0_read(&o,&s)==-EAGAIN && s.clr==9);
   assert(reads==(phase?6:0));
  }
 }
 for(unsigned bits=0;bits<16;bits++) {
  reset();values[0]=values[3]=bits&1;values[1]=values[4]=(bits>>1)&1;
  values[2]=values[5]=(bits>>2)&3;
  assert(!ccci_scp_core0_read(&o,&s) && reads==6 && top_reads==2);
  assert(s.clr==(bits&1) && s.set==((bits>>1)&1) && s.status==((bits>>2)&3));
 }
 for(unsigned field=3;field<6;field++) {
  reset();values[field]=1;s.clr=9;
  assert(ccci_scp_core0_read(&o,&s)==-EAGAIN && s.clr==9);
 }
 reset();words[1]=BIT(1);values[3]=BIT(31);values[4]=BIT(31);values[5]=BIT(31);
 assert(!ccci_scp_core0_read(&o,&s));
 puts("PASS: opt-out, before/after mux refusal, errors, exact six-read allowlist, stability and bit masks");
}
'''
with tempfile.TemporaryDirectory(prefix='op6893-core0-') as directory:
    p = Path(directory)
    (p / 'test.c').write_text(code)
    subprocess.run(['cc', '-Wall', '-Wextra', '-Werror', '-Wno-misleading-indentation',
                    '-fsanitize=address,undefined', '-fno-sanitize-recover=all',
                    '-no-pie', str(p / 'test.c'), '-o', str(p / 'test')], check=True)
    subprocess.run([str(p / 'test')], check=True)
