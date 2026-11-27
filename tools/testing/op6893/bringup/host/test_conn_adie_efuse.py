#!/usr/bin/env python3
# SPDX-License-Identifier: GPL-2.0-only
"""Actual read-mode engine kick/completion; private data addresses are forbidden."""
from pathlib import Path
import runpy
import subprocess
import tempfile

base = runpy.run_path(str(Path(__file__).with_name('test_conn_adie_efuse_ctrl.py')))['harness']
base = base[:base.index('int main(void) {')]
base = base.replace('owner_reads[16384]', 'owner_reads[262144]')
base = base.replace('static bool ctrl_change;',r'''static bool ctrl_change;
static bool engine_started,engine_invalid,engine_stuck,engine_rebusy,engine_late;
static unsigned engine_reads,engine_delay,engine_writes,engine_corrupt,engine_clock_jump;
static u32 engine_extra;
static u32 engine_read(void) {
 if(!engine_started)return efuse_control;
 unsigned n=++engine_reads;
 if(engine_late && n==3)adie_clock+=250000000;
 u32 value=5;
 if(engine_stuck || n<=engine_delay || (engine_rebusy && n==3))value|=BIT(30);
 else if(!engine_invalid)value|=BIT(29);
 if(n==engine_corrupt)value^=engine_extra;
 return value;
}''',1)
base = base.replace('value==0xb108 || value==0xb02c', 'value==0xa108 || value==0xb108 || value==0xb02c',1)
base = base.replace('  if(writing) {',r'''  if(addr==0xa108) {
   assert(value==(5U|BIT(30)) && !(value&0x23ff00c0));
   assert(conn.adie_efuse_pending && conn.adie_efuse_issued && !engine_writes);
   assert(!spi[3] && conn.adie_fm_dirty && conn.adie_prefix_dirty==3);
  } else if(writing) {''',1)
base = base.replace('   if(writing)analog[bit]=value;',r'''   if(addr==0xa108) {
    engine_started=true;engine_writes++;
    if(engine_clock_jump)adie_clock_step=engine_clock_jump;
   } else if(writing)analog[bit]=value;''',1)
base = base.replace('ctrl_reads++;spi[0x58/4]=efuse_control ^', 'ctrl_reads++;spi[0x58/4]=engine_read() ^',1)
base = base.replace(' if(p==spi+3) {\n  assert(!inaccessible',
                    ' if(p==spi+3) {\n  assert(!conn.adie_efuse_pending);\n  assert(!inaccessible',1)
harness = base+r'''
static void engine_setup(void) {
 ctrl_setup();conn.adie_efuse_requested=true;efuse_control=5;
 engine_started=engine_invalid=engine_stuck=engine_rebusy=engine_late=false;
 engine_reads=engine_writes=engine_corrupt=engine_extra=engine_clock_jump=0;engine_delay=1;
 adie_clock=0;adie_clock_step=1000;
}
int main(void) {
 engine_setup();assert(!run());restored();unsigned total_guards=guards,total_mail=mail_reads;
 assert(writes==67 && transfers==30 && engine_writes==1 && engine_reads==3);
 assert(conn.adie_efuse_complete && !conn.adie_efuse_pending && conn.adie_efuse_busy_seen);
 assert(!conn.adie_efuse_changed);
 assert(conn.adie_efuse_confirmed==2 && conn.adie_efuse_transfers==7 && conn.adie_efuse_polls==3);
 assert(conn.adie_efuse_last==(5U|BIT(29)) && conn.adie_fm_restored && conn.adie_complete);
 for(unsigned n=1;n<=total_guards;n++) {
  engine_setup();guardfail=n;assert(run()<0 && conn.adie_unsafe && !conn.adie_complete);
 }
 for(unsigned n=1;n<=total_mail;n++) {
  engine_setup();mail_loss=n;assert(run()<0 && conn.adie_unsafe && !conn.adie_complete);
 }
 for(unsigned n=1;n<=67;n++) {
  engine_setup();dropwrite=n;assert(run()<0 && !conn.adie_complete);
  if(n>=2 && n<=38){restored();assert(!conn.adie_efuse_pending && !mailbox);}
  else assert(conn.adie_unsafe || conn.adie_addr_dirty);
 }
 for(unsigned n=38;n<=51;n++)for(unsigned kind=1;kind<=16;kind++) {
  engine_setup();losswrite=n;losstype=kind;assert(run()<0 && conn.adie_unsafe);
  assert(writes==n && conn.adie_fm_dirty && conn.adie_prefix_dirty==3 && conn.adie_mailbox_dirty);
 }
 for(unsigned n=18;n<=24;n++) {
  engine_setup();stuck_transfer=n;assert(run()==-ETIMEDOUT && conn.adie_efuse_pending && conn.adie_unsafe);
 }
 engine_setup();engine_delay=0;busy_cycles=0;assert(!run());restored();
 assert(!conn.adie_efuse_busy_seen && !conn.adie_efuse_spi_busy_count && conn.adie_efuse_confirmed==2);
 engine_setup();engine_rebusy=true;assert(!run());restored();assert(engine_reads==5 && conn.adie_efuse_confirmed==2);
 engine_setup();engine_stuck=true;assert(run()==-ETIMEDOUT && conn.adie_efuse_pending && conn.adie_unsafe);
 assert(engine_reads<=70 && conn.adie_efuse_polls==engine_reads);
 engine_setup();engine_invalid=true;assert(run()==-ENODATA && conn.adie_efuse_pending && conn.adie_unsafe);
 engine_setup();engine_delay=0;engine_invalid=true;assert(run()==-ETIMEDOUT && conn.adie_efuse_pending);
 engine_setup();engine_late=true;assert(run()==-ETIMEDOUT && conn.adie_efuse_pending && !conn.adie_efuse_complete);
 assert(conn.adie_efuse_confirmed==1 && engine_reads==3);
 engine_setup();engine_clock_jump=250000000;assert(run()==-ETIMEDOUT && writes==39 && !engine_reads);
 assert(conn.adie_efuse_pending && !strcmp(conn.failure_stage,"adie-efuse-deadline"));
 for(unsigned bit=0;bit<32;bit++) {
  if(bit==29 || bit==30)continue;
  engine_setup();engine_corrupt=1;engine_extra=BIT(bit);
  assert(run()==-EIO && conn.adie_efuse_pending && conn.adie_unsafe);
  assert(conn.adie_efuse_changed==BIT(bit) && engine_reads==1);
 }
 for(unsigned n=19;n<=23;n+=2) {
  engine_setup();corrupt_transfer=n;assert(run()==-ENODEV && conn.adie_efuse_pending && conn.adie_unsafe);
 }
 engine_setup();efuse_control|=BIT(29);assert(run()==-EINVAL);restored();assert(!engine_writes);
 engine_setup();efuse_control|=BIT(16);assert(run()==-EINVAL);restored();assert(!engine_writes);
 puts("PASS: actual read-mode efuse engine,67 dropped writes,224 write faults,all guard/mailbox points,"
      "7 SPI timeouts,wall-clock deadline,poll cap,fast completion,busy reassertion,invalid data,30 control mutations,stale valid refusal");
}
'''
with tempfile.TemporaryDirectory() as tmp:
    path = Path(tmp)
    (path / 'test.c').write_text(harness)
    subprocess.run(['cc', '-O1', '-Wall', '-Wextra', '-Werror', '-Wno-misleading-indentation',
                    '-fsanitize=undefined', '-fno-sanitize-recover=all',
                    str(path / 'test.c'), '-o', str(path / 'test')], check=True)
    subprocess.run([str(path / 'test')], check=True)
