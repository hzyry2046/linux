#!/usr/bin/env python3
# SPDX-License-Identifier: GPL-2.0-only
"""Fixed XTAL command routing and containment through the whole power cycle."""
from pathlib import Path
import runpy
import subprocess
import tempfile

base = runpy.run_path(str(Path(__file__).with_name('test_conn_adie_integration.py')))['harness']
base = base[:base.index('int main(void) {')]
base = base.replace('static u32 adie_spi[0x5c/4],adie_response;',
                    'static u32 adie_spi[0x5c/4],adie_response;\n'
                    'static unsigned transfers, stuck_transfer;')
base = base.replace('adie_spi[0x50/4]==0xb02c && !adie_fired',
                    'adie_spi[0x50/4]==(transfers?0xba18+(transfers-1)*4:0xb02c)')
base = base.replace('adie_fired=true;adie_spi[0x58/4]=adie_response;',
                    'adie_fired=true;adie_reads=0;'
                    'adie_spi[0x58/4]=transfers?0x12340000+transfers:adie_response;'
                    'transfers++;if(transfers==stuck_transfer)adie_stuck=true;')
harness = base + r'''
static void xtal_setup(void) {adie_setup();transfers=stuck_transfer=0;}
static int xtal_run(void) {return rail_cycle_store(&dev,NULL,"adie-xtal-cycle",15);}
int main(void) {
 char output[4096];
 xtal_setup();assert(xtal_run()==15);stopped();
 assert(conn.adie_xtal_valid==3 && conn.adie_complete && adie_writes==9 && transfers==3);
 assert(conn.sema_released && conn.adie_reset_restored);
 assert(adie_status_show(&dev,NULL,output)>0 && strstr(output,"xtal_valid=0x3"));
 unsigned saved_writes=adie_writes;
 assert(xtal_run()==-EALREADY && adie_writes==saved_writes && conn.adie_xtal_valid==3);
 for(unsigned n=1;n<=9;n++) {
  xtal_setup();adie_drop=n;assert(xtal_run()<0 && !conn.adie_complete);
  if(n>=2 && n<=7)stopped();
  else {retained();assert(conn.sema_pending && !sema_writes && config_writes==36);}
 }
 for(unsigned n=1;n<=9;n++)for(unsigned kind=1;kind<=4;kind++) {
  xtal_setup();adie_loss=n;adie_change=kind;assert(xtal_run()<0);retained();
  assert(adie_writes==n && conn.adie_unsafe && conn.sema_pending && conn.strap_unsafe);
  assert(!sema_writes && config_writes==36 && rgu_writes==4 && remap_writes==4);
 }
 for(unsigned n=2;n<=3;n++) {
  xtal_setup();stuck_transfer=n;assert(xtal_run()==-ETIMEDOUT);retained();
  assert(!sema_writes && adie_writes==1+2*n && config_adie==3);
 }
 xtal_setup();config_drop_write=37;assert(xtal_run()==-EIO);retained();
 assert(conn.adie_complete && conn.sema_released && conn.spi_config_dirty);
 puts("PASS: nested XTAL command,one-shot caching,9 dropped writes,36 guard losses,"
      "both busy timeouts,reset-before-unlock and outer restoration failure");
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
