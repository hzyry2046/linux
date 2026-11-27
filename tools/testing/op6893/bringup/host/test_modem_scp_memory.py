#!/usr/bin/env python3
# SPDX-License-Identifier: GPL-2.0-only
"""Compile actual SCP region decoder/bounds helpers with ASan/UBSan.

Synthetic metadata only. Optional A/V helper headers verify sizeof/offsetof
against their actual region structure, without accessing firmware or a device.
"""
import argparse
from pathlib import Path
import subprocess
import tempfile

KERNEL = Path(__file__).resolve().parents[5]

HARNESS = r'''
#include <assert.h>
#include <stddef.h>
#include <stdint.h>
#include <stdio.h>
#include <string.h>
#include <linux/errno.h>
#include "ccci-scp-memory.h"
@VENDOR@
static void put32(void *p,u32 value) {
 unsigned char *b=p;for(unsigned i=0;i<4;i++) b[i]=value>>(8*i);
}
static void clear(const void *p,size_t n) {
 const unsigned char *b=p;for(size_t i=0;i<n;i++) assert(!b[i]);
}
static unsigned char fixture[72];
static void reset(void) {
 memset(fixture,0,sizeof(fixture));
 put32(fixture,0x9fa00000);put32(fixture+4,0x10000);
 put32(fixture+8,0x9fa10000);put32(fixture+12,0x40000);
 put32(fixture+16,0x9fb00000);put32(fixture+20,0x40004);
 put32(fixture+24,0x9fb80800);put32(fixture+28,72);
 put32(fixture+44,0x9fe00000);put32(fixture+48,0x1000);
}
static void bad(void *p,size_t n) {
 struct ccci_scp_region r;memset(&r,0xa5,sizeof(r));
 assert(ccci_scp_decode_region(p,n,&r)<0);clear(&r,sizeof(r));
}
static u32 seed=0x52566893;
static u32 rand32(void) {seed^=seed<<13;seed^=seed>>17;seed^=seed<<5;return seed;}
int main(void) {
 struct ccci_scp_region r;
 struct ccci_scp_span map,window={0x9fa00000,0x500000};
 reset();assert(!ccci_scp_decode_region(fixture,72,&r));
 assert(r.loader.base==0x9fa00000 && r.loader.size==0x10000);
 assert(r.firmware.base==0x9fa10000 && r.firmware.size==0x40000);
 assert(r.dram.base==0x9fb00000 && r.dram.size==0x40004);
 assert(r.regdump.base==0x9fe00000 && r.regdump.size==0x1000);
 assert(r.backup_start==0x9fb80800);
 assert(ccci_scp_span_allowed(&window,&r.loader));
 assert(ccci_scp_span_allowed(&window,&r.firmware));
 assert(ccci_scp_span_allowed(&window,&r.regdump));
 assert(!ccci_scp_dram_span(&r,&window,&map));
 assert(map.base==0x9fb00000 && map.size==0x101000);
 unsigned char unaligned[74];memset(unaligned,0xa5,sizeof(unaligned));
 memcpy(unaligned+1,fixture,72);assert(!ccci_scp_decode_region(unaligned+1,72,&r));
 assert(unaligned[0]==0xa5 && unaligned[73]==0xa5);
 bad(NULL,72);assert(ccci_scp_decode_region(fixture,72,NULL)<0);
 for(size_t n=0;n<=74;n++) if(n!=72)bad(fixture,n);
 bad(fixture,SIZE_MAX);
 const u32 versions[]={0,4,28,32,52,56,68,71,73,76,UINT32_MAX};
 for(unsigned i=0;i<sizeof(versions)/4;i++){reset();put32(fixture+28,versions[i]);bad(fixture,72);}
 for(unsigned offset=0;offset<72;offset+=4) {
  if(offset!=32 && offset!=36 && offset!=40 && offset<52)continue;
  reset();put32(fixture+offset,UINT32_MAX);
  assert(!ccci_scp_decode_region(fixture,72,&r)); /* ignored, never used as pointers */
 }
 const unsigned pairs[]={0,8,16,44};
 for(unsigned i=0;i<4;i++) {
  unsigned offset=pairs[i];
  reset();put32(fixture+offset,0);bad(fixture,72);
  reset();put32(fixture+offset+4,0);bad(fixture,72);
  reset();put32(fixture+offset,5);bad(fixture,72);
  reset();put32(fixture+offset+4,5);bad(fixture,72);
  reset();put32(fixture+offset,0xfffffffc);put32(fixture+offset+4,8);bad(fixture,72);
  reset();put32(fixture+offset,0);put32(fixture+offset+4,0);
  assert(!ccci_scp_decode_region(fixture,72,&r));
  reset();put32(fixture+offset,0xfffffffc);put32(fixture+offset+4,4);
  assert(!ccci_scp_decode_region(fixture,72,&r));
 }
 reset();put32(fixture+24,3);bad(fixture,72);
 reset();assert(!ccci_scp_decode_region(fixture,72,&r));
 struct ccci_scp_region full=r;
 unsigned char legacy[68];memcpy(legacy,fixture,sizeof(legacy));put32(legacy+28,68);
 assert(!ccci_scp_decode_region(legacy,sizeof(legacy),&r));
 assert(!memcmp(&r,&full,sizeof(r))); /* No read beyond the 68-byte object. */
 for(size_t n=0;n<=74;n++)if(n!=68)bad(legacy,n);
 for(unsigned offset=0;offset<68;offset+=4) {
  if(offset!=32 && offset!=36 && offset!=40 && offset<52)continue;
  put32(legacy+offset,UINT32_MAX);
  assert(!ccci_scp_decode_region(legacy,sizeof(legacy),&r));
 }
 for(unsigned i=0;i<4;i++) {
  memcpy(legacy,fixture,sizeof(legacy));put32(legacy+28,68);
  put32(legacy+pairs[i],0);bad(legacy,sizeof(legacy));
 }

 puts("PASS: exact LE68/LE72 ABIs, size at +28, four pairs, ignored fields, unaligned snapshot, failure clearing");
 const struct ccci_scp_span spans[]={
  {0,4},{4,0},{5,4},{4,5},{0x100000000ULL,4},{0xfffffffc,8},
  {UINT64_MAX-3,4},{4,UINT64_MAX-3},{0x9f9ffffc,4},{0x9ff00000,4},
  {0x9feffffc,8}
 };
 for(unsigned i=0;i<sizeof(spans)/sizeof(spans[0]);i++) assert(!ccci_scp_span_allowed(&window,&spans[i]));
 struct ccci_scp_span tail={0x9feffffc,4};assert(ccci_scp_span_allowed(&window,&tail));
 struct ccci_scp_span boundary={0xfffffffc,4};assert(ccci_scp_span_allowed(&boundary,&boundary));
 struct ccci_scp_span wrapping={UINT64_MAX-3,8};assert(!ccci_scp_span_allowed(&wrapping,&boundary));
 struct ccci_scp_span empty={0};assert(!ccci_scp_span_allowed(&empty,&boundary));
 assert(!ccci_scp_span_allowed(NULL,&tail));assert(!ccci_scp_span_allowed(&window,NULL));
 reset();assert(!ccci_scp_decode_region(fixture,72,&r));
 const u32 lengths[]={4,1020,1024,1028,0x40004};
 const u64 totals[]={4096,4096,4096,8192,0x101000};
 for(unsigned i=0;i<5;i++){
  r.dram.size=lengths[i];assert(!ccci_scp_dram_span(&r,&window,&map));assert(map.size==totals[i]);
 }
 struct ccci_scp_span exact={r.dram.base,0x101000};
 assert(!ccci_scp_dram_span(&r,&exact,&map));exact.size--;
 memset(&map,0xa5,sizeof(map));assert(ccci_scp_dram_span(&r,&exact,&map)<0);clear(&map,sizeof(map));
 r.dram=(struct ccci_scp_span){0,0};assert(!ccci_scp_dram_span(&r,NULL,&map));clear(&map,sizeof(map));
 r.dram.base=4;assert(ccci_scp_dram_span(&r,&window,&map)<0);clear(&map,sizeof(map));
 r.dram=(struct ccci_scp_span){0x9fb00000,4};assert(ccci_scp_dram_span(&r,NULL,&map)<0);clear(&map,sizeof(map));
 r.dram=(struct ccci_scp_span){4,0xfffffffc};assert(ccci_scp_dram_span(&r,&window,&map)<0);clear(&map,sizeof(map));
 r.dram=(struct ccci_scp_span){4,UINT64_MAX-3};assert(ccci_scp_dram_span(&r,&window,&map)<0);clear(&map,sizeof(map));
 assert(ccci_scp_dram_span(NULL,&window,&map)<0);clear(&map,sizeof(map));
 assert(ccci_scp_dram_span(&r,&window,NULL)<0);
 puts("PASS: trusted-window containment, nonwrapping spans, roundup(bytes)*4, empty DRAM and boundary rejection");
 for(unsigned trial=0;trial<20000;trial++) {
  for(unsigned offset=0;offset<72;offset+=4)put32(fixture+offset,rand32());
  unsigned len=(trial&2)?68:72;
  if(trial&1)put32(fixture+28,len);
  int ret=ccci_scp_decode_region(fixture,len,&r);
  if(ret)clear(&r,sizeof(r));else {
   ret=ccci_scp_dram_span(&r,&window,&map);if(ret)clear(&map,sizeof(map));
  }
 }
 for(unsigned trial=0;trial<10000;trial++) {
  reset();u64 size=4*(1+rand32()%0x10000);put32(fixture+20,size);
  unsigned len=(trial&1)?68:72;put32(fixture+28,len);
  assert(!ccci_scp_decode_region(fixture,len,&r));
  assert(!ccci_scp_dram_span(&r,&window,&map));
  u64 rounded=((size-1)/1024+1)*1024;
  assert(map.size==rounded*4 && map.base==0x9fb00000);
 }
 puts("PASS: 20000 malformed headers and 10000 valid randomized byte-size mapping calculations");
 return 0;
}
'''


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--vendor-header', type=Path, action='append', default=[])
    args = parser.parse_args()
    checks = []
    for index, path in enumerate(args.vendor_header):
        source = path.read_text()
        start = source.index('struct scp_region_info_st {')
        definition = source[start:source.index('\n};', start) + 3]
        definition = definition.replace('scp_region_info_st', f'vendor_region_{index}')
        checks.append(definition)
        checks.append(f'_Static_assert(sizeof(struct vendor_region_{index})==72,"vendor ABI size");')
        for name, offset in [('ap_loader_start', 0), ('ap_loader_size', 4),
                             ('ap_firmware_start', 8), ('ap_firmware_size', 12),
                             ('ap_dram_start', 16), ('ap_dram_size', 20),
                             ('ap_dram_backup_start', 24), ('struct_size', 28),
                             ('regdump_start', 44), ('regdump_size', 48)]:
            checks.append(f'_Static_assert(offsetof(struct vendor_region_{index},{name})=={offset},"{name}");')
    with tempfile.TemporaryDirectory(prefix='op6893-scp-memory-') as directory:
        tmp = Path(directory)
        inc = tmp / 'linux'
        inc.mkdir()
        (inc / 'types.h').write_text('''#pragma once
#include <stdint.h>
#include <stddef.h>
#include <stdbool.h>
typedef uint64_t u64; typedef uint32_t u32; typedef uint8_t u8;
''')
        (inc / 'errno.h').write_text('#include <asm-generic/errno.h>\n')
        (inc / 'limits.h').write_text('#include <stdint.h>\n#define U32_MAX UINT32_MAX\n#define U64_MAX UINT64_MAX\n')
        (inc / 'string.h').write_text('#include <string.h>\n')
        (inc / 'unaligned.h').write_text('''#include <linux/types.h>
static inline u32 get_unaligned_le32(const void *p) {
 const u8 *b=p;return (u32)b[0]|(u32)b[1]<<8|(u32)b[2]<<16|(u32)b[3]<<24;
}
''')
        (tmp / 'test.c').write_text(HARNESS.replace('@VENDOR@', '\n'.join(checks)))
        source = KERNEL / 'drivers/misc/mediatek/ccci'
        subprocess.run(['cc', '-O1', '-g', '-Wall', '-Wextra', '-Werror',
                        '-fsanitize=address,undefined', '-fno-sanitize-recover=all',
                        '-no-pie', '-I' + str(tmp), '-I' + str(source),
                        str(source / 'ccci-scp-memory.c'), str(tmp / 'test.c'),
                        '-o', str(tmp / 'test')], check=True)
        subprocess.run([str(tmp / 'test')], check=True)
    if args.vendor_header:
        print(f'PASS: sizeof/offsetof checked against {len(args.vendor_header)} actual vendor region structures')


if __name__ == '__main__':
    main()
