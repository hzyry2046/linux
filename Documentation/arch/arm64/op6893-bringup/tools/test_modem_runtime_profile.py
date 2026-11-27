#!/usr/bin/env python3
# SPDX-License-Identifier: GPL-2.0-only
"""Actual bootstrap payload builder and handshake C with synthetic SMEM only."""
from pathlib import Path
import runpy

BASE = runpy.run_path(str(Path(__file__).with_name('test_modem_handshake.py')))
TEST = r'''
static struct ccci_smem_layout layout;
static struct ccci_runtime_offer built[64];
static struct ccci_runtime_boot boot = {0x12340200, CCCI_RUNTIME_CRYSTAL_ABSENT};
static void user(unsigned id,unsigned offset,unsigned size,bool cached){
 struct ccci_smem_region *r=&layout.users[id];
 *r=(struct ccci_smem_region){.ap=(cached?layout.cached.base:layout.noncached.base)+offset,
 .md=(cached?layout.cache_md_base:0x40000000)+offset,.offset=offset,.size=size,
 .present=true,.cached=cached};
}
static void setup_profile(void){
 memset(&layout,0,sizeof(layout));
 layout.noncached=(struct ccci_lk_region){0x80000000,0x400000};
 layout.cached=(struct ccci_lk_region){0x90000000,0x200000};layout.cache_md_base=0x48000000;
 user(12,0,0x800,false);user(14,0x8000,0x1000,false);user(16,0x10000,0x8000,false);
 user(19,0x20000,0xb4400,false);user(20,0xe0000,0x1e400,false);user(32,0x1000,0x100000,true);
 boot.crystal=CCCI_RUNTIME_CRYSTAL_ABSENT;memset(built,0xa5,sizeof(built));
}
/* The LK CCB aggregate plus its control area, both reported to the MD. */
static void setup_ccb(void){
 setup_profile();
 layout.cached=(struct ccci_lk_region){0x90000000,0x8000000};
 user(1,0,0x4000000,true);user(4,0x10,0x1000,false);
}
static void zero_offers(void){
 const unsigned char *p=(const unsigned char *)built;
 for(unsigned i=0;i<sizeof(built);i++)assert(!p[i]);
}
static void profile_tests(void){
 setup_profile();assert(!ccci_runtime_bootstrap(&layout,&boot,built));
 assert(!ccci_runtime_validate(built));
 const unsigned ids[]={0,1,2,5,6,7,8,9,10,11,12,14,19,20,25,27,28,32,36};
 for(unsigned i=0;i<64;i++){
  bool expected=false;for(unsigned j=0;j<19;j++)if(i==ids[j])expected=true;
  assert(built[i].supported==expected && !built[i].version);
  if(!expected)assert(!built[i].length);
 }
 assert(built[0].length==16 && !get_unaligned_le32(built[0].data));
 assert(get_unaligned_le32(built[0].data+4)==boot.booting_start_id);
 assert(!get_unaligned_le64(built[0].data+8));
 assert(built[1].length==8 && get_unaligned_le32(built[1].data)==0x40000000);
 assert(get_unaligned_le32(built[1].data+4)==0x10000);
 const unsigned users[]={19,16,20,32},features[]={2,14,28,36};
 for(unsigned j=0;j<4;j++){
  assert(get_unaligned_le32(built[features[j]].data)==layout.users[users[j]].md);
  assert(get_unaligned_le32(built[features[j]].data+4)==layout.users[users[j]].size);
 }
 /* Board scalars: zero-flag features, seed, sbp/wmid, CCCI flags, time, C2K. */
 const unsigned zeros[]={5,8,19};
 for(unsigned j=0;j<3;j++){
  assert(built[zeros[j]].length==16);
  for(unsigned k=0;k<16;k++)assert(!built[zeros[j]].data[k]);
 }
 assert(built[7].length==16 && get_unaligned_le32(built[7].data)==0x5a5a1234U);
 assert(!get_unaligned_le32(built[7].data+4));
 assert(!get_unaligned_le32(built[9].data));
 assert(get_unaligned_le32(built[9].data+4)==0x7d);
 assert(!get_unaligned_le32(built[9].data+8));
 assert(get_unaligned_le32(built[10].data)==3);
 assert(!get_unaligned_le32(built[10].data+4));
 assert(get_unaligned_le32(built[11].data)==1700000000U);
 assert(!get_unaligned_le32(built[11].data+4));
 assert(!get_unaligned_le32(built[11].data+8));
 assert(get_unaligned_le32(built[12].data)==4);
 assert(built[20].length==4 && get_unaligned_le32(built[20].data)==3584-16);
 assert(built[32].length==4 && !get_unaligned_le32(built[32].data));
 /* LWA is advertised with an explicit empty region, as the vendor does. */
 assert(built[25].length==8 && !get_unaligned_le32(built[25].data));
 assert(!get_unaligned_le32(built[25].data+4));
 /* Regions absent from this layout stay unsupported. */
 const unsigned absent[]={15,16,17,18,26,30,31,35,38};
 for(unsigned j=0;j<9;j++)assert(!built[absent[j]].supported);
 /* CCB present: only the raw downlink split is advertised, never CCB itself. */
 setup_ccb();assert(!ccci_runtime_bootstrap(&layout,&boot,built));
 assert(!built[15].supported);
 assert(built[16].length==8);
 assert(get_unaligned_le32(built[16].data)==layout.users[1].md+0x200000);
 assert(get_unaligned_le32(built[16].data+4)==layout.users[1].size-0x200000);
 /* A CCB aggregate that cannot hold the 2 MiB window is not advertised. */
 setup_ccb();layout.users[1].size=0x200000;
 assert(!ccci_runtime_bootstrap(&layout,&boot,built));
 assert(!built[16].supported);
 setup_ccb();layout.users[1].md+=4;
 assert(!ccci_runtime_bootstrap(&layout,&boot,built));
 assert(!built[15].supported && !built[16].supported);
 setup_profile();assert(!ccci_runtime_bootstrap(&layout,&boot,built));
 memset(query,3,sizeof(query));query[0]=2;
 assert(!ccci_runtime_encode(query,built,blob,sizeof(blob),&used,negotiated,&rejected));
 assert(negotiated[6]==2 && negotiated[27]==2 && negotiated[36]==2);
 struct ccci_runtime_plan p;struct ccci_handshake hs={0};
 assert(!ccci_runtime_plan(&layout,&p));
 assert(!ccci_handshake_begin(&hs,&hops,NULL,&p,built,60000,0));
 boot.crystal=CCCI_RUNTIME_CRYSTAL_PRESENT;
 assert(!ccci_runtime_bootstrap(&layout,&boot,built));assert(!built[6].supported);
 assert(!ccci_runtime_encode(query,built,blob,sizeof(blob),&used,negotiated,&rejected));
 assert(negotiated[6]==1);
 const unsigned required[]={12,14,16,19,20,32};
 for(unsigned j=0;j<6;j++)for(unsigned mutation=0;mutation<7;mutation++){
  setup_profile();struct ccci_smem_region *r=&layout.users[required[j]];
  switch(mutation){case 0:r->present=false;break;case 1:r->cached=!r->cached;break;
   case 2:r->no_map=true;break;case 3:r->size=0;break;case 4:r->md++;break;
   case 5:r->ap++;break;case 6:r->ap=layout.noncached.base+layout.noncached.size;break;}
  assert(ccci_runtime_bootstrap(&layout,&boot,built)<0);zero_offers();
 }
 setup_profile();layout.users[16].size=32764;
 assert(ccci_runtime_bootstrap(&layout,&boot,built)==-ERANGE);zero_offers();
 setup_profile();layout.users[20]=layout.users[19];
 assert(ccci_runtime_bootstrap(&layout,&boot,built)==-EINVAL);zero_offers();
 setup_profile();user(12,0x3ff800,0x800,false);
 assert(ccci_runtime_bootstrap(&layout,&boot,built)==-ERANGE);zero_offers();
 setup_profile();user(16,0x800,0x8000,false);
 assert(ccci_runtime_bootstrap(&layout,&boot,built)==-EINVAL);zero_offers();
 setup_profile();layout.users[32].offset++;
 assert(ccci_runtime_bootstrap(&layout,&boot,built)==-ERANGE);zero_offers();
 setup_profile();boot.crystal=CCCI_RUNTIME_CRYSTAL_UNKNOWN;
 assert(ccci_runtime_bootstrap(&layout,&boot,built)==-ENODATA);zero_offers();
 setup_profile();assert(ccci_runtime_bootstrap(NULL,&boot,built)==-EINVAL);zero_offers();
 assert(ccci_runtime_bootstrap(&layout,NULL,built)==-EINVAL);zero_offers();
 assert(ccci_runtime_bootstrap(&layout,&boot,NULL)==-EINVAL);
 puts("PASS: actual typed runtime bootstrap, vendor 32K-less direction, exception span and layout failure atomicity");
}
int main(void){handshake_tests();profile_tests();return 0;}
'''

if __name__ == '__main__':
    BASE['main'](TEST, ('ccci-runtime-profile.c',))
