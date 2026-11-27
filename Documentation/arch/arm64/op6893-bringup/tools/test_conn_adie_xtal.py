#!/usr/bin/env python3
# SPDX-License-Identifier: GPL-2.0-only
"""Exercise actual fixed XTAL reads, including per-transfer freshness failures."""
from pathlib import Path
import runpy
import subprocess
import tempfile

base = runpy.run_path(str(Path(__file__).with_name('test_conn_adie.py')))['harness']
base = base[:base.index('int main(void) {')]
base = base.replace('static u32 response;',
                    'static u32 response, xtal_response[2];\n'
                    'static unsigned transfers, transfer_stuck;\n'
                    'static bool xtal_fast;')
base = base.replace('value==0xb02c || value==0x1234',
                    'value==0xb02c || value==0xba18 || value==0xba1c || value==0x1234')
base = base.replace('spi[0x50/4]==0xb02c && !triggered',
                    'spi[0x50/4]==(transfers==0?0xb02c:0xba18+(transfers-1)*4)')
base = base.replace('triggered=true;spi[0x58/4]=response;',
                    'triggered=true;busy_reads=0;'
                    'spi[0x58/4]=transfers?xtal_response[transfers-1]:response;'
                    'transfers++;stuck=transfers==transfer_stuck;'
                    'if(transfers>1 && xtal_fast)busy_cycles=0;')
harness = base + r'''
static void xtal_setup(void) {
 setup();conn.adie_xtal_requested=true;transfers=transfer_stuck=0;xtal_fast=false;
 xtal_response[0]=0x12345678;xtal_response[1]=0x98765432;
}
int main(void) {
 xtal_setup();assert(!run());restored();
 unsigned total_guards=guards,owners=owner_count,points[1024];
 memcpy(points,owner_reads,sizeof(points));
 assert(writes==9 && transfers==3 && conn.adie_xtal_read==3 && conn.adie_xtal_valid==3);
 assert(conn.adie_xtal_busy_mask==3 && conn.adie_complete);
 assert(conn.adie_xtal_before[0]==response && conn.adie_xtal_before[1]==xtal_response[0]);
 for(unsigned i=1;i<=total_guards;i++) {
  xtal_setup();guardfail=i;assert(run()<0 && conn.adie_unsafe && !conn.adie_complete);
 }
 for(unsigned i=0;i<owners;i++) {
  xtal_setup();lossread=points[i];losstype=3;assert(run()<0 && !conn.adie_complete);
 }
 for(unsigned i=1;i<=9;i++) {
  xtal_setup();dropwrite=i;assert(run()<0 && !conn.adie_complete);
  if(i>=2 && i<=7)restored();
 }
 for(unsigned i=1;i<=9;i++)for(unsigned kind=1;kind<=5;kind++) {
  xtal_setup();losswrite=i;losstype=kind;assert(run()<0 && conn.adie_unsafe && writes==i);
 }
 xtal_setup();busy_cycles=0;assert(!run());restored();assert(!conn.adie_xtal_busy_mask);
 xtal_setup();xtal_fast=true;xtal_response[0]=response;
 assert(run()==-EAGAIN);restored();assert(conn.adie_busy_seen && !conn.adie_xtal_valid);
 xtal_setup();xtal_fast=true;xtal_response[1]=xtal_response[0];
 assert(run()==-EAGAIN);restored();assert(conn.adie_xtal_valid==1 && conn.adie_xtal_read==3);
 xtal_setup();xtal_response[1]=xtal_response[0];assert(!run());restored();
 for(unsigned i=2;i<=3;i++) {
  xtal_setup();transfer_stuck=i;assert(run()==-ETIMEDOUT && conn.adie_unsafe);
  assert(writes==1+i*2 && conn.adie_reset_dirty && !conn.adie_complete);
 }
 puts("PASS: actual two XTAL reads,per-transfer freshness,all guard/owner losses,"
      "9 dropped writes,45 write-time faults and each XTAL busy timeout");
}
'''
with tempfile.TemporaryDirectory() as tmp:
    path = Path(tmp)
    (path / 'test.c').write_text(harness)
    subprocess.run(['cc', '-O1', '-Wall', '-Wextra', '-Werror',
                    '-fsanitize=undefined', '-fno-sanitize-recover=all',
                    str(path / 'test.c'), '-o', str(path / 'test')], check=True)
    subprocess.run([str(path / 'test')], check=True)
