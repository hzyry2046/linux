#!/usr/bin/env python3
# SPDX-License-Identifier: GPL-2.0-only
"""Actual fixed A18 write/restore with independent stateful analog registers."""
from pathlib import Path
import runpy
import subprocess
import tempfile

base = runpy.run_path(str(Path(__file__).with_name('test_conn_adie.py')))['harness']
base = base[:base.index('int main(void) {')]
base = base.replace('static u32 response;',
                    'static u32 response, analog[2], corrupt_value;\n'
                    'static unsigned transfers, stuck_transfer, corrupt_transfer;')
start = base.index('static void writel(')
end = base.index('#define read_poll_timeout', start)
base = base[:start] + r'''
static void writel(u32 value,void *p) {
 assert(!inaccessible && !conn.adie_unsafe && sema[0x2400/4]==0x800 && wb==0x80000);
 assert(p==&control || p==spi+0x50/4 || p==spi+0x54/4);
 unsigned n=++writes;
 if(p==&control) {
  assert(value==2 || value==3);
  assert(conn.adie_reset_dirty);
  if(value==2)assert(!conn.adie_write_dirty);
  if(n!=dropwrite)control=value;
 } else if(p==spi+0x50/4) {
  assert(conn.adie_addr_dirty);
  assert(value==0xb02c || value==0xba18 || value==0xba1c || value==0xaa18 || value==0x1234);
  if(n!=dropwrite)*(u32 *)p=value;
 } else {
  assert(control==3 && conn.adie_triggered);
  u32 addr=spi[0x50/4];
  if(addr==0xaa18) {
   assert(conn.adie_write_dirty);
   assert(value==0xf6e8fff5 || value==0xf668fff5);
  } else assert(!value && (addr==0xb02c || addr==0xba18 || addr==0xba1c));
  if(n!=dropwrite) {
   transfers++;triggered=true;busy_reads=0;stuck=transfers==stuck_transfer;
   if(addr==0xaa18)analog[0]=value;
   else spi[0x58/4]=addr==0xb02c?response:analog[(addr-0xba18)/4];
   if(transfers==corrupt_transfer)spi[0x58/4]=corrupt_value;
  }
 }
 if(n==losswrite)lose();
}
''' + base[end:]
harness = base + r'''
static void write_setup(void) {
 setup();conn.adie_write_requested=conn.adie_xtal_requested=true;
 response=0x66358a11;analog[0]=0xf668fff5;analog[1]=0x55555fff;
 transfers=stuck_transfer=corrupt_transfer=0;corrupt_value=0;
}
int main(void) {
 write_setup();assert(!run());restored();
 unsigned total_guards=guards,owners=owner_count,points[1024];
 memcpy(points,owner_reads,sizeof(points));
 assert(writes==19 && transfers==8 && conn.adie_complete);
 assert(conn.adie_write_applied && conn.adie_write_restored && !conn.adie_write_dirty);
 assert(conn.adie_write_issued==3 && conn.adie_write_read==7 && conn.adie_write_busy_mask==31);
 assert(conn.adie_write_value[0]==0xf6e8fff5 && conn.adie_write_value[1]==response);
 assert(conn.adie_write_value[2]==0xf668fff5 && analog[0]==0xf668fff5);
 for(unsigned i=1;i<=total_guards;i++) {
  write_setup();guardfail=i;assert(run()<0 && conn.adie_unsafe && !conn.adie_complete);
 }
 for(unsigned i=0;i<owners;i++) {
  write_setup();lossread=points[i];losstype=3;assert(run()<0 && !conn.adie_complete);
 }
 for(unsigned i=1;i<=19;i++) {
  write_setup();dropwrite=i;assert(run()<0 && !conn.adie_complete);
  if(i>=2 && i<=11){restored();assert(!conn.adie_write_dirty && analog[0]==0xf668fff5);}
  if(i>=12 && i<=17)assert(conn.adie_write_dirty && conn.adie_unsafe && control==3);
 }
 for(unsigned i=1;i<=19;i++)for(unsigned kind=1;kind<=5;kind++) {
  write_setup();losswrite=i;losstype=kind;assert(run()<0 && conn.adie_unsafe && writes==i);
 }
 for(unsigned i=4;i<=8;i++) {
  write_setup();stuck_transfer=i;assert(run()==-ETIMEDOUT && conn.adie_write_dirty);
  assert(writes==1+2*i && control==3);
 }
 write_setup();busy_cycles=0;assert(!run());restored();assert(!conn.adie_write_busy_mask);
 for(unsigned n=0;n<3;n++) {
  write_setup();if(n==0)response=0x66358a10;else analog[n-1]^=1;
  assert(run()==-EINVAL);restored();assert(!conn.adie_write_issued && writes==9);
 }
 write_setup();corrupt_transfer=5;corrupt_value=0xdeadbeef;
 assert(run()==-EIO);restored();assert(conn.adie_write_restored && !conn.adie_write_applied);
 assert(!strcmp(conn.failure_stage,"adie-write-apply-verify"));
 write_setup();corrupt_transfer=5;corrupt_value=0xdeadbeef;dropwrite=13;
 assert(run()==-EIO && conn.adie_write_dirty && conn.adie_write_cleanup);
 assert(!strcmp(conn.failure_stage,"adie-write-apply-verify"));
 for(unsigned n=7;n<=8;n++) {
  write_setup();corrupt_transfer=n;corrupt_value=0xdeadbeef;
  assert(run()==-EIO && conn.adie_write_dirty && conn.adie_unsafe && control==3);
 }
 /* No busy and unchanged latch must fail even if it looks like a good value. */
 write_setup();busy_cycles=0;dropwrite=11;
 assert(run()==-EAGAIN);restored();assert(conn.adie_write_restored && !conn.adie_write_applied);
 puts("PASS: actual A18 apply/read/restore/ID/read,exact baseline refusal,19 dropped writes,"
      "95 write-time faults,all guard/owner losses,5 busy timeouts,corrupt/stale readbacks,"
      "original-error preservation and analog restoration before reset");
}
'''
with tempfile.TemporaryDirectory() as tmp:
    path = Path(tmp)
    (path / 'test.c').write_text(harness)
    subprocess.run(['cc', '-O1', '-Wall', '-Wextra', '-Werror',
                    '-fsanitize=undefined', '-fno-sanitize-recover=all',
                    str(path / 'test.c'), '-o', str(path / 'test')], check=True)
    subprocess.run([str(path / 'test')], check=True)
