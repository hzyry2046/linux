#!/usr/bin/env python3
# SPDX-License-Identifier: GPL-2.0-only
"""Audit vendor thermal trim arithmetic using synthetic data; no device access."""
import argparse
import hashlib
import json
from pathlib import Path
import re
import subprocess
import tempfile


def function(source, name):
    """Extract a definition, skipping its forward declaration."""
    match = re.search(r'static (?:void|int) ' + name + r'\([^;]*?\)\s*\{', source)
    if not match:
        raise ValueError(f'missing definition: {name}')
    start = match.start()
    pos = source.index('{', start)
    depth = 1
    end = pos + 1
    while depth:
        depth += (source[end] == '{') - (source[end] == '}')
        end += 1
    return source[start:end]


parser = argparse.ArgumentParser(description=__doc__)
parser.add_argument('--source', type=Path, required=True)
parser.add_argument('--register-header', type=Path, required=True)
args = parser.parse_args()
source = args.source.read_text()
header = args.register_header.read_text()
macro = re.search(r'^#define GET_BIT_RANGE\([^\n]+', header, re.M).group(0)
helper = function(source, 'consys_spi_write_offset_range_nolock')
calibration = function(source, 'connsys_a_die_thermal_cal')
prelude = r'''
#include <assert.h>
#include <stdint.h>
#include <stdio.h>
#include <string.h>
#define GENMASK(h,l) ((~0UL << (l)) & (~0UL >> (63-(h))))
#define pr_info(...) ((void)0)
#define pr_notice(...) ((void)0)
#define pr_err(...) ((void)0)
enum sys_spi_subsystem { SYS_SPI_TOP=5, SYS_SPI_MAX=8 };
#define ATOP_RG_TOP_THADC_BG 0x034
#define ATOP_RG_TOP_THADC 0x038
struct consys_plat_thermal_data_mt6893 { int thermal_b,slop_molecule,offset; };
static struct consys_plat_thermal_data_mt6893 saved;
static uint32_t regs[2], trace[3], address[3];
static unsigned writes;
static int consys_spi_read_nolock(enum sys_spi_subsystem sub,unsigned addr,unsigned *v) {
 assert(sub==SYS_SPI_TOP && (addr==0x34 || addr==0x38));
 *v=regs[addr==0x38];return 0;
}
static int consys_spi_write_nolock(enum sys_spi_subsystem sub,unsigned addr,unsigned v) {
 assert(sub==SYS_SPI_TOP && (addr==0x34 || addr==0x38));assert(writes<3);
 trace[writes]=v;address[writes++]=addr;regs[addr==0x38]=v;return 0;
}
static void update_thermal_data_mt6893(struct consys_plat_thermal_data_mt6893 *v) {saved=*v;}
'''
tests = r'''
/* This bounded interpretation is a comparison oracle, not a hardware fix. */
static uint32_t replace(uint32_t before,uint32_t data,unsigned dst,unsigned src,unsigned size,int extra) {
 uint32_t mask=((1U<<size)-1)<<dst;
 return (before&~mask)|(((data>>src)&((1U<<(size+extra))-1))<<dst);
}
static void setup(uint32_t bg,uint32_t adc) {regs[0]=bg;regs[1]=adc;writes=0;memset(&saved,0xa5,sizeof(saved));}
int main(void) {
 unsigned cases=0,different=0;
 uint32_t patterns[]={0,~0U,0xaaaaaaaa,0x55555555};
 for(unsigned p=0;p<4;p++)for(uint32_t low=0;low<65536;low++) {
  uint32_t before=patterns[p], bg=before,adc=before,strict_bg=before,strict_adc=before;
  uint32_t f=low|((low&255)<<16)|((low>>8)<<24);
  unsigned n=0;
  setup(before,before);assert(!connsys_a_die_thermal_cal(1,f));
  if(f&128) {
   bg=replace(bg,f,12,3,4,1);adc=replace(adc,f,23,0,3,1);
   strict_bg=replace(strict_bg,f,12,3,4,0);strict_adc=replace(strict_adc,f,23,0,3,0);
   assert(address[n]==0x34 && trace[n++]==bg);
   assert(address[n]==0x38 && trace[n++]==adc);
  }
  if(f&32768) {
   adc=replace(adc,f,26,13,2,1);strict_adc=replace(strict_adc,f,26,13,2,0);
   assert(address[n]==0x38 && trace[n++]==adc);
  }
  assert(writes==n && regs[0]==bg && regs[1]==adc);
  assert(!((bg^strict_bg)&~(1U<<16)));
  assert(!((adc^strict_adc)&~((1U<<26)|(1U<<28))));
  assert((unsigned)saved.slop_molecule==((f&32768)?((f>>8)&31):0));
  assert((unsigned)saved.thermal_b==((f&(1U<<23))?((f>>16)&127):0));
  assert((unsigned)saved.offset==((f&(1U<<31))?((f>>24)&127):0));
  different+=(bg!=strict_bg || adc!=strict_adc);cases++;
 }
 setup(0,0);connsys_a_die_thermal_cal(1,0x80);assert(regs[0]==0x10000 && !regs[1]);
 setup(0,0);connsys_a_die_thermal_cal(1,0x88);assert(regs[0]==0x11000 && regs[1]==0x4000000);
 setup(0,0);connsys_a_die_thermal_cal(1,0x8000);assert(!regs[0] && regs[1]==0x10000000);
 /* The third write clears the second write's bit26 spill when its source is zero. */
 setup(0,0);connsys_a_die_thermal_cal(1,0x8088);
 assert(writes==3 && trace[1]==0x4000000 && trace[2]==0x10000000);
 setup(0xaaaaaaaa,0x55555555);connsys_a_die_thermal_cal(0,~0U);
 assert(!writes && regs[0]==0xaaaaaaaa && regs[1]==0x55555555);
 assert(!saved.slop_molecule && !saved.thermal_b && !saved.offset);
 printf("PASS: %u synthetic cases; %u differ from width-bounded interpretation; exact source, write order, coefficients, invalid efuse and four counterexamples\n",cases,different);
}
'''
with tempfile.TemporaryDirectory() as tmp:
    p = Path(tmp)
    (p/'audit.c').write_text(prelude+'\n'+macro+'\n'+helper+'\n'+calibration+tests)
    subprocess.run(['cc','-O2','-Wall','-Wextra','-Werror','-fno-strict-overflow','-fsanitize=undefined',
                    '-fno-sanitize-recover=all',str(p/'audit.c'),'-o',str(p/'audit')],check=True)
    subprocess.run([str(p/'audit')],check=True)
print(json.dumps({'source': str(args.source),
                  'source_sha256': hashlib.sha256(args.source.read_bytes()).hexdigest(),
                  'register_header': str(args.register_header),
                  'header_sha256': hashlib.sha256(args.register_header.read_bytes()).hexdigest(),
                  'helper_sha256': hashlib.sha256(helper.encode()).hexdigest(),
                  'calibration_sha256': hashlib.sha256(calibration.encode()).hexdigest(),
                  'device_access': False,'synthetic_data_only':True},indent=2))
