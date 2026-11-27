#!/usr/bin/env python3
# SPDX-License-Identifier: GPL-2.0-only
"""Fixed config read command and whole nested cleanup containment."""
from pathlib import Path
import runpy
import subprocess
import tempfile

base = runpy.run_path(str(Path(__file__).with_name('test_conn_adie_integration.py')))['harness']
base = base[:base.index('int main(void) {')]
base = base.replace('static u32 adie_spi[0x5c/4],adie_response;',
                    'static u32 adie_spi[0x5c/4],adie_response;\n'
                    'static unsigned transfers,stuck_transfer,corrupt_transfer;')
base = base.replace('adie_spi[0x50/4]==0xb02c && !adie_fired',
                    '(adie_spi[0x50/4]==0xb02c || adie_spi[0x50/4]==0xb064 || adie_spi[0x50/4]==0xb0bc)')
base = base.replace('adie_fired=true;adie_spi[0x58/4]=adie_response;',
                    'adie_fired=true;adie_reads=0;transfers++;'
                    'adie_spi[0x58/4]=adie_spi[0x50/4]==0xb02c?adie_response:(adie_spi[0x50/4]==0xb064?0:0x20);'
                    'if(transfers==stuck_transfer)adie_stuck=true;'
                    'if(transfers==corrupt_transfer)adie_spi[0x58/4]=0xdeadbeef;')
harness = base + r'''
static void config_setup(void) {adie_setup();transfers=stuck_transfer=corrupt_transfer=0;}
static int config_run(void) {return rail_cycle_store(&dev,NULL,"adie-config-read",16);}
int main(void) {
 char output[4096];
 config_setup();assert(config_run()==16);stopped();
 assert(conn.adie_config_stable && conn.adie_complete && adie_writes==21 && transfers==9);
 assert(conn.adie_config_valid==255 && conn.sema_released);
 assert(adie_status_show(&dev,NULL,output)>0 && strstr(output,"config_stable=1"));
 assert(config_run()==-EALREADY && adie_writes==21);
 for(unsigned n=1;n<=21;n++) {
  config_setup();adie_drop=n;assert(config_run()<0 && !conn.adie_complete);
  if(n>=2 && n<=19)stopped();
  else {
   retained();assert(conn.sema_pending && conn.sema_unsafe && conn.strap_unsafe);
   assert(!sema_writes && config_writes==36 && rgu_writes==4 && remap_writes==4);
  }
 }
 for(unsigned n=1;n<=21;n++)for(unsigned kind=1;kind<=4;kind++) {
  config_setup();adie_loss=n;adie_change=kind;assert(config_run()<0);retained();
  assert(adie_writes==n && conn.adie_unsafe && conn.sema_pending && conn.strap_unsafe);
  assert(!sema_writes && config_writes==36 && rgu_writes==4 && remap_writes==4);
 }
 for(unsigned n=2;n<=9;n++) {
  config_setup();stuck_transfer=n;assert(config_run()==-ETIMEDOUT);retained();
  assert(!sema_writes && adie_writes==1+2*n && config_adie==3);
 }
 config_setup();corrupt_transfer=6;assert(config_run()==-EIO);stopped();
 assert(!conn.adie_config_stable && !strcmp(conn.failure_stage,"adie-config-data"));
 config_setup();config_drop_write=37;assert(config_run()==-EIO);retained();
 assert(conn.adie_complete && conn.sema_released && conn.spi_config_dirty);
 config_setup();conn.domain_allowed=false;assert(config_run()==-EOPNOTSUPP && !conn.attempted);
 puts("PASS: nested fixed config reads,21 dropped writes,84 guard faults,8 timeouts,"
      "unstable-value cleanup,outer restoration failure and one-shot command");
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
