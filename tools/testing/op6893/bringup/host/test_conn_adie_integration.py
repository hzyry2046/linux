#!/usr/bin/env python3
# SPDX-License-Identifier: GPL-2.0-only
"""Execute A-die read inside the real nested preparation and cleanup code."""
from pathlib import Path
import runpy
import subprocess
import tempfile

base = runpy.run_path(str(Path(__file__).with_name('test_conn_prepare.py')))['harness']
base = base[:base.index('int main(void) {')]
marker = 'static u32 gpio[0x470/4]'
base = base.replace(marker, r'''
static u32 adie_spi[0x5c/4],adie_response;
static unsigned adie_writes,adie_drop,adie_loss,adie_change,adie_reads;
static unsigned adie_maps,adie_map_fail;
static bool adie_live,adie_fired,adie_stuck,adie_fast;
''' + marker)
marker = 'static u32 readl(void *p) {\n'
base = base.replace(marker, marker + r'''
 if(p==adie_spi) {
  if(adie_fired && !(config_busy&~32)) {
   config_busy=adie_stuck || (!adie_fast && adie_reads++==0)?32:0;
  }
  return config_busy;
 }
 if(p==adie_spi+0x50/4 || p==adie_spi+0x58/4)return *(u32 *)p;
 if(p==sema_hw+0x202c/4) {
  held_strap();u32 result=lower_readl(p);adie_live=true;return result;
 }
''', 1)
marker = 'static void writel(u32 value,void *p) {\n'
base = base.replace(marker, marker + r'''
 if(p==&config_adie || p==adie_spi+0x50/4 || p==adie_spi+0x54/4) {
  held_strap();assert(adie_live && sema_hw[0x2400/4]==0x800);
  unsigned n=++adie_writes;
  if(n!=adie_drop) {
   if(p==&config_adie){assert(value==2 || value==3);config_adie=value;}
   else if(p==adie_spi+0x50/4)*(u32 *)p=value;
   else {assert(!value && config_adie==3 && adie_spi[0x50/4]==0xb02c && !adie_fired);
    adie_fired=true;adie_spi[0x58/4]=adie_response;}
  }
  if(n==adie_loss) {
   if(adie_change==1)fresh[0]&=~2;
   if(adie_change==2)sema_hw[0x2400/4]=0;
   if(adie_change==3)config_wt[2]^=0x4000000;
   if(adie_change==4)config_busy=2;
  }
  return;
 }
''', 1)
marker = 'static void *ioremap(unsigned long addr,unsigned long size) {\n'
base = base.replace(marker, marker + r'''
 if(adie_live && (addr==0x18001900 || (addr==0x18004000 && size==0x5c) || addr==0x18005008)) {
  if(++adie_maps==adie_map_fail)return NULL;
  maps++;
  if(addr==0x18001900){assert(size==4);return &config_adie;}
  if(addr==0x18005008){assert(size==4);return config_wt+2;}
  return adie_spi;
 }
''', 1)
marker = 'static void iounmap(void *p) {\n'
base = base.replace(marker, marker+' if(p==adie_spi || p==config_wt+2){unmaps++;return;}\n', 1)
base = base.replace('if(p==sema_hw+0x222c/4)held_strap();',
                    'if(p==sema_hw+0x222c/4){held_strap();assert(config_adie==2 && adie_spi[0x50/4]==0x1234);}')
harness = base + r'''
static void adie_setup(void) {
 prepare();memset(adie_spi,0,sizeof(adie_spi));adie_spi[0x50/4]=0x1234;
 adie_response=0x66358a10;adie_writes=adie_drop=adie_loss=adie_change=adie_reads=0;
 adie_maps=adie_map_fail=0;adie_live=adie_fired=adie_stuck=adie_fast=false;
}
static int adie_run(void) {return rail_cycle_store(&dev,NULL,"adie-id-cycle",13);}
int main(void) {
 char output[4096];
 adie_setup();assert(adie_run()==13);stopped();
 assert(conn.adie_complete && conn.adie_id_valid && conn.adie_id==0x66358a10);
 assert(conn.adie_reset_restored && !conn.adie_reset_dirty && !conn.adie_addr_dirty && !conn.adie_unsafe);
 assert(adie_writes==5 && conn.sema_released && config_adie==2 && adie_spi[0x50/4]==0x1234);
 assert(adie_status_show(&dev,NULL,output)>0 && strstr(output,"id_valid=1 reset_restored=1 complete=1"));
 adie_setup();adie_response=0;assert(adie_run()==-ENODEV);stopped();
 assert(conn.adie_reset_restored && !strcmp(conn.failure_stage,"adie-top-id"));
 adie_setup();adie_spi[0x58/4]=adie_response;adie_fast=true;
 assert(adie_run()==-EAGAIN);stopped();assert(!conn.adie_id_valid);
 for(unsigned n=1;n<=3;n++) {
  adie_setup();adie_map_fail=n;assert(adie_run()==-ENOMEM);stopped();assert(!adie_writes);
 }
 for(unsigned n=1;n<=5;n++) {
  adie_setup();adie_drop=n;assert(adie_run()<0);
  if(n==2 || n==3)stopped();
  else {
   retained();assert(conn.sema_pending && conn.sema_unsafe && conn.strap_unsafe);
   assert(conn.spi_config_dirty && conn.rgu_dirty==15 && conn.remap_dirty==15);
   assert(!sema_writes && config_writes==36 && rgu_writes==4 && remap_writes==4);
  }
 }
 for(unsigned n=1;n<=5;n++)for(unsigned change=1;change<=4;change++) {
  adie_setup();adie_loss=n;adie_change=change;assert(adie_run()<0);retained();
  assert(adie_writes==n && conn.adie_unsafe && conn.sema_pending && conn.strap_unsafe);
  assert(!sema_writes && config_writes==36 && rgu_writes==4 && remap_writes==4);
 }
 adie_setup();adie_stuck=true;assert(adie_run()==-ETIMEDOUT);retained();
 assert(adie_writes==3 && config_adie==3 && !sema_writes && strap_phase==2);
 adie_setup();adie_response=0;adie_drop=4;assert(adie_run()==-ENODEV);retained();
 assert(!strcmp(conn.failure_stage,"adie-top-id") && conn.adie_cleanup_result);
 adie_setup();config_drop_write=37;assert(adie_run()==-EIO);retained();
 assert(conn.adie_complete && conn.sema_released && conn.spi_config_dirty && rgu_writes==4);
 adie_setup();conn.domain_allowed=false;assert(adie_run()==-EOPNOTSUPP && !conn.attempted);
 adie_setup();conn.cycle_allowed=false;assert(adie_run()==-EOPNOTSUPP && !conn.attempted);
 adie_setup();conn.emi_valid=false;assert(adie_run()==-EINVAL && !conn.attempted);
 puts("PASS: actual nested A-die ID,clean unknown/stale ID unwind,all mapping and dropped-write faults,"
      "20 write-time guard losses,reset-before-unlock enforcement,busy-timeout containment,"
      "earliest-error preservation,outer restore failure and cached one-shot routing");
}
'''
with tempfile.TemporaryDirectory() as tmp:
    path = Path(tmp)
    (path / 'test.c').write_text(harness)
    subprocess.run(['cc', '-O1', '-Wall', '-Wextra', '-Werror', '-Wno-unused-parameter',
                    '-Wno-unused-variable', '-Wno-unused-function',
                    '-fsanitize=undefined', '-fno-sanitize-recover=all',
                    str(path / 'test.c'), '-o', str(path / 'test')], check=True)
    subprocess.run([str(path / 'test')], check=True)
