#!/usr/bin/env python3
# SPDX-License-Identifier: GPL-2.0-only
"""Read-only four-register config baselines nested after the TOP070 read."""
from pathlib import Path
import runpy
import subprocess
import tempfile

base = runpy.run_path(str(Path(__file__).with_name('test_conn_adie_pad_integration.py')))['harness']
base = base[:base.index('int main(void) {')]
base = base.replace('"adie-pad-read",14', '"adie-cfg-read",14')
base = base.replace('static bool pad_mode(void);', '''static bool pad_mode(void);
static uint32_t cfg_values[6];
static unsigned cfg_reads,cfg_drift,cfg_late,cfg_over,cfg_stale;
static u64 cfg_transfer_ns,cfg_late_ns,pad_late_ns,thermal_late_ns;
static bool cfg_mode(void);''', 1)
base = base.replace('#define memzero_explicit(p,n) private_wipe(p,n)',
    'static unsigned cfg_wipes;\nstatic void cfg_wipe(void *p,unsigned n) {assert(n==28);cfg_wipes++;'
    'memset(p,0,n);for(unsigned i=0;i<n;i++)assert(!((unsigned char *)p)[i]);}'
    '\n#define memzero_explicit(p,n) private_wipe(p,n)', 1)
base = base.replace('memzero_explicit(&data, sizeof(data));\n\tconn->adie_cfg_cleared',
                    'cfg_wipe(&data, sizeof(data));\n\tconn->adie_cfg_cleared', 1)
marker = 'if(addr==0xb034 || addr==0xb038) {'
assert marker in base
base = base.replace(marker, '''if(addr==0xb380 || addr==0xb384 || addr==0xb390 || addr==0xb394 || addr==0xba18 || addr==0xba1c) {
    assert(cfg_mode());cfg_reads++;
    if(cfg_reads!=cfg_stale)
     adie_spi[0x58/4]=cfg_values[addr==0xb380?0:addr==0xb384?1:addr==0xb390?2:addr==0xb394?3:addr==0xba18?4:5] ^
      (cfg_reads==cfg_drift?1U:0U);
    if(cfg_reads==cfg_late)adie_clock+=cfg_late_ns;
    if(cfg_reads==cfg_over)adie_clock+=4000000000ULL;
   } else ''' + marker, 1)
base = base.replace('if(pad_reads==pad_late)adie_clock+=2000000000ULL;',
                    'if(pad_reads==pad_late)adie_clock+=pad_late_ns;', 1)
base = base.replace('if(thermal_reads==thermal_late)adie_clock+=2000000000ULL;',
                    'if(thermal_reads==thermal_late)adie_clock+=thermal_late_ns;', 1)
base = base.replace('addr==0xb070 || addr==0xb034 || addr==0xb038 || (addr>=0xb130',
                    'addr==0xb380 || addr==0xb384 || addr==0xb390 || addr==0xb394 || '
                    'addr==0xba18 || addr==0xba1c || '
                    'addr==0xb070 || addr==0xb034 || addr==0xb038 || (addr>=0xb130')
marker = 'transfers++;adie_fired=true;adie_reads=0;'
assert marker in base
# Per-transfer latency only inside the shared data budget window.
base = base.replace(marker, marker + 'if(data_mode())adie_clock+=cfg_transfer_ns;', 1)
harness = base + r'''
static bool cfg_mode(void) {return conn.adie_cfg_started;}
static void cfg_setup(void) {
 pad_setup();
 cfg_values[0]=0xe8002;cfg_values[1]=0x92837461;cfg_values[2]=0x13579bdf;cfg_values[3]=0;
 cfg_values[4]=0xf6e8fff5;cfg_values[5]=0x2468ace0;
 cfg_reads=cfg_drift=cfg_late=cfg_over=cfg_stale=cfg_wipes=0;cfg_transfer_ns=0;
 cfg_late_ns=pad_late_ns=thermal_late_ns=2000000000ULL;
}
static void cfg_clean(void) {
 pad_clean();assert(conn.adie_cfg_cleared && cfg_wipes==1);
 for(unsigned w=0;w<4;w++)if(cfg_values[w] && cfg_values[w]!=0x66358a11)
  for(unsigned i=0;i+4<=sizeof(conn);i++)
   if((unsigned char *)&conn+i+4<=(unsigned char *)&conn.adie_cfg_value ||
      (unsigned char *)&conn+i>=(unsigned char *)(&conn.adie_cfg_value+1))
    assert(memcmp((unsigned char *)&conn+i,&cfg_values[w],4));
}
static void cfg_held(void) {
 cfg_clean();retained();assert(conn.adie_unsafe && !conn.adie_cfg_complete);
 assert(!conn.adie_cfg_valid && conn.adie_pad_value_valid);
 assert(conn.adie_fm_dirty && conn.adie_prefix_dirty==3 && conn.adie_mailbox_dirty);
 assert(!sema_writes && fm_writes==1 && conn.adie_trim_plan_complete);
 assert(conn.adie_efuse_handoff_complete && !conn.adie_efuse_handoff_dirty);
}
int main(void) {
 char output[4096];
 cfg_setup();assert(data_run()==14);stopped();cfg_clean();
 assert(conn.adie_cfg_complete && conn.adie_cfg_valid && conn.adie_pad_complete);
 assert(conn.adie_cfg_matched==0x3f && conn.adie_cfg_target_match==0x11);
 assert(conn.adie_cfg_issued==0xfff && conn.adie_cfg_read==0xfff);
 assert(conn.adie_cfg_value[0]==0xe8002 && conn.adie_cfg_value[1]==0x92837461);
 assert(conn.adie_cfg_value[2]==0x13579bdf && !conn.adie_cfg_value[3]);
 assert(conn.adie_cfg_value[4]==0xf6e8fff5 && conn.adie_cfg_value[5]==0x2468ace0);
 assert(conn.adie_cfg_transfers==48 && cfg_reads==12 && conn.adie_pad_transfers==8);
 assert(conn.adie_thermal_transfers==16 && conn.adie_efuse_data_transfers==32);
 assert(adie_writes==273 && transfers==134 && !conn.adie_pad_write_issued);
 assert(efuse_status_show(&dev,NULL,output)>0 && strstr(output,"cfg_complete=1 cfg_cleared=1"));
 assert(strstr(output,"cfg_issued=0xfff cfg_read=0xfff cfg_matched=0x3f cfg_target_match=0x11 cfg_transfers=48"));
 assert(strstr(output,"cfg_valid=1 top380=0xe8002 top384=0x92837461 top390=0x13579bdf top394=0 topa18=0xf6e8fff5 topa1c=0x2468ace0\n"));
 assert(data_run()==-EALREADY && cfg_reads==12);
 cfg_setup();private_words[1]=0x80000080;
 assert(data_run()==-EOPNOTSUPP);pad_held();
 assert(!conn.adie_cfg_started && !cfg_reads && !conn.adie_cfg_valid && !cfg_wipes);
 assert(!conn.adie_cfg_cleared && !strcmp(conn.failure_stage,"adie-pad-noop-prerequisite"));
 assert(adie_writes==146);
 for(unsigned n=163;n<=258;n++) {
  cfg_setup();adie_drop=n;assert(data_run()<0);cfg_held();
  for(unsigned k=1;k<=4;k++) {
   cfg_setup();adie_loss=n;adie_change=k;assert(data_run()<0);cfg_held();
   assert(adie_writes==n);
  }
 }
 for(unsigned n=89;n<=98;n++) {
  cfg_setup();stuck_transfer=n;assert(data_run()==-ETIMEDOUT);cfg_held();
 }
 for(unsigned n=2;n<=12;n+=2) {
  cfg_setup();cfg_drift=n;assert(data_run()==-EIO);cfg_held();
  assert(conn.adie_cfg_matched==((1U<<(n/2-1))-1) && cfg_reads==n);
  assert(conn.adie_cfg_issued==((1U<<n)-1) && conn.adie_cfg_read==((1U<<n)-1));
 }
 for(unsigned n=2;n<=12;n+=10) {
  cfg_setup();cfg_stale=n;assert(data_run()<0);cfg_held();
  assert(!conn.adie_cfg_valid && !conn.adie_cfg_complete);
 }
 for(unsigned n=1;n<=12;n++) {
  cfg_setup();cfg_late=n;assert(data_run()==14);stopped();cfg_clean();
  assert(conn.adie_cfg_complete && conn.adie_cfg_valid && conn.adie_efuse_data_phase==3);
  assert(conn.adie_efuse_data_phase_elapsed_ns>=2000000000ULL &&
         conn.adie_efuse_data_phase_elapsed_ns<4000000000ULL);
 }
 for(unsigned n=1;n<=12;n++) {
  cfg_setup();cfg_over=n;assert(data_run()==-ETIMEDOUT);cfg_held();
  assert(!conn.adie_cfg_valid && !conn.adie_cfg_complete);
  assert(!strcmp(conn.failure_stage,"adie-efuse-data-deadline"));
  assert(conn.adie_efuse_data_phase_elapsed_ns>=4000000000ULL &&
         conn.adie_efuse_data_elapsed_ns<8000000000ULL);
 }
 cfg_setup();thermal_late=4;assert(data_run()==-ETIMEDOUT);
 retained();assert(conn.adie_unsafe && !conn.adie_pad_started && !conn.adie_cfg_started);
 assert(!conn.adie_pad_cleared && !conn.adie_cfg_cleared && !cfg_wipes);
 assert(conn.adie_efuse_data_phase==1 &&
        !strcmp(conn.failure_stage,"adie-efuse-data-deadline"));
 cfg_setup();pad_late=1;assert(data_run()==-ETIMEDOUT);pad_held();
 assert(conn.adie_pad_started && !conn.adie_pad_value_valid);
 assert(!conn.adie_cfg_started && !conn.adie_cfg_cleared && !cfg_wipes);
 assert(conn.adie_efuse_data_phase==2 &&
        conn.adie_efuse_data_phase_elapsed_ns>=2000000000ULL &&
        conn.adie_efuse_data_elapsed_ns<8000000000ULL);
 cfg_setup();thermal_late=4;thermal_late_ns=1900000000ULL;
 pad_late=2;pad_late_ns=1900000000ULL;
 cfg_late=1;cfg_late_ns=2900000000ULL;assert(data_run()==14);stopped();cfg_clean();
 assert(conn.adie_cfg_valid && conn.adie_efuse_data_phase==3 &&
        conn.adie_efuse_data_phase_elapsed_ns<3000000000ULL);
 assert(conn.adie_efuse_data_elapsed_ns>=5000000000ULL &&
        conn.adie_efuse_data_elapsed_ns<8000000000ULL);
 for(unsigned n=15;n<=26;n++) {
  cfg_setup();private_ctrl_bad=n;assert(data_run()==-EIO);cfg_held();
 }
 cfg_setup();adie_fast=true;assert(data_run()==14);stopped();cfg_clean();
 assert(!conn.adie_cfg_busy_count && conn.adie_cfg_valid);
 cfg_setup();adie_fast=true;cfg_stale=12;assert(data_run()==-EAGAIN);cfg_held();
 cfg_setup();cfg_transfer_ns=40000000ULL;assert(data_run()==14);stopped();cfg_clean();
 assert(conn.adie_cfg_valid && conn.adie_efuse_data_elapsed_ns>=3000000000ULL &&
        conn.adie_efuse_data_elapsed_ns<8000000000ULL);
 for(unsigned n=259;n<=273;n++) {
  cfg_setup();adie_drop=n;assert(data_run()<0);cfg_clean();
  assert(conn.adie_cfg_complete && conn.adie_cfg_valid);
 }
 puts("PASS: fresh no-op gate, TOP380/384/390/394/A18/A1C two reads/48 transfers, values/targets"
      " published only after guard,96 dropped writes,384 guard faults,10 timeouts,6 repeat mismatches,"
      "2 stale readbacks,12 in-phase late reads,12 deadline expiries,prereq/pad phase deadlines,"
      "3-phase independent timers,12 control changes,no-busy,stale-fast,realistic-latency,"
      "15 cleanup faults,erasure/redaction/one-shot; zero config writes");
}
'''
with tempfile.TemporaryDirectory() as tmp:
    path = Path(tmp)
    (path / 'test.c').write_text(harness)
    subprocess.run(['cc', '-O1', '-Wall', '-Wextra', '-Werror', '-Wno-unused-parameter',
                    '-Wno-unused-variable', '-Wno-unused-function', '-fsanitize=undefined',
                    '-fno-sanitize-recover=all', str(path / 'test.c'), '-o', str(path / 'test')], check=True)
    subprocess.run([str(path / 'test')], check=True)
