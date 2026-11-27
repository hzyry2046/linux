#!/usr/bin/env python3
# SPDX-License-Identifier: GPL-2.0-only
"""Actual RX backend with ordered synthetic operations and fault injection."""
from pathlib import Path
import runpy
import subprocess
import tempfile

K = Path(__file__).resolve().parents[5]
D = K / 'drivers/misc/mediatek/ccci'
tx, rx, count = runpy.run_path(str(Path(__file__).with_name('test_modem_scp.py')))['audited_fixture']()


def source(name):
    return '\n'.join(line for line in (D / name).read_text().splitlines()
                     if not line.startswith('#include'))


preamble = r'''
#include <assert.h>
#include <errno.h>
#include <stdbool.h>
#include <stdint.h>
#include <stdio.h>
#include <string.h>
typedef uint8_t u8;typedef uint16_t u16;typedef uint32_t u32;typedef uint64_t u64;
#define U32_MAX UINT32_MAX
#define BIT(n) (1U<<(n))
#define BIT_ULL(n) (1ULL<<(n))
#define ARRAY_SIZE(a) (sizeof(a)/sizeof((a)[0]))
static u16 get_unaligned_le16(const void *p) {const u8 *b=p;return (u16)b[0]|(u16)b[1]<<8;}
static u32 get_unaligned_le32(const void *p) {const u8 *b=p;return (u32)b[0]|(u32)b[1]<<8|(u32)b[2]<<16|(u32)b[3]<<24;}
static void put_unaligned_le16(u16 v,void *p) {u8 *b=p;for(unsigned i=0;i<2;i++)b[i]=v>>(8*i);}
static void put_unaligned_le32(u32 v,void *p) {u8 *b=p;for(unsigned i=0;i<4;i++)b[i]=v>>(8*i);}
'''
harness = r'''
static const u32 tx[]={@TX@},rt[]={@RX@};
static struct ccci_scp_layout layout;
static struct ccci_scp_rx receiver;
static struct ccci_scp_rx_result result;
static unsigned stage,reads,delivers,ack_calls,post_calls,operations,fail_at;
static u32 pending_mask,ack_mask,copied_mask;
static unsigned mailbox;
static u8 wire[256];
static bool overwrite_on_ack;
static int fails(void) {return ++operations==fail_at?-EIO:0;}
static int pending(void *context,u32 *out) {
 assert(context==wire && stage==0);stage=1;*out=pending_mask;return fails();
}
static int read_words(void *context,u32 offset,u32 words,void *buffer) {
 assert(context==wire && stage==1 && offset+words<=64);
 const struct ccci_scp_pin *found=NULL;
 for(unsigned i=0;i<layout.rx_count;i++) {
  const struct ccci_scp_pin *p=&layout.rx[i];
  if(p->mbox==mailbox && p->offset==offset && p->words==words)found=p;
 }
 assert(found && (pending_mask&BIT(found->irq)) && !(copied_mask&BIT(found->irq)));
 reads++;if(fails())return -EIO;
 memcpy(buffer,wire+offset*4,words*4);copied_mask|=BIT(found->irq);return 0;
}
static int post_capture(void *context) {
 assert(context==wire && stage==1 && copied_mask==pending_mask);
 post_calls++;stage=2;return fails();
}
static int ack(void *context,u32 mask) {
 assert(context==wire && stage==2 && mask==pending_mask && mask==copied_mask);
 ack_calls++;ack_mask=mask;stage=3;
 if(overwrite_on_ack)memset(wire,0xe5,sizeof(wire));
 return fails();
}
static void deliver(void *context,const struct ccci_scp_pin *pin,const void *buffer,size_t bytes,u64 generation) {
 assert(context==wire && stage==3 && generation==17);
 assert(pin->mbox==mailbox && bytes==pin->words*4 && ack_mask&BIT(pin->irq));
 const u8 *p=buffer;for(unsigned i=0;i<bytes;i++)assert(p[i]==(u8)(pin->offset*4+i));
 delivers++;
}
static const struct ccci_scp_rx_ops ops={pending,read_words,post_capture,ack,deliver};
static void reset(u32 box,u32 mask) {
 assert(!ccci_scp_build_layout(tx,ARRAY_SIZE(tx),rt,ARRAY_SIZE(rt),5,&layout));
 mailbox=box;stage=reads=delivers=ack_calls=post_calls=operations=fail_at=0;
 pending_mask=mask;ack_mask=copied_mask=0;overwrite_on_ack=true;
 for(unsigned i=0;i<256;i++)wire[i]=i;
 u32 known=0;for(unsigned i=0;i<layout.rx_count;i++)if(layout.rx[i].mbox==box)known|=BIT(layout.rx[i].irq);
 assert(!ccci_scp_rx_init(&receiver,&layout,box,known,17,&ops,wire));
}
static void sticky(void) {
 unsigned before=operations;assert(receiver.fault);
 assert(ccci_scp_rx_step(&receiver,&result)==-ESHUTDOWN && operations==before);
 assert(!result.pending && !result.delivered && !result.ack_attempted);
}
int main(void) {
 reset(1,0);assert(!ccci_scp_rx_step(&receiver,&result));
 assert(!reads && !post_calls && !ack_calls && !delivers && !receiver.fault);
 u32 seed=0x68930001;
 for(unsigned box=0;box<5;box++) {
  reset(box,0);u32 mask=receiver.known_mask;
  for(unsigned iteration=0;iteration<150;iteration++) {
   seed^=seed<<13;seed^=seed>>17;seed^=seed<<5;
   reset(box,iteration?mask&seed:mask);
   unsigned n=__builtin_popcount(pending_mask);
   assert(!ccci_scp_rx_step(&receiver,&result));
   assert(reads==n && delivers==n && result.copied==pending_mask);
   assert(result.acknowledged==pending_mask && result.delivered==pending_mask);
   assert(ack_calls==!!n && post_calls==!!n && !receiver.fault);
  }
 }
 /* READY0 is a one-word pin, unlike APCCCI. Keep the complete table. */
 reset(1,BIT(14)|BIT(20));
 const struct ccci_scp_pin *ready=NULL;
 for(unsigned i=0;i<layout.rx_count;i++)if(layout.rx[i].channel==9)ready=&layout.rx[i];
 assert(ready && ready->mbox==1 && ready->offset==40 && ready->irq==20 && ready->words==1);
 for(unsigned failure=1;failure<=5;failure++) { /* pending, copy x2, post, ack */
  reset(1,BIT(14)|BIT(20));fail_at=failure;
  assert(ccci_scp_rx_step(&receiver,&result)==-EIO && !delivers);
  assert(ack_calls==(failure==5));assert(result.ack_attempted==(failure==5));
  assert(!result.acknowledged);sticky();
 }
 reset(1,BIT(14)|BIT(0)); /* AP TX bit is never an RX acknowledgement. */
 assert(ccci_scp_rx_step(&receiver,&result)==-EOPNOTSUPP);
 assert(result.unexpected==BIT(0) && !reads && !ack_calls && !post_calls);sticky();
 reset(1,BIT(14)|BIT(20));receiver.supported_mask=BIT(20);
 assert(ccci_scp_rx_step(&receiver,&result)==-EOPNOTSUPP && result.unexpected==BIT(14));
 assert(!reads && !ack_calls);sticky();
 reset(1,0);ccci_scp_rx_invalidate(&receiver);sticky();ccci_scp_rx_invalidate(NULL);
 /* Pending that arrives after sampling stays for the next transaction. */
 reset(1,BIT(20));assert(!ccci_scp_rx_step(&receiver,&result));
 stage=0;pending_mask=BIT(14);copied_mask=0;for(unsigned i=0;i<256;i++)wire[i]=i;
 assert(!ccci_scp_rx_step(&receiver,&result) && result.acknowledged==BIT(14));
 /* Synthetic last pin, including unsigned bit31 and maximal 64-word span. */
 for(unsigned words=1;words<=64;words=words==1?64:65) {
  memset(&layout,0,sizeof(layout));layout.rx_count=1;
  layout.rx[0]=(struct ccci_scp_pin){.channel=9,.mbox=0,.offset=words==1?62:0,.irq=words==1?31:0,.words=words};
  u32 mask=words==1?BIT(31):BIT(0);
  assert(!ccci_scp_rx_init(&receiver,&layout,0,mask,17,&ops,wire));
  mailbox=0;stage=reads=delivers=ack_calls=post_calls=operations=fail_at=0;
  copied_mask=0;pending_mask=mask;for(unsigned i=0;i<256;i++)wire[i]=i;
  assert(!ccci_scp_rx_step(&receiver,&result) && result.delivered==mask);
 }
 reset(1,0);
 struct ccci_scp_pin saved=layout.rx[2];
 for(unsigned bad=0;bad<6;bad++) {
  layout.rx[2]=saved;
  switch(bad){case 0:layout.rx[2].words=0;break;case 1:layout.rx[2].offset=63;break;
  case 2:layout.rx[2].irq=32;break;case 3:layout.rx[2].channel=64;break;
  case 4:layout.rx[2].words=64;break;case 5:layout.rx[3]=layout.rx[2];break;}
  assert(ccci_scp_rx_init(&receiver,&layout,1,BIT(14),17,&ops,wire)<0 && receiver.fault);
 }
 reset(1,0);struct ccci_scp_rx_ops bad_ops=ops;bad_ops.post_capture=NULL;
 assert(ccci_scp_rx_init(&receiver,&layout,1,BIT(14),17,&bad_ops,wire)==-EINVAL);
 assert(ccci_scp_rx_init(&receiver,&layout,1,BIT(14),0,&ops,wire)==-EINVAL);
 assert(ccci_scp_rx_init(&receiver,&layout,1,BIT(0),17,&ops,wire)==-EINVAL);
 assert(ccci_scp_rx_init(NULL,&layout,1,BIT(14),17,&ops,wire)==-EINVAL);
 assert(ccci_scp_rx_step(NULL,&result)==-ESHUTDOWN);
 assert(ccci_scp_rx_step(&receiver,NULL)==-EINVAL);
 reset(1,0);ready=&layout.rx[4];assert(ready->channel==9);
 u8 payload[6];put_unaligned_le32(0x180000,payload+1);
 assert(!ccci_scp_decode_ready(ready,payload+1,4,0x180000));
 for(unsigned n=0;n<6;n++)if(n!=4)assert(ccci_scp_decode_ready(ready,payload+1,n,0x180000)==-EMSGSIZE);
 assert(ccci_scp_decode_ready(ready,NULL,4,0x180000)==-EMSGSIZE);
 assert(ccci_scp_decode_ready(ready,payload+1,4,0x170000)==-EPROTO);
 assert(ccci_scp_decode_ready(ready,payload+1,4,0)==-EINVAL);
 assert(ccci_scp_decode_ready(NULL,payload+1,4,0x180000)==-EPROTONOSUPPORT);
 struct ccci_scp_pin wrong=*ready;wrong.response=1;
 assert(ccci_scp_decode_ready(&wrong,payload+1,4,0x180000)==-EPROTONOSUPPORT);
 /* Real firmware emits READY1; both channel IDs use the same size contract. */
 wrong=*ready;wrong.channel=22;
 assert(!ccci_scp_decode_ready(&wrong,payload+1,4,0x180000));
 assert(ccci_scp_decode_ready(&wrong,payload+1,4,0x170000)==-EPROTO);
 wrong.channel=21;
 assert(ccci_scp_decode_ready(&wrong,payload+1,4,0x180000)==-EPROTONOSUPPORT);
 puts("PASS: full-board randomized RX, exact copy/post/ack/delivery, overwrite at ack, all operation failures, unknown/TX/unregistered bits, sticky invalidation, bit31/full mailbox, READY0/READY1 payload");
}
'''.replace('@TX@', ','.join(map(str, tx))).replace('@RX@', ','.join(map(str, rx)))
code = preamble + '\n'.join(source(n) for n in (
    'ccci-scp-protocol.h', 'ccci-scp-rx.h', 'ccci-scp-protocol.c', 'ccci-scp-rx.c')) + harness
with tempfile.TemporaryDirectory(prefix='op6893-rx-') as directory:
    p = Path(directory)
    (p / 'test.c').write_text(code)
    subprocess.run(['cc', '-Wall', '-Wextra', '-Werror', '-Wno-misleading-indentation', '-Wno-sign-compare',
                    '-fsanitize=address,undefined', '-fno-sanitize-recover=all',
                    '-no-pie', str(p / 'test.c'), '-o', str(p / 'test')], check=True)
    subprocess.run([str(p / 'test')], check=True)
