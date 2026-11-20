#!/usr/bin/env python3
# SPDX-License-Identifier: GPL-2.0-only
"""Compile real 6297 ring/reset C with sanitizer-backed I/O and peer fixtures."""
from pathlib import Path
import argparse
import re
import subprocess
import tempfile

K = Path(__file__).resolve().parents[5]
HARNESS = r'''
#include <assert.h>
#include <stdio.h>
#include <stdlib.h>
#include <string.h>
#include <linux/errno.h>
#include <linux/unaligned.h>
#include "ccci-ccif-ring.h"
#include "ccci-ccif-hw.h"
#include "ccci-smem.h"
static u8 memory[2048];
static unsigned calls,fail,publishes,acquires;
static int event(void){return ++calls==fail?-EACCES:0;}
static void bounds(u32 o,u32 s){assert(o<=sizeof(memory) && s<=sizeof(memory)-o);}
static int rd(void *c,u32 o,u32 *v){(void)c;bounds(o,4);int r=event();if(!r)*v=get_unaligned_le32(memory+o);return r;}
static int wr(void *c,u32 o,u32 v){(void)c;bounds(o,4);int r=event();if(!r)put_unaligned_le32(v,memory+o);return r;}
static int from(void *c,u32 o,void *p,u32 s){(void)c;bounds(o,s);int r=event();if(!r)memcpy(p,memory+o,s);return r;}
static int to(void *c,u32 o,const void *p,u32 s){(void)c;bounds(o,s);int r=event();if(!r)memcpy(memory+o,p,s);return r;}
static int zero(void *c,u32 o,u32 s){(void)c;bounds(o,s);int r=event();if(!r)memset(memory+o,0,s);return r;}
static void fence(void *c,bool publish){(void)c;if(publish)publishes++;else acquires++;}
static const struct ccci_ccif_ring_ops ops={rd,wr,from,to,zero,fence,NULL};
static struct ccci_ccif_slot slot={16,256,256,552};
static void clear(void){calls=fail=publishes=acquires=0;}
static void setup(struct ccci_ccif_ring *r){
 memset(memory,0x5a,sizeof(memory));clear();
 assert(!ccci_ccif_ring_init(r,&ops,NULL,&slot,sizeof(memory)));
 assert(!ccci_ccif_ring_format(r));assert(!ccci_ccif_ring_verify_empty(r));clear();
}
/* Independent peer producer: intentionally does not call the driver's TX. */
static void peer_bytes(u32 pos,const void *p,u32 n){
 const u8 *b=p;for(u32 i=0;i<n;i++)memory[slot.offset+32+(pos+i)%slot.rx]=b[i];
}
static void peer_packet(u32 start,const u8 *p,u32 n){
 u8 h[8],f[8];u32 span=((n+7)&~7U)+16;
 put_unaligned_le32(0xaabbaabb,h);put_unaligned_le32(n,h+4);
 put_unaligned_le32(0xccddeeff,f);put_unaligned_le32(0xccddeeff,f+4);
 peer_bytes(start,h,8);peer_bytes((start+8)%slot.rx,p,n);
 peer_bytes((start+span-8)%slot.rx,f,8);
 put_unaligned_le32(start,memory+slot.offset+8);
 put_unaligned_le32((start+span)%slot.rx,memory+slot.offset+12);
}
static void geometry(void){
 struct ccci_smem_layout sm={0};struct ccci_ccif_layout p;
 sm.users[19]=(struct ccci_smem_region){.present=true,.size=721*1024};
 sm.users[20]=(struct ccci_smem_region){.present=true,.size=121*1024};
 sm.users[13]=(struct ccci_smem_region){.present=true,.md=0x40110800,.size=14*1024};
 assert(!ccci_ccif_plan(&sm,&p));
 assert(p.used[0]==0xb4280 && p.used[1]==0x1e280);
 assert(p.debug_md==0x40110800 && p.debug_size==14336);
 assert(p.slots[0][1].offset==208*1024+40 && p.slots[0][7].span==40);
 assert(p.slots[0][8].offset==704*1024+8*40);
 assert(p.slots[1][15].offset==120*1024+15*40);
 for(unsigned n=0;n<2;n++){
  u32 id=n?20:19,old=sm.users[id].size;sm.users[id].size=p.used[n]-1;
  memset(&p,0x55,sizeof(p));assert(ccci_ccif_plan(&sm,&p)<0);
  for(unsigned i=0;i<sizeof(p);i++)assert(!((u8 *)&p)[i]);sm.users[id].size=old;
  assert(!ccci_ccif_plan(&sm,&p));
 }
 sm.users[13].cached=true;assert(ccci_ccif_plan(&sm,&p)<0);
 assert(ccci_ccif_plan(NULL,&p)<0 && ccci_ccif_plan(&sm,NULL)<0);
}
static void rings(void){
 struct ccci_ccif_ring r;u8 payload[240],out[240];u32 size;
 for(u32 i=0;i<sizeof(payload);i++)payload[i]=i^0xa5;
 setup(&r);
 assert(get_unaligned_le32(memory+16)==0xee0000ee);
 assert(get_unaligned_le32(memory+16+16)==256);
 assert(get_unaligned_le32(memory+16+28)==256);
 assert(get_unaligned_le32(memory+16+544)==0xff0000ff);
 for(unsigned i=0;i<16;i++)assert(memory[i]==0x5a);
 for(unsigned i=568;i<sizeof(memory);i++)assert(memory[i]==0x5a);
 assert(ccci_ccif_ring_receive(&r,out,sizeof(out),&size)==-ENODATA && !size);
 /* All legal starting offsets and byte lengths: headers/payload/footer wrap. */
 for(u32 start=0;start<256;start+=8)for(u32 n=16;n<=232;n++){
  setup(&r);peer_packet(start,payload,n);
  assert(!ccci_ccif_ring_receive(&r,out,sizeof(out),&size));
  assert(size==n && !memcmp(payload,out,n) && acquires && publishes);
  assert(get_unaligned_le32(memory+24)==get_unaligned_le32(memory+28));
  assert(ccci_ccif_ring_receive(&r,out,sizeof(out),&size)==-ENODATA);
  setup(&r);put_unaligned_le32(start,memory+36);put_unaligned_le32(start,memory+40);
  assert(!ccci_ccif_ring_transmit(&r,payload,n));
  u32 base=16+32+256;
  assert(get_unaligned_le32(memory+base+start)==0xaabbaabb);
  for(u32 i=0;i<n;i++)assert(memory[base+(start+8+i)%256]==payload[i]);
  for(u32 i=n;i<((n+7)&~7U);i++)assert(!memory[base+(start+8+i)%256]);
  u32 fpos=(start+8+((n+7)&~7U))%256;
  assert(get_unaligned_le32(memory+base+fpos)==0xccddeeff);
  assert(get_unaligned_le32(memory+base+(fpos+4)%256)==0xccddeeff);
  assert(get_unaligned_le32(memory+40)==(start+16+((n+7)&~7U))%256);
  for(unsigned i=0;i<16;i++)assert(memory[i]==0x5a);
  for(unsigned i=568;i<sizeof(memory);i++)assert(memory[i]==0x5a);
 }
 setup(&r);assert(ccci_ccif_ring_transmit(&r,payload,233)==-ENOSPC);
 assert(!get_unaligned_le32(memory+40));
 /* A failed read/copy/footer never advances AP's consumer pointer. */
 setup(&r);peer_packet(248,payload,25);assert(!ccci_ccif_ring_receive(&r,out,240,&size));
 unsigned steps=calls;
 for(unsigned n=1;n<=steps;n++){
  setup(&r);peer_packet(248,payload,25);fail=n;
  assert(ccci_ccif_ring_receive(&r,out,240,&size)==-EACCES && calls==n && !size);
  assert(get_unaligned_le32(memory+24)==248);
 }
 setup(&r);put_unaligned_le32(248,memory+36);put_unaligned_le32(248,memory+40);
 assert(!ccci_ccif_ring_transmit(&r,payload,25));steps=calls;
 for(unsigned n=1;n<=steps;n++){
  setup(&r);put_unaligned_le32(248,memory+36);put_unaligned_le32(248,memory+40);fail=n;
  assert(ccci_ccif_ring_transmit(&r,payload,25)==-EACCES && calls==n);
  assert(get_unaligned_le32(memory+40)==248);
 }
 setup(&r);peer_packet(0,payload,24);
 assert(ccci_ccif_ring_receive(&r,out,23,&size)==-ENOSPC && !size && !get_unaligned_le32(memory+24));
 memory[48]^=1;assert(ccci_ccif_ring_receive(&r,out,240,&size)==-EBADMSG);
 setup(&r);peer_packet(0,payload,24);memory[80]^=1;
 assert(ccci_ccif_ring_receive(&r,out,240,&size)==-EBADMSG && !get_unaligned_le32(memory+24));
 setup(&r);peer_packet(0,payload,24);put_unaligned_le32(0xffffffff,memory+52);
 assert(ccci_ccif_ring_receive(&r,out,240,&size)==-EBADMSG);
 setup(&r);peer_packet(0,payload,24);put_unaligned_le32(32,memory+28);
 assert(ccci_ccif_ring_receive(&r,out,240,&size)==-EAGAIN);
 setup(&r);put_unaligned_le32(257,memory+24);
 assert(ccci_ccif_ring_receive(&r,out,240,&size)==-EBADMSG);
 setup(&r);put_unaligned_le32(1,memory+40);
 assert(ccci_ccif_ring_transmit(&r,payload,16)==-EBADMSG);
 setup(&r);put_unaligned_le32(40,memory+36);put_unaligned_le32(0,memory+40);
 assert(ccci_ccif_ring_transmit(&r,payload,24)==-ENOSPC && !get_unaligned_le32(memory+40));
 struct ccci_ccif_slot empty={0,0,0,40};
 assert(!ccci_ccif_ring_init(&r,&ops,NULL,&empty,sizeof(memory)));
 assert(!ccci_ccif_ring_format(&r) && !ccci_ccif_ring_verify_empty(&r));
 assert(ccci_ccif_ring_receive(&r,out,240,&size)==-EOPNOTSUPP);
 struct ccci_ccif_slot bad=slot;bad.span--;assert(ccci_ccif_ring_init(&r,&ops,NULL,&bad,2048)<0);
 bad=slot;bad.offset=2040;assert(ccci_ccif_ring_init(&r,&ops,NULL,&bad,2048)<0);
 /* Count only format callbacks, then inject each without retrying hardware. */
 setup(&r);clear();assert(!ccci_ccif_ring_format(&r));steps=calls;
 for(unsigned n=1;n<=steps;n++){
  setup(&r);clear();fail=n;assert(ccci_ccif_ring_format(&r)==-EACCES && calls==n);
 }
}
static u32 hw[3][0x1000/4];
static unsigned hw_calls,hw_fail;
static bool corrupt;
static int hwrite(void *c,u32 b,u32 o,u32 v){
 (void)c;assert(b<3 && o<0x1000 && !(o&3));
 if(++hw_calls==hw_fail)return -EACCES;
 if(!b){assert((o==0x150 || o==0x154) && v==256);}
 else {assert(o>=0x100 && o<0x300);hw[1][o/4]=hw[2][o/4]=v;}
 return 0;
}
static int hread(void *c,u32 b,u32 o,u32 *v){
 (void)c;assert(b>=1 && b<=2 && o<0x1000);
 if(++hw_calls==hw_fail)return -EACCES;*v=hw[b][o/4];
 if(corrupt && b==2 && o==0x100)*v=1;return 0;
}
static void hfence(void *c){(void)c;assert(hw_calls==261);}
static const struct ccci_ccif_hw_ops hops={hwrite,hread,hfence};
static void hw_setup(void){
 memset(hw,0xa5,sizeof(hw));hw_calls=hw_fail=0;corrupt=false;
 hw[1][1]=hw[2][1]=hw[1][4]=hw[2][4]=0;
}
static void hardware(void){
 struct ccci_ccif_layout layout={.debug_md=0x40110800,.debug_size=14336};
 hw_setup();assert(!ccci_ccif_hw_reset(&hops,NULL,&layout));
 assert(hw_calls==521 && hw[1][0x2f4/4]==0x7274626e);
 assert(hw[1][0x2f8/4]==0x40110800 && hw[1][0x2fc/4]==14336);
 assert(hw[1][0xff/4]==0xa5a5a5a5 && hw[2][0x300/4]==0xa5a5a5a5);
 for(unsigned n=1;n<=521;n++){
  hw_setup();hw_fail=n;assert(ccci_ccif_hw_reset(&hops,NULL,&layout)==-EACCES);
  assert(hw_calls==n);
 }
 hw_setup();corrupt=true;assert(ccci_ccif_hw_reset(&hops,NULL,&layout)==-EIO);
 hw_setup();hw[1][1]=1;assert(ccci_ccif_hw_reset(&hops,NULL,&layout)==-EBUSY);
 hw_setup();layout.debug_size=0;assert(ccci_ccif_hw_reset(&hops,NULL,&layout)==-EINVAL && !hw_calls);
}
int main(void){
 geometry();rings();hardware();
 puts("PASS: actual 6297 geometry and all byte-length/offset ring wraps, malformed");
 puts("      packets/metadata, publish-on-success, I/O failures, empty slots, SRAM");
 puts("      reset/readback bounds and 521 hardware failure positions; ASan/UBSan");
}
'''


OWNER = r'''
#include <assert.h>
#include <errno.h>
#include <stdbool.h>
#include <stdio.h>
#include <string.h>
#include "ccci-ccif-ring.h"
#include "ccci-ccif-hw.h"
#define __iomem
#include "ccci-ccif-rx.h"
struct mutex { bool held; };
static void mutex_lock(struct mutex *m){assert(!m->held);m->held=true;}
static void mutex_unlock(struct mutex *m){assert(m->held);m->held=false;}
#define READ_ONCE(x) (x)
struct regmap;
struct ccci_ccif_controller;
struct ccci_runtime_offer;
typedef void (*ccci_ccif_control_fault_fn)(void *context,int error);
int ccci_ccif_control_set_fault(struct ccci_ccif_controller *c,ccci_ccif_control_fault_fn fn,void *ctx){(void)c;(void)fn;(void)ctx;return -EOPNOTSUPP;}
static int control_error;
int ccci_ccif_control_error(struct ccci_ccif_controller *c){(void)c;return control_error;}
void ccci_ccif_control_quiesce(struct ccci_ccif_controller *c){(void)c;}
int ccci_ccif_control_rearm(struct ccci_ccif_controller *c,bool commit){(void)c;(void)commit;return control_error;}
int ccci_ccif_control_start(struct ccci_ccif_controller *c,const struct ccci_runtime_offer *o,ccci_ccif_consume_fn fn,void *ctx){(void)c;(void)o;(void)fn;(void)ctx;return -EOPNOTSUPP;}
static int rx_error;
int ccci_ccif_rx_rearm(struct ccci_ccif_rx *r,bool commit){(void)r;(void)commit;return rx_error;}
static unsigned rx_stops;
int ccci_ccif_rx_error(struct ccci_ccif_rx *rx){(void)rx;return rx_error;}
void ccci_ccif_rx_stop(struct ccci_ccif_rx *rx){(void)rx;rx_stops++;}
int ccci_ccif_rx_start(struct ccci_ccif_rx *rx,ccci_ccif_consume_fn fn,void *ctx){(void)rx;(void)fn;(void)ctx;return 0;}
#define IRQCHIP_STATE_MASKED 1
static unsigned calls,fail,mask_fail;
static bool masked=true;
static int irq_get_irqchip_state(int irq,int which,bool *v){
 assert((irq==11 || irq==12) && which==1);
 if(mask_fail)return -EACCES;*v=masked;return 0;
}
static int step(void){return ++calls==fail?-EACCES:0;}
int ccci_ccif_ring_format(struct ccci_ccif_ring *r){(void)r;return step();}
int ccci_ccif_ring_verify_empty(struct ccci_ccif_ring *r){(void)r;return step();}
static const struct ccci_ccif_hw_ops ccif_hw_ops={0};
int ccci_ccif_hw_reset(const struct ccci_ccif_hw_ops *o,void *c,
 const struct ccci_ccif_layout *l){(void)c;(void)l;assert(o==&ccif_hw_ops);return step();}
'''
OWNER_MAIN = r'''
static void setup(struct ccci_ccif *c){
 memset(c,0,sizeof(*c));c->irq[0]=11;c->irq[1]=12;c->step="reserved";
 calls=fail=mask_fail=rx_stops=0;rx_error=control_error=0;masked=true;
}
int main(void){
 struct ccci_ccif c;
 setup(&c);assert(!ccci_ccif_stop(&c) && !calls);
 masked=false;assert(ccci_ccif_prepare(&c)==-EBUSY && !c.attempted && !calls);
 masked=true;mask_fail=1;assert(ccci_ccif_prepare(&c)==-EACCES && !c.attempted);
 mask_fail=0;assert(!ccci_ccif_prepare(&c) && c.prepared && c.attempted && calls==65);
 assert(ccci_ccif_prepare(&c)==-EALREADY && calls==65);
 assert(!ccci_ccif_stop(&c) && !c.prepared && calls==66);
 assert(!ccci_ccif_stop(&c) && calls==66);
 assert(ccci_ccif_prepare(&c)==-EALREADY && calls==66);
 for(unsigned n=1;n<=65;n++){
  setup(&c);fail=n;assert(ccci_ccif_prepare(&c)==-EACCES);
  assert(c.error==-EACCES && c.attempted && !c.prepared && calls==n);
  assert(ccci_ccif_prepare(&c)==-EIO && ccci_ccif_stop(&c)==-EIO && calls==n);
 }
 setup(&c);assert(!ccci_ccif_prepare(&c));masked=false;
 assert(ccci_ccif_stop(&c)==-EBUSY && c.error==-EBUSY && c.prepared && calls==65);
 masked=true;assert(ccci_ccif_stop(&c)==-EIO && calls==65);
 setup(&c);assert(!ccci_ccif_prepare(&c));fail=66;
 assert(ccci_ccif_stop(&c)==-EACCES && c.prepared && calls==66);
 assert(ccci_ccif_stop(&c)==-EIO && calls==66);
 setup(&c);rx_error=-EIO;
 assert(ccci_ccif_prepare(&c)==-EIO && !ccci_ccif_stop(&c) && !calls);
 setup(&c);assert(ccci_ccif_receive_start(&c,NULL,NULL)==-EAGAIN);
 assert(!ccci_ccif_prepare(&c));rx_error=-EPROTO;
 assert(ccci_ccif_receive_start(&c,NULL,NULL)==-EIO);
 assert(!ccci_ccif_stop(&c) && rx_stops==1 && calls==66 && !c.prepared);
 setup(&c);assert(!ccci_ccif_prepare(&c));control_error=-ETIMEDOUT;
 assert(!ccci_ccif_stop(&c) && rx_stops==1 && calls==66 && !c.prepared);
 puts("PASS: extracted actual CCIF prepare/stop: IRQ mask gates, 65 failure positions,");
 puts("      one-shot preparation, RX fault containment and stop fault retention");
}
'''


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--vendor-root', action='append', type=Path, default=[])
    args = parser.parse_args()
    with tempfile.TemporaryDirectory(prefix='op6893-ccif-') as directory:
        root = Path(directory)
        inc = root / 'linux'
        inc.mkdir()
        files = {
            'types.h': '#pragma once\n#include <stdint.h>\n#include <stdbool.h>\n'
                       '#include <stddef.h>\ntypedef uint8_t u8; typedef uint16_t u16;'
                       'typedef uint32_t u32; typedef uint64_t u64;\n',
            'errno.h': '#include <asm-generic/errno.h>\n',
            'string.h': '#include <string.h>\n',
            'limits.h': '#include <stdint.h>\n#define U64_MAX UINT64_MAX\n',
            'bitops.h': '#define BIT(n) (1U<<(n))\n',
            'kernel.h': '#define ALIGN(n,a) (((n)+(a)-1)&~((a)-1))\n'
                        '#define min(a,b) ((a)<(b)?(a):(b))\n',
            'unaligned.h': '#pragma once\n#include <linux/types.h>\n'
                          'static inline u32 get_unaligned_le32(const void *p){'
                          'const u8 *b=p;return (u32)b[0]|(u32)b[1]<<8|'
                          '(u32)b[2]<<16|(u32)b[3]<<24;}\n'
                          'static inline u64 get_unaligned_le64(const void *p){'
                          'return get_unaligned_le32(p)|((u64)get_unaligned_le32((const u8 *)p+4)<<32); }\n'
                          'static inline void put_unaligned_le32(u32 v,void *p){'
                          'u8 *b=p;for(u32 i=0;i<4;i++)b[i]=v>>(8*i);}\n',
        }
        for name, content in files.items():
            (inc / name).write_text(content)
        source = K / 'drivers/misc/mediatek/ccci'
        (root / 'test.c').write_text(HARNESS)
        subprocess.run(['cc', '-O1', '-g', '-Wall', '-Wextra', '-Werror',
                        '-Wno-misleading-indentation', '-fsanitize=address,undefined',
                        '-fno-sanitize-recover=all', '-no-pie', '-I'+str(root),
                        '-I'+str(K/'include'), '-I'+str(source),
                        str(source/'ccci-ccif-ring.c'), str(source/'ccci-ccif-hw.c'),
                        str(root/'test.c'), '-o', str(root/'test')], check=True)
        subprocess.run([str(root/'test')], check=True)
        owner_code = (source/'ccci-ccif.c').read_text()
        structures = owner_code[owner_code.index('struct ccci_ccif_bank {'):
                                owner_code.index('static int ccif_bank_read(')]
        lifecycle = owner_code[owner_code.index('static bool ccci_ccif_faulted('):
                               owner_code.index('ssize_t ccci_ccif_status(')]
        gate = owner_code[owner_code.index('static void ccif_tx_gate('):
                          owner_code.index('void ccci_ccif_abort(')]
        (root/'owner.c').write_text(OWNER+structures+gate+lifecycle+OWNER_MAIN)
        subprocess.run(['cc', '-O1', '-g', '-Wall', '-Wextra', '-Werror',
                        '-Wno-misleading-indentation', '-fsanitize=address,undefined',
                        '-fno-sanitize-recover=all', '-no-pie', '-I'+str(root),
                        '-I'+str(source), str(root/'owner.c'),
                        '-o', str(root/'owner')], check=True)
        subprocess.run([str(root/'owner')], check=True)
        expected = [[80, 80, 40, 80, 20, 20, 64, 0, 8]+[0]*7,
                    [128, 40, 8, 40, 20, 20, 64, 0, 8]+[0]*7,
                    [12, 32, 8, 0, 0, 0, 8]+[0]*9,
                    [12, 32, 8, 0, 0, 0, 8]+[0]*9]
        names = ['rx_queue_buffer_size_up_95', 'tx_queue_buffer_size_up_95',
                 'rx_exp_buffer_size_up_95', 'tx_exp_buffer_size_up_95']
        for vendor in args.vendor_root:
            code = (vendor/'drivers/misc/mediatek/eccci/hif/ccci_hif_ccif.c').read_text()
            for name, want in zip(names, expected):
                body = re.search(r'\b'+name+r'\[QUEUE_NUM\]\s*=\s*\{([^}]+)', code)[1]
                numbers = [int(v) for v in re.findall(r'(\d+)\s*\*\s*1024', body)]
                assert numbers == want, (vendor, name, numbers)
            print(f'PASS: same-board vendor 6297 normal/exception tables: {vendor}')


if __name__ == '__main__':
    main()
