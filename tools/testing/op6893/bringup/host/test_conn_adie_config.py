#!/usr/bin/env python3
# SPDX-License-Identifier: GPL-2.0-only
"""Actual fixed config reads with ID separators and repeatability checks."""
from pathlib import Path
import runpy
import subprocess
import tempfile

base = runpy.run_path(str(Path(__file__).with_name('test_conn_adie.py')))['harness']
base = base[:base.index('int main(void) {')]
base = base.replace('static u32 response;',
                    'static u32 response,config_value[2],corrupt_value;\n'
                    'static unsigned transfers,stuck_transfer,corrupt_transfer;')
base = base.replace('value==0xb02c || value==0x1234',
                    'value==0xb02c || value==0xb064 || value==0xb0bc || value==0x1234')
base = base.replace('spi[0x50/4]==0xb02c && !triggered',
                    '(spi[0x50/4]==0xb02c || spi[0x50/4]==0xb064 || spi[0x50/4]==0xb0bc)')
base = base.replace('triggered=true;spi[0x58/4]=response;',
                    'triggered=true;busy_reads=0;transfers++;stuck=transfers==stuck_transfer;'
                    'spi[0x58/4]=spi[0x50/4]==0xb02c?response:config_value[spi[0x50/4]==0xb0bc];'
                    'if(transfers==corrupt_transfer)spi[0x58/4]=corrupt_value;')
harness = base + r'''
static void config_setup(void) {
 setup();conn.adie_config_requested=true;response=0x66358a11;
 config_value[0]=0;config_value[1]=0x20;
 transfers=stuck_transfer=corrupt_transfer=0;corrupt_value=0xdeadbeef;
}
int main(void) {
 config_setup();assert(!run());restored();
 unsigned total_guards=guards,owners=owner_count,points[1024];
 memcpy(points,owner_reads,sizeof(points));
 assert(writes==21 && transfers==9 && conn.adie_complete && conn.adie_config_stable);
 assert(conn.adie_config_read==255 && conn.adie_config_valid==255 && conn.adie_config_busy_mask==255);
 for(unsigned i=0;i<8;i++)assert(conn.adie_config_value[i]==(i&1?response:config_value[!!(i&2)]));
 for(unsigned i=1;i<=total_guards;i++) {
  config_setup();guardfail=i;assert(run()<0 && conn.adie_unsafe && !conn.adie_complete);
 }
 for(unsigned i=0;i<owners;i++) {
  config_setup();lossread=points[i];losstype=3;assert(run()<0 && !conn.adie_complete);
 }
 for(unsigned i=1;i<=21;i++) {
  config_setup();dropwrite=i;assert(run()<0 && !conn.adie_complete);
  if(i>=2 && i<=19)restored();
 }
 for(unsigned i=1;i<=21;i++)for(unsigned kind=1;kind<=5;kind++) {
  config_setup();losswrite=i;losstype=kind;assert(run()<0 && conn.adie_unsafe && writes==i);
 }
 for(unsigned i=2;i<=9;i++) {
  config_setup();stuck_transfer=i;assert(run()==-ETIMEDOUT && writes==1+2*i && control==3);
 }
 config_setup();busy_cycles=0;assert(!run());restored();assert(!conn.adie_config_busy_mask);
 config_setup();busy_cycles=0;config_value[0]=response;
 assert(run()==-EAGAIN);restored();assert(!conn.adie_config_valid);
 config_setup();config_value[0]=config_value[1]=0;
 assert(!run());restored();assert(conn.adie_config_stable);
 for(unsigned i=3;i<=9;i+=2) {
  config_setup();corrupt_transfer=i;assert(run()==-ENODEV);restored();assert(!conn.adie_config_stable);
 }
 for(unsigned i=6;i<=8;i+=2) {
  config_setup();corrupt_transfer=i;assert(run()==-EIO);restored();assert(!conn.adie_config_stable);
 }
 config_setup();corrupt_transfer=6;dropwrite=14;
 assert(run()==-EIO && conn.adie_reset_dirty && conn.adie_unsafe);
 assert(!strcmp(conn.failure_stage,"adie-config-data"));
 puts("PASS: actual two-round fixed config reads,ID separators,21 dropped writes,"
      "105 write-time faults,all guard/owner losses,8 timeouts,stale response,"
      "bad separator IDs,unstable values and original-error preservation");
}
'''
with tempfile.TemporaryDirectory() as tmp:
    path = Path(tmp)
    (path / 'test.c').write_text(harness)
    subprocess.run(['cc', '-O1', '-Wall', '-Wextra', '-Werror',
                    '-fsanitize=undefined', '-fno-sanitize-recover=all',
                    str(path / 'test.c'), '-o', str(path / 'test')], check=True)
    subprocess.run([str(path / 'test')], check=True)
