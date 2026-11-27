#!/usr/bin/env python3
# SPDX-License-Identifier: GPL-2.0-only
"""Whole config prefix with shared SYSRAM and independent analog state."""
from pathlib import Path
import runpy
import subprocess
import tempfile

base = runpy.run_path(str(Path(__file__).with_name('test_conn_adie_mailbox_integration.py')))['harness']
base = base[:base.index('int main(void) {')]
base = base.replace('static u32 adie_spi[0x5c/4],adie_response;',
                    'static u32 adie_spi[0x5c/4],adie_response,analog[2];\n'
                    'static unsigned transfers,stuck_transfer,corrupt_transfer;\n'
                    'static unsigned prefix_dirty(void);')
base = base.replace('assert(mailbox_dirty() && config_adie==3 && (!value || value==adie_response));*MAILBOX=value;',
                    'assert(mailbox_dirty() && config_adie==3 && (!value || value==adie_response));'
                    'if(!value)assert(!prefix_dirty() && !analog[0] && analog[1]==1);*MAILBOX=value;')
old = '''else {assert(!value && config_adie==3 && adie_spi[0x50/4]==0xb02c && !adie_fired);
    adie_fired=true;adie_spi[0x58/4]=adie_response;}'''
new = r'''else {
    assert(config_adie==3);u32 addr=adie_spi[0x50/4];
    if(addr==0xa064 || addr==0xa0bc) {
     unsigned bit=addr==0xa0bc;
     assert(*MAILBOX==adie_response && mailbox_dirty() && (prefix_dirty() & (1U<<bit)));
     assert(bit?(value==1 || value==0x21):(!value || value==0x7700));analog[bit]=value;
    } else {
     assert(!value && (addr==0xb02c || addr==0xb064 || addr==0xb0bc));
     adie_spi[0x58/4]=addr==0xb02c?adie_response:analog[addr==0xb0bc];
    }
    transfers++;adie_fired=true;adie_reads=0;if(transfers==stuck_transfer)adie_stuck=true;
    if(transfers==corrupt_transfer)adie_spi[0x58/4]=0xdeadbeef;
   }'''
assert old in base
base = base.replace(old,new)
harness = base + r'''
static unsigned prefix_dirty(void) {return conn.adie_prefix_dirty;}
static void prefix_setup(void) {
 mailbox_setup();transfers=stuck_transfer=corrupt_transfer=0;adie_response=0x66358a11;
 analog[0]=0;analog[1]=1;
}
static int prefix_run(void) {return rail_cycle_store(&dev,NULL,"adie-config-cycle",17);}
int main(void) {
 char output[4096];
 prefix_setup();assert(prefix_run()==17);stopped();
 assert(conn.adie_complete && conn.adie_prefix_applied==3 && conn.adie_prefix_restored==3);
 assert(!conn.adie_prefix_dirty && !*MAILBOX && adie_writes==43 && transfers==19);
 assert(conn.adie_mailbox_restored && conn.sema_released && conn.adie_reset_restored);
 assert(adie_status_show(&dev,NULL,output)>0 && strstr(output,"prefix_restored=0x3 prefix_dirty=0"));
 assert(prefix_run()==-EALREADY && adie_writes==43);
 for(unsigned n=1;n<=43;n++) {
  prefix_setup();adie_drop=n;assert(prefix_run()<0 && !conn.adie_complete);
  if(n>=2 && n<=28) {stopped();assert(!conn.adie_prefix_dirty && !*MAILBOX);}
  else {
   retained();assert(conn.sema_pending && conn.sema_unsafe && conn.strap_unsafe);
   assert(!sema_writes && config_writes==36 && rgu_writes==4 && remap_writes==4);
  }
 }
 for(unsigned n=1;n<=43;n++)for(unsigned kind=1;kind<=4;kind++) {
  prefix_setup();adie_loss=n;adie_change=kind;assert(prefix_run()<0);retained();
  assert(adie_writes==n && conn.adie_unsafe && conn.sema_pending && conn.strap_unsafe);
  assert(!sema_writes && config_writes==36 && rgu_writes==4 && remap_writes==4);
 }
 for(unsigned n=10;n<=19;n++) {
  prefix_setup();stuck_transfer=n;assert(prefix_run()==-ETIMEDOUT);retained();
  assert(!sema_writes && adie_writes==2*n+2 && config_adie==3 && *MAILBOX==adie_response);
 }
 prefix_setup();corrupt_transfer=13;assert(prefix_run()==-EIO);stopped();
 assert(conn.adie_prefix_restored==3 && !strcmp(conn.failure_stage,"adie-prefix-apply-verify"));
 prefix_setup();corrupt_transfer=13;adie_drop=30;assert(prefix_run()==-EIO);retained();
 assert(conn.adie_prefix_dirty==3 && conn.adie_mailbox_dirty && !sema_writes);
 assert(!strcmp(conn.failure_stage,"adie-prefix-apply-verify"));
 prefix_setup();adie_fast=true;adie_drop=24;assert(prefix_run()==-EAGAIN);retained();
 assert(conn.adie_prefix_dirty==1 && *MAILBOX==adie_response);
 prefix_setup();config_drop_write=37;assert(prefix_run()==-EIO);retained();
 assert(conn.adie_complete && conn.adie_mailbox_restored && conn.sema_released && conn.spi_config_dirty);
 prefix_setup();conn.domain_allowed=false;assert(prefix_run()==-EOPNOTSUPP && !conn.attempted);
 puts("PASS: nested config prefix/shared mailbox,43 dropped writes,172 guard faults,10 timeouts,"
      "partial apply cleanup,uncertain separator retention,first-error preservation,outer restore failure");
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
