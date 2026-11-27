#!/usr/bin/env python3
# SPDX-License-Identifier: GPL-2.0-only
"""Compile actual LK/SMEM parsers with sanitizers; synthetic metadata only."""
from pathlib import Path
import argparse
import subprocess
import tempfile

K = Path(__file__).resolve().parents[5]
HARNESS = r'''
#include <assert.h>
#include <stdio.h>
#include "ccci-smem.h"
static u8 raw[2048];
static u32 pos, tags, starts[8];
static struct ccci_lk_header h;
static struct ccci_lk_region nc={0x8e000000,0x1800000}, ca={0x88000000,0x4960000};
static struct ccci_lk_tag ws[CCCI_LK_MAX_TAGS];
static struct ccci_smem_layout out;
static void p32(void *p,u32 x){u8 *b=p;for(u32 i=0;i<4;i++)b[i]=x>>(i*8);}
static void p64(void *p,u64 x){p32(p,x);p32((u8 *)p+4,x>>32);}
static u8 *tag(const char *name,u32 size){
 u32 n=tags++,off=n*76;assert(tags<=8 && pos+size<=sizeof(raw));
 strcpy((char *)raw+off,name);p32(raw+off+64,pos);p32(raw+off+68,size);
 p32(raw+off+72,tags==8?0:off+76);starts[n]=pos;u8 *p=raw+pos;pos+=size;return p;
}
static void item(u8 *p,u32 id,u32 off,u32 size){
 p64(p,ca.base+off);p32(p+8,off);p32(p+12,size);p32(p+16,id);
}
static void fixture(void){
 memset(raw,0,sizeof(raw));pos=8*76;tags=0;
 u8 *p=tag("smem_layout",40);p64(p,nc.base);p32(p+12,nc.size);p32(p+32,nc.size);
 p=tag("ccb_info",16);p64(p,ca.base+0x900000);p32(p+8,0x4000000);
 p=tag("nc_smem_info_ext_num",4);p32(p,3);
 p=tag("nc_smem_info_ext",48);
 p32(p,0x1000000);p32(p+4,0x1000000);p32(p+8,0x800000);p32(p+12,10);
 p32(p+16,0x100000);p32(p+20,0x100000);p32(p+24,0x10000);p32(p+28,31);
 p32(p+32,0x110000);p32(p+36,0x110000);p32(p+44,29);
 p=tag("md1_bank4_cache_info",24);p64(p,ca.base);p32(p+12,ca.size);p32(p+16,5);
 p=tag("md1_bank4_cache_layout",120);
 item(p,22,0,0x180000);item(p+24,32,0x180000,0x700000);
 item(p+48,1,0x900000,0x4000000);item(p+72,28,0x4900000,0);
 item(p+96,24,0x4900000,0x60000);
 p=tag("md1_smem_cahce_offset",4);p32(p,0x8000000);
 p=tag("uninterpreted_private_tag",8);memset(p,0xff,8);
 h=(struct ccci_lk_header){.base=0xbff70000,.size=pos,.version=3,.count=8};
}
static int parse(void){return ccci_smem_parse(&h,raw,pos,&nc,&ca,ws,&out);}
static void bad(void){
 memset(&out,0xa5,sizeof(out));assert(parse()<0);
 const u8 *p=(void *)&out;for(u32 i=0;i<sizeof(out);i++)assert(!p[i]);
}
static void region(u32 id,u32 off,u32 size,bool cached){
 const struct ccci_smem_region *r=&out.users[id];
 assert(r->present && r->cached==cached && r->offset==off && r->size==size);
 assert(r->ap==(cached?ca.base:nc.base)+off);
 assert(r->md==(cached?0x48000000:0x40000000)+off);
}
int main(void){
 fixture();assert(!parse());assert(out.count==23);
 /* Independent same-device 4.19 boot geometry, not a sum of 6.6 entries. */
 region(10,0x1000000,0x800000,false);region(31,0x100000,0x10000,false);
 region(14,0x11e800,0x1000,false);region(16,0x120000,0x8000,false);
 region(19,0x139000,0xb4400,false);region(20,0x1ed400,0x1e400,false);
 region(32,0x180000,0x700000,true);region(1,0x900000,0x4000000,true);
 assert(out.users[19].preserve_first && !out.users[16].preserve_first);
 assert(out.users[22].no_map && out.users[22].preserve_first);
 assert(out.users[10].from_lk && !out.users[14].from_lk);
 assert(out.cached.size==0x4960000 && out.cache_gap_bytes==0x80000);
 assert(out.cached.size-out.cache_gap_bytes==0x48e0000);
 assert(out.noncached.size==0x1800000);
 struct ccci_smem_layout good=out;
 /* Same geometry at different trusted AP addresses; not hardcoded PA. */
 nc.base+=0x10000000;ca.base+=0x10000000;fixture();assert(!parse());
 region(16,0x120000,0x8000,false);region(32,0x180000,0x700000,true);
 nc.base-=0x10000000;ca.base-=0x10000000;
 for(u32 n=0;n<7;n++){
  fixture();p32(raw+n*76+68,1);bad(); /* wrong exact payload length */
 }
 fixture();p32(raw+7*76+68,1);assert(!parse()); /* unknown payload ignored */
 fixture();p32(raw+7*76+64,0);bad();
 const u32 counts[]={0,43,0xffffffff};
 for(u32 i=0;i<3;i++){
  fixture();p32(raw+starts[2],counts[i]);bad();
  fixture();p32(raw+starts[4]+16,counts[i]);bad();
 }
 fixture();p32(raw+starts[3]+28,10);bad(); /* duplicate NC ID */
 fixture();p32(raw+starts[3]+4,4);bad(); /* AP/MD offset disagreement */
 fixture();p32(raw+starts[3]+12,42);bad(); /* unsupported NC ID */
 fixture();p32(raw+starts[3]+8,0);bad(); /* missing DFD anchor */
 fixture();p32(raw+starts[3]+24,0);bad(); /* missing WiFi anchor */
 fixture();p32(raw+starts[3]+44,16);bad(); /* empty CCISM override */
 fixture();p32(raw+starts[3]+44,14);bad(); /* empty runtime override */
 fixture();p32(raw+starts[3]+8,0x900000);bad(); /* exceeds bank */
 fixture();p32(raw+starts[5]+24+16,22);bad(); /* duplicate cached ID */
 fixture();p32(raw+starts[5]+16,2);bad(); /* no premature CCB aliases */
 fixture();p64(raw+starts[5]+24,ca.base+0x180004);bad(); /* address mismatch */
 fixture();item(raw+starts[5]+24,32,0x17fffc,0x700000);bad(); /* overlap */
 fixture();item(raw+starts[5]+24,32,0x180000,0);bad(); /* required NVRAM */
 fixture();p32(raw+starts[5]+96+12,0x60004);bad(); /* cache overflow */
 fixture();p32(raw+starts[5]+12,3);bad(); /* unaligned item */
 fixture();p32(raw+starts[1]+8,0x200000);bad(); /* CCB conflict */
 fixture();p32(raw+starts[6],0xffffffff);bad(); /* MD address overflow */
 fixture();p32(raw+starts[6],0x8000001);bad(); /* misaligned MD bank */
 fixture();p32(raw+starts[6],0);bad(); /* MD banks alias */
 fixture();p32(raw+starts[4]+12,0x4960004);bad(); /* reservation overflow */
 fixture();p32(raw+starts[0]+12,0x17fffff);bad(); /* misaligned bank */
 fixture();h.version=4;bad();
 fixture();p32(raw+72,0);bad(); /* never bypass linked-list validation */
 fixture();u8 shifted[2049];memcpy(shifted+1,raw,pos);
 assert(!ccci_smem_parse(&h,shifted+1,pos,&nc,&ca,ws,&out));
 assert(!memcmp(&out,&good,sizeof(out)));
 memset(&out,0xa5,sizeof(out));
 assert(ccci_smem_parse(NULL,raw,pos,&nc,&ca,ws,&out)<0);
 assert(ccci_smem_parse(&h,raw,pos,&nc,&ca,ws,NULL)<0);
 puts("PASS: actual LK + 6297 SMEM: runtime/CCISM/NVRAM geometry, 0x80000 gap, relocated AP banks, exact ABI lengths, bounds, aliases, duplicate IDs, truncation and failure output clearing");
}
'''


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--vendor-root', type=Path, action='append', default=[])
    args = parser.parse_args()
    with tempfile.TemporaryDirectory(prefix='op6893-smem-') as directory:
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
        (inc / 'limits.h').write_text('#include <stdint.h>\n#define U64_MAX UINT64_MAX\n')
        (inc / 'string.h').write_text('#include <string.h>\n')
        (inc / 'kernel.h').write_text('#define ARRAY_SIZE(a) (sizeof(a)/sizeof((a)[0]))\n')
        (inc / 'unaligned.h').write_text('''#pragma once
#include <linux/types.h>
static inline u32 get_unaligned_le32(const void *p) {
 const u8 *b=p;return (u32)b[0]|(u32)b[1]<<8|(u32)b[2]<<16|(u32)b[3]<<24;
}
static inline u64 get_unaligned_le64(const void *p) {
 return get_unaligned_le32(p)|((u64)get_unaligned_le32((const u8 *)p+4)<<32);
}
''')
        (tmp / 'test.c').write_text(HARNESS)
        source = K / 'drivers/misc/mediatek/ccci'
        subprocess.run(['cc', '-O1', '-g', '-Wall', '-Wextra', '-Werror',
                        '-Wno-sign-compare', '-fsanitize=address,undefined',
                        '-fno-sanitize-recover=all', '-no-pie', '-I'+str(tmp),
                        '-I'+str(K / 'include'), '-I'+str(source),
                        str(source / 'ccci-lk.c'), str(source / 'ccci-smem.c'),
                        str(tmp / 'test.c'), '-o', str(tmp / 'test')], check=True)
        subprocess.run([str(tmp / 'test')], check=True)
        for index, root in enumerate(args.vendor_root):
            common = root / 'drivers/misc/mediatek/include/mt-plat/mtk_ccci_common.h'
            source_text = common.read_text()
            start = source_text.index('enum SMEM_USER_ID {')
            enum = source_text[start:source_text.index('\n};', start)+3]
            source_text = (root / 'drivers/misc/mediatek/ccci_util/ccci_util_lib_fo.c').read_text()
            definitions = []
            for name in ['_csmem_item', 'nc_smem_node', '_smem_layout']:
                start = source_text.index('struct '+name+' {')
                definitions.append(source_text[start:source_text.index('\n};', start)+3])
            probe = '''#include <stddef.h>
typedef unsigned long long phys_addr_t;
@ENUM@
@STRUCTS@
_Static_assert(sizeof(struct _csmem_item)==24,"cached native ABI size");
_Static_assert(offsetof(struct _csmem_item,md_offset)==8,"cached offset");
_Static_assert(offsetof(struct _csmem_item,csmem_buffer_size)==12,"cached size");
_Static_assert(offsetof(struct _csmem_item,item_cnt)==16,"cached count/ID");
_Static_assert(sizeof(struct nc_smem_node)==16,"NC native ABI size");
_Static_assert(offsetof(struct nc_smem_node,id)==12,"NC ID");
_Static_assert(sizeof(struct _smem_layout)==40,"bank native ABI size");
_Static_assert(SMEM_USER_RAW_RUNTIME_DATA==14,"runtime ID");
_Static_assert(SMEM_USER_CCISM_SCP==16,"SCP ID");
_Static_assert(SMEM_USER_CCISM_MCU==19,"MCU ID");
_Static_assert(SMEM_USER_CCISM_MCU_EXP==20,"MCU exception ID");
_Static_assert(SMEM_USER_MD_NVRAM_CACHE==32,"NVRAM ID");
int main(void){return 0;}
'''.replace('@ENUM@', enum).replace('@STRUCTS@', '\n'.join(definitions))
            (tmp / 'abi.c').write_text(probe)
            subprocess.run(['cc', '-Wall', '-Wextra', '-Werror', str(tmp / 'abi.c'),
                            '-o', str(tmp / f'abi-{index}')], check=True)
            subprocess.run([str(tmp / f'abi-{index}')], check=True)
            print(f'PASS: actual vendor enum, native sizes and offsets: {root}')


if __name__ == '__main__':
    main()
