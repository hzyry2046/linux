#!/usr/bin/env python3
# SPDX-License-Identifier: GPL-2.0-only
"""Gate on all six measured baselines, then fixed THADC IR apply/restore."""
from pathlib import Path
import runpy
import subprocess
import tempfile

base = runpy.run_path(str(Path(__file__).with_name('test_conn_adie_cal_cycle_integration.py')))['harness']
base = base[:base.index('int main(void) {')]
base = base.replace('"adie-cal-cycle",15', '"adie-ir-cycle",14')
base = base.replace('static bool cal_mode(void);', '''static bool cal_mode(void);
static u32 ir_values[3];
static unsigned ir_writes,ir_reads,ir_drift,ir_stale,ir_late,ir_over;
static u64 ir_late_ns;
static bool ir_mode(void);''', 1)
marker = 'if(addr==0xa380 || addr==0xa390) {'
assert marker in base
base = base.replace(marker, '''if(addr==0xaa18 || addr==0xa384 || addr==0xa394) {
     assert(ir_mode() &&
            (value==0xf6e8fff5 || value==0xf668fff5 || value==0x2008 || value==0x8));
     ir_writes++;ir_values[addr==0xaa18?0:addr==0xa384?1:2]=value;
    } else ''' + marker, 1)
marker = '''assert(cfg_mode() || cal_mode());
    if(cal_mode()) {'''
assert marker in base
base = base.replace(marker, '''assert(cfg_mode() || cal_mode() || ir_mode());
    if(ir_mode()) {
     ir_reads++;
     if(ir_reads!=ir_stale)
      adie_spi[0x58/4]=ir_values[addr==0xba18?0:addr==0xb384?1:2] ^
       (ir_reads==ir_drift?1U:0U);
     if(ir_reads==ir_late)adie_clock+=ir_late_ns;
     if(ir_reads==ir_over)adie_clock+=4000000000ULL;
    } else if(cal_mode()) {''', 1)
harness = base + r'''
static bool ir_mode(void) {return conn.adie_ir_started;}
static void ir_setup(void) {
 cfg_setup();
 cfg_values[0]=0xe0002;cfg_values[1]=0x8;cfg_values[2]=0xe0002;cfg_values[3]=0x8;
 cfg_values[4]=0xf668fff5;cfg_values[5]=0x55555fff;
 ir_values[0]=0xf668fff5;ir_values[1]=0x8;ir_values[2]=0x8;
 ir_writes=ir_reads=ir_drift=ir_stale=ir_late=ir_over=0;
 ir_late_ns=2000000000ULL;cal_writes=cal_reads=0;wv_wipes=0;
}
/* Gate words are public vendor constants; only word-sized values get a leak scan. */
static void ir_clean(void) {
 pad_clean();assert(conn.adie_cfg_cleared && cfg_wipes==1);
 for(unsigned w=0;w<6;w++)if(cfg_values[w]>0xffff)
  for(unsigned i=0;i+4<=sizeof(conn);i++)
   if((unsigned char *)&conn+i+4<=(unsigned char *)&conn.adie_cfg_value ||
      (unsigned char *)&conn+i>=(unsigned char *)(&conn.adie_cfg_value+1))
    assert(memcmp((unsigned char *)&conn+i,&cfg_values[w],4));
}
static void ir_held(void) {
 ir_clean();retained();assert(conn.adie_unsafe && !conn.adie_ir_complete);
}
int main(void) {
 char output[4096];
 ir_setup();assert(data_run()==14);stopped();ir_clean();
 assert(conn.adie_ir_complete && conn.adie_ir_gate_ok && conn.adie_cfg_complete);
 assert(!conn.adie_cal_started);
 assert(conn.adie_ir_write_issued==0x7 && conn.adie_ir_applied==0x7 &&
        conn.adie_ir_restored==0x7 && !conn.adie_ir_dirty);
 assert(conn.adie_ir_issued==0x7 && conn.adie_ir_read==0x7);
 assert(conn.adie_ir_transfers==30 && ir_writes==6 && ir_reads==6 && wv_wipes==6);
 assert(ir_values[0]==0xf668fff5 && ir_values[1]==0x8 && ir_values[2]==0x8);
 assert(conn.adie_efuse_data_phase==5);
 assert(efuse_status_show(&dev,NULL,output)>0 &&
        strstr(output,"ir_requested=1 ir_started=1 ir_complete=1 ir_gate_ok=1"));
 assert(strstr(output,"ir_write_issued=0x7 ir_applied=0x7 ir_restored=0x7 ir_dirty=0 ir_transfers=30"));
 assert(data_run()==-EALREADY && ir_writes==6);
 for(unsigned n=0;n<6;n++) {
  ir_setup();cfg_values[n]^=1;
  assert(data_run()==-EOPNOTSUPP);ir_held();
  assert(!conn.adie_ir_started && !conn.adie_ir_gate_ok && !conn.adie_ir_write_issued);
  assert(!ir_writes && !ir_reads && !conn.adie_ir_dirty && !wv_wipes);
  assert(conn.adie_cfg_valid && conn.adie_efuse_data_phase==3);
 }
 for(unsigned n=259;n<=318;n++) {
  ir_setup();adie_drop=n;assert(data_run()<0);ir_held();
  for(unsigned k=1;k<=4;k++) {
   ir_setup();adie_loss=n;adie_change=k;assert(data_run()<0);ir_held();
   assert(adie_writes==n);
  }
 }
 for(unsigned n=135;n<=144;n++) {
  ir_setup();stuck_transfer=n;assert(data_run()==-ETIMEDOUT);ir_held();
  assert(conn.adie_ir_dirty);
 }
 for(unsigned n=1;n<=6;n++) {
  ir_setup();ir_drift=n;assert(data_run()==-EIO);ir_held();
  assert(ir_reads==n && conn.adie_ir_write_issued==((1U<<((n+1)/2))-1));
  assert(conn.adie_ir_applied==((1U<<((n-(n&1))/2))-1) &&
         conn.adie_ir_restored==((1U<<((n-1)/2))-1));
  assert(conn.adie_ir_dirty==BIT((n-1)/2));
  if(n<5)assert(ir_values[2]==0x8);
  if(n<3)assert(ir_values[1]==0x8);
 }
 for(unsigned n=1;n<=6;n+=5) {
  ir_setup();ir_stale=n;assert(data_run()<0);ir_held();
 }
 for(unsigned n=1;n<=6;n++) {
  ir_setup();ir_late=n;assert(data_run()==14);stopped();ir_clean();
  assert(conn.adie_ir_complete && conn.adie_efuse_data_phase==5);
  assert(conn.adie_efuse_data_phase_elapsed_ns>=2000000000ULL &&
         conn.adie_efuse_data_phase_elapsed_ns<3000000000ULL);
 }
 for(unsigned n=1;n<=6;n++) {
  ir_setup();ir_over=n;assert(data_run()==-ETIMEDOUT);ir_held();
  assert(!strcmp(conn.failure_stage,"adie-efuse-data-deadline"));
  assert(conn.adie_efuse_data_phase_elapsed_ns>=3000000000ULL &&
         conn.adie_efuse_data_elapsed_ns<8000000000ULL);
  assert(conn.adie_ir_write_issued==((1U<<((n+1)/2))-1) &&
         conn.adie_ir_dirty==BIT((n-1)/2));
 }
 ir_setup();thermal_late=4;thermal_late_ns=1900000000ULL;
 pad_late=2;pad_late_ns=1900000000ULL;cfg_late=1;cfg_late_ns=3900000000ULL;
 ir_late=1;ir_late_ns=2000000000ULL;
 assert(data_run()==-ETIMEDOUT);ir_held();
 assert(!strcmp(conn.failure_stage,"adie-efuse-data-deadline"));
 assert(conn.adie_efuse_data_phase==5 &&
        conn.adie_efuse_data_phase_elapsed_ns<3000000000ULL);
 assert(conn.adie_efuse_data_elapsed_ns>=8000000000ULL);
 for(unsigned n=27;n<=32;n++) {
  ir_setup();private_ctrl_bad=n;assert(data_run()==-EIO);ir_held();
 }
 ir_setup();adie_fast=true;assert(data_run()==14);stopped();ir_clean();
 assert(!conn.adie_ir_busy_count && conn.adie_ir_complete);
 ir_setup();adie_fast=true;ir_stale=1;assert(data_run()==-EAGAIN);ir_held();
 ir_setup();cfg_transfer_ns=40000000ULL;assert(data_run()==14);stopped();ir_clean();
 assert(conn.adie_ir_complete && conn.adie_efuse_data_elapsed_ns>=5000000000ULL &&
        conn.adie_efuse_data_elapsed_ns<8000000000ULL);
 for(unsigned n=319;n<=333;n++) {
  ir_setup();adie_drop=n;assert(data_run()<0);ir_clean();
  assert(conn.adie_ir_complete);
 }
 puts("PASS: six-baseline gate per register, fixed apply/restore A18 f6e8fff5/f668fff5 then 384/394"
      " 2008/8,30 transfers,A1C never written,6 gate refusals,60 dropped writes,240 guard faults,"
      "10 timeouts,6 verify mismatches,2 stale readbacks,6 in-phase late reads,6 deadline expiries,"
      "global cap isolation,6 control changes,no-busy,stale-fast,realistic-latency,15 cleanup faults,"
      "erasure,one-shot; later registers untouched on failure, dirty retained per register");
}
'''
with tempfile.TemporaryDirectory() as tmp:
    path = Path(tmp)
    (path / 'test.c').write_text(harness)
    subprocess.run(['cc', '-O1', '-Wall', '-Wextra', '-Werror', '-Wno-unused-parameter',
                    '-Wno-unused-variable', '-Wno-unused-function', '-fsanitize=undefined',
                    '-fno-sanitize-recover=all', str(path / 'test.c'), '-o', str(path / 'test')], check=True)
    subprocess.run([str(path / 'test')], check=True)
