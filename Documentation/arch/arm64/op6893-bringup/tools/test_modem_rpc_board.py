#!/usr/bin/env python3
# SPDX-License-Identifier: GPL-2.0-only
"""Actual op6893 facts and RPC codecs with synthetic requests and ASan/UBSan.

No device, saved FDT, GPIO, ADC, modem, identity or calibration data is read.
Board matching is the platform caller's responsibility, outside this harness.
"""
from pathlib import Path
import subprocess
import tempfile

K = Path(__file__).resolve().parents[5]
SRC = K / 'drivers/misc/mediatek/ccci'
TEST = r'''
#include <assert.h>
#include <stdio.h>
#include <string.h>
#include <linux/errno.h>
#include <linux/unaligned.h>
#include "ccci-rpc-op6893.h"
#include "ccci-rpc-lhif.h"
#include "ccci-rpc-provider.h"
static u8 packet[2048],reply[2048];
static const struct ccci_rpc_provider *board;
static size_t request(u32 op,const struct ccci_rpc_arg *args,unsigned argc){
 size_t n=24;memset(packet,0,sizeof(packet));put_unaligned_le32(0x12345678,packet);
 put_unaligned_le32(0x80320020,packet+8);put_unaligned_le32(2,packet+12);
 put_unaligned_le32(op,packet+16);put_unaligned_le32(argc,packet+20);
 for(unsigned i=0;i<argc;i++){
  put_unaligned_le32(args[i].size,packet+n);n+=4;
  if(args[i].size)memcpy(packet+n,args[i].data,args[i].size);
  n+=(args[i].size+3)&~3U;
 }
 put_unaligned_le32(n,packet+4);return n;
}
static int call(size_t n){
 struct ccci_rpc_message decoded;assert(!ccci_rpc_decode_request(packet,n,&decoded));
 int out=ccci_rpc_provider_reply(board,packet,n,reply,sizeof(reply));
 if(out>0){
  assert(!ccci_rpc_validate_reply(&decoded,reply,out));
  assert(!memcmp(reply,packet,4)&&!memcmp(reply+12,packet+12,4));
  assert(get_unaligned_le32(reply+8)==0x80320021);
 }
 return out;
}
static void scalars(size_t n,s32 first,s32 second){
 assert(call(n)==40&&get_unaligned_le32(reply+20)==2);
 assert(get_unaligned_le32(reply+24)==4&&get_unaligned_le32(reply+32)==4);
 assert((s32)get_unaligned_le32(reply+28)==first);
 assert((s32)get_unaligned_le32(reply+36)==second);
}
static void unavailable(u32 operation){
 size_t n=request(operation,NULL,0);memset(reply,0xa5,sizeof(reply));
 assert(call(n)==-EOPNOTSUPP);
 for(unsigned i=0;i<sizeof(reply);i++)assert(reply[i]==0xa5);
}
static void gpio_adc(void){
 /* No strap has been sampled yet, so only the audited MD-view numbers appear. */
 static u8 record[425];struct ccci_rpc_arg a={record,425};
 memset(record,0,sizeof(record));
 put_unaligned_le16(3,record);put_unaligned_le16(0x1,record+2);
 memcpy(record+4,"GPIO_FDD_Band_Support_Detection_1",33);
 size_t n=request(0x4009,&a,1);
 assert(call(n)==24+8+4+88);
 assert(get_unaligned_le32(reply+28)==0&&get_unaligned_le32(reply+32)==88);
 assert(get_unaligned_le32(reply+36)==63);
 for(unsigned i=40;i<88;i++)assert(reply[36+i]==0x0f);
 /* A request without the packed record still answers A's -2 pair. */
 scalars(request(0x4009,NULL,0),-2,-2);
}
static void gpio_queries(void){
 /* Board numbers come from the MD-view cell, not phandle or Linux gpiochip base. */
 static const struct {const char *name;u32 md;} expected[]={
  {"GPIO_SIM1_HOT_PLUG",43},{"GPIO_SIM2_SCLK",45},{"GPIO_SIM2_SRST",46},
  {"GPIO_SIM2_SIO",47},{"GPIO_SIM1_SIO",48},{"GPIO_SIM1_SRST",49},
  {"GPIO_SIM1_SCLK",50},{"GPIO_FDD_BAND_SUPPORT_DETECT_1ST_PIN",63},
  {"GPIO_FDD_BAND_SUPPORT_DETECT_2ND_PIN",64},{"GPIO_FDD_BAND_SUPPORT_DETECT_3RD_PIN",65},
  {"GPIO_FDD_BAND_SUPPORT_DETECT_4TH_PIN",66},{"GPIO_FDD_Band_Support_Detection_1",63},
  {"GPIO_FDD_Band_Support_Detection_2",64},{"GPIO_FDD_Band_Support_Detection_3",65},
  {"GPIO_FDD_Band_Support_Detection_4",66}
 };
 assert(board->gpio_count==15&&board->gpio_present);
 for(unsigned i=0;i<15;i++)for(unsigned nul=0;nul<2;nul++){
  struct ccci_rpc_arg args[]={{(const u8 *)expected[i].name,strlen(expected[i].name)+nul},{NULL,0}};
  scalars(request(0x4002,args,2),expected[i].md,expected[i].md);
 }
 const char *missing[]={"GPIO_FDD_Band_Support_Detection_5","GPIO_FDD_Band_Support_Detection_A",
  "GPIO_RF_PWREN_RST_PIN","GPIO_SIM3_SCLK","GPIO_SIM1","GPIO_FDD_BAND_SUPPORT_DETECT_5TH_PIN"};
 for(unsigned i=0;i<sizeof(missing)/sizeof(missing[0]);i++){
  struct ccci_rpc_arg args[]={{(const u8 *)missing[i],strlen(missing[i])+1},{NULL,0}};
  scalars(request(0x4002,args,2),-5,-5);
 }
 puts("PASS: all 15 board GPIO names return exact MD-view numbers; absent names and prefixes fail");
}
static void eint_queries(void){
 const s32 expected[]={0,10,0,0,0,0,1};u8 type[4];
 struct ccci_rpc_arg args[]={{(const u8 *)"MD1_SIM1_HOT_PLUG_EINT",23},{NULL,0},{type,4}};
 args[0].size=strlen((const char *)args[0].data)+1;
 assert(board->eint_present&&board->eint_count==1);
 for(unsigned i=0;i<7;i++){
  put_unaligned_le32(i,type);scalars(request(0x4005,args,3),0,expected[i]);
 }
 for(unsigned slot=2;slot<=4;slot++){
  char name[32];snprintf(name,sizeof(name),"MD1_SIM%u_HOT_PLUG_EINT",slot);
  args[0]=(struct ccci_rpc_arg){(const u8 *)name,strlen(name)+1};
  for(unsigned i=0;i<7;i++){
   put_unaligned_le32(i,type);scalars(request(0x4005,args,3),-11,-11);
  }
 }
 args[0]=(struct ccci_rpc_arg){(const u8 *)"MD1_SIM1_HOT_PLUG_EINT",sizeof("MD1_SIM1_HOT_PLUG_EINT")};
 put_unaligned_le32(7,type);scalars(request(0x4005,args,3),-12,-12);
 put_unaligned_le32(0xffffffff,type);scalars(request(0x4005,args,3),-12,-12);
 puts("PASS: SIM1 uses MD EINT units/flags; SIM2/3/4 fail; vendor enum errors are -12/-11");
}
static void dtsi_query(const char *name,u8 req,u32 expected){
 u8 query[66]={0};query[0]=req;assert(strlen(name)<64);memcpy(query+2,name,strlen(name)+1);
 struct ccci_rpc_arg arg={query,sizeof(query)};
 assert(call(request(0x400e,&arg,1))==104);
 assert(get_unaligned_le32(reply+20)==2&&get_unaligned_le32(reply+24)==4);
 assert(!get_unaligned_le32(reply+28)&&get_unaligned_le32(reply+32)==68);
 assert(get_unaligned_le32(reply+36)==expected);
 for(unsigned i=40;i<104;i++)assert(reply[i]==0x0f);
}
static void dtsi_queries(void){
 assert(board->dtsi_present&&board->dtsi_count==3);
 dtsi_query("mediatek,md_product_name_model_id",1,20615);
 dtsi_query("mediatek,md_drdi_rf_set_idx",1,0);
 dtsi_query("compatible",1,0x6d656469);
 dtsi_query("mediatek,md_missing",1,0x0f0f0f0f);
 dtsi_query("phandle",1,0x0f0f0f0f);
 dtsi_query("mediatek,md_product_name_model_id",2,0x0f0f0f0f);
 puts("PASS: all three saved DTSI properties, compatible first cell and untouched failure sentinel");
}
int main(void){
 board=ccci_rpc_op6893_provider();assert(board&&board==ccci_rpc_op6893_provider());
 assert(!board->adc&&!board->adc_count&&!board->adc_present);
 assert(ccci_rpc_provider_available(board,0x4002)==1);
 assert(ccci_rpc_provider_available(board,0x4005)==1);
 assert(ccci_rpc_provider_available(board,0x400e)==1);
 assert(!ccci_rpc_provider_available(board,0x4003));
 gpio_queries();eint_queries();dtsi_queries();
 /* 0x400d is a command: A records the remap and always replies two zeros. */
 {
  u8 map[8];u32 q=0;
  ccci_rpc_lhif_reset();
  put_unaligned_le32(0,map);put_unaligned_le32(2,map+4);
  struct ccci_rpc_arg a={map,8};
  scalars(request(0x400d,&a,1),0,0);
  assert(ccci_rpc_lhif_queue(0,&q)&&q==0);
  put_unaligned_le32(3,map+4);
  scalars(request(0x400d,&a,1),0,0);
  assert(ccci_rpc_lhif_queue(0,&q)&&q==3);
  ccci_rpc_lhif_reset();
 }
 gpio_adc();
 /* No ADC namespace, secure operation or RF-clock success is invented. */
 const u32 blocked[]={0x4001,0x4003,0x4004,0x4006,0x400b,0x400c};
 for(unsigned i=0;i<sizeof(blocked)/sizeof(blocked[0]);i++)unavailable(blocked[i]);
 puts("PASS: ADC and unavailable hardware services remain unsupported with unchanged output");
 return 0;
}
'''


def main():
    with tempfile.TemporaryDirectory(prefix='op6893-rpc-board-') as directory:
        tmp = Path(directory)
        inc = tmp / 'linux'
        inc.mkdir()
        headers = {
            'types.h': '#pragma once\n#include <stdint.h>\n#include <stddef.h>\n'
                       '#include <stdbool.h>\ntypedef uint8_t u8; typedef uint16_t u16; typedef uint32_t u32; '
                       'typedef int32_t s32;\n',
            'errno.h': '#include <asm-generic/errno.h>\n',
            'string.h': '#include <string.h>\n',
            'kernel.h': '#pragma once\n#include <linux/compiler.h>\n'
                        '#define ARRAY_SIZE(a) (sizeof(a)/sizeof((a)[0]))\n',
            'array_size.h': '#pragma once\n'
                            '#define ARRAY_SIZE(a) (sizeof(a)/sizeof((a)[0]))\n',
            'compiler.h': '#pragma once\n'
                          '#define READ_ONCE(x) (x)\n'
                          '#define WRITE_ONCE(x, v) ((x) = (v))\n',
            'spinlock.h': '''#pragma once
typedef struct { int unused; } spinlock_t;
#define DEFINE_SPINLOCK(name) spinlock_t name
#define spin_lock_irqsave(l, f) do { (void)(l); (f) = 0; } while (0)
#define spin_unlock_irqrestore(l, f) do { (void)(l); (void)(f); } while (0)
''',
            'unaligned.h': '''#pragma once
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
''',
        }
        for name, content in headers.items():
            (inc / name).write_text(content)
        (tmp / 'test.c').write_text(TEST)
        subprocess.run(['cc', '-O1', '-g', '-Wall', '-Wextra', '-Werror',
                        '-fsanitize=address,undefined', '-fno-sanitize-recover=all',
                        '-no-pie', '-I' + str(tmp), '-I' + str(SRC),
                        str(SRC / 'ccci-rpc-protocol.c'), str(SRC / 'ccci-rpc-provider.c'),
                        str(SRC / 'ccci-rpc-op6893.c'), str(SRC / 'ccci-rpc-lhif.c'),
                        str(tmp / 'test.c'),
                        '-o', str(tmp / 'test')], check=True)
        subprocess.run([str(tmp / 'test')], check=True)


if __name__ == '__main__':
    main()
