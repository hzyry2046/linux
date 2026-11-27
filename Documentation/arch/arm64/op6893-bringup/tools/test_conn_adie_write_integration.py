#!/usr/bin/env python3
# SPDX-License-Identifier: GPL-2.0-only
"""Actual nested write command, stateful analog model and cleanup containment."""
from pathlib import Path
import runpy
import subprocess
import tempfile

base = runpy.run_path(str(Path(__file__).with_name('test_conn_adie_integration.py')))['harness']
base = base[:base.index('int main(void) {')]
base = base.replace('static u32 adie_spi[0x5c/4],adie_response;',
                    'static u32 adie_spi[0x5c/4],adie_response,analog[2];\n'
                    'static unsigned transfers, stuck_transfer;\n'
                    'static bool analog_dirty(void);')
base = base.replace('assert(value==2 || value==3);config_adie=value;',
                    'assert(value==2 || value==3);'
                    'if(value==2)assert(!analog_dirty() && analog[0]==0xf668fff5);config_adie=value;')
old = '''else {assert(!value && config_adie==3 && adie_spi[0x50/4]==0xb02c && !adie_fired);
    adie_fired=true;adie_spi[0x58/4]=adie_response;}'''
new = r'''else {
    assert(config_adie==3);u32 addr=adie_spi[0x50/4];
    if(addr==0xaa18) {
     assert(analog_dirty() && (value==0xf6e8fff5 || value==0xf668fff5));analog[0]=value;
    } else {
     assert(!value && (addr==0xb02c || addr==0xba18 || addr==0xba1c));
     adie_spi[0x58/4]=addr==0xb02c?adie_response:analog[(addr-0xba18)/4];
    }
    transfers++;adie_fired=true;adie_reads=0;if(transfers==stuck_transfer)adie_stuck=true;
   }'''
assert old in base
base = base.replace(old, new)
harness = base + r'''
static bool analog_dirty(void) {return conn.adie_write_dirty;}
static void write_setup(void) {
 adie_setup();transfers=stuck_transfer=0;adie_response=0x66358a11;
 analog[0]=0xf668fff5;analog[1]=0x55555fff;
}
static int write_run(void) {return rail_cycle_store(&dev,NULL,"adie-write-cycle",16);}
int main(void) {
 char output[4096];
 write_setup();assert(write_run()==16);stopped();
 assert(conn.adie_write_applied && conn.adie_write_restored && conn.adie_complete);
 assert(!conn.adie_write_dirty && analog[0]==0xf668fff5 && adie_writes==19 && transfers==8);
 assert(conn.sema_released && conn.adie_reset_restored);
 assert(adie_status_show(&dev,NULL,output)>0 && strstr(output,"write_applied=1 write_restored=1 write_dirty=0"));
 assert(write_run()==-EALREADY && adie_writes==19);
 for(unsigned n=1;n<=19;n++) {
  write_setup();adie_drop=n;assert(write_run()<0 && !conn.adie_complete);
  if(n>=2 && n<=11) {stopped();assert(!conn.adie_write_dirty && analog[0]==0xf668fff5);}
  else {
   retained();assert(conn.sema_pending && conn.sema_unsafe && conn.strap_unsafe);
   assert(!sema_writes && config_writes==36 && rgu_writes==4 && remap_writes==4);
  }
 }
 for(unsigned n=1;n<=19;n++)for(unsigned kind=1;kind<=4;kind++) {
  write_setup();adie_loss=n;adie_change=kind;assert(write_run()<0);retained();
  assert(adie_writes==n && conn.adie_unsafe && conn.sema_pending && conn.strap_unsafe);
  assert(!sema_writes && config_writes==36 && rgu_writes==4 && remap_writes==4);
 }
 for(unsigned n=4;n<=8;n++) {
  write_setup();stuck_transfer=n;assert(write_run()==-ETIMEDOUT);retained();
  assert(!sema_writes && adie_writes==1+2*n && config_adie==3 && conn.adie_write_dirty);
 }
 write_setup();config_drop_write=37;assert(write_run()==-EIO);retained();
 assert(conn.adie_complete && conn.adie_write_restored && conn.sema_released && conn.spi_config_dirty);
 write_setup();conn.domain_allowed=false;assert(write_run()==-EOPNOTSUPP && !conn.attempted);
 write_setup();conn.emi_valid=false;assert(write_run()==-EINVAL && !conn.attempted);
 puts("PASS: nested A18 write/restore,one-shot routing,19 dropped writes,76 guard losses,"
      "5 busy timeouts,analog restore before reset/unlock and outer restore failure");
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
