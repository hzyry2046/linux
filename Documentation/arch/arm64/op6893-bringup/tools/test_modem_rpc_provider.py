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
#include "ccci-rpc-provider.h"
static u8 packet[2048],reply[2048];
static struct ccci_rpc_named_fact gp[2]={{{'p','i','n',0},513},{{'a','l','t',0},71}};
static struct ccci_rpc_named_fact ad[1]={{{'a','d','c',0},9}};
static struct ccci_rpc_named_fact dt[1]={{{'c','o','n','f','i','g',0},0x87654321}};
static struct ccci_rpc_eint_fact ei[1]={{{'s','i','m',0},{1,2,1,0,3,-14,6}}};
static struct ccci_rpc_provider facts={gp,ad,dt,ei,2,1,1,1,true,true,true,true};
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
 args[0]=(struct ccci_rpc_arg){(const u8 *)"p\0in",4};n=make(0x4002,args,2);unchanged(-EPROTO,&facts,n);
 args[0]=(struct ccci_rpc_arg){NULL,0};n=make(0x4002,args,2);unchanged(-EPROTO,&facts,n);
 u8 type[4];put_unaligned_le32(0,type);args[0]=(struct ccci_rpc_arg){(const u8 *)"sim",4};
 args[2]=(struct ccci_rpc_arg){type,4};n=make(0x4005,args,3);scalars(&facts,n,0,1,2);
 put_unaligned_le32(5,type);n=make(0x4005,args,3);scalars(&facts,n,-15,-15,2);
 put_unaligned_le32(7,type);n=make(0x4005,args,3);scalars(&facts,n,-14,-14,2);
 put_unaligned_le32(0,type);args[2].size=3;n=make(0x4005,args,3);unchanged(-EPROTO,&facts,n);
 args[2].size=4;args[0]=(struct ccci_rpc_arg){(const u8 *)"missing",8};n=make(0x4005,args,3);scalars(&facts,n,-15,-15,2);
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
  assert(ccci_rpc_provider_known(op));n=make(op,NULL,0);unchanged(-EOPNOTSUPP,NULL,n);
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
        (inc / 'types.h').write_text('#pragma once\n#include <stdint.h>\n#include <stddef.h>\n#include <stdbool.h>\ntypedef uint8_t u8; typedef uint32_t u32; typedef int32_t s32;\n')
        (inc / 'errno.h').write_text('#include <asm-generic/errno.h>\n')
        (inc / 'string.h').write_text('#include <string.h>\n')
        (inc / 'unaligned.h').write_text('''#pragma once
#include <linux/types.h>
static inline u32 get_unaligned_le32(const void *p) {
 const u8 *b=p;return (u32)b[0]|(u32)b[1]<<8|(u32)b[2]<<16|(u32)b[3]<<24;
}
static inline void put_unaligned_le32(u32 v,void *p) {
 u8 *b=p;for(unsigned i=0;i<4;i++)b[i]=v>>(i*8);
}
''')
        (tmp / 'test.c').write_text(TEST)
        subprocess.run(['cc', '-O1', '-g', '-Wall', '-Wextra', '-Werror',
                        '-fsanitize=address,undefined', '-fno-sanitize-recover=all',
                        '-no-pie', '-I' + str(tmp), '-I' + str(SRC),
                        str(SRC / 'ccci-rpc-protocol.c'), str(SRC / 'ccci-rpc-provider.c'), str(tmp / 'test.c'),
                        '-o', str(tmp / 'test')], check=True)
        subprocess.run([str(tmp / 'test')], check=True)


if __name__ == '__main__':
    main()
