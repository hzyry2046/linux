#!/usr/bin/env python3
# SPDX-License-Identifier: GPL-2.0-only
"""Private SYSRAM handoff with actual nested preparation and failure retention."""
from pathlib import Path
import runpy
import subprocess
import tempfile

base = runpy.run_path(str(Path(__file__).with_name('test_conn_adie_efuse_data_integration.py')))['harness']
base = base[:base.index('int main(void) {')]
marker = 'static u32 readl(void *p) {\n'
base = base.replace(marker, r'''
static unsigned hand_writes,hand_reads,hand_drop,hand_loss,hand_kind;
static unsigned hand_bad,hand_corrupt,hand_late;
static bool hand_map_fail,hand_mapped;
static bool hand_ptr(void *p) {
 for(unsigned i=1;i<=4;i++)if(p==MAILBOX+i)return true;
 return false;
}
''' + marker + r'''
 if(hand_mapped && hand_ptr(p)) {
  held_strap();assert(config_adie==3);
  unsigned n=++hand_reads;
  if(n==hand_corrupt)return *(u32 *)p ^ 1U;
  return *(u32 *)p;
 }
''', 1)
marker = 'static void writel(u32 value,void *p) {\n'
base = base.replace(marker, marker + r'''
 if(hand_mapped && hand_ptr(p)) {
  held_strap();assert(config_adie==3 && *MAILBOX==adie_response);
  unsigned n=++hand_writes;
  assert(n<=8 && p==MAILBOX+1+(n-1)%4);
  if(n<=4)assert(value==private_words[n-1]);else assert(!value);
  if(n!=hand_drop)*(u32 *)p=value;
  if(n==hand_late)adie_clock+=2000000000ULL;
  if(n==hand_loss) {
   if(hand_kind==1)fresh[0]&=~2;
   if(hand_kind==2)sema_hw[0x2400/4]=0;
   if(hand_kind==3)config_wt[2]^=0x4000000;
   if(hand_kind==4)config_busy=2;
  }
  return;
 }
 if(hand_writes && p==MAILBOX && !value) {
  assert(!hand_mapped && hand_writes==8);
  for(unsigned i=1;i<=4;i++)assert(!MAILBOX[i]);
 }
''', 1)
marker = 'static void *ioremap(unsigned long addr,unsigned long size) {\n'
base = base.replace(marker, marker + r'''
 if(addr==0x18052804) {
  assert(size==16 && adie_live && !hand_mapped);
  if(hand_map_fail)return NULL;
  maps++;hand_mapped=true;
  if(hand_bad)MAILBOX[hand_bad]=1;
  return MAILBOX+1;
 }
''', 1)
marker = 'static void iounmap(void *p) {\n'
base = base.replace(marker, marker + ' if(p==MAILBOX+1){assert(hand_mapped);hand_mapped=false;unmaps++;return;}\n', 1)
base = base.replace('"adie-efuse-data-read",20', '"adie-efuse-handoff-cycle",23')
harness = base + r'''
static void hand_setup(void) {
 data_setup();hand_writes=hand_reads=hand_drop=hand_loss=hand_kind=0;
 hand_bad=hand_corrupt=hand_late=0;hand_map_fail=hand_mapped=false;
}
static void hand_held(void) {
 clean_secret();retained();assert(!hand_mapped && !sema_writes && fm_writes==1);
 assert(conn.adie_unsafe && conn.adie_fm_dirty && conn.adie_prefix_dirty==3);
 assert(conn.adie_mailbox_dirty && conn.adie_efuse_data_complete);
 assert(!conn.adie_efuse_handoff_complete);
 if(hand_writes)assert(conn.adie_efuse_handoff_dirty);
}
int main(void) {
 char output[4096];
 hand_setup();assert(data_run()==23);stopped();clean_secret();
 assert(hand_writes==8 && hand_reads==16 && !hand_mapped);
 assert(conn.adie_efuse_handoff_complete && !conn.adie_efuse_handoff_dirty);
 assert(conn.adie_efuse_handoff_issued==15 && conn.adie_efuse_handoff_verified==15);
 assert(conn.adie_efuse_handoff_cleared==15 && private_reads==8);
 assert(efuse_status_show(&dev,NULL,output)>0 && strstr(output,"handoff_complete=1"));
 assert(adie_status_show(&dev,NULL,output)>0 && strstr(output,"private_diagnostics=redacted"));
 for(unsigned i=0;i<4;i++){char word[16];snprintf(word,sizeof(word),"%x",private_words[i]);assert(!strstr(output,word));}
 assert(data_run()==-EALREADY && hand_writes==8);
 hand_setup();hand_map_fail=true;assert(data_run()==-ENOMEM);hand_held();assert(!hand_writes);
 for(unsigned n=1;n<=4;n++) {
  hand_setup();hand_bad=n;assert(data_run()==-EBUSY);hand_held();assert(!hand_writes);
 }
 for(unsigned n=1;n<=8;n++) {
  hand_setup();hand_drop=n;assert(data_run()==-EIO);hand_held();assert(hand_writes==n);
  hand_setup();hand_late=n;assert(data_run()==-ETIMEDOUT);hand_held();assert(hand_writes==n);
  for(unsigned k=1;k<=4;k++) {
   hand_setup();hand_loss=n;hand_kind=k;assert(data_run()<0);hand_held();assert(hand_writes==n);
  }
 }
 for(unsigned n=5;n<=16;n++) {
  hand_setup();hand_corrupt=n;assert(data_run()==-EIO);hand_held();
  if(n>=13)assert(conn.adie_efuse_handoff_cleared==15 && conn.adie_efuse_handoff_dirty==15);
 }
 hand_setup();memset(private_words,0,sizeof(private_words));
 assert(data_run()==23);stopped();assert(conn.adie_efuse_handoff_complete);
 assert(conn.adie_efuse_data_cleared && wipe_parents==1);
 puts("PASS: nested handoff, fixed mapping, erase before parent release, redaction, one-shot, zero words,"
      "mapping/baseline faults, all8 dropped writes/deadlines,32 guard losses,12 readback/final faults");
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
