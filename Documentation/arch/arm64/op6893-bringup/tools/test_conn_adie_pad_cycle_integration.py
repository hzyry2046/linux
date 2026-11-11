#!/usr/bin/env python3
# SPDX-License-Identifier: GPL-2.0-only
"""Execute the production fixed-value pad cycle with nested fault injection."""
from pathlib import Path
import runpy
import subprocess
import tempfile

base = runpy.run_path(str(Path(__file__).with_name('test_conn_adie_pad_integration.py')))['harness']
base = base[:base.index('int main(void) {')]
base = base.replace('"adie-pad-read",14', '"adie-pad-cycle",15')
base = base.replace('static unsigned pad_reads,pad_drift,pad_late,pad_wipes;',
                    'static unsigned pad_reads,pad_drift,pad_late,pad_wipes,pad_stale,pad_over;\nstatic u64 pad_transfer_ns,pad_late_ns,thermal_late_ns;', 1)
marker = 'if(addr==0xa108) {'
assert marker in base
base = base.replace(marker, '''if(addr==0xa070) {
     assert(pad_mode() && (value==0x80000000 || !value));
     pad_value=value;
    } else ''' + marker, 1)
marker = 'adie_spi[0x58/4]=pad_value ^ (pad_reads==pad_drift?1U:0U);'
assert marker in base
# Stale readback: engine fires but RDAT keeps its previous content.
base = base.replace(marker, 'if(pad_reads!=pad_stale)' + marker, 1)
marker = 'if(pad_reads==pad_late)adie_clock+=2000000000ULL;'
assert marker in base
# Late/over jumps: the pad stage now has its own 2 s phase deadline.
base = base.replace(marker, 'if(pad_reads==pad_late)adie_clock+=pad_late_ns;\n    if(pad_reads==pad_over)adie_clock+=3000000000ULL;', 1)
marker = 'if(thermal_reads==thermal_late)adie_clock+=2000000000ULL;'
assert marker in base
base = base.replace(marker, 'if(thermal_reads==thermal_late)adie_clock+=thermal_late_ns;', 1)
marker = 'transfers++;adie_fired=true;adie_reads=0;'
assert marker in base
# Per-transfer latency only inside the shared data budget window.
base = base.replace(marker, marker + 'if(data_mode()||thermal_mode()||pad_mode())adie_clock+=pad_transfer_ns;', 1)
harness = base + r'''
static void cycle_setup(void) {pad_setup();pad_value=0;pad_stale=pad_over=0;pad_transfer_ns=0;pad_late_ns=thermal_late_ns=2000000000ULL;}
static void cycle_clean(void) {
 thermal_clean();assert(conn.adie_pad_cleared && pad_wipes==1);
}
static void cycle_held(void) {
 cycle_clean();retained();assert(conn.adie_unsafe && !conn.adie_pad_complete);
 assert(conn.adie_fm_dirty && conn.adie_prefix_dirty==3 && conn.adie_mailbox_dirty);
 assert(!sema_writes && fm_writes==1);
}
int main(void) {
 char output[4096];
 cycle_setup();assert(data_run()==15);stopped();cycle_clean();
 assert(conn.adie_pad_complete && conn.adie_pad_applied && conn.adie_pad_restored);
 assert(conn.adie_pad_baseline_supported && !conn.adie_pad_dirty && !pad_value);
 assert(conn.adie_pad_value_valid && !conn.adie_pad_value);
 assert(conn.adie_pad_write_issued==3 && conn.adie_pad_transfers==18 && pad_reads==4);
 assert(adie_writes==197 && transfers==96);
 assert(efuse_status_show(&dev,NULL,output)>0 && strstr(output,"pad_restored=1 pad_dirty=0"));
 assert(strstr(output,"pad_value_valid=1 pad_value=0\n"));
 assert(data_run()==-EALREADY && adie_writes==197);
 for(unsigned n=0;n<3;n++) {
  cycle_setup();pad_value=n==0?5:n==1?0x80000000:0xffffffff;
  assert(data_run()==-EOPNOTSUPP);cycle_held();
  assert(!conn.adie_pad_write_issued && !conn.adie_pad_dirty && adie_writes==162);
  assert(conn.adie_pad_value_valid && conn.adie_pad_value==pad_value);
 }
 cycle_setup();private_words[1]=0x80000080;
 assert(data_run()==-EOPNOTSUPP);cycle_held();
 assert(!pad_reads && !conn.adie_pad_write_issued);
 assert(!conn.adie_pad_value_valid && !conn.adie_pad_value);
 for(unsigned n=163;n<=182;n++) {
  cycle_setup();adie_drop=n;assert(data_run()<0);cycle_held();
  assert(conn.adie_pad_value_valid && !conn.adie_pad_value);
  for(unsigned k=1;k<=4;k++) {
   cycle_setup();adie_loss=n;adie_change=k;assert(data_run()<0);cycle_held();
   assert(adie_writes==n && conn.adie_pad_value_valid && !conn.adie_pad_value);
  }
 }
 for(unsigned n=81;n<=90;n++) {
  cycle_setup();stuck_transfer=n;assert(data_run()==-ETIMEDOUT);cycle_held();
  assert(conn.adie_pad_dirty && conn.adie_pad_value_valid && !conn.adie_pad_value);
 }
 for(unsigned n=3;n<=4;n++) {
  cycle_setup();pad_drift=n;assert(data_run()==-EIO);cycle_held();
  assert(conn.adie_pad_dirty && conn.adie_pad_value_valid && !conn.adie_pad_value);
  cycle_setup();pad_stale=n;assert(data_run()<0);cycle_held();
  assert(conn.adie_pad_dirty && !conn.adie_pad_restored);
  assert(conn.adie_pad_value_valid && !conn.adie_pad_value);
 }
 cycle_setup();adie_fast=true;pad_stale=4;assert(data_run()==-EAGAIN);cycle_held();
 assert(conn.adie_pad_dirty && !conn.adie_pad_restored);
 for(unsigned n=1;n<=4;n++) {
  cycle_setup();pad_late=n;assert(data_run()==-ETIMEDOUT);cycle_held();
  assert(!strcmp(conn.failure_stage,"adie-efuse-data-deadline"));
  assert(conn.adie_efuse_data_phase_elapsed_ns>=2000000000ULL);
  if(n<3)assert(!conn.adie_pad_value_valid && !conn.adie_pad_value &&
                !conn.adie_pad_write_issued && !conn.adie_pad_dirty);
  else {assert(conn.adie_pad_value_valid && !conn.adie_pad_value);
   assert(conn.adie_pad_dirty && !conn.adie_pad_restored);
   assert(n==4?conn.adie_pad_applied:!conn.adie_pad_applied);}
 }
 for(unsigned n=1;n<=4;n++) {
  cycle_setup();pad_over=n;assert(data_run()==-ETIMEDOUT);cycle_held();
  assert(!strcmp(conn.failure_stage,"adie-efuse-data-deadline"));
  assert(conn.adie_efuse_data_phase_elapsed_ns>=3000000000ULL);
  if(n<3)assert(!conn.adie_pad_value_valid && !conn.adie_pad_value &&
                !conn.adie_pad_write_issued && !conn.adie_pad_dirty);
  else {assert(conn.adie_pad_value_valid && !conn.adie_pad_value);
   assert(conn.adie_pad_dirty && !conn.adie_pad_restored);
   assert(n==4?conn.adie_pad_applied:!conn.adie_pad_applied);}
 }
 cycle_setup();thermal_late=4;assert(data_run()==-ETIMEDOUT);
 retained();assert(conn.adie_unsafe && !conn.adie_pad_started && !conn.adie_pad_cleared);
 assert(!pad_wipes && !conn.adie_pad_value_valid && conn.adie_efuse_data_phase==1);
 assert(!strcmp(conn.failure_stage,"adie-efuse-data-deadline"));
 cycle_setup();thermal_late=4;thermal_late_ns=1900000000ULL;
 pad_late=2;pad_late_ns=1900000000ULL;assert(data_run()==15);stopped();cycle_clean();
 assert(conn.adie_pad_restored && !conn.adie_pad_dirty);
 assert(conn.adie_efuse_data_phase==2 &&
        conn.adie_efuse_data_phase_elapsed_ns<2000000000ULL);
 assert(conn.adie_efuse_data_elapsed_ns>=3000000000ULL);
 cycle_setup();pad_transfer_ns=40000000ULL;assert(data_run()==15);stopped();cycle_clean();
 assert(conn.adie_pad_restored && conn.adie_pad_value_valid && !conn.adie_pad_value);
 assert(conn.adie_efuse_data_elapsed_ns>=2000000000ULL &&
        conn.adie_efuse_data_elapsed_ns<8000000000ULL);
 for(unsigned n=15;n<=16;n++) {
  cycle_setup();private_ctrl_bad=n;assert(data_run()==-EIO);cycle_held();
  assert(conn.adie_pad_dirty && conn.adie_pad_value_valid && !conn.adie_pad_value);
 }
 cycle_setup();adie_fast=true;assert(data_run()==15);stopped();cycle_clean();
 assert(!conn.adie_pad_busy_count && conn.adie_pad_restored && !pad_value);
 assert(conn.adie_pad_value_valid && !conn.adie_pad_value);
 for(unsigned n=183;n<=197;n++) {
  cycle_setup();adie_drop=n;assert(data_run()<0);cycle_clean();
  assert(conn.adie_pad_complete && conn.adie_pad_restored && !conn.adie_pad_dirty);
  assert(conn.adie_pad_value_valid && !conn.adie_pad_value);
 }
 puts("PASS: zero baseline gate, fresh trim gate, pad apply/verify/restore/verify,20 dropped writes,"
      "80 guard faults,10 timeouts,2 read mismatches,2 stale readbacks,8 phase deadline expiries,"
      "prereq overrun,no stage after prereq failure,independent phase timers,2 control faults,"
      "15 cleanup faults,no-busy,stale-fast,realistic-latency,erasure,one-shot;"
      " failures retain parents without retry");
}
'''
with tempfile.TemporaryDirectory() as tmp:
    path = Path(tmp)
    (path / 'test.c').write_text(harness)
    subprocess.run(['cc', '-O1', '-Wall', '-Wextra', '-Werror', '-Wno-unused-parameter',
                    '-Wno-unused-variable', '-Wno-unused-function', '-fsanitize=undefined',
                    '-fno-sanitize-recover=all', str(path / 'test.c'), '-o', str(path / 'test')], check=True)
    subprocess.run([str(path / 'test')], check=True)
