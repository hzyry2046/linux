#!/usr/bin/env python3
# SPDX-License-Identifier: GPL-2.0-only
"""Read-engine completion inside all real parents; uncertain kick retains power."""
from pathlib import Path
import runpy
import subprocess
import tempfile

base = runpy.run_path(str(Path(__file__).with_name('test_conn_adie_efuse_ctrl_integration.py')))['harness']
base = base[:base.index('int main(void) {')]
base = base.replace('static bool ctrl_change;',r'''static bool ctrl_change;
static bool engine_started,engine_stuck,engine_invalid,engine_late;
static unsigned engine_reads,engine_writes,engine_delay,engine_clock_jump,engine_corrupt;
static u32 engine_extra;
static bool engine_pending(void);
static u32 engine_read(void) {
 if(!engine_started)return efuse_control;
 unsigned n=++engine_reads;
 if(engine_late && n==3)adie_clock+=250000000;
 u32 value=5;
 if(engine_stuck || n<=engine_delay)value|=BIT(30);
 else if(!engine_invalid)value|=BIT(29);
 if(n==engine_corrupt)value^=engine_extra;
 return value;
}''',1)
base = base.replace('    if(addr==0xa064 || addr==0xa0bc) {',r'''    if(addr==0xa108) {
     assert(engine_pending() && !engine_writes && value==(5U|BIT(30)) && !(value&0x23ff00c0));
     assert(fm_dirty() && !adie_spi[3] && *MAILBOX==adie_response && prefix_dirty()==3);
     engine_started=true;engine_writes++;
     if(engine_clock_jump)adie_clock_step=engine_clock_jump;
    } else if(addr==0xa064 || addr==0xa0bc) {''',1)
base = base.replace('ctrl_reads++;adie_spi[0x58/4]=efuse_control ^','ctrl_reads++;adie_spi[0x58/4]=engine_read() ^',1)
base = base.replace(' if(p==adie_spi+3) {\n  held_strap();',' if(p==adie_spi+3) {\n  assert(!engine_pending());\n  held_strap();',1)
harness = base+r'''
static bool engine_pending(void) {return conn.adie_efuse_pending;}
static void engine_setup(void) {
 ctrl_setup();efuse_control=5;engine_started=engine_stuck=engine_invalid=engine_late=false;
 engine_reads=engine_writes=engine_clock_jump=engine_corrupt=engine_extra=0;engine_delay=1;
 adie_clock=0;adie_clock_step=1000;
}
static int engine_run(void) {return rail_cycle_store(&dev,NULL,"adie-efuse-cycle",16);}
int main(void) {
 char output[4096];engine_setup();assert(engine_run()==16);stopped();
 assert(adie_writes==65 && fm_writes==2 && engine_writes==1 && engine_reads==3);
 assert(conn.adie_efuse_complete && !engine_pending() && conn.adie_efuse_confirmed==2);
 assert(conn.adie_fm_restored && conn.adie_prefix_restored==3 && conn.sema_released);
 assert(efuse_status_show(&dev,NULL,output)>0 && strstr(output,"pending=0 complete=1"));
 assert(strstr(output,"changed=0") && !conn.adie_efuse_changed);
 assert(strstr(output,"flags=0x20000000") && !strstr(output,"20000005"));
 assert(adie_status_show(&dev,NULL,output)>0 && !strstr(output,"20000005"));
 assert(engine_run()==-EALREADY && engine_writes==1);
 for(unsigned n=1;n<=65;n++) {
  engine_setup();adie_drop=n;assert(engine_run()<0 && !conn.adie_complete);
  if(n>=2 && n<=37){stopped();assert(!engine_pending());}
  else retained();
 }
 for(unsigned n=37;n<=50;n++)for(unsigned kind=1;kind<=4;kind++) {
  engine_setup();adie_loss=n;adie_change=kind;assert(engine_run()<0);retained();
  assert(adie_writes==n && fm_writes==1 && conn.adie_fm_dirty && conn.adie_prefix_dirty==3);
  assert(!sema_writes && config_writes==36 && rgu_writes==4 && remap_writes==4);
 }
 for(unsigned n=18;n<=24;n++) {
  engine_setup();stuck_transfer=n;assert(engine_run()==-ETIMEDOUT);retained();
  assert(engine_pending() && fm_writes==1 && !sema_writes);
 }
 engine_setup();engine_stuck=true;assert(engine_run()==-ETIMEDOUT);retained();
 assert(engine_pending() && engine_reads<=70 && !sema_writes && fm_writes==1);
 engine_setup();engine_invalid=true;assert(engine_run()==-ENODATA);retained();assert(engine_pending());
 engine_setup();engine_late=true;assert(engine_run()==-ETIMEDOUT);retained();
 assert(engine_pending() && conn.adie_efuse_confirmed==1 && engine_reads==3 && fm_writes==1);
 engine_setup();engine_clock_jump=250000000;assert(engine_run()==-ETIMEDOUT);retained();
 assert(adie_writes==38 && !engine_reads && !sema_writes && engine_pending());
 for(unsigned bit=0;bit<32;bit++) {
  if(bit==29 || bit==30)continue;
  engine_setup();engine_corrupt=1;engine_extra=BIT(bit);
  assert(engine_run()==-EIO);retained();assert(engine_pending() && fm_writes==1 && !sema_writes);
  assert(conn.adie_efuse_changed==BIT(bit) && engine_reads==1);
  char expected[40];snprintf(expected,sizeof(expected),"changed=%#x\n",BIT(bit));
  assert(efuse_status_show(&dev,NULL,output)>0 && strstr(output,expected));
  char saved[4096];strcpy(saved,output);
  assert(efuse_status_show(&dev,NULL,output)>0 && !strcmp(saved,output));

 }
 engine_setup();engine_delay=0;adie_fast=true;assert(engine_run()==16);stopped();
 assert(conn.adie_efuse_complete && !conn.adie_efuse_busy_seen && !conn.adie_efuse_spi_busy_count);
 engine_setup();efuse_control|=BIT(29);assert(engine_run()==-EINVAL);stopped();assert(!engine_writes);
 engine_setup();efuse_control|=BIT(16);assert(engine_run()==-EINVAL);stopped();assert(!engine_writes);
 engine_setup();fm_drop=2;assert(engine_run()==-EIO);retained();
 assert(conn.adie_efuse_complete && !engine_pending() && conn.adie_fm_dirty && !sema_writes);
 engine_setup();config_drop_write=37;assert(engine_run()==-EIO);retained();
 assert(conn.adie_efuse_complete && conn.adie_complete && conn.sema_released && conn.spi_config_dirty);
 puts("PASS: nested read engine,65 dropped writes,56 write faults,7 SPI timeouts,"
      "deadline/poll cap,invalid/changed controls,masked status,no cleanup before engine completion,outer failures and one-shot");
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
