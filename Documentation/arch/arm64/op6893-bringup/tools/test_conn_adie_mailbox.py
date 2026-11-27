#!/usr/bin/env python3
# SPDX-License-Identifier: GPL-2.0-only
"""Actual ID mailbox write/read/clear with guard and write fault injection."""
from pathlib import Path
import runpy
import subprocess
import tempfile

base = runpy.run_path(str(Path(__file__).with_name('test_conn_adie.py')))['harness']
base = base[:base.index('int main(void) {')]
base = base.replace('static u32 response;', 'static u32 response,mailbox;')
base = base.replace('if(addr==0x18001900)', 'if(addr==0x18052800){assert(size==4);return &mailbox;}\n if(addr==0x18001900)',1)
base = base.replace('p==&control || p==spi || p==&wb', 'p==&control || p==spi || p==&wb || p==&mailbox')
base = base.replace('assert(p==&control || p==spi+0x50/4 || p==spi+0x54/4);', 'assert(p==&control || p==spi+0x50/4 || p==spi+0x54/4 || p==&mailbox);')
base = base.replace('if(p==&control) {\n  assert(value==2', '''if(p==&mailbox) {
  assert(conn.adie_mailbox_dirty && control==3 && (value==response || !value));
  if(n!=dropwrite)mailbox=value;
 } else if(p==&control) {
  if(value==2)assert(!conn.adie_mailbox_dirty && !mailbox);
  assert(value==2''',1)
harness = base + r'''
static void mailbox_setup(void) {
 setup();conn.adie_mailbox_requested=true;conn.sysram_complete=true;
 conn.sysram_verified=conn.sysram_scanned=4096;conn.rgu_applied=4;conn.rgu_dirty=15;
 mailbox=0;
}
int main(void) {
 mailbox_setup();assert(!run());restored();unsigned total_guards=guards;
 unsigned owners=owner_count,points[1024];memcpy(points,owner_reads,sizeof(points));
 assert(writes==7 && maps==4 && conn.adie_complete && conn.adie_mailbox_issued);
 assert(conn.adie_mailbox_applied && conn.adie_mailbox_restored && !conn.adie_mailbox_dirty);
 assert(conn.adie_mailbox_on==response && !conn.adie_mailbox_after && !mailbox);
 for(unsigned i=1;i<=total_guards;i++) {
  mailbox_setup();guardfail=i;assert(run()<0 && conn.adie_unsafe && !conn.adie_complete);
 }
 for(unsigned i=0;i<owners;i++) {
  mailbox_setup();lossread=points[i];losstype=3;assert(run()<0 && !conn.adie_complete);
 }
 for(unsigned i=1;i<=7;i++) {
  mailbox_setup();dropwrite=i;assert(run()<0 && !conn.adie_complete);
  if(i==2 || i==3 || i==4)restored();
  if(i==5)assert(conn.adie_mailbox_dirty && conn.adie_unsafe && mailbox==response);
 }
 for(unsigned i=1;i<=7;i++)for(unsigned kind=1;kind<=5;kind++) {
  mailbox_setup();losswrite=i;losstype=kind;assert(run()<0 && conn.adie_unsafe && writes==i);
 }
 for(unsigned i=1;i<=4;i++) {
  mailbox_setup();mapfail=i;assert(run()==-ENOMEM);
  if(i==4){restored();assert(!conn.adie_mailbox_issued);}
 }
 mailbox_setup();mailbox=0xdeadbeef;assert(run()==-EBUSY && writes==3);
 assert(conn.adie_unsafe && !conn.adie_mailbox_issued && mailbox==0xdeadbeef);
 for(unsigned i=0;i<6;i++) {
  mailbox_setup();
  if(i==0)conn.sysram_complete=false;if(i==1)conn.sysram_unsafe=true;
  if(i==2)conn.sysram_verified--;if(i==3)conn.sysram_scanned--;
  if(i==4)conn.rgu_applied--;if(i==5)conn.rgu_dirty--;
  assert(run()==-EINVAL);restored();assert(!conn.adie_mailbox_issued);
 }
 mailbox_setup();busy_cycles=0;assert(!run());restored();
 puts("PASS: actual ID mailbox,7 dropped writes,35 write-time faults,all guard/owner losses,"
      "4 map failures,unexpected contents retention,6 prerequisite refusals and clear before reset");
}
'''
with tempfile.TemporaryDirectory() as tmp:
    path = Path(tmp)
    (path / 'test.c').write_text(harness)
    subprocess.run(['cc', '-O1', '-Wall', '-Wextra', '-Werror', '-Wno-misleading-indentation',
                    '-fsanitize=undefined', '-fno-sanitize-recover=all',
                    str(path / 'test.c'), '-o', str(path / 'test')], check=True)
    subprocess.run([str(path / 'test')], check=True)
