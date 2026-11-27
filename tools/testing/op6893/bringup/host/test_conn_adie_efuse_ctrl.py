#!/usr/bin/env python3
# SPDX-License-Identifier: GPL-2.0-only
"""Actual fixed control reads under held FM, with independent TOP register state."""
from pathlib import Path
import runpy
import subprocess
import tempfile

base = runpy.run_path(str(Path(__file__).with_name('test_conn_adie_fm.py')))['harness']
base = base[:base.index('int main(void) {')]
base = base.replace('static unsigned lost_writes;',
                    'static u32 efuse_control;\nstatic unsigned ctrl_reads;\n'
                    'static bool ctrl_change;\nstatic unsigned lost_writes;',1)
base = base.replace('if(losstype>=12)sema', 'if(losstype==16)spi[3]=2;\n if(losstype>=12 && losstype<=15)sema',1)
base = base.replace('value==0xb02c || value==0xb064', 'value==0xb108 || value==0xb02c || value==0xb064',1)
base = base.replace('addr==0xb02c || addr==0xb064 || addr==0xb0bc',
                    'addr==0xb108 || addr==0xb02c || addr==0xb064 || addr==0xb0bc',1)
needle='else spi[0x58/4]=addr==0xb02c?response:analog[addr==0xb0bc];'
assert needle in base
base = base.replace(needle,r'''else if(addr==0xb108) {
    assert(!spi[3] && conn.adie_fm_dirty && conn.adie_fm_applied && mailbox==response);
    ctrl_reads++;spi[0x58/4]=efuse_control ^ ((ctrl_change && ctrl_reads==2)?1U:0U);
   } else spi[0x58/4]=addr==0xb02c?response:analog[addr==0xb0bc];''',1)
harness = base+r'''
static void ctrl_setup(void) {
 fm_setup();conn.adie_efuse_ctrl_requested=true;
 efuse_control=0x20000005;ctrl_reads=0;ctrl_change=false;
}
int main(void) {
 ctrl_setup();assert(!run());restored();unsigned total_guards=guards,total_mail=mail_reads;
 assert(writes==53 && transfers==23 && ctrl_reads==2 && conn.adie_complete);
 assert(conn.adie_efuse_ctrl_read==15 && conn.adie_efuse_ctrl_valid==15);
 assert(conn.adie_efuse_ctrl_busy_mask==15 && conn.adie_efuse_ctrl_stable);
 assert(conn.adie_efuse_ctrl_value[0]==response && conn.adie_efuse_ctrl_value[2]==response);
 assert(conn.adie_efuse_ctrl_value[1]==efuse_control && conn.adie_efuse_ctrl_value[3]==efuse_control);
 assert(conn.adie_fm_restored && conn.adie_prefix_restored==3 && conn.adie_mailbox_restored);
 for(unsigned n=1;n<=total_guards;n++) {
  ctrl_setup();guardfail=n;assert(run()<0 && conn.adie_unsafe && !conn.adie_complete);
 }
 for(unsigned n=1;n<=total_mail;n++) {
  ctrl_setup();mail_loss=n;assert(run()<0 && conn.adie_unsafe && !conn.adie_complete);
 }
 for(unsigned n=1;n<=53;n++) {
  ctrl_setup();dropwrite=n;assert(run()<0 && !conn.adie_complete);
  if(n>=2 && n<=37){restored();assert(!conn.adie_fm_dirty && !mailbox);}
  else assert(conn.adie_unsafe || conn.adie_addr_dirty);
 }
 for(unsigned n=30;n<=37;n++)for(unsigned kind=1;kind<=16;kind++) {
  ctrl_setup();losswrite=n;losstype=kind;assert(run()<0 && conn.adie_unsafe);
  assert(writes==n && conn.adie_fm_dirty && conn.adie_prefix_dirty==3 && conn.adie_mailbox_dirty);
 }
 for(unsigned n=14;n<=17;n++) {
  ctrl_setup();stuck_transfer=n;assert(run()==-ETIMEDOUT && conn.adie_unsafe);
  assert(conn.adie_fm_dirty && conn.adie_prefix_dirty==3 && mailbox==response);
 }
 for(unsigned mode=0;mode<4;mode++) {
  ctrl_setup();efuse_control=mode==0?BIT(30):(mode<<6);
  assert(run()==-EBUSY && conn.adie_unsafe && ctrl_reads==1);
  assert(conn.adie_fm_dirty && conn.adie_prefix_dirty==3 && writes==33);
 }
 ctrl_setup();ctrl_change=true;assert(run()==-EBUSY && conn.adie_unsafe && ctrl_reads==2);
 assert(conn.adie_fm_dirty && writes==37 && !conn.adie_efuse_ctrl_stable);
 for(unsigned n=14;n<=16;n+=2) {
  ctrl_setup();corrupt_transfer=n;assert(run()==-ENODEV);restored();
  assert(conn.adie_fm_restored && !conn.adie_efuse_ctrl_stable);
 }
 ctrl_setup();busy_cycles=0;assert(!run());restored();assert(!conn.adie_efuse_ctrl_busy_mask);
 ctrl_setup();busy_cycles=0;dropwrite=33;
 assert(run()==-EAGAIN && conn.adie_prefix_dirty && conn.adie_unsafe);
 assert(conn.adie_fm_restored && conn.adie_mailbox_dirty);
 ctrl_setup();corrupt_transfer=14;dropwrite=32;
 assert(run()==-ENODEV && conn.adie_fm_cleanup && conn.adie_fm_dirty);
 assert(!strcmp(conn.failure_stage,"adie-efuse-response"));
 puts("PASS: actual efuse control-only reads,53 dropped writes,128 write-time faults,"
      "all guard/mailbox points,4 timeouts,inherited kick/modes,changed controls,bad IDs,stale response and first-error retention");
}
'''
with tempfile.TemporaryDirectory() as tmp:
    path = Path(tmp)
    (path / 'test.c').write_text(harness)
    subprocess.run(['cc', '-O1', '-Wall', '-Wextra', '-Werror', '-Wno-misleading-indentation',
                    '-fsanitize=undefined', '-fno-sanitize-recover=all',
                    str(path / 'test.c'), '-o', str(path / 'test')], check=True)
    subprocess.run([str(path / 'test')], check=True)
