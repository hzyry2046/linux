#!/usr/bin/env python3
# SPDX-License-Identifier: GPL-2.0-only
"""Actual full SYSRAM clear under held RGU policies, with containment faults."""
from pathlib import Path
import runpy
import subprocess
import tempfile
here = Path(__file__).resolve().parent
base = runpy.run_path(str(here / 'test_conn_domain.py'))['harness']
base = base[:base.index('int main(void) {')]
harness = base + r'''
static void ram_setup(void) {domain_setup();ram_mode=rgu_mode=fresh_mode=true;settle_change=4;}
static int ram_run(void) {return rail_cycle_store(&dev,NULL,"sysram-cycle",12);}
static void stopped(void) {
 assert(maps==unmaps && !conn.rgu_dirty && !conn.sysram_unsafe);
 assert(!conn.domain_uncertain && !conn.pins_dirty && !pin_active && !host);
 assert(!rails[2].enabled && !rails[3].enabled && rails[0].refs==1 && rails[1].refs==1);
 assert(ram_hw[0]==0xa5000000 && ram_hw[4097]==0xa5001001);
}
static void retained(void) {
 assert(maps==unmaps && conn.domain_uncertain && conn.pins_dirty && pin_active && host==1);
 assert(rails[2].enabled && rails[3].enabled && spm[0x304/4]==13);
 assert(conn.domain_cleanup_result==-EUCLEAN && conn.cleanup_result==-EUCLEAN);
 assert(ram_run()==-EALREADY);
}
int main(void) {
 char output[4096];
 ram_setup();conn.emi_valid=false;assert(ram_run()==12);stopped();
 assert(conn.sysram_started && conn.sysram_complete && !conn.sysram_unsafe);
 assert(ram_writes==4096 && ram_reads==8192 && conn.sysram_written==4096);
 assert(conn.sysram_verified==4096 && conn.sysram_scanned==4096);
 assert(rgu_writes==8 && conn.rgu_restored==4 && mmio_writes==30 && maps==5);
 for(unsigned i=1;i<=4096;i++)assert(!ram_hw[i]);
 assert(sysram_status_show(&dev,NULL,output)>0 && strstr(output,"complete=1 unsafe=0 written=4096 verified=4096 scanned=4096"));
 assert(ram_run()==-EALREADY && ram_writes==4096 && ram_reads==8192);
 for(unsigned fail=1;fail<=2;fail++) {
  ram_setup();ram_map_fail=fail;assert(ram_run()==-ENOMEM && !ram_writes);stopped();
 }
 unsigned locations[]={1,2,1024,2048,2561,2574,4095,4096};
 for(unsigned n=0;n<ARRAY_SIZE(locations);n++) {
  unsigned fail=locations[n];
  ram_setup();ram_drop=fail;
  assert(ram_run()==-EIO && ram_writes==fail && conn.sysram_verified==fail-1);
  assert(!conn.sysram_complete && conn.sysram_bad_offset==(fail-1)*4);stopped();
  ram_setup();ram_bad_read=fail;
  assert(ram_run()==-EIO && conn.sysram_verified==fail-1);stopped();
  ram_setup();ram_bad_read=4096+fail;
  assert(ram_run()==-EIO && ram_writes==4096 && conn.sysram_scanned==fail-1);
  assert(!conn.sysram_complete && !strcmp(conn.failure_stage,"sysram-final-scan"));stopped();
  for(unsigned change=1;change<=5;change++) {
   ram_setup();ram_loss_write=fail;ram_change=change;
   assert(ram_run()<0 && conn.sysram_unsafe && ram_writes==fail && rgu_writes==4);
   assert(conn.rgu_dirty==15 && conn.rgu_cleanup_result==-EUCLEAN);retained();
   ram_setup();ram_loss_read=fail;ram_change=change;
   assert(ram_run()<0 && conn.sysram_unsafe && ram_writes==fail && rgu_writes==4);retained();
   ram_setup();ram_loss_read=4096+fail;ram_change=change;
   assert(ram_run()<0 && conn.sysram_unsafe && !conn.sysram_complete && rgu_writes==4);retained();
  }
 }
 for(unsigned fail=1;fail<=2;fail++)for(unsigned change=1;change<=5;change++) {
  ram_setup();ram_map_loss=fail;ram_change=change;
  assert(ram_run()<0 && conn.sysram_unsafe && !ram_writes && rgu_writes==4);retained();
 }
 for(unsigned fail=1;fail<=4;fail++) {
  ram_setup();rgu_drop_write=fail;
  assert(ram_run()==-EIO && !ram_writes && !conn.sysram_started);stopped();
 }
 for(unsigned fail=5;fail<=8;fail++) {
  ram_setup();rgu_drop_write=fail;
  assert(ram_run()==-EIO && conn.sysram_complete && conn.rgu_dirty);retained();
 }
 ram_setup();ram_bad_read=1;rgu_drop_write=5;
 assert(ram_run()==-EIO && conn.rgu_cleanup_result==-EIO && !strcmp(conn.failure_stage,"sysram-readback"));retained();
 ram_setup();cfg[0]^=1;assert(ram_run()==-ENODEV && !ram_writes && !rgu_writes);stopped();
 ram_setup();conn.domain_allowed=false;assert(ram_run()==-EOPNOTSUPP && !conn.attempted);
 ram_setup();conn.cycle_allowed=false;assert(ram_run()==-EOPNOTSUPP && !conn.attempted);
 puts("PASS:4096-word SYSRAM clear,8192 verified reads,held RGU policies,boundary sentinels,"
      "mapping and readback failures,late corruption,five-way guard loss,retained unsafe cleanup,"
      "RGU failures and one-shot lockout");
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
