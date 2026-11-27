#!/usr/bin/env python3
# SPDX-License-Identifier: GPL-2.0-only
"""Private thermal baselines, with actual nested preparation and cleanup."""
from pathlib import Path
import runpy
import subprocess
import tempfile

base = runpy.run_path(str(Path(__file__).with_name('test_conn_adie_efuse_handoff_integration.py')))['harness']
base = base[:base.index('int main(void) {')]
base = base.replace('static uint32_t private_words[4];', '''static uint32_t private_words[4];
static uint32_t thermal_words[2];
static unsigned thermal_reads,thermal_drift,thermal_late,thermal_wipes;
static bool thermal_mode(void);''', 1)
base = base.replace('#define memzero_explicit(p,n) private_wipe(p,n)',
                    'static void thermal_wipe(void *p,unsigned n) {assert(n==12);thermal_wipes++;private_wipe(p,n);}'
                    '\n#define memzero_explicit(p,n) private_wipe(p,n)', 1)
base = base.replace('memzero_explicit(&data, sizeof(data));\n\tconn->adie_thermal_cleared',
                    'thermal_wipe(&data, sizeof(data));\n\tconn->adie_thermal_cleared', 1)
marker = 'if(addr>=0xb130 && addr<=0xb13c && !(addr&3)) {'
assert marker in base
base = base.replace(marker, '''if(addr==0xb034 || addr==0xb038) {
    assert(thermal_mode());thermal_reads++;
    adie_spi[0x58/4]=thermal_words[(addr-0xb034)/4] ^ (thermal_reads==thermal_drift?1U:0U);
    if(thermal_reads==thermal_late)adie_clock+=2000000000ULL;
   } else ''' + marker, 1)
base = base.replace('(addr>=0xb130 && addr<=0xb13c && !(addr&3)) || addr==0xb108',
                    'addr==0xb034 || addr==0xb038 || (addr>=0xb130 && addr<=0xb13c && !(addr&3)) || addr==0xb108')
base = base.replace('"adie-efuse-handoff-cycle",23','"adie-thermal-read",18')
harness = base + r'''
static bool thermal_mode(void) {return conn.adie_thermal_started;}
static void thermal_setup(void) {
 hand_setup();thermal_words[0]=0x91ab7342;thermal_words[1]=0x5e3196cd;
 thermal_reads=thermal_drift=thermal_late=thermal_wipes=0;
}
static void thermal_clean(void) {
 clean_secret();assert(conn.adie_thermal_cleared && thermal_wipes==1);
 for(unsigned i=0;i<2;i++)if(thermal_words[i]!=0x66358a11)for(unsigned j=0;j+4<=sizeof(conn);j++)
  assert(memcmp((unsigned char *)&conn+j,&thermal_words[i],4));
}
static void thermal_held(void) {
 thermal_clean();retained();assert(!sema_writes && fm_writes==1);
 assert(conn.adie_unsafe && conn.adie_fm_dirty && conn.adie_prefix_dirty==3);
 assert(conn.adie_mailbox_dirty && !conn.adie_thermal_complete);
 assert(conn.adie_efuse_handoff_complete && !conn.adie_efuse_handoff_dirty);
 for(unsigned i=1;i<=4;i++)assert(!MAILBOX[i]);
}
int main(void) {
 char output[4096];
 thermal_setup();assert(data_run()==18);stopped();thermal_clean();
 assert(conn.adie_thermal_complete && thermal_reads==4 && conn.adie_thermal_transfers==16);
 assert(conn.adie_thermal_issued==15 && conn.adie_thermal_read==15 && conn.adie_thermal_matched==3);
 assert(conn.adie_efuse_data_transfers==32 && private_reads==8 && hand_writes==8 && adie_writes==161);
 assert(efuse_status_show(&dev,NULL,output)>0 && strstr(output,"thermal_complete=1 thermal_cleared=1"));
 assert(adie_status_show(&dev,NULL,output)>0 && strstr(output,"private_diagnostics=redacted"));
 assert(!strstr(output,"91ab7342") && !strstr(output,"5e3196cd"));
 assert(data_run()==-EALREADY && thermal_reads==4);
 for(unsigned n=115;n<=146;n++) {
  thermal_setup();adie_drop=n;assert(data_run()<0);thermal_held();
  for(unsigned k=1;k<=4;k++) {
   thermal_setup();adie_loss=n;adie_change=k;assert(data_run()<0);thermal_held();assert(adie_writes==n);
  }
 }
 for(unsigned n=57;n<=72;n++) {
  thermal_setup();stuck_transfer=n;assert(data_run()==-ETIMEDOUT);thermal_held();
 }
 for(unsigned n=3;n<=4;n++) {
  thermal_setup();thermal_drift=n;assert(data_run()==-EIO);thermal_held();
  assert(!strcmp(conn.failure_stage,"adie-thermal-compare"));
 }
 for(unsigned n=9;n<=12;n++) {
  thermal_setup();private_ctrl_bad=n;assert(data_run()==-EIO);thermal_held();
 }
 for(unsigned n=1;n<=4;n++) {
  thermal_setup();thermal_late=n;assert(data_run()==-ETIMEDOUT);thermal_held();
 }
 thermal_setup();adie_fast=true;assert(data_run()==18);stopped();thermal_clean();
 assert(!conn.adie_thermal_busy_count);
 thermal_setup();adie_fast=true;thermal_words[0]=0x66358a11;
 assert(data_run()==-EAGAIN);thermal_held();
 thermal_setup();thermal_words[0]=thermal_words[1]=0;
 assert(data_run()==18);stopped();assert(thermal_wipes==1 && conn.adie_thermal_cleared);
 for(unsigned n=147;n<=161;n++) {
  thermal_setup();adie_drop=n;assert(data_run()<0);thermal_clean();assert(conn.adie_thermal_complete);
 }
 puts("PASS: thermal fixed four reads/16 transfers,32 dropped writes,128 guard faults,16 timeouts,"
      "2 repeat mismatches,4 changed controls,4 deadlines,no-busy/stale/zero responses,15 cleanup faults,"
      "private erasure/redaction and one-shot; no thermal writes");
}
'''
with tempfile.TemporaryDirectory() as tmp:
    path = Path(tmp)
    (path / 'test.c').write_text(harness)
    subprocess.run(['cc', '-O1', '-Wall', '-Wextra', '-Werror',
                    '-Wno-unused-parameter', '-Wno-unused-variable', '-Wno-unused-function',
                    '-fsanitize=undefined', '-fno-sanitize-recover=all',
                    str(path / 'test.c'), '-o', str(path / 'test')], check=True)
    subprocess.run([str(path / 'test')], check=True)
