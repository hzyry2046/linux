#!/usr/bin/env python3
# SPDX-License-Identifier: GPL-2.0-only
"""Three guarded control observations never authorize completion or cleanup."""
from pathlib import Path
import runpy
import subprocess
import tempfile

base = runpy.run_path(str(Path(__file__).with_name('test_conn_adie_efuse_integration.py')))['harness']
base = base[:base.index('int main(void) {')]
base = base.replace('static bool engine_started,', 'static u32 observe_delta[3];\nstatic bool engine_started,', 1)
base = base.replace('if(n==engine_corrupt)value^=engine_extra;',
                    'if(n<=3)value^=observe_delta[n-1];\n if(n==engine_corrupt)value^=engine_extra;', 1)
harness = base+r'''

static void observe_setup(void) {
 engine_setup();engine_delay=0;
 observe_delta[0]=observe_delta[1]=observe_delta[2]=0x3b;
 
}
static int observe_run(void) {return rail_cycle_store(&dev,NULL,"adie-efuse-observe",18);}
static void held(void) {
 assert(conn.adie_efuse_pending && conn.adie_unsafe && !conn.adie_efuse_complete);
 assert(!conn.adie_efuse_confirmed && conn.adie_fm_dirty && conn.adie_prefix_dirty==3);
 assert(conn.adie_mailbox_dirty && !conn.adie_reset_restored);
 retained();assert(!sema_writes && fm_writes==1);
}
int main(void) {
 observe_setup();assert(observe_run()==-EUCLEAN);held();
 assert(conn.adie_efuse_observe_stable && conn.adie_efuse_observed==3);
 assert(engine_reads==3 && engine_writes==1 && conn.adie_efuse_transfers==7);
 assert(!strcmp(conn.failure_stage,"adie-efuse-observe-held"));
 assert(conn.adie_efuse_observe_delta[0]==0x3b && conn.adie_efuse_observe_delta[2]==0x3b);
 char output[4096];assert(efuse_status_show(&dev,NULL,output)>0);
 assert(strstr(output,"observe=1 observed=3 stable=1 delta0=0x3b delta1=0x3b delta2=0x3b"));
 assert(!strstr(output,"2000003e"));
 assert(observe_run()==-EALREADY && engine_writes==1);
 for(unsigned n=39;n<=50;n++) {
  observe_setup();adie_drop=n;assert(observe_run()<0);held();
  assert(!conn.adie_efuse_observe_stable);
 }
 for(unsigned n=39;n<=50;n++)for(unsigned kind=1;kind<=4;kind++) {
  observe_setup();adie_loss=n;adie_change=kind;assert(observe_run()<0);held();
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
 assert(observe_run()==-EUCLEAN);held();assert(conn.adie_efuse_observe_stable);
 puts("PASS: nested observer 3-sample hold-only,all new dropped writes/guard faults,7 SPI timeouts,"
      "72 high-bit changes,12 low-bit instability,6 status faults,late deadline,no-change holds,one kick,no private data");
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
