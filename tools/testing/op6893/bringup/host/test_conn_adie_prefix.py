#!/usr/bin/env python3
# SPDX-License-Identifier: GPL-2.0-only
"""Actual two-register config prefix with held mailbox and reverse restoration."""
from pathlib import Path
import runpy
import subprocess
import tempfile

base = runpy.run_path(str(Path(__file__).with_name('test_conn_adie_mailbox.py')))['harness']
base = base[:base.index('int main(void) {')]
base = base.replace('static u32 response,mailbox;',
                    'static u32 response,mailbox,analog[2],original[2],corrupt_value;\n'
                    'static unsigned transfers,stuck_transfer,corrupt_transfer,mail_reads,mail_loss;')
base = base.replace('if(p==sema+0x2400/4)',
                    'if(p==&mailbox && conn.adie_mailbox_applied && ++mail_reads==mail_loss)mailbox^=1;\n if(p==sema+0x2400/4)',1)
start = base.index('static void writel(')
end = base.index('#define read_poll_timeout',start)
base = base[:start] + r'''
static void writel(u32 value,void *p) {
 assert(!inaccessible && !conn.adie_unsafe && sema[0x2400/4]==0x800 && wb==0x80000);
 assert(p==&control || p==spi+0x50/4 || p==spi+0x54/4 || p==&mailbox);
 unsigned n=++writes;
 if(p==&mailbox) {
  assert(conn.adie_mailbox_dirty && control==3 && (value==response || !value));
  if(!value)assert(!conn.adie_prefix_dirty && analog[0]==original[0] && analog[1]==original[1]);
  if(n!=dropwrite)mailbox=value;
 } else if(p==&control) {
  assert(value==2 || value==3);assert(conn.adie_reset_dirty);
  if(value==2)assert(!conn.adie_mailbox_dirty && !mailbox && !conn.adie_prefix_dirty);
  if(n!=dropwrite)control=value;
 } else if(p==spi+0x50/4) {
  assert(conn.adie_addr_dirty);
  assert(value==0xb02c || value==0xb064 || value==0xb0bc || value==0xa064 || value==0xa0bc || value==0x1234);
  if(n!=dropwrite)*(u32 *)p=value;
 } else {
  assert(control==3 && conn.adie_triggered);
  u32 addr=spi[0x50/4];bool writing=addr==0xa064 || addr==0xa0bc;
  unsigned bit=addr==0xa0bc;
  if(writing) {
   assert(mailbox==response && conn.adie_mailbox_dirty && (conn.adie_prefix_dirty & (1U<<bit)));
   assert(bit?(value==1 || value==0x21):(!value || value==0x7700));
  } else assert(!value && (addr==0xb02c || addr==0xb064 || addr==0xb0bc));
  if(n!=dropwrite) {
   transfers++;triggered=true;busy_reads=0;stuck=transfers==stuck_transfer;
   if(writing)analog[bit]=value;
   else spi[0x58/4]=addr==0xb02c?response:analog[addr==0xb0bc];
   if(transfers==corrupt_transfer)spi[0x58/4]=corrupt_value;
  }
 }
 if(n==losswrite)lose();
}
''' + base[end:]
harness = base + r'''
static void prefix_setup(void) {
 mailbox_setup();conn.adie_prefix_requested=conn.adie_config_requested=true;
 response=0x66358a11;analog[0]=original[0]=0;analog[1]=original[1]=1;
 transfers=stuck_transfer=corrupt_transfer=mail_reads=mail_loss=0;corrupt_value=0xdeadbeef;
}
int main(void) {
 prefix_setup();assert(!run());restored();
 unsigned total_guards=guards,owners=owner_count,points[1024],total_mail_reads=mail_reads;
 memcpy(points,owner_reads,sizeof(points));
 assert(writes==43 && transfers==19 && conn.adie_complete);
 assert(conn.adie_prefix_applied==3 && conn.adie_prefix_restored==3 && !conn.adie_prefix_dirty);
 assert(conn.adie_prefix_issued==0x95 && conn.adie_prefix_read==63 && conn.adie_prefix_busy_mask==1023);
 assert(conn.adie_prefix_value[0]==0x7700 && conn.adie_prefix_value[1]==0x21);
 assert(conn.adie_prefix_value[2]==response && conn.adie_prefix_value[3]==1);
 assert(conn.adie_prefix_value[4]==response && !conn.adie_prefix_value[5]);
 assert(conn.adie_mailbox_restored && !mailbox && analog[0]==0 && analog[1]==1);
 for(unsigned i=1;i<=total_guards;i++) {
  prefix_setup();guardfail=i;assert(run()<0 && conn.adie_unsafe && !conn.adie_complete);
 }
 for(unsigned i=0;i<owners;i++) {
  prefix_setup();lossread=points[i];losstype=3;assert(run()<0 && !conn.adie_complete);
 }
 for(unsigned i=1;i<=total_mail_reads;i++) {
  prefix_setup();mail_loss=i;assert(run()<0 && conn.adie_unsafe && !conn.adie_complete);
 }
 for(unsigned i=1;i<=43;i++) {
  prefix_setup();dropwrite=i;assert(run()<0 && !conn.adie_complete);
  if(i>=2 && i<=28){restored();assert(!conn.adie_prefix_dirty && !mailbox);}
  else assert(conn.adie_unsafe || conn.adie_addr_dirty);
 }
 for(unsigned i=1;i<=43;i++)for(unsigned kind=1;kind<=5;kind++) {
  prefix_setup();losswrite=i;losstype=kind;assert(run()<0 && conn.adie_unsafe && writes==i);
 }
 for(unsigned i=10;i<=19;i++) {
  prefix_setup();stuck_transfer=i;assert(run()==-ETIMEDOUT && conn.adie_prefix_dirty);
  assert(writes==2*i+2 && control==3 && mailbox==response);
 }
 prefix_setup();busy_cycles=0;assert(!run());restored();assert(!conn.adie_prefix_busy_mask);
 for(unsigned n=0;n<3;n++) {
  prefix_setup();if(!n)response=0x66358a10;else analog[n-1]=original[n-1]=8+n;
  assert(run()==-EINVAL);restored();assert(!conn.adie_prefix_issued);
 }
 for(unsigned n=11;n<=13;n+=2) {
  prefix_setup();corrupt_transfer=n;assert(run()==-EIO);restored();
  assert(!conn.adie_prefix_dirty && !strcmp(conn.failure_stage,"adie-prefix-apply-verify"));
 }
 for(unsigned n=15;n<=19;n++) {
  if(n==17)continue;
  prefix_setup();corrupt_transfer=n;assert(run()==-EIO && conn.adie_prefix_dirty && conn.adie_unsafe);
 }
 prefix_setup();busy_cycles=0;dropwrite=24;
 assert(run()==-EAGAIN && conn.adie_prefix_dirty==1 && conn.adie_unsafe);
 assert(mailbox==response && control==3);
 prefix_setup();corrupt_transfer=13;dropwrite=30;
 assert(run()==-EIO && conn.adie_prefix_cleanup && conn.adie_prefix_dirty==3);
 assert(!strcmp(conn.failure_stage,"adie-prefix-apply-verify"));
 puts("PASS: actual held-mailbox config apply/reverse-restore,43 dropped writes,215 write faults,"
      "all guard/owner/mailbox samples,10 timeouts,exact baseline refusal,corrupt/stale responses,"
      "partial apply cleanup and first-error preservation");
}
'''
with tempfile.TemporaryDirectory() as tmp:
    path = Path(tmp)
    (path / 'test.c').write_text(harness)
    subprocess.run(['cc', '-O1', '-Wall', '-Wextra', '-Werror',
                    '-fsanitize=undefined', '-fno-sanitize-recover=all',
                    str(path / 'test.c'), '-o', str(path / 'test')], check=True)
    subprocess.run([str(path / 'test')], check=True)
