#!/usr/bin/env python3
# SPDX-License-Identifier: GPL-2.0-only
"""Compile actual bounded RPC codec with synthetic packets and sanitizers."""
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
#include "ccci-rpc-protocol.h"
static u8 packet[2048], reply[2048];
static struct ccci_rpc_message request, decoded;
static void make(unsigned op, unsigned slot) {
 memset(packet,0,sizeof(packet));
 put_unaligned_le32(0x13579bdf,packet);
 put_unaligned_le32(36,packet+4);
 put_unaligned_le32(0xabc00020,packet+8);
 put_unaligned_le32(slot,packet+12);
 put_unaligned_le32(op,packet+16);
 put_unaligned_le32(2,packet+20);
 put_unaligned_le32(1,packet+24);packet[28]=42;
 put_unaligned_le32(0,packet+32);
 assert(!ccci_rpc_decode_request(packet,36,&request));
 assert(request.args[0].data==packet+28 && request.args[0].size==1);
 assert(request.args[1].size==0);
}
static void bad(size_t length) {
 memset(&decoded,0xa5,sizeof(decoded));
 assert(ccci_rpc_decode_request(packet,length,&decoded)<0);
 const u8 *p=(const void *)&decoded;
 for(size_t i=0;i<sizeof(decoded);i++)assert(!p[i]);
}
int main(void) {
 assert(ccci_rpc_owner(0x400f)==CCCI_RPC_USERSPACE);
 assert(ccci_rpc_owner(0x4010)==CCCI_RPC_USERSPACE);
 assert(ccci_rpc_owner(0x4014)==CCCI_RPC_KERNEL);
 assert(ccci_rpc_owner(0x400d)==CCCI_RPC_KERNEL);
 for(unsigned slot=0;slot<=2;slot++) {
  make(0x400f,slot);
  assert(ccci_rpc_encode_reply(&request,request.args,request.argc,reply,sizeof(reply))==36);
  assert(!ccci_rpc_validate_reply(&request,reply,36));
  assert(reply[29]==0 && reply[30]==0 && reply[31]==0);
  put_unaligned_le32(0x12340021,reply+8);
  assert(!ccci_rpc_validate_reply(&request,reply,36));
  put_unaligned_le32(0xffff4010,reply+16);
  assert(ccci_rpc_validate_reply(&request,reply,36)==-EPROTO);
 }
 make(0x400d,0);
 for(unsigned n=0;n<36;n++)bad(n);
 bad(2049);
 for(unsigned offset=4;offset<=24;offset+=4) {
  make(0x400f,1);put_unaligned_le32(0xffffffff,packet+offset);bad(36);
 }
 make(0x400f,1);put_unaligned_le32(37,packet+4);bad(37);
 make(0x400f,1);put_unaligned_le32(3,packet+12);bad(36);
 make(0x400f,1);put_unaligned_le32(7,packet+20);bad(36);
 make(0x400f,1);put_unaligned_le32(5,packet+24);bad(36);
 make(0x400f,1);memset(reply,0xa5,sizeof(reply));
 assert(ccci_rpc_encode_reply(&request,request.args,2,reply,35)==-ENOSPC);
 for(unsigned i=0;i<sizeof(reply);i++)assert(reply[i]==0xa5);
 struct ccci_rpc_arg args[6]={{packet,2020}};
 assert(ccci_rpc_encode_reply(&request,args,1,reply,sizeof(reply))==2048);
 assert(!ccci_rpc_validate_reply(&request,reply,sizeof(reply)));
 args[0].size=2021;
 assert(ccci_rpc_encode_reply(&request,args,1,reply,sizeof(reply))==-EMSGSIZE);
 args[0].size=0xffffffff;
 assert(ccci_rpc_encode_reply(&request,args,1,reply,sizeof(reply))==-EINVAL);
 args[0]=(struct ccci_rpc_arg){NULL,1};
 assert(ccci_rpc_encode_reply(&request,args,1,reply,sizeof(reply))==-EINVAL);
 assert(ccci_rpc_encode_reply(&request,args,7,reply,sizeof(reply))==-EINVAL);
 assert(ccci_rpc_encode_reply(&request,NULL,0,reply,sizeof(reply))==24);
 assert(!ccci_rpc_validate_reply(&request,reply,24));
 put_unaligned_le32(2,reply+12);assert(ccci_rpc_validate_reply(&request,reply,24)==-EPROTO);
 assert(ccci_rpc_decode_request(NULL,24,&decoded)==-EMSGSIZE);
 assert(ccci_rpc_decode_request(packet,36,NULL)==-EINVAL);
 puts("PASS: actual RPC codec bounds, ownership, padding, lease reply identity");
 return 0;
}
'''


def main():
    with tempfile.TemporaryDirectory(prefix='op6893-rpc-') as directory:
        tmp = Path(directory)
        inc = tmp / 'linux'
        inc.mkdir()
        (inc / 'types.h').write_text('#pragma once\n#include <stdint.h>\n#include <stddef.h>\n#include <stdbool.h>\ntypedef uint8_t u8; typedef uint32_t u32;\n')
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
                        str(SRC / 'ccci-rpc-protocol.c'), str(tmp / 'test.c'),
                        '-o', str(tmp / 'test')], check=True)
        subprocess.run([str(tmp / 'test')], check=True)


if __name__ == '__main__':
    main()
