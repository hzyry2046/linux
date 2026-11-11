#!/usr/bin/env python3
# SPDX-License-Identifier: GPL-2.0-only
"""Actual fixed route baseline reads, inactive-engine gate and containment."""
from pathlib import Path
import runpy
import subprocess
import tempfile

base = runpy.run_path(str(Path(__file__).with_name('test_conn_adie_prefix.py')))['harness']
base = base[:base.index('int main(void) {')]
base = base.replace('owner_reads[1024]', 'owner_reads[16384]')
base = base.replace('static u32 response,mailbox,',
                    'static u32 therm[10],gpt[15];\n'
                    'static unsigned route_reads,route_change,route_loss,thermal_owner;\n'
                    'static u32 response,mailbox,')
base = base.replace('if(addr==0x18052800)',
                    'if(addr==0x18002000){assert(size==sizeof(therm));return therm;}\n'
                    ' if(addr==0x18007000){assert(size==sizeof(gpt));return gpt;}\n'
                    ' if(addr==0x18052800)',1)
base = base.replace('p==&control || p==spi || p==&wb || p==&mailbox',
                    'p==&control || p==spi || p==&wb || p==&mailbox || p==therm || p==gpt')
marker = 'static u32 readl(void *p) {\n'
base = base.replace(marker, marker + r'''
 if(p==spi+3 || p==therm+6 || p==therm+1 || p==therm+9 || p==gpt+14) {
  assert(mailbox==response && conn.adie_prefix_dirty==3);
  assert(analog[0]==0x7700 && analog[1]==0x21 && control==3);
  assert(!inaccessible);route_reads++;
  if(route_reads==route_change)*(u32 *)p^=2;
  u32 result=*(u32 *)p;
  if(route_reads==route_loss)lose();
  if(thermal_owner)sema[(0x400+(thermal_owner-1)*0x1000)/4]|=BIT(13);
  return result;
 }
''',1)
harness = base + r'''
static void route_setup(void) {
 prefix_setup();conn.adie_route_requested=true;
 memset(therm,0,sizeof(therm));memset(gpt,0,sizeof(gpt));
 spi[3]=0x8012;therm[6]=0x12345678;therm[1]=0x30000;
 route_reads=route_change=route_loss=thermal_owner=0;
}
int main(void) {
 route_setup();assert(!run());restored();unsigned total_guards=guards;
 assert(writes==43 && maps==6 && route_reads==10 && conn.adie_route_read==1023);
 assert(conn.adie_route_stable && conn.adie_route_idle && conn.adie_complete);
 for(unsigned i=0;i<5;i++)assert(conn.adie_route_value[i]==conn.adie_route_value[i+5]);
 assert(spi[3]==0x8012 && therm[6]==0x12345678 && therm[1]==0x30000);
 for(unsigned n=1;n<=6;n++) {
  route_setup();mapfail=n;assert(run()==-ENOMEM);
  if(n>=4){restored();assert(!conn.adie_prefix_dirty && !mailbox);}
 }
 for(unsigned n=1;n<=total_guards;n++) {
  route_setup();guardfail=n;assert(run()<0 && conn.adie_unsafe && !conn.adie_complete);
 }
 for(unsigned n=1;n<=10;n++)for(unsigned kind=1;kind<=5;kind++) {
  route_setup();route_loss=n;losstype=kind;assert(run()<0 && conn.adie_unsafe);
  assert(conn.adie_prefix_dirty==3 && mailbox==response && writes==28);
 }
 for(unsigned n=1;n<=4;n++) {
  route_setup();thermal_owner=n;assert(run()==-EBUSY && conn.adie_unsafe);
  assert(writes==28 && conn.adie_prefix_dirty==3 && conn.adie_mailbox_dirty);
 }
 for(unsigned n=0;n<3;n++) {
  route_setup();if(n<2)therm[9]=BIT(18+n);else gpt[14]=1;
  assert(run()==-EBUSY && conn.adie_unsafe && writes==28 && !conn.adie_route_idle);
  assert(!strcmp(conn.failure_stage,"adie-route-active") && conn.adie_prefix_dirty==3);
 }
 for(unsigned n=6;n<=10;n++) {
  route_setup();route_change=n;assert(run()==-EAGAIN && conn.adie_unsafe && writes==28);
  assert(!conn.adie_route_stable && !strcmp(conn.failure_stage,"adie-route-stability"));
 }
 route_setup();busy_cycles=0;assert(!run());restored();assert(conn.adie_route_idle);
 puts("PASS: actual route read,unchanged digital words,6 mapping failures,all guard points,"
      "50 sample-time faults,4 thermal owners,3 active controls,5 unstable baselines,no digital writes");
}
'''
with tempfile.TemporaryDirectory() as tmp:
    path = Path(tmp)
    (path / 'test.c').write_text(harness)
    subprocess.run(['cc', '-O1', '-Wall', '-Wextra', '-Werror',
                    '-fsanitize=undefined', '-fno-sanitize-recover=all',
                    str(path / 'test.c'), '-o', str(path / 'test')], check=True)
    subprocess.run([str(path / 'test')], check=True)
