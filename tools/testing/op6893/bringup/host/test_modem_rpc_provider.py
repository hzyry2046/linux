#!/usr/bin/env python3
# SPDX-License-Identifier: GPL-2.0-only
"""Compile actual immutable RPC providers with synthetic packets and sanitizers."""
from pathlib import Path
import subprocess
import tempfile

K = Path(__file__).resolve().parents[5]
SRC = K / 'drivers/misc/mediatek/ccci'
TEST = r'''
#include <assert.h>
#include <errno.h>
#include <stdio.h>
#include <string.h>
#include <linux/unaligned.h>
#include "ccci-rpc-lhif.h"
#include "ccci-rpc-provider.h"
/* A port_rpc.h:221 / V port_rpc.h:242: implicit values INCREASE from -13. */
enum source_eint_error { SOURCE_EINT_NULL=-13, SOURCE_EINT_TYPE, SOURCE_EINT_NAME };
_Static_assert(SOURCE_EINT_TYPE==-12&&SOURCE_EINT_NAME==-11,"vendor enum values");
static u8 packet[2048],reply[2048];
static struct ccci_rpc_named_fact gp[2]={{{'p','i','n',0},513},{{'a','l','t',0},71}};
static struct ccci_rpc_named_fact ad[1]={{{'a','d','c',0},9}};
static struct ccci_rpc_named_fact dt[1]={{{'c','o','n','f','i','g',0},0x87654321}};
static struct ccci_rpc_eint_fact ei[1]={{{'s','i','m',0},{1,2,1,0,3,-14,6}}};
static struct ccci_rpc_provider facts={gp,ad,dt,ei,2,1,1,1,true,true,true,true,NULL};
static int read_level(u32 id,u32 *level){if(id==513){*level=1;return 0;}return -2;}
static size_t make(u32 op,const struct ccci_rpc_arg *args,u32 argc){
 size_t off=24;memset(packet,0,sizeof(packet));put_unaligned_le32(0x12345678,packet);
 put_unaligned_le32(0x80320020,packet+8);put_unaligned_le32(2,packet+12);
 put_unaligned_le32(op,packet+16);put_unaligned_le32(argc,packet+20);
 for(unsigned i=0;i<argc;i++){put_unaligned_le32(args[i].size,packet+off);off+=4;
  if(args[i].size){memcpy(packet+off,args[i].data,args[i].size);}off+=(args[i].size+3)&~3U;
 }
 put_unaligned_le32(off,packet+4);return off;
}
static void unchanged(int expected,const struct ccci_rpc_provider *p,size_t n){
 memset(reply,0xa5,sizeof(reply));assert(ccci_rpc_provider_reply(p,packet,n,reply,sizeof(reply))==expected);
 for(unsigned i=0;i<sizeof(reply);i++)assert(reply[i]==0xa5);
}
static void scalars(const struct ccci_rpc_provider *p,size_t n,int x,int y,unsigned argc){
 struct ccci_rpc_message req;assert(!ccci_rpc_decode_request(packet,n,&req));
 int count=ccci_rpc_provider_reply(p,packet,n,reply,sizeof(reply));assert(count==(int)(24+argc*8));
 assert(!ccci_rpc_validate_reply(&req,reply,count));assert(get_unaligned_le32(reply+20)==argc);
 assert((int)get_unaligned_le32(reply+28)==x);
 if(argc==2)assert((int)get_unaligned_le32(reply+36)==y);
 assert(!memcmp(reply,packet,4)&&!memcmp(reply+12,packet+12,4));
}
int main(void){
 struct ccci_rpc_arg args[3]={{(const u8 *)"pin",4},{NULL,0},{NULL,0}};
 size_t n=make(0x4002,args,2);scalars(&facts,n,513,513,2);
 args[0].size=3;n=make(0x4002,args,2);scalars(&facts,n,513,513,2);
 args[0]=(struct ccci_rpc_arg){(const u8 *)"pi",2};n=make(0x4002,args,2);scalars(&facts,n,-5,-5,2);
 args[0]=(struct ccci_rpc_arg){(const u8 *)"adc",4};n=make(0x4003,args,2);scalars(&facts,n,9,9,2);
 n=make(0x4003,NULL,0);scalars(&facts,n,-2,-2,2);
 args[0]=(struct ccci_rpc_arg){(const u8 *)"p\0in",4};n=make(0x4002,args,2);scalars(&facts,n,-5,-5,2);
 args[0]=(struct ccci_rpc_arg){NULL,0};n=make(0x4002,args,2);unchanged(-EPROTO,&facts,n);
 u8 type[4];put_unaligned_le32(0,type);args[0]=(struct ccci_rpc_arg){(const u8 *)"sim",4};
 args[2]=(struct ccci_rpc_arg){type,4};n=make(0x4005,args,3);scalars(&facts,n,0,1,2);
 put_unaligned_le32(5,type);n=make(0x4005,args,3);scalars(&facts,n,SOURCE_EINT_NAME,SOURCE_EINT_NAME,2);
 put_unaligned_le32(7,type);n=make(0x4005,args,3);scalars(&facts,n,SOURCE_EINT_TYPE,SOURCE_EINT_TYPE,2);
 put_unaligned_le32(0,type);args[2].size=3;n=make(0x4005,args,3);unchanged(-EPROTO,&facts,n);
 u8 type8[8]={0};put_unaligned_le32(0,type8);args[2]=(struct ccci_rpc_arg){type8,8};
 n=make(0x4005,args,3);scalars(&facts,n,0,1,2);
 args[2]=(struct ccci_rpc_arg){type,4};
 args[2].size=4;args[0]=(struct ccci_rpc_arg){(const u8 *)"missing",8};n=make(0x4005,args,3);scalars(&facts,n,SOURCE_EINT_NAME,SOURCE_EINT_NAME,2);
 n=make(0x4005,args,2);scalars(&facts,n,-2,-2,2);
 u8 query[66]={1,99,'c','o','n','f','i','g',0};args[0]=(struct ccci_rpc_arg){query,66};
 n=make(0x400e,args,1);assert(ccci_rpc_provider_reply(&facts,packet,n,reply,sizeof(reply))==104);
 assert(get_unaligned_le32(reply+28)==0&&get_unaligned_le32(reply+32)==68);
 assert(get_unaligned_le32(reply+36)==0x87654321);
 for(unsigned i=40;i<104;i++)assert(reply[i]==0x0f);
 query[0]=2;n=make(0x400e,args,1);assert(ccci_rpc_provider_reply(&facts,packet,n,reply,sizeof(reply))==104);
 for(unsigned i=36;i<104;i++)assert(reply[i]==0x0f);
 query[0]=1;query[2]='x';n=make(0x400e,args,1);assert(ccci_rpc_provider_reply(&facts,packet,n,reply,sizeof(reply))==104);
 assert(get_unaligned_le32(reply+36)==0x0f0f0f0f);
 memset(query+2,'x',64);n=make(0x400e,args,1);unchanged(-EPROTO,&facts,n);
 args[0].size=65;n=make(0x400e,args,1);unchanged(-EPROTO,&facts,n);
 n=make(0x400e,args,2);scalars(&facts,n,-2,-2,2);
 /* Every declared/reserved A/V ID is unavailable without audited facts. */
 for(unsigned op=0x4001;op<=0x4017;op++){
  assert(ccci_rpc_provider_known(op));
  if(op==0x4007||op==0x4009||op==0x400d)continue;
  n=make(op,NULL,0);unchanged(-EOPNOTSUPP,NULL,n);
 }
 /* 0x4009: audited MD-view pin numbers, A's 0x0f fill for every value. */
 {
  static u8 record[425];
  struct ccci_rpc_arg a={record,425};
  memset(record,0,sizeof(record));
  put_unaligned_le16(3,record);put_unaligned_le16(0x7,record+2);
  memcpy(record+4,"pin",3);
  n=make(0x4009,&a,1);
  int count=ccci_rpc_provider_reply(&facts,packet,n,reply,sizeof(reply));
  assert(count==24+8+4+88);
  assert(get_unaligned_le32(reply+28)==0&&get_unaligned_le32(reply+32)==88);
  assert(get_unaligned_le32(reply+36)==513);
  for(unsigned i=1;i<10;i++)assert(get_unaligned_le32(reply+36+i*4)==0x0f0f0f0f);
  for(unsigned i=40;i<88;i++)assert(reply[36+i]==0x0f);
  /* A board level accessor fills only the value slot it can actually read. */
  {
   struct ccci_rpc_provider live=facts;live.gpio_read=read_level;
   count=ccci_rpc_provider_reply(&live,packet,n,reply,sizeof(reply));
   assert(count==24+8+4+88);
   assert(get_unaligned_le32(reply+36)==513);
   assert(get_unaligned_le32(reply+36+40)==1);
   for(unsigned i=1;i<10;i++)assert(get_unaligned_le32(reply+36+40+i*4)==0x0f0f0f0f);
  }
  /* The v1 record uses one-byte masks and three pins. */
  memset(record,0,sizeof(record));record[0]=3;record[1]=0x1;memcpy(record+2,"pin",3);
  a.size=157;n=make(0x4009,&a,1);
  count=ccci_rpc_provider_reply(&facts,packet,n,reply,sizeof(reply));
  assert(count==24+8+4+32);
  assert(get_unaligned_le32(reply+36)==513);
  /* Unrecognised sizes and arity use A's -2 pair. */
  a.size=100;n=make(0x4009,&a,1);scalars(NULL,n,-2,-2,2);
  n=make(0x4009,NULL,0);scalars(NULL,n,-2,-2,2);
 }
 /* 0x400d: A records the LHIF remap and always replies two zero words. */
 {
  u8 map[8];u32 q=0xdead;struct ccci_rpc_lhif_state st;
  ccci_rpc_lhif_reset();ccci_rpc_lhif_state(&st);
  assert(!st.requests&&!st.ports&&!ccci_rpc_lhif_queue(0,&q)&&q==0xdead);
  put_unaligned_le32(0,map);put_unaligned_le32(2,map+4);
  struct ccci_rpc_arg a={map,8};
  n=make(0x400d,&a,1);scalars(NULL,n,0,0,2);
  ccci_rpc_lhif_state(&st);assert(st.requests==1&&st.ports==1&&!st.unknown);
  assert(st.port[0].net_if==0&&st.port[0].lhif_q==2&&st.port[0].queue==0);
  assert(ccci_rpc_lhif_queue(0,&q)&&q==0);
  put_unaligned_le32(3,map+4);n=make(0x400d,&a,1);scalars(NULL,n,0,0,2);
  ccci_rpc_lhif_state(&st);assert(st.requests==2&&st.ports==1&&st.port[0].queue==3);
  assert(ccci_rpc_lhif_queue(0,&q)&&q==3);
  /* A rejects a queue it does not map, but the MD still sees two zeros. */
  put_unaligned_le32(4,map+4);n=make(0x400d,&a,1);scalars(NULL,n,0,0,2);
  ccci_rpc_lhif_state(&st);assert(st.requests==3&&st.unknown==1&&st.port[0].queue==3);
  put_unaligned_le32(1,map);put_unaligned_le32(3,map+4);
  n=make(0x400d,&a,1);scalars(NULL,n,0,0,2);
  ccci_rpc_lhif_state(&st);assert(st.ports==2&&ccci_rpc_lhif_queue(1,&q)&&q==3);
  assert(!ccci_rpc_lhif_queue(2,&q)&&q==3);
  /* Shape errors use A's -2 pair and never touch the recorded mapping. */
  a.size=4;n=make(0x400d,&a,1);scalars(NULL,n,-2,-2,2);
  struct ccci_rpc_arg pair[2]={a,a};
  n=make(0x400d,pair,2);scalars(NULL,n,-2,-2,2);
  n=make(0x400d,NULL,0);scalars(NULL,n,-2,-2,2);
  ccci_rpc_lhif_state(&st);assert(st.requests==4&&st.malformed==3&&st.ports==2);
  ccci_rpc_lhif_reset();ccci_rpc_lhif_state(&st);assert(!st.requests&&!st.ports);
 }
 /* 0x4007 emits A's unavailable-value reply: get_md_adc_val() returns -1. */
 {
  static const u8 channel[8]={9,0,0,0,0,0,0,0};
  struct ccci_rpc_arg a={channel,4};
  n=make(0x4007,&a,1);scalars(NULL,n,-1,-1,2);
  a.size=8;n=make(0x4007,&a,1);scalars(NULL,n,-2,-2,2);
  n=make(0x4007,NULL,0);scalars(NULL,n,-2,-2,2);
 }
 for(unsigned op=0x3001;op<=0x3012;op++){
  assert(ccci_rpc_provider_known(op));n=make(op,NULL,0);unchanged(-EOPNOTSUPP,&facts,n);
 }
 const unsigned blocked[]={0x2001,0x2002,0x4321};
 for(unsigned i=0;i<3;i++){n=make(blocked[i],NULL,0);unchanged(-EOPNOTSUPP,&facts,n);}
 const unsigned unknown[]={0,0x1234,0x4018,0x4322,0xffff};
 for(unsigned i=0;i<5;i++){
  assert(!ccci_rpc_provider_known(unknown[i]));n=make(unknown[i],NULL,0);scalars(NULL,n,-1,0,1);
 }
 struct ccci_rpc_provider bad=facts;bad.gpio_count=33;n=make(0x4002,args,2);unchanged(-EINVAL,&bad,n);
 bad=facts;bad.gpio_present=false;unchanged(-EINVAL,&bad,n);
 bad=facts;bad.gpio=NULL;unchanged(-EINVAL,&bad,n);
 struct ccci_rpc_named_fact duplicate[2]={gp[0],gp[0]};bad=facts;bad.gpio=duplicate;unchanged(-EINVAL,&bad,n);
 memset(duplicate[0].name,'x',64);unchanged(-EINVAL,&bad,n);
 duplicate[0]=gp[0];duplicate[1]=gp[1];duplicate[0].value=0xffffffff;unchanged(-EINVAL,&bad,n);
 bad=facts;bad.gpio_count=0;bad.gpio=NULL;
 args[0]=(struct ccci_rpc_arg){(const u8 *)"pin",4};n=make(0x4002,args,2);scalars(&bad,n,-5,-5,2);
 assert(ccci_rpc_provider_available(&facts,0x4002)==1);
 assert(ccci_rpc_provider_available(&facts,0x400d)==0);
 assert(ccci_rpc_provider_available(NULL,0x4002)==0);
 memset(reply,0xa5,sizeof(reply));assert(ccci_rpc_provider_reply(&facts,packet,n,reply,39)==-ENOSPC);
 for(unsigned i=0;i<sizeof(reply);i++)assert(reply[i]==0xa5);
 put_unaligned_le32(0xffff4002,packet+16);unchanged(-EPROTO,&facts,n);
 puts("PASS: actual pure RPC fact providers, typed endian replies, capability/known-ID guards, failure atomicity");
 return 0;
}
'''



def main():
    with tempfile.TemporaryDirectory(prefix='op6893-rpc-provider-') as directory:
        tmp = Path(directory)
        inc = tmp / 'linux'
        inc.mkdir()
        (inc / 'types.h').write_text('#pragma once\n#include <stdint.h>\n#include <stddef.h>\n#include <stdbool.h>\ntypedef uint8_t u8; typedef uint16_t u16; typedef uint32_t u32; typedef int32_t s32;\n')
        (inc / 'errno.h').write_text('#include <asm-generic/errno.h>\n')
        (inc / 'array_size.h').write_text('#pragma once\n#define ARRAY_SIZE(a) (sizeof(a) / sizeof((a)[0]))\n')
        (inc / 'string.h').write_text('#include <string.h>\n')
        (inc / 'spinlock.h').write_text('''#pragma once
typedef struct { int unused; } spinlock_t;
#define DEFINE_SPINLOCK(name) spinlock_t name
#define spin_lock_irqsave(l, f) do { (void)(l); (f) = 0; } while (0)
#define spin_unlock_irqrestore(l, f) do { (void)(l); (void)(f); } while (0)
''')
        (inc / 'unaligned.h').write_text('''#pragma once
#include <linux/types.h>
static inline u32 get_unaligned_le32(const void *p) {
 const u8 *b=p;return (u32)b[0]|(u32)b[1]<<8|(u32)b[2]<<16|(u32)b[3]<<24;
}
static inline void put_unaligned_le32(u32 v,void *p) {
 u8 *b=p;for(unsigned i=0;i<4;i++)b[i]=v>>(i*8);
}
static inline u16 get_unaligned_le16(const void *p) {
 const u8 *b=p;return (u16)((u16)b[0]|(u16)b[1]<<8);
}
static inline void put_unaligned_le16(u16 v,void *p) {
 u8 *b=p;b[0]=v;b[1]=v>>8;
}
''')
        (tmp / 'test.c').write_text(TEST)
        subprocess.run(['cc', '-O1', '-g', '-Wall', '-Wextra', '-Werror',
                        '-fsanitize=address,undefined', '-fno-sanitize-recover=all',
                        '-no-pie', '-I' + str(tmp), '-I' + str(SRC),
                        str(SRC / 'ccci-rpc-protocol.c'), str(SRC / 'ccci-rpc-provider.c'),
                        str(SRC / 'ccci-rpc-lhif.c'), str(tmp / 'test.c'),
                        '-o', str(tmp / 'test')], check=True)
        subprocess.run([str(tmp / 'test')], check=True)


if __name__ == '__main__':
    main()
