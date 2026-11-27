#!/usr/bin/env python3
# SPDX-License-Identifier: GPL-2.0-only
"""Experimental stable low-six-bit completion and reverse cleanup."""
from pathlib import Path
import runpy
import subprocess
import tempfile

base = runpy.run_path(str(Path(__file__).with_name('test_conn_adie_efuse.py')))['harness']
base = base[:base.index('int main(void) {')]
base = base.replace('static bool engine_started,', 'static u32 observe_delta[3];\nstatic bool engine_started,', 1)
base = base.replace('if(n==engine_corrupt)value^=engine_extra;',
                    'if(n<=3)value^=observe_delta[n-1];\n if(n==engine_corrupt)value^=engine_extra;', 1)
harness = base+r'''

static void observe_setup(void) {
 engine_setup();engine_delay=0;
 observe_delta[0]=observe_delta[1]=observe_delta[2]=0x3b;
 conn.adie_efuse_observe=true;conn.adie_efuse_stable_cycle=true;
}
static int observe_run(void) {return run();}
static void held(void) {
 assert(conn.adie_efuse_pending && conn.adie_unsafe && !conn.adie_efuse_complete);
 assert(!conn.adie_efuse_confirmed && conn.adie_fm_dirty && conn.adie_prefix_dirty==3);
 assert(conn.adie_mailbox_dirty && !conn.adie_reset_restored);
 
}
int main(void) {
 observe_setup();assert(observe_run()==0);restored();
 assert(conn.adie_efuse_observe_stable && conn.adie_efuse_observed==3);
 assert(engine_reads==3 && engine_writes==1 && conn.adie_efuse_transfers==7);
 assert(conn.adie_efuse_complete && !conn.adie_efuse_pending && conn.adie_efuse_confirmed==3);
 assert(conn.adie_efuse_observe_delta[0]==0x3b && conn.adie_efuse_observe_delta[2]==0x3b);
 
 for(unsigned n=40;n<=51;n++) {
  observe_setup();dropwrite=n;assert(observe_run()<0);held();
  assert(!conn.adie_efuse_observe_stable);
 }
 for(unsigned n=40;n<=51;n++)for(unsigned kind=1;kind<=16;kind++) {
  observe_setup();losswrite=n;losstype=kind;assert(observe_run()<0);held();
  assert(!conn.adie_efuse_observe_stable);
 }
 for(unsigned n=18;n<=24;n++) {
  observe_setup();stuck_transfer=n;assert(observe_run()==-ETIMEDOUT);held();
  assert(!conn.adie_efuse_observe_stable);
 }
 for(unsigned n=0;n<3;n++)for(unsigned bit=6;bit<32;bit++) {
  if(bit==29 || bit==30)continue;
  observe_setup();observe_delta[n]|=BIT(bit);assert(observe_run()==-EIO);held();
  assert(conn.adie_efuse_observed==n+1 && engine_reads==n+1 && !conn.adie_efuse_observe_stable);
 }
 for(unsigned n=1;n<3;n++)for(unsigned bit=0;bit<6;bit++) {
  observe_setup();observe_delta[n]^=BIT(bit);assert(observe_run()==-EIO);held();
  assert(conn.adie_efuse_observed==n+1 && !conn.adie_efuse_observe_stable);
 }
 for(unsigned n=1;n<=3;n++)for(unsigned bit=29;bit<=30;bit++) {
  observe_setup();engine_corrupt=n;engine_extra=BIT(bit);assert(observe_run()==-EIO);held();
  assert(conn.adie_efuse_observed==n && !conn.adie_efuse_observe_stable);
 }
 observe_setup();engine_late=true;assert(observe_run()==-ETIMEDOUT);held();
 assert(conn.adie_efuse_observed==2 && engine_reads==3 && !conn.adie_efuse_observe_stable);
 observe_setup();engine_clock_jump=250000000;assert(observe_run()==-ETIMEDOUT);held();
 assert(!conn.adie_efuse_observed && !engine_reads);
 observe_setup();observe_delta[0]=observe_delta[1]=observe_delta[2]=0;
 assert(observe_run()==0);restored();assert(conn.adie_efuse_observe_stable);
 observe_setup();efuse_control|=BIT(29);assert(observe_run()==-EINVAL);restored();assert(!engine_writes);

 for(unsigned n=52;n<=67;n++) {
  observe_setup();dropwrite=n;assert(observe_run()<0);
  assert(conn.adie_efuse_complete && !conn.adie_efuse_pending);
 }
 puts("PASS: standalone stable-cycle 3-sample completion/cleanup,all new dropped writes/guard faults,7 SPI timeouts,"
      "72 high-bit changes,12 low-bit instability,6 status faults,late deadline,no-change completes,cleanup dropped writes,one kick,no private data");
}
'''
with tempfile.TemporaryDirectory() as tmp:
    path = Path(tmp)
    (path / 'test.c').write_text(harness)
    subprocess.run(['cc', '-O1', '-Wall', '-Wextra', '-Werror', '-Wno-misleading-indentation',
                    '-fsanitize=undefined', '-fno-sanitize-recover=all',
                    str(path / 'test.c'), '-o', str(path / 'test')], check=True)
    subprocess.run([str(path / 'test')], check=True)
