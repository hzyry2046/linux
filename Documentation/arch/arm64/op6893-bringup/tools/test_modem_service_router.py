#!/usr/bin/env python3
# SPDX-License-Identifier: GPL-2.0-only
"""Actual externally serialized FS/RPC broker C, synthetic messages only."""
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
#include "ccci-service-router.h"
static struct ccci_service_router router;
static u8 req[8][CCCI_FS_MESSAGE_MAX],resp[8][CCCI_FS_MESSAGE_MAX];
static u8 scratch[CCCI_SERVICE_TX_SIZE],packet[CCCI_FS_MESSAGE_MAX],answer[CCCI_FS_MESSAGE_MAX];
static u8 values[12000],received[CCCI_FS_MESSAGE_MAX];
static unsigned submits,sends,accepted,pause_at;static int send_error,submit_error;
static u64 tokens[8];static unsigned response_offset;static bool hs2;
static int submit(void *c,u64 gen,u64 token,enum ccci_service_kind kind,u32 slot,const void *p,size_t n){
 (void)c;assert(gen==9&&n>=24&&p);submits++;tokens[slot+(kind==CCCI_SERVICE_RPC?5:0)]=token;
 return submit_error;
}
static int send(void *c,const void *p,size_t n,bool ready){
 (void)c;const u8 *b=p;sends++;assert(ready==hs2);
 if(sends==pause_at)return send_error;
 accepted++;u32 channel=get_unaligned_le32(b+8)&0xffff;
 if(channel==15){
  struct ccci_fs_fragment f;assert(!ccci_fs_fragment_decode(p,n,15,&f));
  assert(response_offset+f.length<=sizeof(received));
  memcpy(received+response_offset,f.data,f.length);response_offset+=f.length;
  assert(f.more==(response_offset<10008));
 }else assert(channel==33&&n==24);
 return 0;
}
static const struct ccci_service_ops ops={submit,send};
static void setup(void){
 struct ccci_service_storage store[8];for(unsigned i=0;i<8;i++)store[i]=(struct ccci_service_storage){req[i],resp[i],sizeof(req[i])};
 assert(!ccci_service_router_init(&router,&ops,NULL,store,scratch,sizeof(scratch)));
 assert(!ccci_service_router_begin(&router,9));
 submits=sends=accepted=pause_at=response_offset=0;send_error=submit_error=0;hs2=false;
 memset(tokens,0,sizeof(tokens));memset(received,0,sizeof(received));
}
static size_t fs(u8 *p,u32 channel,u32 slot,unsigned size){
 struct ccci_fs_arg arg={values,size};int len=ccci_fs_encode(p+16,sizeof(packet)-16,0xffff1003U,&arg,1);
 assert(len>0);memset(p,0,16);put_unaligned_le32(16+len,p+4);
 put_unaligned_le32(channel|0x80120000U,p+8);put_unaligned_le32(slot,p+12);return 16+len;
}
static size_t rpc(u8 *p,u32 slot,u32 op){
 memset(p,0,24);put_unaligned_le32(24,p+4);put_unaligned_le32(32,p+8);
 put_unaligned_le32(slot,p+12);put_unaligned_le32(op,p+16);return 24;
}
static void retry_tests(void){
 for(unsigned i=0;i<sizeof(values);i++)values[i]=i;
 for(unsigned fail_at=1;fail_at<=3;fail_at++)for(unsigned space=0;space<2;space++){
  setup();size_t n=fs(packet,14,4,4),m=fs(answer,15,4,10000);
  assert(!ccci_service_router_receive(&router,9,4,packet,n,100));assert(submits==1&&tokens[4]);
  assert(ccci_service_router_reply(&router,8,tokens[4],CCCI_SERVICE_FS,4,answer,m)==-ESTALE);
  assert(ccci_service_router_reply(&router,9,tokens[4]+1,CCCI_SERVICE_FS,4,answer,m)==-ESTALE);
  /* data0 is not a transaction identity; bit30 has vendor side semantics. */
  put_unaligned_le32(0x40000001U,answer);
  assert(!ccci_service_router_reply(&router,9,tokens[4],CCCI_SERVICE_FS,4,answer,m));
  assert(ccci_service_router_reply(&router,9,tokens[4],CCCI_SERVICE_FS,4,answer,m)==-EALREADY);
  pause_at=fail_at;send_error=space?-ENOSPC:-EBUSY;
  assert(ccci_service_router_pump(&router,9)==send_error);assert(accepted==fail_at-1);
  assert(router.slots[4].cursor==20+(fail_at-1)*0xd80);
  assert(!ccci_service_router_hs2(&router,9));hs2=true;
  assert(!ccci_service_router_pump(&router,9));assert(accepted==3&&response_offset==10008);
  assert(!memcmp(received,answer+20,10008));
  assert(!router.slots[4].occupied);
  for(unsigned j=0;j<sizeof(req[4]);j++)assert(!req[4][j]&&!resp[4][j]);
  u64 old=tokens[4];assert(!ccci_service_router_receive(&router,9,4,packet,n,200));
  assert(tokens[4]>old);
  assert(ccci_service_router_reply(&router,9,old,CCCI_SERVICE_FS,4,answer,m)==-ESTALE);
  assert(!ccci_service_router_reply(&router,9,tokens[4],CCCI_SERVICE_FS,4,answer,m));
  assert(!ccci_service_router_tick(&router,9,60199));
  assert(ccci_service_router_tick(&router,9,60200)==-ETIMEDOUT);
  unsigned previous=sends;assert(ccci_service_router_pump(&router,9)==-ETIMEDOUT&&sends==previous);
 }
 puts("PASS: actual router retained FS fragments resume after BUSY/full without duplicate publication; stale token rejected");
}
static void rpc_tests(void){
 setup();for(unsigned slot=0;slot<3;slot++){
  size_t n=rpc(packet,slot,0x4321);assert(!ccci_service_router_receive(&router,9,1,packet,n,0));
  struct ccci_rpc_message request;assert(!ccci_rpc_decode_request(packet,n,&request));
  int m=ccci_rpc_encode_reply(&request,NULL,0,answer,sizeof(answer));assert(m==24);
  put_unaligned_le32(0xffff4322U,answer+16);
  assert(ccci_service_router_reply(&router,9,tokens[slot+5],CCCI_SERVICE_RPC,slot,answer,m)==-EPROTO);
  put_unaligned_le32(0xffff4321U,answer+16);
  assert(!ccci_service_router_reply(&router,9,tokens[slot+5],CCCI_SERVICE_RPC,slot,answer,m));
 }
 assert(submits==3&&!sends);pause_at=2;send_error=-EBUSY;
 assert(ccci_service_router_pump(&router,9)==-EBUSY&&accepted==1);
 assert(!ccci_service_router_pump(&router,9)&&accepted==3);
 assert(!router.slots[5].occupied&&!router.slots[6].occupied&&!router.slots[7].occupied);
 puts("PASS: all three RPC slots correlated, operation validation, unknown RPC forwarded without fabricated success");
}
static void failures(void){
 for(unsigned mode=0;mode<3;mode++){
  setup();size_t n=fs(packet,14,0,4),m=fs(answer,15,0,10000);
  if(!mode)submit_error=-EIO;
  int ret=ccci_service_router_receive(&router,9,4,packet,n,0);
  if(!mode)assert(ret==-EIO);
  else {
   assert(!ret);assert(!ccci_service_router_reply(&router,9,tokens[0],CCCI_SERVICE_FS,0,answer,m));
   pause_at=mode;send_error=-EIO;assert(ccci_service_router_pump(&router,9)==-EIO);
  }
  unsigned previous=sends;assert(ccci_service_router_pump(&router,9)==-EIO&&sends==previous);
  assert(ccci_service_router_close(&router,9,false)==-EBUSY&&router.active);
  memset(scratch,0xa5,sizeof(scratch));
  assert(!ccci_service_router_close(&router,9,true)&&!router.active);
  for(unsigned i=0;i<8;i++)for(unsigned j=0;j<sizeof(req[i]);j++)assert(!req[i][j]&&!resp[i][j]);
  for(unsigned i=0;i<sizeof(scratch);i++)assert(!scratch[i]);
  assert(ccci_service_router_receive(&router,9,4,packet,n,0)==-ESHUTDOWN);
  assert(ccci_service_router_pump(&router,9)==-ESHUTDOWN&&sends==previous);
  assert(ccci_service_router_begin(&router,10)==-EALREADY);
 }
 setup();size_t n=fs(packet,14,0,4);
 assert(ccci_service_router_receive(&router,9,1,packet,n,0)==-EPROTO&&!submits);
 setup();n=rpc(packet,2,0x400f);
 assert(!ccci_service_router_receive(&router,9,1,packet,n,0));
 assert(ccci_service_router_receive(&router,9,1,packet,n,0)==-EBUSY);
 setup();n=rpc(packet,0,0x400f);
 assert(!ccci_service_router_receive(&router,9,1,packet,n,0));
 assert(ccci_service_router_abort(&router,8,-EPIPE)==-ESTALE&&!router.error);
 assert(ccci_service_router_abort(&router,9,-EPIPE)==-EPIPE);
 assert(router.slots[5].occupied&&ccci_service_router_pump(&router,9)==-EPIPE&&!sends);
 assert(ccci_service_router_abort(&router,9,-EIO)==-EPIPE);
 assert(!ccci_service_router_close(&router,9,true));
 setup();router.next_token=~(u64)0;n=rpc(packet,0,0x400f);
 assert(ccci_service_router_receive(&router,9,1,packet,n,0)==-EOVERFLOW&&!submits);
 setup();n=fs(packet,14,0,4);put_unaligned_le32(CCCI_FS_MORE,packet);
 assert(!ccci_service_router_receive(&router,9,4,packet,n,1)&&!submits);
 assert(ccci_service_router_tick(&router,9,60001)==-ETIMEDOUT);
 puts("PASS: callback/transport faults sticky, fragment deadlines, slot collision, token overflow, stopped-only erasure");
}
int main(void){retry_tests();rpc_tests();failures();return 0;}
'''


def main():
    with tempfile.TemporaryDirectory(prefix='op6893-service-') as directory:
        root = Path(directory)
        inc = root / 'linux'
        inc.mkdir()
        (inc / 'types.h').write_text(
            '#pragma once\n#include <stdint.h>\n#include <stdbool.h>\n'
            '#include <stddef.h>\ntypedef uint8_t u8;typedef uint32_t u32;typedef uint64_t u64;\n')
        (inc / 'errno.h').write_text('#include <asm-generic/errno.h>\n')
        (inc / 'printk.h').write_text('#pragma once\nstatic inline void pr_err(const char *fmt, ...) { (void)fmt; }\nstatic inline void pr_info(const char *fmt, ...) { (void)fmt; }\n')
        (inc / 'kernel.h').write_text('#define ARRAY_SIZE(a) (sizeof(a)/sizeof((a)[0]))\n')
        (inc / 'string.h').write_text(
            '#include <string.h>\nstatic inline void memzero_explicit(void *p,size_t n){'
            'volatile unsigned char *b=p;while(n--)*b++=0;}\n')
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
                        str(source/'ccci-rpc-protocol.c'), str(source/'ccci-service-router.c'),
                        str(root/'test.c'), '-o', str(root/'test')], check=True)
        subprocess.run([str(root/'test')], check=True)


if __name__ == '__main__':
    main()
