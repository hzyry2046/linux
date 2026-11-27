#!/usr/bin/env python3
# SPDX-License-Identifier: GPL-2.0-only
"""Gate on this board's measured cfg baselines, then fixed CAL apply/restore."""
from pathlib import Path
import runpy
import subprocess
import tempfile

base = runpy.run_path(str(Path(__file__).with_name('test_conn_adie_cfg_integration.py')))['harness']
base = base[:base.index('int main(void) {')]
base = base.replace('"adie-cfg-read",14', '"adie-cal-cycle",15')
base = base.replace('static bool cfg_mode(void);', '''static bool cfg_mode(void);
static u32 cal_values[2];
static unsigned cal_writes,cal_reads,cal_drift,cal_stale,cal_late,cal_over;
static u64 cal_late_ns;
static bool cal_mode(void);''', 1)
base = base.replace('#define memzero_explicit(p,n) private_wipe(p,n)',
    'static unsigned wv_wipes;\nstatic void wv_wipe(void *p,unsigned n) {assert(n==4);wv_wipes++;'
    'memset(p,0,n);for(unsigned i=0;i<n;i++)assert(!((unsigned char *)p)[i]);}'
    '\n#define memzero_explicit(p,n) private_wipe(p,n)', 1)
base = base.replace('memzero_explicit(&data, sizeof(data));\n\treturn ret;',
                    'wv_wipe(&data, sizeof(data));\n\treturn ret;', 1)
assert 'wv_wipe(&data' in base
marker = 'if(addr==0xa108) {'
assert marker in base
base = base.replace(marker, '''if(addr==0xa380 || addr==0xa390) {
     assert(cal_mode() && (value==0xe8002 || value==0xe0002));
     cal_writes++;cal_values[addr==0xa390]=value;
    } else ''' + marker, 1)
marker = '''assert(cfg_mode());cfg_reads++;
    if(cfg_reads!=cfg_stale)
     adie_spi[0x58/4]=cfg_values[addr==0xb380?0:addr==0xb384?1:addr==0xb390?2:addr==0xb394?3:addr==0xba18?4:5] ^
      (cfg_reads==cfg_drift?1U:0U);
    if(cfg_reads==cfg_late)adie_clock+=cfg_late_ns;
    if(cfg_reads==cfg_over)adie_clock+=4000000000ULL;'''
assert marker in base
base = base.replace(marker, '''assert(cfg_mode() || cal_mode());
    if(cal_mode()) {
     cal_reads++;
     if(cal_reads!=cal_stale)
      adie_spi[0x58/4]=cal_values[addr==0xb390] ^ (cal_reads==cal_drift?1U:0U);
     if(cal_reads==cal_late)adie_clock+=cal_late_ns;
     if(cal_reads==cal_over)adie_clock+=4000000000ULL;
    } else {
     cfg_reads++;
     if(cfg_reads!=cfg_stale)
      adie_spi[0x58/4]=cfg_values[addr==0xb380?0:addr==0xb384?1:addr==0xb390?2:addr==0xb394?3:addr==0xba18?4:5] ^
       (cfg_reads==cfg_drift?1U:0U);
     if(cfg_reads==cfg_late)adie_clock+=cfg_late_ns;
     if(cfg_reads==cfg_over)adie_clock+=4000000000ULL;
    }''', 1)
harness = base + r'''
static bool cal_mode(void) {return conn.adie_cal_started;}
static void cal_setup(void) {
 cfg_setup();
 cfg_values[0]=0xe0002;cfg_values[1]=0x8;cfg_values[2]=0xe0002;cfg_values[3]=0x8;
 cfg_values[4]=0xf668fff5;cfg_values[5]=0x55555fff;
 cal_values[0]=0xe0002;cal_values[1]=0xe0002;
 cal_writes=cal_reads=cal_drift=cal_stale=cal_late=cal_over=0;
 cal_late_ns=2000000000ULL;wv_wipes=0;
}
/* Gate words are public vendor constants; only word-sized values get a leak scan. */
static void cal_clean(void) {
 pad_clean();assert(conn.adie_cfg_cleared && cfg_wipes==1);
 for(unsigned w=0;w<6;w++)if(cfg_values[w]>0xffff)
  for(unsigned i=0;i+4<=sizeof(conn);i++)
   if((unsigned char *)&conn+i+4<=(unsigned char *)&conn.adie_cfg_value ||
      (unsigned char *)&conn+i>=(unsigned char *)(&conn.adie_cfg_value+1))
    assert(memcmp((unsigned char *)&conn+i,&cfg_values[w],4));
}
static void cal_held(void) {
 cal_clean();retained();assert(conn.adie_unsafe && !conn.adie_cal_complete);
}
int main(void) {
 char output[4096];
 cal_setup();assert(data_run()==15);stopped();cal_clean();
 assert(conn.adie_cal_complete && conn.adie_cal_gate_ok && conn.adie_cfg_complete);
 assert(conn.adie_cal_write_issued==3 && conn.adie_cal_applied==3 &&
        conn.adie_cal_restored==3 && !conn.adie_cal_dirty);
 assert(conn.adie_cal_issued==3 && conn.adie_cal_read==3);
 assert(conn.adie_cal_transfers==20 && cal_writes==4 && cal_reads==4 && wv_wipes==4);
 assert(cal_values[0]==0xe0002 && cal_values[1]==0xe0002);
 assert(conn.adie_efuse_data_phase==4);
 assert(efuse_status_show(&dev,NULL,output)>0 &&
        strstr(output,"cal_requested=1 cal_started=1 cal_complete=1 cal_gate_ok=1"));
 assert(strstr(output,"cal_write_issued=0x3 cal_applied=0x3 cal_restored=0x3 cal_dirty=0 cal_transfers=20"));
 assert(data_run()==-EALREADY && cal_writes==4);
 for(unsigned n=0;n<4;n++) {
  cal_setup();cfg_values[n]=n&1?0x2008:0xe8002;
  assert(data_run()==-EOPNOTSUPP);cal_held();
  assert(!conn.adie_cal_started && !conn.adie_cal_gate_ok && !conn.adie_cal_write_issued);
  assert(!cal_writes && !cal_reads && !conn.adie_cal_dirty && !wv_wipes);
  assert(conn.adie_cfg_valid && conn.adie_cfg_value[n]==(n&1?0x2008U:0xe8002U));
  assert(conn.adie_efuse_data_phase==3);
 }
 for(unsigned n=259;n<=298;n++) {
  cal_setup();adie_drop=n;assert(data_run()<0);cal_held();
  for(unsigned k=1;k<=4;k++) {
   cal_setup();adie_loss=n;adie_change=k;assert(data_run()<0);cal_held();
   assert(adie_writes==n);
  }
 }
 for(unsigned n=135;n<=144;n++) {
  cal_setup();stuck_transfer=n;assert(data_run()==-ETIMEDOUT);cal_held();
  assert(conn.adie_cal_dirty);
 }
 for(unsigned n=1;n<=4;n++) {
  cal_setup();cal_drift=n;assert(data_run()==-EIO);cal_held();
  assert(cal_reads==n && conn.adie_cal_write_issued==(n<3?0x1:0x3));
  assert(conn.adie_cal_applied==(n==1?0:n==4?0x3:0x1) &&
         conn.adie_cal_restored==(n<3?0:0x1));
  assert(conn.adie_cal_dirty==(n<3?0x1:0x2));
 }
 for(unsigned n=1;n<=4;n+=3) {
  cal_setup();cal_stale=n;assert(data_run()<0);cal_held();
 }
 for(unsigned n=1;n<=4;n++) {
  cal_setup();cal_late=n;assert(data_run()==15);stopped();cal_clean();
  assert(conn.adie_cal_complete && conn.adie_efuse_data_phase==4);
  assert(conn.adie_efuse_data_phase_elapsed_ns>=2000000000ULL &&
         conn.adie_efuse_data_phase_elapsed_ns<3000000000ULL);
 }
 for(unsigned n=1;n<=4;n++) {
  cal_setup();cal_over=n;assert(data_run()==-ETIMEDOUT);cal_held();
  assert(!strcmp(conn.failure_stage,"adie-efuse-data-deadline"));
  assert(conn.adie_efuse_data_phase_elapsed_ns>=3000000000ULL &&
         conn.adie_efuse_data_elapsed_ns<8000000000ULL);
  assert(conn.adie_cal_write_issued==(n<3?0x1:0x3) &&
         conn.adie_cal_dirty==(n<3?0x1:0x2));
 }
 cal_setup();thermal_late=4;thermal_late_ns=1900000000ULL;
 pad_late=2;pad_late_ns=1900000000ULL;cfg_late=1;cfg_late_ns=2900000000ULL;
 cal_late=1;cal_late_ns=2000000000ULL;
 assert(data_run()==-ETIMEDOUT);cal_held();
 assert(!strcmp(conn.failure_stage,"adie-efuse-data-deadline"));
 assert(conn.adie_efuse_data_phase==4 &&
        conn.adie_efuse_data_phase_elapsed_ns<3000000000ULL);
 assert(conn.adie_efuse_data_elapsed_ns>=8000000000ULL);
 for(unsigned n=27;n<=30;n++) {
  cal_setup();private_ctrl_bad=n;assert(data_run()==-EIO);cal_held();
 }
 cal_setup();adie_fast=true;assert(data_run()==15);stopped();cal_clean();
 assert(!conn.adie_cal_busy_count && conn.adie_cal_complete);
 cal_setup();adie_fast=true;cal_stale=1;assert(data_run()==-EAGAIN);cal_held();
 for(unsigned n=299;n<=313;n++) {
  cal_setup();adie_drop=n;assert(data_run()<0);cal_clean();
  assert(conn.adie_cal_complete);
 }
 puts("PASS: cfg baseline gate per register, fixed 0xe8002/0xe0002 apply-restore TOP380 then TOP390,"
      "20 transfers,4 gate refusals,4 verify mismatches,2 stale readbacks,4 in-phase late reads,"
      "4 deadline expiries,global cap isolation,4 control changes,no-busy,stale-fast,erasure,one-shot;"
      " TOP390 untouched on TOP380 failure, dirty retained per register");
}
'''
with tempfile.TemporaryDirectory() as tmp:
    path = Path(tmp)
    (path / 'test.c').write_text(harness)
    subprocess.run(['cc', '-O1', '-Wall', '-Wextra', '-Werror', '-Wno-unused-parameter',
                    '-Wno-unused-variable', '-Wno-unused-function', '-fsanitize=undefined',
                    '-fno-sanitize-recover=all', str(path / 'test.c'), '-o', str(path / 'test')], check=True)
    subprocess.run([str(path / 'test')], check=True)
