#!/usr/bin/env python3
# SPDX-License-Identifier: GPL-2.0-only
"""Actual FM format apply/restore with thermal guards and independent MMIO."""
from pathlib import Path
import runpy
import subprocess
import tempfile

base = runpy.run_path(str(Path(__file__).with_name('test_conn_adie_route.py')))['harness']
base = base[:base.index('int main(void) {')]
base = base.replace('static unsigned route_reads,',
                    'static unsigned lost_writes;\nstatic bool bad_apply,bad_restore;\n'
                    'static unsigned route_reads,',1)
base = base.replace('static void lose(void) {',r'''static void lose(void) {
 lost_writes=writes;
 if(losstype==6)therm[9]|=BIT(19);
 if(losstype==7)therm[9]|=BIT(18);
 if(losstype==8)gpt[14]|=1;
 if(losstype==9)therm[6]^=2;
 if(losstype==10)therm[1]^=2;
 if(losstype==11)mailbox^=1;
 if(losstype>=12)sema[(0x400+(losstype-12)*0x1000)/4]|=BIT(13);
''',1)
base = base.replace('  u32 result=*(u32 *)p;',r'''  u32 result=*(u32 *)p;
  if(p==spi+3 && conn.adie_fm_issued==1 && bad_apply)result=0xdeadbeef;
  if(p==spi+3 && conn.adie_fm_issued==3 && bad_restore)result=0xdeadbeef;''',1)
base = base.replace('static void writel(u32 value,void *p) {',r'''static void writel(u32 value,void *p) {
 if(p==spi+3) {
  assert(!inaccessible && !conn.adie_unsafe && sema[0x2400/4]==0x800);
  assert(control==3 && wb==0x80000 && !spi[0] && mailbox==response);
  assert(conn.adie_fm_dirty && conn.adie_prefix_dirty==3 && analog[0]==0x7700 && analog[1]==0x21);
  assert(value==0 || value==0x801f);
  unsigned n=++writes;if(n!=dropwrite)*(u32 *)p=value;
  if(n==losswrite)lose();return;
 }
 if(p==spi+0x54/4 && (spi[0x50/4]==0xa064 || spi[0x50/4]==0xa0bc) && value<=1)
  assert(!conn.adie_fm_dirty && (!conn.adie_fm_issued || spi[3]==conn.adie_fm_before));
''',1)
harness = base+r'''
static void fm_setup(void) {
 route_setup();conn.adie_fm_requested=true;
 spi[3]=0x801f;therm[6]=0x50305a00;therm[1]=0x7f0300ff;
 lost_writes=0;bad_apply=bad_restore=false;
}
int main(void) {
 fm_setup();assert(!run());restored();unsigned total_guards=guards,total_reads=route_reads,total_mail=mail_reads;
 assert(writes==45 && conn.adie_complete && conn.adie_fm_applied && conn.adie_fm_restored);
 assert(conn.adie_fm_issued==3 && conn.adie_fm_read==7 && !conn.adie_fm_dirty);
 assert(conn.adie_fm_before==0x801f && !conn.adie_fm_target && !conn.adie_fm_on && conn.adie_fm_after==0x801f);
 assert(spi[3]==0x801f && therm[6]==0x50305a00 && therm[1]==0x7f0300ff && !therm[9] && !gpt[14]);
 for(unsigned n=1;n<=total_guards;n++) {
  fm_setup();guardfail=n;assert(run()<0 && conn.adie_unsafe && !conn.adie_complete);
 }
 for(unsigned n=1;n<=total_mail;n++) {
  fm_setup();mail_loss=n;assert(run()<0 && conn.adie_unsafe && !conn.adie_complete);
 }
 for(unsigned n=1;n<=45;n++) {
  fm_setup();dropwrite=n;assert(run()<0 && !conn.adie_complete);
  if(n>=2 && n<=29){restored();assert(!conn.adie_fm_dirty && !mailbox);}
  else assert(conn.adie_unsafe || conn.adie_addr_dirty);
 }
 for(unsigned n=29;n<=30;n++)for(unsigned kind=1;kind<=15;kind++) {
  fm_setup();losswrite=n;losstype=kind;assert(run()<0 && conn.adie_unsafe);
  assert(writes==n && conn.adie_fm_dirty && conn.adie_prefix_dirty==3 && conn.adie_mailbox_dirty);
 }
 for(unsigned n=1;n<=total_reads;n++)for(unsigned kind=1;kind<=15;kind++) {
  if(kind>=6 && kind<=10)continue;
  fm_setup();route_loss=n;losstype=kind;assert(run()<0 && conn.adie_unsafe);
  assert(writes==lost_writes && conn.adie_prefix_dirty==3 && conn.adie_mailbox_dirty);
 }
 for(unsigned n=11;n<=total_reads;n++) {
  fm_setup();route_change=n;assert(run()<0);
  if(n==24){restored();assert(conn.adie_fm_restored);}
  else assert(conn.adie_unsafe && conn.adie_prefix_dirty==3 && conn.adie_mailbox_dirty);
 }
 fm_setup();bad_apply=true;assert(run()==-EIO);restored();assert(conn.adie_fm_restored && !conn.adie_fm_applied);
 assert(!strcmp(conn.failure_stage,"adie-fm-apply-readback"));
 fm_setup();bad_restore=true;assert(run()==-EIO && conn.adie_fm_dirty && conn.adie_unsafe);
 fm_setup();bad_apply=true;dropwrite=30;assert(run()==-EIO && conn.adie_fm_cleanup==-EIO);
 assert(!strcmp(conn.failure_stage,"adie-fm-apply-readback") && conn.adie_fm_dirty);
 for(unsigned n=0;n<3;n++) {
  fm_setup();if(n==0)spi[3]^=2;if(n==1)therm[6]^=2;if(n==2)therm[1]^=2;
  assert(run()==-EINVAL);restored();assert(!conn.adie_fm_issued);
 }
 fm_setup();busy_cycles=0;assert(!run());restored();
 printf("PASS: actual FM clear/restore,45 dropped writes,30 write-time faults,%u sample-time faults,"
        "all guard/mailbox points,27 changed samples,thermal/ownership containment,readback corruption,first-error preservation\n",total_reads*10);
}
'''
with tempfile.TemporaryDirectory() as tmp:
    path = Path(tmp)
    (path / 'test.c').write_text(harness)
    subprocess.run(['cc', '-O1', '-Wall', '-Wextra', '-Werror', '-Wno-misleading-indentation',
                    '-fsanitize=undefined', '-fno-sanitize-recover=all',
                    str(path / 'test.c'), '-o', str(path / 'test')], check=True)
    subprocess.run([str(path / 'test')], check=True)
