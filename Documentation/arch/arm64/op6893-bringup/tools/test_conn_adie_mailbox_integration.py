#!/usr/bin/env python3
# SPDX-License-Identifier: GPL-2.0-only
"""Mailbox uses the same SYSRAM storage as nested initialization, not a stub."""
from pathlib import Path
import runpy
import subprocess
import tempfile

base = runpy.run_path(str(Path(__file__).with_name('test_conn_adie_integration.py')))['harness']
base = base[:base.index('int main(void) {')]
base = base.replace('static u32 adie_spi[0x5c/4],adie_response;',
                    'static u32 adie_spi[0x5c/4],adie_response;\n'
                    '#define MAILBOX (ram_hw+1+0x2800/4)\n'
                    'static bool mailbox_bad,mailbox_map_fail;\n'
                    'static bool mailbox_dirty(void);')
base = base.replace('static u32 readl(void *p) {\n',
                    'static u32 readl(void *p) {\n'
                    ' if(adie_live && p==MAILBOX){held_strap();assert(config_adie==3);return *MAILBOX;}\n',1)
base = base.replace('p==&config_adie || p==adie_spi+0x50/4 || p==adie_spi+0x54/4',
                    'p==&config_adie || p==adie_spi+0x50/4 || p==adie_spi+0x54/4 || (adie_live && p==MAILBOX)',1)
base = base.replace('if(p==&config_adie){assert(value==2 || value==3);config_adie=value;}',
                    'if(p==MAILBOX){assert(mailbox_dirty() && config_adie==3 && (!value || value==adie_response));*MAILBOX=value;}\n'
                    '   else if(p==&config_adie){assert(value==2 || value==3);'
                    'if(value==2)assert(!mailbox_dirty() && !*MAILBOX);config_adie=value;}')
base = base.replace('static void *ioremap(unsigned long addr,unsigned long size) {\n',
                    'static void *ioremap(unsigned long addr,unsigned long size) {\n'
                    ' if(addr==0x18052800){assert(adie_live && size==4);if(mailbox_map_fail)return NULL;'
                    'maps++;if(mailbox_bad)*MAILBOX=0xdeadbeef;return MAILBOX;}\n',1)
base = base.replace('static void iounmap(void *p) {\n',
                    'static void iounmap(void *p) {\n if(p==MAILBOX){unmaps++;return;}\n',1)
harness = base + r'''
static bool mailbox_dirty(void) {return conn.adie_mailbox_dirty;}
static void mailbox_setup(void) {adie_setup();mailbox_bad=mailbox_map_fail=false;}
static int mailbox_run(void) {return rail_cycle_store(&dev,NULL,"adie-mailbox-cycle",18);}
int main(void) {
 char output[4096];
 mailbox_setup();assert(mailbox_run()==18);stopped();
 assert(conn.adie_complete && conn.adie_mailbox_applied && conn.adie_mailbox_restored);
 assert(!conn.adie_mailbox_dirty && !*MAILBOX && adie_writes==7 && ram_writes==4096 && ram_reads==8192);
 assert(conn.sema_released && conn.adie_reset_restored);
 assert(adie_status_show(&dev,NULL,output)>0 && strstr(output,"mailbox_applied=1 mailbox_restored=1 mailbox_dirty=0"));
 assert(mailbox_run()==-EALREADY && adie_writes==7);
 for(unsigned n=1;n<=7;n++) {
  mailbox_setup();adie_drop=n;assert(mailbox_run()<0 && !conn.adie_complete);
  if(n==2 || n==3 || n==4)stopped();
  else {
   retained();assert(conn.sema_pending && conn.sema_unsafe && conn.strap_unsafe);
   assert(!sema_writes && config_writes==36 && rgu_writes==4 && remap_writes==4);
  }
 }
 for(unsigned n=1;n<=7;n++)for(unsigned kind=1;kind<=4;kind++) {
  mailbox_setup();adie_loss=n;adie_change=kind;assert(mailbox_run()<0);retained();
  assert(adie_writes==n && conn.adie_unsafe && conn.sema_pending && conn.strap_unsafe);
  assert(!sema_writes && config_writes==36 && rgu_writes==4 && remap_writes==4);
 }
 mailbox_setup();mailbox_bad=true;assert(mailbox_run()==-EBUSY);retained();
 assert(!conn.adie_mailbox_issued && *MAILBOX==0xdeadbeef && adie_writes==3 && !sema_writes);
 mailbox_setup();mailbox_map_fail=true;assert(mailbox_run()==-ENOMEM);stopped();
 assert(!conn.adie_mailbox_issued && adie_writes==5);
 mailbox_setup();adie_drop=4;adie_loss=5;adie_change=1;
 assert(mailbox_run()==-EIO);retained();
 assert(!strcmp(conn.failure_stage,"adie-mailbox-readback") && conn.adie_mailbox_cleanup);
 mailbox_setup();config_drop_write=37;assert(mailbox_run()==-EIO);retained();
 assert(conn.adie_complete && conn.adie_mailbox_restored && conn.sema_released && conn.spi_config_dirty);
 mailbox_setup();conn.domain_allowed=false;assert(mailbox_run()==-EOPNOTSUPP && !conn.attempted);
 mailbox_setup();conn.emi_valid=false;assert(mailbox_run()==-EINVAL && !conn.attempted);
 puts("PASS: nested ID mailbox shares SYSRAM,clear-before-reset/unlock,7 dropped writes,"
      "28 guard losses,unexpected-content containment,map failure,first-error preservation,"
      "outer restore failure and one-shot routing");
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
