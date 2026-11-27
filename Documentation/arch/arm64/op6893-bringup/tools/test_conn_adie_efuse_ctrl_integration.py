#!/usr/bin/env python3
# SPDX-License-Identifier: GPL-2.0-only
"""Control-only TOP reads inside real FM/prefix/mailbox lifetime."""
from pathlib import Path
import runpy
import subprocess
import tempfile

base = runpy.run_path(str(Path(__file__).with_name('test_conn_adie_fm_integration.py')))['harness']
base = base[:base.index('int main(void) {')]
base = base.replace('static u32 therm[10],gpt[15];',
                    'static u32 therm[10],gpt[15],efuse_control;\n'
                    'static unsigned ctrl_reads;\nstatic bool ctrl_change;\n'
                    'static bool ctrl_requested(void);',1)
base = base.replace('addr==0xb02c || addr==0xb064 || addr==0xb0bc',
                    'addr==0xb108 || addr==0xb02c || addr==0xb064 || addr==0xb0bc',1)
needle='adie_spi[0x58/4]=addr==0xb02c?adie_response:analog[addr==0xb0bc];'
assert needle in base
base = base.replace(needle,r'''if(addr==0xb108) {
      assert(ctrl_requested() && fm_dirty() && !adie_spi[3] && *MAILBOX==adie_response);
      ctrl_reads++;adie_spi[0x58/4]=efuse_control ^ ((ctrl_change && ctrl_reads==2)?1U:0U);
     } else adie_spi[0x58/4]=addr==0xb02c?adie_response:analog[addr==0xb0bc];''',1)
harness = base+r'''
static bool ctrl_requested(void) {return conn.adie_efuse_ctrl_requested;}
static void ctrl_setup(void) {
 fm_setup();efuse_control=0x20000005;ctrl_reads=0;ctrl_change=false;
}
static int ctrl_run(void) {return rail_cycle_store(&dev,NULL,"adie-efuse-ctrl-read",20);}
int main(void) {
 char output[4096];ctrl_setup();assert(ctrl_run()==20);stopped();
 assert(ctrl_reads==2 && transfers==23 && adie_writes==51 && fm_writes==2);
 assert(conn.adie_efuse_ctrl_stable && conn.adie_efuse_ctrl_read==15 && conn.adie_efuse_ctrl_valid==15);
 assert(conn.adie_fm_restored && conn.adie_prefix_restored==3 && conn.adie_mailbox_restored);
 assert(conn.adie_complete && conn.sema_released);
 int len=adie_status_show(&dev,NULL,output);assert(len>0 && len<4096);
 assert(strstr(output,"efuse_ctrl_stable=1 efuse_ctrl_flags0=0x20000000 efuse_ctrl_flags1=0x20000000"));
 assert(!strstr(output,"20000005"));
 assert(ctrl_run()==-EALREADY && adie_writes==51 && fm_writes==2);
 for(unsigned n=1;n<=51;n++) {
  ctrl_setup();adie_drop=n;assert(ctrl_run()<0 && !conn.adie_complete);
  if(n>=2 && n<=36){stopped();assert(!conn.adie_fm_dirty && !*MAILBOX);}
  else retained();
 }
 for(unsigned n=29;n<=36;n++)for(unsigned kind=1;kind<=4;kind++) {
  ctrl_setup();adie_loss=n;adie_change=kind;assert(ctrl_run()<0);retained();
  assert(adie_writes==n && fm_writes==1 && conn.adie_fm_dirty && conn.adie_prefix_dirty==3);
  assert(!sema_writes && config_writes==36 && rgu_writes==4 && remap_writes==4);
 }
 for(unsigned n=14;n<=17;n++) {
  ctrl_setup();stuck_transfer=n;assert(ctrl_run()==-ETIMEDOUT);retained();
  assert(fm_writes==1 && conn.adie_fm_dirty && !sema_writes && *MAILBOX==adie_response);
 }
 for(unsigned mode=0;mode<4;mode++) {
  ctrl_setup();efuse_control=mode==0?BIT(30):(mode<<6);
  assert(ctrl_run()==-EBUSY);retained();assert(ctrl_reads==1 && fm_writes==1 && !sema_writes);
 }
 ctrl_setup();ctrl_change=true;assert(ctrl_run()==-EBUSY);retained();
 assert(ctrl_reads==2 && conn.adie_prefix_dirty==3 && conn.adie_fm_dirty && !sema_writes);
 ctrl_setup();corrupt_transfer=14;assert(ctrl_run()==-ENODEV);stopped();assert(conn.adie_fm_restored);
 ctrl_setup();adie_fast=true;assert(ctrl_run()==20);stopped();assert(!conn.adie_efuse_ctrl_busy_mask);
 ctrl_setup();adie_fast=true;adie_drop=32;assert(ctrl_run()==-EAGAIN);retained();
 assert(conn.adie_fm_restored && conn.adie_prefix_dirty && conn.adie_mailbox_dirty);
 ctrl_setup();corrupt_transfer=14;fm_drop=2;assert(ctrl_run()==-ENODEV);retained();
 assert(conn.adie_fm_cleanup && !strcmp(conn.failure_stage,"adie-efuse-response"));
 ctrl_setup();config_drop_write=37;assert(ctrl_run()==-EIO);retained();
 assert(conn.adie_complete && conn.adie_fm_restored && conn.sema_released && conn.spi_config_dirty);
 puts("PASS: nested control reads,51 dropped writes,32 write-time faults,4 timeouts,"
      "held FM/mailbox,control-state refusal,no-busy freshness,first-error retention,masked status and outer cleanup");
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
