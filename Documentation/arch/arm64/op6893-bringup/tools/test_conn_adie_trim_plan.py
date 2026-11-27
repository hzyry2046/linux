#!/usr/bin/env python3
# SPDX-License-Identifier: GPL-2.0-only
"""Compare actual private planner against vendor code, including transient states."""
from pathlib import Path
import runpy
import subprocess
import sys
import tempfile

here = Path(__file__).resolve().parent
root = Path('/data/src/6.6-exp/android_kernel_modules_oneplus_mt6833/vendor/mediatek/kernel_modules/connectivity/conninfra')
sys.argv = [str(here/'test_conn_thermal_trim_source.py'), '--source',
            str(root/'conn_drv/connv2/platform/mt6893/mt6893_pos.c'), '--register-header',
            str(root/'base/include/consys_reg_util.h')]
vendor = runpy.run_path(sys.argv[0])
source = (here.parents[4]/'arch/arm64/kernel/op6893-conn-adie.h').read_text()
planner = vendor['function'](source, 'op6893_conn_adie_trim_plan')
model = r'''
#include <stdbool.h>
typedef uint8_t u8;
typedef uint32_t u32;
#define BIT(n) (1U<<(n))
#define ARRAY_SIZE(a) (sizeof(a)/sizeof((a)[0]))
struct op6893_conn {
 bool adie_trim_vendor_noop,adie_trim_bounded_noop,adie_trim_equivalent,adie_trim_plan_cleared;
};
static unsigned wipes;
static void wipe(void *p,unsigned n) {
 assert(n==28);wipes++;memset(p,0,n);
 for(unsigned i=0;i<n;i++)assert(!((unsigned char *)p)[i]);
}
#define memzero_explicit(p,n) wipe(p,n)
'''
tests = r'''
static uint32_t bounded(uint32_t old,uint32_t f,unsigned dst,unsigned src,unsigned width) {
 uint32_t bits=(1U<<width)-1;
 return (old&~(bits<<dst))|(((f>>src)&bits)<<dst);
}
int main(void) {
 unsigned cases=0,transient=0;
 uint32_t patterns[]={0,~0U,0xaaaaaaaa,0x55555555};
 for(unsigned p=0;p<4;p++)for(uint32_t f=0;f<65536;f++) {
  uint32_t baseline[2]={patterns[p],patterns[(p+1)%4]},v[2],b[2],bt[3];
  struct op6893_conn c={0};unsigned n=0;
  bool vn=true,bn=true,eq=true;
  memcpy(v,baseline,sizeof(v));memcpy(b,baseline,sizeof(b));
  setup_unused: ;
  regs[0]=baseline[0];regs[1]=baseline[1];writes=0;
  connsys_a_die_thermal_cal(1,f);
  if(f&128){b[0]=bounded(b[0],f,12,3,4);bt[n++]=b[0];b[1]=bounded(b[1],f,23,0,3);bt[n++]=b[1];}
  if(f&32768){b[1]=bounded(b[1],f,26,13,2);bt[n++]=b[1];}
  assert(n==writes);memcpy(b,baseline,sizeof(b));
  for(unsigned i=0;i<n;i++) {
   unsigned w=address[i]==0x38;
   vn &= trace[i]==v[w];bn &= bt[i]==b[w];eq &= trace[i]==bt[i];
   v[w]=trace[i];b[w]=bt[i];
  }
  unsigned old_writes=writes;wipes=0;
  op6893_conn_adie_trim_plan(&c,&f,baseline);
  assert(writes==old_writes && wipes==1 && c.adie_trim_plan_cleared);
  assert(c.adie_trim_vendor_noop==vn && c.adie_trim_bounded_noop==bn && c.adie_trim_equivalent==eq);
  if(!eq && v[0]==b[0] && v[1]==b[1])transient++;
  cases++;
 }
 /* Same final state does not imply equivalent sequences. */
 struct op6893_conn c={0};uint32_t f=0x8088,baseline[2]={0x11000,0x10000000};
 op6893_conn_adie_trim_plan(&c,&f,baseline);
 assert(!c.adie_trim_vendor_noop && c.adie_trim_bounded_noop && !c.adie_trim_equivalent);
 printf("PASS: planner %u cases against actual vendor sequence, %u transient-only differences, explicit transient counterexample, zeroization, no hardware calls\n",cases,transient);
}
'''.replace('  setup_unused: ;\n','')
with tempfile.TemporaryDirectory() as tmp:
    p=Path(tmp)
    (p/'test.c').write_text(vendor['prelude']+'\n'+vendor['macro']+'\n'+vendor['helper']+'\n'+vendor['calibration']+model+planner+tests)
    subprocess.run(['cc','-O2','-Wall','-Wextra','-Werror','-fno-strict-overflow',
                    '-fsanitize=undefined','-fno-sanitize-recover=all',str(p/'test.c'),'-o',str(p/'test')],check=True)
    subprocess.run([str(p/'test')],check=True)
