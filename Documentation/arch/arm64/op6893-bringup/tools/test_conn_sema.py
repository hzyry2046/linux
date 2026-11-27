#!/usr/bin/env python3
# SPDX-License-Identifier: GPL-2.0-only
"""Run actual semaphore acquisition/release against a read-to-acquire model."""
from pathlib import Path
import runpy
import subprocess
import tempfile

here = Path(__file__).resolve().parent
base = runpy.run_path(str(here / 'test_conn_domain.py'))['harness']
base = base[:base.index('int main(void) {')]
harness = base + r'''
static void sema_setup(void) {domain_setup();sema_mode=fresh_mode=true;settle_change=4;}
static int sema_run(void) {return rail_cycle_store(&dev,NULL,"sema-cycle",10);}
static void stopped(void) {
 assert(maps==unmaps && !conn.sema_pending && !conn.sema_unsafe);
 assert(!conn.domain_uncertain && !conn.pins_dirty && !pin_active && !host);
 assert(!rails[2].enabled && !rails[3].enabled && rails[0].refs==1 && rails[1].refs==1);
}
static void retained(void) {
 assert(maps==unmaps && conn.domain_uncertain && conn.pins_dirty && pin_active && host==1);
 assert(rails[2].enabled && rails[3].enabled && spm[0x304/4]==13);
 assert(conn.domain_cleanup_result==-EUCLEAN && conn.cleanup_result==-EUCLEAN);
 assert(sema_run()==-EALREADY);
}
int main(void) {
 char output[4096];
 sema_setup();conn.emi_valid=false;
 /* Other semaphore bits are preserved, never released by this experiment. */
 for(unsigned i=0;i<4;i++)sema_hw[(0x400+i*0x1000)/4]=1U<<(i+1);
 assert(sema_run()==10);stopped();
 assert(sema_grants==1 && sema_writes==1 && sema_reads==13 && mmio_writes==23 && maps==3);
 assert(conn.sema_request_issued && conn.sema_acquired && conn.sema_release_issued && conn.sema_released);
 assert(!conn.sema_cleanup_result && conn.sema_polls==1);
 assert(trace[12].addr==sema_hw+0x222c/4 && trace[12].value==1);
 for(unsigned phase=0;phase<3;phase++) {
  assert(conn.sema_samples[phase]==4);
  for(unsigned i=0;i<4;i++)assert(conn.sema_report[phase][i]==((1U<<(i+1))|((phase==1 && i==2)?0x800:0)));
 }
 assert(sema_status_show(&dev,NULL,output)>0 && strstr(output,"released=1 pending=0 unsafe=0"));
 assert(sema_grants==1 && sema_reads==13 && sema_writes==1);
 assert(sema_run()==-EALREADY && sema_grants==1);
 sema_setup();sema_release_delay=3;assert(sema_run()==10 && conn.sema_polls==3);stopped();
 sema_setup();sema_response=0;assert(sema_run()==-EBUSY && !sema_writes && !conn.sema_acquired);stopped();
 for(unsigned response=2;response<=3;response++) {
  sema_setup();sema_response=response;assert(sema_run()==-EIO && !sema_writes && conn.sema_pending);
  assert(conn.sema_unsafe);retained();
 }
 for(unsigned master=0;master<4;master++) {
  sema_setup();sema_hw[(0x400+master*0x1000)/4]=0x800;
  assert(sema_run()==-EBUSY && !sema_grants && !sema_writes && conn.sema_unsafe);retained();
 }
 sema_setup();sema_map_fail=true;assert(sema_run()==-ENOMEM && !sema_grants && !sema_writes);stopped();
 for(unsigned word=0;word<2;word++) {
  sema_setup();cfg[word]^=1;assert(sema_run()==-ENODEV && !sema_grants && !sema_writes);stopped();
 }
 /* Report contradictions never cause an unacknowledged or speculative unlock. */
 for(unsigned fail=5;fail<=8;fail++) {
  sema_setup();sema_bad_report=fail;
  assert(sema_run()==-EIO && conn.sema_pending && conn.sema_unsafe && !sema_writes);retained();
 }
 for(unsigned fail=10;fail<=13;fail++) {
  sema_setup();sema_bad_report=fail;
  assert(sema_run()==-EIO && conn.sema_pending && conn.sema_unsafe && sema_writes==1);retained();
 }
 sema_setup();sema_drop_release=true;
 assert(sema_run()==-ETIMEDOUT && conn.sema_pending && !conn.sema_released);
 assert(conn.sema_cleanup_result==-ETIMEDOUT && conn.sema_polls==4 && sema_grants==1 && sema_writes==1);
 retained();
 for(unsigned change=1;change<=4;change++) {
  for(unsigned read=1;read<=13;read++) {
   sema_setup();sema_loss_read=read;sema_change=change;
   assert(sema_run()<0 && conn.sema_unsafe && !conn.sema_released);retained();
   if(read<=4)assert(!sema_grants && !sema_writes);
   if(read>=5 && read<=8)assert(sema_grants==1 && !sema_writes);
   if(read>=9)assert(sema_grants==1 && sema_writes==1 && conn.sema_pending);
  }
  sema_setup();sema_loss_read=100;sema_change=change;
  assert(sema_run()<0 && conn.sema_pending && conn.sema_unsafe && !sema_writes);retained();
  sema_setup();sema_loss_release=1;sema_change=change;
  assert(sema_run()<0 && conn.sema_pending && conn.sema_unsafe && sema_writes==1);retained();
 }
 sema_setup();conn.domain_allowed=false;
 assert(sema_run()==-EOPNOTSUPP && !conn.attempted && !mmio_writes);
 sema_setup();conn.cycle_allowed=false;
 assert(sema_run()==-EOPNOTSUPP && !conn.attempted && !mmio_writes);
 puts("PASS: semaphore11 single acquire-read, passive ownership reports, exact release, "
      "delayed release, denied/ambiguous grants, inherited owners, report contradictions, "
      "release timeout, access-loss retention, unrelated locks and cached one-shot status");
}
'''
with tempfile.TemporaryDirectory() as tmp:
    path = Path(tmp)
    (path / 'test.c').write_text(harness)
    subprocess.run(['cc', '-Wall', '-Wextra', '-Werror', '-Wno-unused-parameter',
                    '-Wno-unused-variable', '-Wno-unused-function',
                    '-fsanitize=undefined', '-fno-sanitize-recover=all',
                    str(path / 'test.c'), '-o', str(path / 'test')], check=True)
    subprocess.run([str(path / 'test')], check=True)
