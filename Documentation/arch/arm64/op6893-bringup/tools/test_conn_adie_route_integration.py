#!/usr/bin/env python3
# SPDX-License-Identifier: GPL-2.0-only
"""Route snapshots inside real nested preparation, with shared SPI/SYSRAM."""
from pathlib import Path
import runpy
import subprocess
import tempfile

base = runpy.run_path(str(Path(__file__).with_name('test_conn_adie_prefix_integration.py')))['harness']
base = base[:base.index('int main(void) {')]
base = base.replace('static u32 adie_spi[0x5c/4]',
                    'static u32 therm[10],gpt[15];\n'
                    'static unsigned route_reads,route_loss,route_kind,route_change,route_map_fail;\n'
                    'static u32 adie_spi[0x5c/4]',1)
marker = 'static u32 readl(void *p) {\n'
base = base.replace(marker,marker+r'''
 if(p==adie_spi+3 || p==therm+6 || p==therm+1 || p==therm+9 || p==gpt+14) {
  held_strap();assert(config_adie==3 && *MAILBOX==adie_response && prefix_dirty()==3);
  assert(analog[0]==0x7700 && analog[1]==0x21);
  route_reads++;if(route_reads==route_change)*(u32 *)p^=2;
  u32 result=*(u32 *)p;
  if(route_reads==route_loss) {
   if(route_kind==0)fresh[0]&=~2;
   if(route_kind==1)sema_hw[0x2400/4]=0;
   if(route_kind==2)config_wt[2]^=0x4000000;
   if(route_kind==3)config_busy=2;
   if(route_kind==4)*MAILBOX^=1;
   if(route_kind>=5)sema_hw[(0x400+(route_kind-5)*0x1000)/4]|=BIT(13);
  }
  return result;
 }
''',1)
marker = 'static void *ioremap(unsigned long addr,unsigned long size) {\n'
base = base.replace(marker, marker+r'''
 if(addr==0x18002000 || addr==0x18007000) {
  held_strap();assert(prefix_dirty()==3 && *MAILBOX==adie_response);
  if(route_map_fail==(addr==0x18002000?1U:2U))return NULL;
  maps++;if(addr==0x18002000){assert(size==sizeof(therm));return therm;}
  assert(size==sizeof(gpt));return gpt;
 }
''',1)
base = base.replace('static void iounmap(void *p) {\n',
                    'static void iounmap(void *p) {\n if(p==therm || p==gpt){unmaps++;return;}\n',1)
harness = base+r'''
static void route_setup(void) {
 prefix_setup();memset(therm,0,sizeof(therm));memset(gpt,0,sizeof(gpt));
 adie_spi[3]=0x8012;therm[6]=0x12345678;therm[1]=0x30000;
 route_reads=route_loss=route_kind=route_change=route_map_fail=0;
}
static int route_run(void) {return rail_cycle_store(&dev,NULL,"adie-route-read",15);}
int main(void) {
 char output[4096];route_setup();assert(route_run()==15);stopped();
 assert(conn.adie_route_stable && conn.adie_route_idle && conn.adie_route_read==1023);
 assert(adie_writes==43 && route_reads==10 && conn.adie_complete && conn.sema_released);
 assert(adie_spi[3]==0x8012 && therm[6]==0x12345678 && therm[1]==0x30000);
 int len=adie_status_show(&dev,NULL,output);assert(len>0 && len<4096);
 assert(strstr(output,"route_requested=1 route_read=0x3ff route_stable=1 route_idle=1"));
 assert(route_run()==-EALREADY && adie_writes==43);
 for(unsigned n=1;n<=10;n++)for(unsigned kind=0;kind<9;kind++) {
  route_setup();route_loss=n;route_kind=kind;assert(route_run()<0);retained();
  assert(conn.adie_unsafe && conn.adie_prefix_dirty==3 && conn.adie_mailbox_dirty);
  assert(adie_writes==28 && !sema_writes && config_writes==36 && rgu_writes==4 && remap_writes==4);
 }
 for(unsigned n=0;n<3;n++) {
  route_setup();if(n<2)therm[9]=BIT(18+n);else gpt[14]=1;
  assert(route_run()==-EBUSY);retained();assert(!sema_writes && conn.adie_prefix_dirty==3);
 }
 for(unsigned n=6;n<=10;n++) {
  route_setup();route_change=n;assert(route_run()==-EAGAIN);retained();
  assert(conn.adie_prefix_dirty==3 && conn.adie_mailbox_dirty && !sema_writes);
 }
 for(unsigned n=1;n<=2;n++) {
  route_setup();route_map_fail=n;assert(route_run()==-ENOMEM);stopped();
  assert(conn.adie_prefix_restored==3 && conn.adie_mailbox_restored);
 }
 route_setup();config_drop_write=37;assert(route_run()==-EIO);retained();
 assert(conn.adie_route_idle && conn.adie_complete && conn.sema_released && conn.spi_config_dirty);
 route_setup();adie_drop=30;assert(route_run()==-EIO);retained();
 assert(conn.adie_route_idle && conn.adie_prefix_dirty && !sema_writes);
 puts("PASS: nested route read,90 read-time faults including mailbox/thermal owners,"
      "active/changing controls retain parents,map failure unwinds,one-shot/status size,outer restoration faults");
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
