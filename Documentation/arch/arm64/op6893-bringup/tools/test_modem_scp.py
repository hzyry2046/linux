#!/usr/bin/env python3
# SPDX-License-Identifier: GPL-2.0-only
"""Exercise the actual SCP layout/codec C with sanitizers, without device I/O.

Optional vendor SCP RV directories compile their real mbox_setup_pin_table()
functions as independent layout oracles. An optional saved DTB supplies only
mailbox tables, not firmware data. The default fixture is the audited DT table.
"""
import argparse
import json
from pathlib import Path
import struct
import subprocess
import tempfile

KERNEL = Path(__file__).resolve().parents[5]


def audited_fixture():
    fixture = Path(__file__).with_name('fixtures') / 'scp-mailbox.json'
    node = json.loads(fixture.read_text())
    return tuple([int(x, 0) for x in node[name]] for name in
                 ('send_table', 'recv_table', 'mbox_count'))


def dtb_fixture(path):
    import libfdt
    fdt = libfdt.Fdt(path.read_bytes())
    node = fdt.path_offset('/scp@10700000')

    def cells(old, new):
        present = []
        for name in (old, new):
            try:
                present.append(bytes(fdt.getprop(node, name)))
            except libfdt.FdtException as exc:
                assert exc.err == -libfdt.NOTFOUND
        assert present and all(p == present[0] for p in present)
        assert len(present[0]) % 4 == 0
        return list(struct.unpack('>' + 'I' * (len(present[0]) // 4), present[0]))

    return tuple(cells(old, new) for old, new in
                 [('send_table', 'send-table'), ('recv_table', 'recv-table'),
                  ('mbox_count', 'mbox-count')])


def vendor_oracle(path, index):
    source = (path / 'scp_wrapper_ipi.c').read_text()
    start = source.index('void mbox_setup_pin_table(unsigned int mbox)')
    body = source[start:source.index('\n}', start) + 2]
    return (f'#define mbox_setup_pin_table vendor_{index}\n' + body +
            '\n#undef mbox_setup_pin_table\n')


HARNESS = r'''
#include <assert.h>
#include <stdint.h>
#include <stdio.h>
#include <stdlib.h>
#include <string.h>
#include "ccci-scp-protocol.h"
#define ARRAY_SIZE(a) (sizeof(a) / sizeof((a)[0]))
#define DIV_ROUND_UP(a,b) (((a)+(b)-1)/(b))
#define pr_notice(...) ((void)0)
#define WARN_ON(x) assert(!(x))
struct vendor_pin { u32 chan_id, mbox, msg_size, offset, pin_index; };
static struct vendor_pin scp_mbox_pin_send[64], scp_mbox_pin_recv[64];
static struct { int send_count, recv_count; } scp_mboxdev;
static struct { int is64d; } scp_mbox_info[5];
@ORACLES@
static void compare_vendor(struct ccci_scp_layout *l) {
 @COMPARE@
}
static const u32 board_tx[] = {@TX@};
static const u32 board_rx[] = {@RX@};
static void zeroed(const void *p, size_t n) {
 const unsigned char *b=p;
 for (size_t i=0;i<n;i++) assert(!b[i]);
}
static void expect_bad(const u32 *tx, size_t nt, const u32 *rx, size_t nr, u32 boxes) {
 struct ccci_scp_layout l;
 memset(&l,0xa5,sizeof(l));
 assert(ccci_scp_build_layout(tx,nt,rx,nr,boxes,&l)<0); zeroed(&l,sizeof(l));
}
static uint32_t seed=0xc0316893;
static u32 random32(void) { seed^=seed<<13; seed^=seed>>17; seed^=seed<<5; return seed; }
int main(void) {
 struct ccci_scp_layout l;
 const struct ccci_scp_pin *tx,*rx;
 assert(!ccci_scp_build_layout(board_tx,ARRAY_SIZE(board_tx),board_rx,
                              ARRAY_SIZE(board_rx),5,&l));
 assert(l.tx_count==14 && l.rx_count==17);
 const u8 expected_used[]={38,64,64,36,64};
 assert(!memcmp(l.used_words,expected_used,5));
 assert(!ccci_scp_apccci_pins(&l,&tx,&rx));
 assert(tx->channel==3 && tx->mbox==1 && tx->words==2 && tx->offset==0 && tx->irq==0);
 assert(rx->channel==7 && rx->mbox==1 && rx->words==2 && rx->offset==28 && rx->irq==14);
 compare_vendor(&l);
 puts("PASS: saved board: 14 TX / 17 RX, shared 64-bit layout, APCCCI TX(1,0,0) RX(1,28,14)");
 u32 a[195]={3,0,2},b[260]={7,0,2,0};
 assert(!ccci_scp_build_layout(a,3,b,4,1,&l));
 assert(!ccci_scp_apccci_pins(&l,&tx,&rx));
 expect_bad(NULL,3,b,4,1); expect_bad(a,3,NULL,4,1);
 expect_bad(a,0,b,4,1); expect_bad(a,3,b,0,1);
 expect_bad(a,4,b,4,1); expect_bad(a,3,b,5,1); expect_bad(a,3,b,7,1);
 expect_bad(a,195,b,4,1); expect_bad(a,3,b,260,1);
 expect_bad(a,SIZE_MAX,b,4,1); expect_bad(a,3,b,SIZE_MAX,1);
 expect_bad(a,3,b,4,0); expect_bad(a,3,b,4,6);
 assert(ccci_scp_build_layout(a,3,b,4,1,NULL)<0);
 for (unsigned dir=0;dir<2;dir++) {
  u32 *p=dir?b:a; size_t n=dir?4:3;
  for (unsigned field=0;field<n;field++) {
   u32 old=p[field];
   p[field]=UINT32_MAX; expect_bad(a,3,b,4,1); p[field]=old;
  }
  u32 old=p[2];p[2]=0;expect_bad(a,3,b,4,1);p[2]=65;expect_bad(a,3,b,4,1);p[2]=old;
 }
 for (unsigned dir=0;dir<2;dir++) {
  u32 *p=dir?b:a; unsigned stride=dir?4:3;
  memcpy(p+stride,p,stride*4);
  expect_bad(a,dir?3:6,b,dir?8:4,1);
  p[stride]=8; p[1]=1; p[stride+1]=0;
  expect_bad(a,dir?3:6,b,dir?8:4,2);
  p[1]=0;
 }
 b[3]=2;expect_bad(a,3,b,4,1);b[3]=0;
 a[2]=63;expect_bad(a,3,b,4,1);a[2]=62;
 assert(!ccci_scp_build_layout(a,3,b,4,1,&l));assert(l.rx[0].irq==31 && l.rx[0].offset==62);
 a[2]=2;
 /* Duplicate IDs across directions are legitimate response channels. */
 b[0]=3;assert(!ccci_scp_build_layout(a,3,b,4,1,&l));
 tx=rx=(void *)1; assert(ccci_scp_apccci_pins(&l,&tx,&rx)<0 && !tx && !rx);b[0]=7;
 a[2]=4;assert(!ccci_scp_build_layout(a,3,b,4,1,&l));
 assert(!ccci_scp_apccci_pins(&l,&tx,&rx));
 for (u32 words=1;words<=5;words++) {
  a[2]=words;assert(!ccci_scp_build_layout(a,3,b,4,1,&l));
  int ret=ccci_scp_apccci_pins(&l,&tx,&rx);
  assert((words==2 || words==4)?ret==0:ret<0);
 }
 a[2]=2;b[3]=1;assert(!ccci_scp_build_layout(a,3,b,4,1,&l));
 assert(ccci_scp_apccci_pins(&l,&tx,&rx)<0 && !tx && !rx);b[3]=0;
 b[2]=4;assert(!ccci_scp_build_layout(a,3,b,4,1,&l));assert(ccci_scp_apccci_pins(&l,&tx,&rx)<0);b[2]=2;
 l.tx_count=65;assert(ccci_scp_apccci_pins(&l,&tx,&rx)<0);
 assert(ccci_scp_apccci_pins(NULL,&tx,&rx)<0);
 assert(ccci_scp_apccci_pins(&l,NULL,&rx)<0);
 assert(ccci_scp_apccci_pins(&l,&tx,NULL)<0);
 puts("PASS: table lengths, limits, duplicates, ordering, overflow, IRQ31 boundary, APCCCI ABI rejection");
 /* Random, valid full layouts; compare real vendor algorithms when supplied. */
 for (unsigned trial=0;trial<10000;trial++) {
  u32 st[192],rt[256],nt=0,nr=0;
  for (u32 box=0;box<5;box++) {
   u32 budget=64,ns=1+random32()%6,nrecv=1+random32()%6;
   for (u32 j=0;j<ns && budget>2;j++) {
    u32 limit=budget-2<9?budget-2:9,words=1+random32()%limit;
    u32 channel=nt/3;
    st[nt++]=channel;st[nt++]=box;st[nt++]=words;
    budget-=(words+1)&~1U;
   }
   for (u32 j=0;j<nrecv && budget;j++) {
    u32 limit=budget<9?budget:9,words=1+random32()%limit,channel=nr/4;
    rt[nr++]=channel;rt[nr++]=box;rt[nr++]=words;rt[nr++]=random32()%2;
    budget-=(words+1)&~1U;
   }
  }
  assert(!ccci_scp_build_layout(st,nt,rt,nr,5,&l));compare_vendor(&l);
 }
 /* Unstructured bounded input exercises rejection and output clearing. */
 for (unsigned trial=0;trial<20000;trial++) {
  for (unsigned i=0;i<195;i++) a[i]=random32()%80;
  for (unsigned i=0;i<260;i++) b[i]=random32()%80;
  size_t nt=random32()%196,nr=random32()%261;
  if (ccci_scp_build_layout(a,nt,b,nr,random32()%8,&l)) zeroed(&l,sizeof(l));
 }
 puts("PASS: 10000 valid randomized layouts and 20000 malformed inputs");
 u32 addr=0xffffffff;
 assert(!ccci_scp_shm_u32(0x8e000000,0x20000,&addr)&&addr==0x8e000000);
 assert(!ccci_scp_shm_u32(0xfffffffc,4,&addr)&&addr==0xfffffffc);
 const u64 bad[][2]={{0,4},{4,0},{5,4},{4,5},{0x100000000ULL,4},
  {0xfffffffc,8},{UINT64_MAX-3,4},{4,UINT64_MAX-3}};
 for (unsigned i=0;i<ARRAY_SIZE(bad);i++) {addr=~0U;assert(ccci_scp_shm_u32(bad[i][0],bad[i][1],&addr)<0 && !addr);}
 assert(ccci_scp_shm_u32(4,4,NULL)<0);
 unsigned char buf[32],before[32];
 const unsigned char expected[]={0,0,2,0,0,0,0,0x8e,0xba,0xdc,0xcd,0xab,0xdd,0xcc,0xbb,0xaa};
 for (u32 words=2;words<=4;words+=2) {
  memset(buf,0x5a,sizeof(buf));
  assert(ccci_scp_encode(buf+1,16,words,2,0x8e000000)==(int)words*4);
  assert(!memcmp(buf+1,expected,words*4));assert(buf[0]==0x5a && buf[words*4+1]==0x5a);
 }
 for (size_t capacity=0;capacity<16;capacity++) {
  memset(buf,0x5a,sizeof(buf));memcpy(before,buf,sizeof(buf));
  assert(ccci_scp_encode(buf+1,capacity,4,2,0x8e000000)<0);
  assert(!memcmp(buf,before,sizeof(buf)));
 }
 for (unsigned word=0;word<70;word++) if (word!=2 && word!=4) {
  assert(ccci_scp_encode(buf,32,word,1,0)<0);assert(!memcmp(buf,before,sizeof(buf)));
 }
 for (unsigned op=0;op<10;op++) if(op!=1 && op!=2) assert(ccci_scp_encode(buf,32,2,op,0)<0);
 assert(ccci_scp_encode(NULL,32,2,1,0)<0);
 assert(ccci_scp_encode(buf,32,2,1,4)<0);
 assert(ccci_scp_encode(buf,32,2,2,0)<0);
 assert(ccci_scp_encode(buf,32,2,2,5)<0);
 for (u32 value=0;value<=3;value++) {
  assert(ccci_scp_encode(buf+1,8,2,1,value)==8);
  const u8 state_expected[]={0,0,1,0,(u8)value,0,0,0};
  assert(!memcmp(buf+1,state_expected,8));
 }
 memset(buf,0,sizeof(buf));u32 state;
 for (u32 value=1;value<=3;value++) {
  buf[5]=value;assert(!ccci_scp_decode_state(buf+1,8,&state)&&state==value);
 }
 for (size_t n=0;n<=32;n++) if(n!=8) {state=99;assert(ccci_scp_decode_state(buf,n,&state)<0&&!state);}
 for (unsigned byte=0;byte<4;byte++) {
  buf[byte+1]=1;assert(ccci_scp_decode_state(buf+1,8,&state)<0&&!state);buf[byte+1]=0;
 }
 buf[5]=0;assert(ccci_scp_decode_state(buf+1,8,&state)<0&&!state);
 buf[5]=4;assert(ccci_scp_decode_state(buf+1,8,&state)<0&&!state);
 assert(ccci_scp_decode_state(NULL,8,&state)<0&&!state);
 assert(ccci_scp_decode_state(buf,8,NULL)<0);
 puts("PASS: 32-bit SHM span bounds, LE 8/16-byte TX, magic, unaligned buffers, exact RX length/id/op/state");
 return 0;
}
'''


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--lk-dtb', type=Path)
    parser.add_argument('--vendor-scp', type=Path, action='append', default=[])
    args = parser.parse_args()
    fixture = audited_fixture()
    if args.lk_dtb:
        assert dtb_fixture(args.lk_dtb) == fixture
        print('PASS: saved DTB matches audited mailbox tables', flush=True)
    tx, rx, boxes = fixture
    assert boxes == [5]
    oracles, compare = [], []
    for i, path in enumerate(args.vendor_scp):
        oracles.append(vendor_oracle(path, i))
        compare.append(f'''
 scp_mboxdev.send_count=l->tx_count;scp_mboxdev.recv_count=l->rx_count;
 memset(scp_mbox_pin_send,0,sizeof(scp_mbox_pin_send));
 memset(scp_mbox_pin_recv,0,sizeof(scp_mbox_pin_recv));
 for (u32 j=0;j<l->tx_count;j++) scp_mbox_pin_send[j]=(struct vendor_pin){{
  .chan_id=l->tx[j].channel,.mbox=l->tx[j].mbox,.msg_size=l->tx[j].words}};
 for (u32 j=0;j<l->rx_count;j++) scp_mbox_pin_recv[j]=(struct vendor_pin){{
  .chan_id=l->rx[j].channel,.mbox=l->rx[j].mbox,.msg_size=l->rx[j].words}};
 for (u32 j=0;j<5;j++) {{scp_mbox_info[j].is64d=1;vendor_{i}(j);}}
 for (u32 j=0;j<l->tx_count;j++) {{assert(scp_mbox_pin_send[j].offset==l->tx[j].offset);
  assert(scp_mbox_pin_send[j].pin_index==l->tx[j].irq);}}
 for (u32 j=0;j<l->rx_count;j++) {{assert(scp_mbox_pin_recv[j].offset==l->rx[j].offset);
  assert(scp_mbox_pin_recv[j].pin_index==l->rx[j].irq);}}
''')
    if not oracles:
        # Keep unused stand-ins out of the default build.
        start = HARNESS.index('struct vendor_pin')
        end = HARNESS.index('@ORACLES@')
        harness = HARNESS[:start] + HARNESS[end:]
    else:
        harness = HARNESS
    harness = harness.replace('@ORACLES@', '\n'.join(oracles))
    harness = harness.replace('@COMPARE@', '\n'.join(compare) if compare else '(void)l;')
    harness = harness.replace('@TX@', ','.join(map(str, tx))).replace('@RX@', ','.join(map(str, rx)))
    with tempfile.TemporaryDirectory(prefix='op6893-scp-test-') as directory:
        tmp = Path(directory)
        inc = tmp / 'linux'
        inc.mkdir()
        (inc / 'types.h').write_text('''#pragma once
#include <stdint.h>
#include <stddef.h>
#include <stdbool.h>
typedef uint64_t u64; typedef uint32_t u32; typedef uint16_t u16; typedef uint8_t u8;
''')
        (inc / 'errno.h').write_text('#include <asm-generic/errno.h>\n')
        (inc / 'limits.h').write_text('#include <stdint.h>\n#define U32_MAX UINT32_MAX\n')
        (inc / 'string.h').write_text('#include <string.h>\n')
        (inc / 'unaligned.h').write_text('''#include <linux/types.h>
static inline u16 get_unaligned_le16(const void *p) {
 const u8 *b=p; return (u16)b[0] | (u16)b[1]<<8;
}
static inline u32 get_unaligned_le32(const void *p) {
 const u8 *b=p; return (u32)b[0]|(u32)b[1]<<8|(u32)b[2]<<16|(u32)b[3]<<24;
}
static inline void put_unaligned_le16(u16 v,void *p) {u8 *b=p;b[0]=v;b[1]=v>>8;}
static inline void put_unaligned_le32(u32 v,void *p) {
 u8 *b=p;for(unsigned i=0;i<4;i++)b[i]=v>>(i*8);
}
''')
        (tmp / 'test.c').write_text(harness)
        source = KERNEL / 'drivers/misc/mediatek/ccci'
        subprocess.run(['cc', '-O1', '-g', '-Wall', '-Wextra', '-Werror',
                        '-Wno-sign-compare', '-fsanitize=address,undefined',
                        '-fno-sanitize-recover=all', '-no-pie', '-I' + str(tmp),
                        '-I' + str(source), str(source / 'ccci-scp-protocol.c'),
                        str(tmp / 'test.c'), '-o', str(tmp / 'test')], check=True)
        subprocess.run([str(tmp / 'test')], check=True)
    if args.vendor_scp:
        print(f'PASS: {len(args.vendor_scp)} actual vendor layout implementations matched')


if __name__ == '__main__':
    main()
