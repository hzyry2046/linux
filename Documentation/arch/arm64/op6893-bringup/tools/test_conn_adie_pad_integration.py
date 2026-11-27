#!/usr/bin/env python3
# SPDX-License-Identifier: GPL-2.0-only
"""Gate post-trim TOP070 reads on a fresh no-op plan; retain on uncertainty."""
from pathlib import Path
import runpy
import subprocess
import tempfile

base = runpy.run_path(str(Path(__file__).with_name('test_conn_adie_trim_plan_integration.py')))['harness']
base = base[:base.index('int main(void) {')]
base = base.replace('static bool thermal_mode(void);', '''static bool thermal_mode(void);
static uint32_t pad_value;
static unsigned pad_reads,pad_drift,pad_late,pad_wipes;
static bool pad_mode(void);''',1)
base = base.replace('#define memzero_explicit(p,n) private_wipe(p,n)',
    'static void pad_wipe(void *p,unsigned n) {assert(n==8);pad_wipes++;private_wipe(p,n);}'
    '\n#define memzero_explicit(p,n) private_wipe(p,n)',1)
base = base.replace('memzero_explicit(&data, sizeof(data));\n\tconn->adie_pad_cleared',
                    'pad_wipe(&data, sizeof(data));\n\tconn->adie_pad_cleared',1)
marker='if(addr==0xb034 || addr==0xb038) {'
assert marker in base
base = base.replace(marker, '''if(addr==0xb070) {
    assert(pad_mode());pad_reads++;
    adie_spi[0x58/4]=pad_value ^ (pad_reads==pad_drift?1U:0U);
    if(pad_reads==pad_late)adie_clock+=2000000000ULL;
   } else '''+marker,1)
base = base.replace('addr==0xb034 || addr==0xb038 || (addr>=0xb130',
                    'addr==0xb070 || addr==0xb034 || addr==0xb038 || (addr>=0xb130')
base = base.replace('"adie-thermal-plan",18','"adie-pad-read",14')
harness = base + r'''
static bool pad_mode(void) {return conn.adie_pad_started;}
static void pad_setup(void) {
 thermal_setup();private_words[1]&=~0x8080U;
 pad_value=0x92837465;pad_reads=pad_drift=pad_late=pad_wipes=0;plan_fault=0;
}
static void pad_clean(void) {
 thermal_clean();assert(conn.adie_pad_cleared && pad_wipes==1);
 if(pad_value!=0x66358a11)for(unsigned i=0;i+4<=sizeof(conn);i++)
  if((unsigned char *)&conn+i+4<=(unsigned char *)&conn.adie_pad_value ||
     (unsigned char *)&conn+i>=(unsigned char *)(&conn.adie_pad_value+1))
   assert(memcmp((unsigned char *)&conn+i,&pad_value,4));
}
static void pad_held(void) {
 pad_clean();retained();assert(conn.adie_unsafe && !conn.adie_pad_complete);
 assert(!conn.adie_pad_value_valid && !conn.adie_pad_value);
 assert(conn.adie_fm_dirty && conn.adie_prefix_dirty==3 && conn.adie_mailbox_dirty);
 assert(!sema_writes && fm_writes==1 && conn.adie_trim_plan_complete);
 assert(conn.adie_efuse_handoff_complete && !conn.adie_efuse_handoff_dirty);
}
int main(void) {
 char output[4096];
 pad_setup();assert(data_run()==14);stopped();pad_clean();
 assert(conn.adie_pad_complete && conn.adie_pad_matched && !conn.adie_pad_target_match);
 assert(conn.adie_pad_value_valid && conn.adie_pad_value==0x92837465);
 assert(conn.adie_pad_issued==3 && conn.adie_pad_read==3 && conn.adie_pad_transfers==8 && pad_reads==2);
 assert(conn.adie_thermal_transfers==16 && conn.adie_efuse_data_transfers==32 && adie_writes==177);
 assert(efuse_status_show(&dev,NULL,output)>0 && strstr(output,"pad_complete=1 pad_cleared=1"));
 assert(strstr(output,"pad_value_valid=1 pad_value=0x92837465"));
 assert(adie_status_show(&dev,NULL,output)>0 && strstr(output,"private_diagnostics=redacted"));
 assert(!strstr(output,"92837465"));assert(data_run()==-EALREADY && pad_reads==2);
 pad_setup();private_words[1]=0x80000080;
 assert(data_run()==-EOPNOTSUPP);pad_held();assert(!conn.adie_pad_started && !pad_reads && adie_writes==146);
 assert(!strcmp(conn.failure_stage,"adie-pad-noop-prerequisite"));
 for(unsigned n=147;n<=162;n++) {
  pad_setup();adie_drop=n;assert(data_run()<0);pad_held();
  for(unsigned k=1;k<=4;k++) {
   pad_setup();adie_loss=n;adie_change=k;assert(data_run()<0);pad_held();assert(adie_writes==n);
  }
 }
 for(unsigned n=73;n<=80;n++) {
  pad_setup();stuck_transfer=n;assert(data_run()==-ETIMEDOUT);pad_held();
 }
 pad_setup();pad_drift=2;assert(data_run()==-EIO);pad_held();
 assert(!strcmp(conn.failure_stage,"adie-pad-compare"));
 for(unsigned n=13;n<=14;n++) {
  pad_setup();private_ctrl_bad=n;assert(data_run()==-EIO);pad_held();
 }
 for(unsigned n=1;n<=2;n++) {
  pad_setup();pad_late=n;assert(data_run()==-ETIMEDOUT);pad_held();
 }
 pad_setup();adie_fast=true;assert(data_run()==14);stopped();pad_clean();assert(!conn.adie_pad_busy_count);
 pad_setup();adie_fast=true;pad_value=0x66358a11;assert(data_run()==-EAGAIN);pad_held();
 pad_setup();pad_value=0;assert(data_run()==14);stopped();
 assert(conn.adie_pad_cleared && pad_wipes==1 && conn.adie_pad_value_valid && !conn.adie_pad_value);
 pad_setup();pad_value=0x80000000;assert(data_run()==14);stopped();
 assert(conn.adie_pad_target_match && conn.adie_pad_value_valid && conn.adie_pad_value==0x80000000);
 for(unsigned n=163;n<=177;n++) {
  pad_setup();adie_drop=n;assert(data_run()<0);pad_clean();
  assert(conn.adie_pad_complete && conn.adie_pad_value_valid && conn.adie_pad_value==0x92837465);
 }
 puts("PASS: fresh no-op gating, TOP070 two reads/eight transfers, target equality,16 dropped writes,64 guard faults,"
      "8 timeouts,repeat mismatch,2 control changes,2 deadlines,stale/zero/no-busy,15 cleanup faults,erasure/redaction/one-shot; no pad writes");
}
'''
with tempfile.TemporaryDirectory() as tmp:
    path=Path(tmp)
    (path/'test.c').write_text(harness)
    subprocess.run(['cc','-O1','-Wall','-Wextra','-Werror','-Wno-unused-parameter',
                    '-Wno-unused-variable','-Wno-unused-function','-fsanitize=undefined',
                    '-fno-sanitize-recover=all',str(path/'test.c'),'-o',str(path/'test')],check=True)
    subprocess.run([str(path/'test')],check=True)
