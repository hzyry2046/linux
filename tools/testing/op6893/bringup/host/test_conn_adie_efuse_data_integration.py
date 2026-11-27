#!/usr/bin/env python3
# SPDX-License-Identifier: GPL-2.0-only
"""Private result reads: fixed addresses, repeated equality, zeroization and redaction."""
from pathlib import Path
import runpy
import subprocess
import tempfile

base = runpy.run_path(str(Path(__file__).with_name('test_conn_adie_efuse_stable_integration.py')))['harness']
base = base[:base.index('static int observe_run(void)')]
base = base.replace("#define memzero_explicit(p,n) memset(p,0,n)", '\nstatic bool data_mode(void);\nstatic uint32_t private_words[4];\nstatic unsigned private_reads,private_drift,private_ctrl_bad,private_ctrl_reads,private_late;\nstatic unsigned wipe_parents,wipe_samples;\nstatic void private_wipe(void *p,unsigned n) {\n if(n==20)wipe_parents++;else if(n==8)wipe_samples++;\n memset(p,0,n);for(unsigned i=0;i<n;i++)assert(!((unsigned char *)p)[i]);\n}\n\n#define memzero_explicit(p,n) private_wipe(p,n)', 1)
assert 'if(addr==0xb108) {' in base
base = base.replace('if(addr==0xb108) {', 'if(addr>=0xb130 && addr<=0xb13c && !(addr&3)) {\n    assert(data_mode());private_reads++;\n    adie_spi[0x58/4]=private_words[(addr-0xb130)/4] ^ (private_reads==private_drift?1U:0U);\n    if(private_reads==private_late)adie_clock+=2000000000ULL;\n   } else if(addr==0xb108) {', 1)
base = base.replace('ctrl_reads++;adie_spi[0x58/4]=engine_read() ^', 'ctrl_reads++;adie_spi[0x58/4]=engine_read() ^ (data_mode()?0x3bU:0U) ^\n     ((data_mode() && ++private_ctrl_reads==private_ctrl_bad)?BIT(29):0U) ^', 1)
base = base.replace('addr==0xb108 || addr==0xb02c', '(addr>=0xb130 && addr<=0xb13c && !(addr&3)) || addr==0xb108 || addr==0xb02c')
harness = base+r'''

static bool data_mode(void) {return conn.adie_efuse_data_started;}
static void data_setup(void) {
 observe_setup();
 private_words[0]=0x9172a3b4;private_words[1]=0xe165d2c3;
 private_words[2]=0x5a96c387;private_words[3]=0x7b24e6d1;
 private_reads=private_drift=private_ctrl_bad=private_ctrl_reads=private_late=0;
 wipe_samples=wipe_parents=0;
}
static int data_run(void) {return rail_cycle_store(&dev,NULL,"adie-efuse-data-read",20);}
static void clean_secret(void) {
 assert(conn.adie_efuse_data_cleared && wipe_parents==1);
 for(unsigned i=0;i<4;i++)if(private_words[i]!=0x66358a11)for(unsigned j=0;j+4<=sizeof(conn);j++)
  assert(memcmp((unsigned char *)&conn+j,&private_words[i],4));
}
static void data_held(void) {
 clean_secret();assert(conn.adie_unsafe && conn.adie_fm_dirty && conn.adie_prefix_dirty==3);
 assert(conn.adie_mailbox_dirty && !conn.adie_efuse_data_complete);
 retained();assert(!sema_writes && fm_writes==1);
}
int main(void) {
 data_setup();assert(data_run()==20);stopped();clean_secret();
 assert(conn.adie_efuse_data_complete && private_reads==8 && wipe_samples>=32);
 assert(conn.adie_efuse_data_transfers==32 && conn.adie_efuse_data_issued==255);
 assert(conn.adie_efuse_data_read==255 && conn.adie_efuse_data_matched==15 && engine_writes==1);
 assert(adie_writes==129 && conn.adie_efuse_complete && !conn.adie_efuse_pending);
 
 char output[4096];assert(adie_status_show(&dev,NULL,output)>0);
 assert(strstr(output,"private_diagnostics=redacted") && !strstr(output,"data_before="));
 assert(efuse_status_show(&dev,NULL,output)>0 && strstr(output,"data_complete=1 data_cleared=1"));
 assert(data_run()==-EALREADY && private_reads==8);
 for(unsigned i=0;i<8;i++)conn.adie_config_before[i]=conn.adie_config_value[i]=0x9172a3b4;
 conn.adie_data_before=conn.adie_id=0x9172a3b4;
 for(unsigned i=0;i<6;i++)conn.adie_prefix_before[i]=conn.adie_prefix_value[i]=0x9172a3b4;
 assert(adie_status_show(&dev,NULL,output)>0 && !strstr(output,"9172a3b4"));

 for(unsigned n=51;n<=114;n++) {
  data_setup();adie_drop=n;assert(data_run()<0);data_held();
 }
 for(unsigned n=51;n<=114;n++)for(unsigned kind=1;kind<=4;kind++) {
  data_setup();adie_loss=n;adie_change=kind;assert(data_run()<0);data_held();assert(adie_writes==n);
 }
 for(unsigned n=25;n<=56;n++) {
  data_setup();stuck_transfer=n;assert(data_run()==-ETIMEDOUT);data_held();
 }
 for(unsigned n=5;n<=8;n++) {
  data_setup();private_drift=n;assert(data_run()==-EIO);data_held();
  assert(!strcmp(conn.failure_stage,"adie-efuse-data-compare"));
 }
 for(unsigned n=1;n<=8;n++) {
  data_setup();private_ctrl_bad=n;assert(data_run()==-EIO);data_held();
 }
 data_setup();private_late=8;assert(data_run()==-ETIMEDOUT);data_held();
 assert(!strcmp(conn.failure_stage,"adie-efuse-data-deadline"));
 data_setup();adie_fast=true;;assert(data_run()==20);stopped();clean_secret();assert(!conn.adie_efuse_data_busy_count);
 data_setup();adie_fast=true;;private_words[0]=0x66358a11;assert(data_run()==-EAGAIN);data_held();
 for(unsigned n=115;n<=129;n++) {
  data_setup();adie_drop=n;assert(data_run()<0);clean_secret();
  assert(conn.adie_efuse_data_complete);
 }
 puts("PASS: nested private data fixed eight private reads/32 transfers,all64 dropped writes/write guard faults,"
      "32 SPI timeouts,4 repeat mismatches,8 lost-valid controls,2s deadline,stale/no-busy,zeroization and cleanup faults");
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
