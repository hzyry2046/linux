#!/usr/bin/env python3
# SPDX-License-Identifier: GPL-2.0-only
"""Exercise actual FS codec/reassembly C, using synthetic bytes only.

ABI oracle: same-board ccci_mdinit, SHA256
0740831c74b699ee802a7e7c0ccb25266a29f4105a5dc233203ef9dc2ff71a4e.
Offsets are ELF
virtual addresses, not relocated Ghidra addresses. 17ec4/17ec8 data0/slot;
17fb0 slot <=4; 17ff8 MORE bit31; 182c8 continuation skips20 bytes;
18310 final header replaces initial; 18364..1836c argc bound5/6;
189d8 user-visible reply channel RX+1; 18af0..18b2c fragment payload<=0xd80,
length=20+payload and repeated op. TX HIF subsequently replaces seq/assert;
the codec preserves the final RX metadata, without asserting transport echo.
The bit30 flag is accepted and carried, not interpreted as an operation.
"""
from pathlib import Path
import subprocess
import tempfile

K = Path(__file__).resolve().parents[5]
TEST = r'''
#include <assert.h>
#include <stdio.h>
#include <string.h>
#include <linux/errno.h>
#include <linux/unaligned.h>
#include "ccci-fs-protocol.h"
static u8 body[CCCI_FS_BODY_MAX+8], wire[3500], store[CCCI_FS_MESSAGE_MAX+8];
static u8 value[CCCI_FS_BODY_MAX];
static size_t packet(u32 op,u32 slot,u32 seq,bool more,const u8 *data,u32 size){
 memset(wire,0,sizeof(wire));put_unaligned_le32(0x40000000U|(more?CCCI_FS_MORE:0),wire);
 put_unaligned_le32(20+size,wire+4);put_unaligned_le32((seq<<16)|14,wire+8);
 put_unaligned_le32(slot,wire+12);put_unaligned_le32(op,wire+16);
 memcpy(wire+20,data,size);return 20+size;
}
static void bodies(void){
 struct ccci_fs_message m;struct ccci_fs_arg args[6];int n;
 for(unsigned i=0;i<sizeof(value);i++)value[i]=(u8)i;
 assert(ccci_fs_encode(body,sizeof(body),0xffff1016U,NULL,0)==8);
 assert(!ccci_fs_decode(body,8,&m)&&m.operation==0xffff1016U&&!m.argc);
 for(unsigned count=0;count<=6;count++)for(unsigned size=0;size<40;size++){
  for(unsigned i=0;i<count;i++)args[i]=(struct ccci_fs_arg){value+i,size};
  memset(body,0xa5,sizeof(body));
  n=ccci_fs_encode(body,sizeof(body),0xffff1022U,args,count);assert(n>=8);
  assert(!ccci_fs_decode(body,n,&m)&&m.argc==count);
  for(unsigned i=0;i<count;i++){
   assert(m.args[i].length==size&&!memcmp(m.args[i].data,value+i,size));
   const u8 *b=m.args[i].data;for(unsigned j=size;j<((size+3)&~3U);j++)assert(!b[j]);
  }
  assert(body[n]==0xa5);
  for(int shortlen=0;shortlen<n;shortlen++){
   memset(&m,0xa5,sizeof(m));assert(ccci_fs_decode(body,shortlen,&m)<0);
   for(unsigned j=0;j<sizeof(m);j++)assert(!((u8 *)&m)[j]);
  }
  assert(ccci_fs_decode(body,n+1,&m)<0);
 }
 args[0]=(struct ccci_fs_arg){value,CCCI_FS_BODY_MAX-12};
 n=ccci_fs_encode(body,sizeof(body),0xffff1003U,args,1);assert(n==CCCI_FS_BODY_MAX);
 assert(!ccci_fs_decode(body,n,&m));
 args[0].length++;memset(body,0x5a,sizeof(body));
 assert(ccci_fs_encode(body,sizeof(body),0xffff1003U,args,1)==-EMSGSIZE);
 for(unsigned i=0;i<sizeof(body);i++)assert(body[i]==0x5a);
 args[0].length=1;assert(ccci_fs_encode(body,15,0xffff1003U,args,1)==-ENOSPC);
 assert(body[0]==0x5a);
 assert(ccci_fs_encode(body,sizeof(body),0x1003,args,1)==-EINVAL);
 assert(ccci_fs_encode(body,sizeof(body),0xffff1026U,args,1)==-EINVAL);
 assert(ccci_fs_encode(body,sizeof(body),0xffff1003U,args,7)==-EINVAL);
 args[0].data=NULL;assert(ccci_fs_encode(body,sizeof(body),0xffff1003U,args,1)<0);
 args[0]=(struct ccci_fs_arg){value,1};
 n=ccci_fs_encode(body,sizeof(body),0xffff1003U,args,1);assert(n==16);
 put_unaligned_le32(0xffffffff,body+8);assert(ccci_fs_decode(body,n,&m)==-EBADMSG);
 put_unaligned_le32(7,body+4);assert(ccci_fs_decode(body,n,&m)==-EPROTO);
 assert(ccci_fs_decode(NULL,8,&m)<0&&ccci_fs_decode(body,8,NULL)<0);
 puts("PASS: actual FS body codec: 0..6 arguments, alignment, exact bounds, transactional errors");
}
static void fragments(void){
 struct ccci_fs_arg arg={value,10000};struct ccci_fs_fragment f;
 struct ccci_fs_assembly a;size_t n;u32 size=ccci_fs_encode(body,sizeof(body),0xffff1004U,&arg,1);
 assert(size==10012);
 /* Arbitrary split points include splitting argc, len and padding. */
 for(unsigned split=1;split<3500;split+=29){
  assert(!ccci_fs_assembly_init(&a,store,CCCI_FS_MESSAGE_MAX));
  unsigned pos=4,turn=0;
  while(pos<size){
   unsigned len=size-pos;if(len>split)len=split;if(len>0xd80)len=0xd80;
   n=packet(0xffff1004U,4,turn++,(pos+len<size),body+pos,len);
   assert(!ccci_fs_fragment_decode(wire,n,14,&f)&&f.slot==4&&f.length==len);
   int ret=ccci_fs_assembly_feed(&a,wire,n);pos+=len;
   assert(ret==(pos==size?1:0));
  }
  assert(a.length==size+16&&!memcmp(store+16,body,size));
  assert(get_unaligned_le32(store+4)==size+16);
  assert(get_unaligned_le32(store)==0x40000000U);
  assert(get_unaligned_le32(store+8)==((turn-1)<<16|14));
  assert(ccci_fs_assembly_feed(&a,wire,n)==-EALREADY);
 }
 /* All five slots independent, interleaved; sequences need not match. */
 struct ccci_fs_assembly slots[5];u8 slots_store[5][128];
 struct ccci_fs_arg small={value,5};size=ccci_fs_encode(body,sizeof(body),0xffff1001U,&small,1);
 for(unsigned s=0;s<5;s++){
  assert(!ccci_fs_assembly_init(slots+s,slots_store[s],128));
  n=packet(0xffff1001U,s,1,true,body+4,3);
  assert(!ccci_fs_assembly_feed(slots+s,wire,n));
 }
 for(unsigned s=0;s<5;s++){
  n=packet(0xffff1001U,s,63,false,body+7,size-7);
  assert(ccci_fs_assembly_feed(slots+s,wire,n)==1);
 }
 n=packet(0xffff1001U,0,0,false,body+4,size-4);
 for(unsigned len=0;len<20;len++)assert(ccci_fs_fragment_decode(wire,len,14,&f)<0);
 assert(ccci_fs_fragment_decode(wire,n,15,&f)==-EPROTO);
 put_unaligned_le32(15,wire+8);assert(!ccci_fs_fragment_decode(wire,n,15,&f));
 put_unaligned_le32(14,wire+8);put_unaligned_le32(5,wire+12);
 assert(ccci_fs_fragment_decode(wire,n,14,&f)==-EPROTO);
 put_unaligned_le32(0,wire+12);put_unaligned_le32(n-1,wire+4);
 assert(ccci_fs_fragment_decode(wire,n,14,&f)==-EBADMSG);
 assert(ccci_fs_fragment_decode(wire,sizeof(wire),14,&f)==-EMSGSIZE);
 /* Partial transaction changing slot/op poisons before copying. */
 for(unsigned change=0;change<2;change++){
  assert(!ccci_fs_assembly_init(&a,store,sizeof(store)));
  n=packet(0xffff1001U,0,0,true,body+4,4);assert(!ccci_fs_assembly_feed(&a,wire,n));
  n=packet(change?0xffff1002U:0xffff1001U,change?0:1,1,false,body+8,size-8);
  assert(ccci_fs_assembly_feed(&a,wire,n)==-EPROTO);
  assert(ccci_fs_assembly_feed(&a,wire,n)==-EPROTO);
 }
 assert(!ccci_fs_assembly_init(&a,store,24));
 n=packet(0xffff1001U,0,0,false,body+4,size-4);
 assert(ccci_fs_assembly_feed(&a,wire,n)==-EMSGSIZE);
 /* Exact maximum assembled message retains a trailing canary. */
 struct ccci_fs_arg large={value,CCCI_FS_BODY_MAX-12};
 size=ccci_fs_encode(body,sizeof(body),0xffff1003U,&large,1);
 assert(size==CCCI_FS_BODY_MAX);
 assert(!ccci_fs_assembly_init(&a,store,CCCI_FS_MESSAGE_MAX));
 memset(store,0xa5,sizeof(store));
 for(unsigned pos=4;pos<size;){
  unsigned chunk=size-pos;if(chunk>0xd80)chunk=0xd80;
  n=packet(0xffff1003U,0,0,pos+chunk<size,body+pos,chunk);pos+=chunk;
  assert(ccci_fs_assembly_feed(&a,wire,n)==(pos==size?1:0));
 }
 assert(a.length==CCCI_FS_MESSAGE_MAX&&store[CCCI_FS_MESSAGE_MAX]==0xa5);
 /* Malformed final body is never published as complete. */
 assert(!ccci_fs_assembly_init(&a,store,sizeof(store)));
 put_unaligned_le32(0xffffffff,body+8);
 n=packet(0xffff1003U,0,0,false,body+4,12);
 assert(ccci_fs_assembly_feed(&a,wire,n)==-EBADMSG&&!a.active);
 /* Whole-message boundary and repeated MORE overflow. */
 assert(!ccci_fs_assembly_init(&a,store,sizeof(store)));
 memset(value,0,sizeof(value));
 for(unsigned i=0;i<4;i++){
  n=packet(0xffff1001U,0,i,true,value,0xd80);assert(!ccci_fs_assembly_feed(&a,wire,n));
 }
 n=packet(0xffff1001U,0,4,true,value,0xd80);
 assert(ccci_fs_assembly_feed(&a,wire,n)==-EMSGSIZE);
 assert(ccci_fs_assembly_init(NULL,store,sizeof(store))==-EINVAL);
 assert(ccci_fs_assembly_init(&a,NULL,sizeof(store))==-EINVAL);
 assert(ccci_fs_assembly_feed(&a,wire,n)==-EINVAL);
 puts("PASS: actual FS fragments: repeated op, five interleaved slots, final metadata, sticky bounds/order");
}
static void malformed_fuzz(void){
 struct ccci_fs_message message;struct ccci_fs_fragment fragment;u32 state=0x6893;
 for(unsigned turn=0;turn<10000;turn++){
  for(unsigned i=0;i<sizeof(wire);i++){state=state*1664525U+1013904223U;wire[i]=state>>24;}
  unsigned n=state%sizeof(wire);
  (void)ccci_fs_decode(wire,n,&message);
  (void)ccci_fs_fragment_decode(wire,n,14,&fragment);
 }
 puts("PASS: deterministic malformed byte corpus under ASan/UBSan");
}
int main(void){bodies();fragments();malformed_fuzz();return 0;}
'''


def main():
    with tempfile.TemporaryDirectory(prefix='op6893-fs-') as directory:
        root = Path(directory)
        inc = root / 'linux'
        inc.mkdir()
        (inc / 'types.h').write_text(
            '#pragma once\n#include <stdint.h>\n#include <stdbool.h>\n'
            '#include <stddef.h>\ntypedef uint8_t u8;typedef uint32_t u32;\n')
        (inc / 'errno.h').write_text('#include <asm-generic/errno.h>\n')
        (inc / 'string.h').write_text('#include <string.h>\n')
        (inc / 'unaligned.h').write_text(
            '#include <linux/types.h>\n'
            'static inline u32 get_unaligned_le32(const void *p){'
            'const u8 *b=p;return (u32)b[0]|(u32)b[1]<<8|(u32)b[2]<<16|(u32)b[3]<<24;}\n'
            'static inline void put_unaligned_le32(u32 v,void *p){'
            'u8 *b=p;for(unsigned i=0;i<4;i++)b[i]=v>>(8*i);}\n')
        (root / 'test.c').write_text(TEST)
        source = K / 'drivers/misc/mediatek/ccci'
        subprocess.run(['cc', '-O1', '-g', '-Wall', '-Wextra', '-Werror',
                        '-Wno-misleading-indentation', '-fsanitize=address,undefined',
                        '-fno-sanitize-recover=all', '-no-pie', '-I'+str(root),
                        '-I'+str(source), str(source/'ccci-fs-protocol.c'),
                        str(root/'test.c'), '-o', str(root/'test')], check=True)
        subprocess.run([str(root/'test')], check=True)


if __name__ == '__main__':
    main()
