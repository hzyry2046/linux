#!/usr/bin/env python3
# SPDX-License-Identifier: GPL-2.0-only
"""Exercise actual guarded SPI table writes and restoration under MMIO faults."""
from pathlib import Path
import json
import runpy
import subprocess
import tempfile

here = Path(__file__).resolve().parent
base = runpy.run_path(str(here / 'test_conn_domain.py'))['harness']
base = base[:base.index('int main(void) {')]
# Independently archived vendor audit and physical originals from attempt67.
rows = json.loads((here.parent / 'evidence/attempt-67/spi-comparison.json').read_text())['rows']
rows = [row for row in rows if row['address'] != '0x18005004'] + [
    row for row in rows if row['address'] == '0x18005004']
expected = 'static const struct { u32 offset,mask,value,original; } expected[] = {\n'
for row in rows:
    expected += ' {%#x,%s,%s,%s},\n' % (int(row['address'], 16) - 0x18005000,
                                        row['mask'], row['target'], row['observed'])
expected += '};\n'
harness = base + expected + r'''
static void config_setup(void) {
 domain_setup();config_mode=fresh_mode=true;settle_change=4;
 for(unsigned i=0;i<36;i++)config_wt[expected[i].offset/4]=expected[i].original;
}
static int config_run(void) {return rail_cycle_store(&dev,NULL,"spi-config-cycle",16);}
static void stopped(void) {
 assert(maps==unmaps && !conn.spi_config_dirty && !conn.spi_config_unsafe);
 assert(!conn.domain_uncertain && !conn.pins_dirty && !pin_active && !host);
 assert(!rails[2].enabled && !rails[3].enabled && rails[0].refs==1 && rails[1].refs==1);
}
static void retained(void) {
 assert(maps==unmaps && conn.domain_uncertain && conn.pins_dirty && pin_active && host==1);
 assert(rails[2].enabled && rails[3].enabled && spm[0x304/4]==13);
 assert(conn.domain_cleanup_result==-EUCLEAN && conn.cleanup_result==-EUCLEAN);
 assert(config_run()==-EALREADY);
}
int main(void) {
 char output[4096];
 config_setup();conn.emi_valid=false;assert(config_run()==16);
 assert(config_writes==72 && config_reads==108 && mmio_writes==94 && maps==5);
 assert(conn.spi_config_saved==36 && conn.spi_config_applied==36 && conn.spi_config_restored==36);
 assert(!conn.spi_config_cleanup_result && !conn.result && !conn.faulted);
 stopped();
 for(unsigned i=0;i<36;i++) {
  u32 target=(expected[i].original&~expected[i].mask)|expected[i].value;
  assert(op6893_conn_spi_settings[i].offset==expected[i].offset);
  assert(op6893_conn_spi_settings[i].mask==expected[i].mask);
  assert(op6893_conn_spi_settings[i].value==expected[i].value);
  assert(conn.spi_config_before[i]==expected[i].original && conn.spi_config_target[i]==target);
  assert(conn.spi_config_on[i]==target && conn.spi_config_after[i]==expected[i].original);
  assert(config_wt[expected[i].offset/4]==expected[i].original);
  assert(trace[12+i].addr==config_wt+expected[i].offset/4 && trace[12+i].value==target);
  assert(trace[48+i].addr==config_wt+expected[35-i].offset/4);
  assert(trace[48+i].value==expected[35-i].original);
 }
 assert(expected[35].offset==4 && conn.spi_config_on[35]==0xf808);
 assert(spi_config_show(&dev,NULL,output)>0 && strlen(output)<4096);
 assert(strstr(output,"saved=36 applied=36 restored=36 dirty=0 unsafe=0"));
 assert(config_reads==108 && config_writes==72);
 assert(config_run()==-EALREADY && config_writes==72);
 /* Baseline is exact, including unknown high fields; no speculative write. */
 for(unsigned i=0;i<36;i++) {
  config_setup();config_wt[expected[i].offset/4]^=0x10000000;
  assert(config_run()==-EBUSY && !config_writes && conn.spi_config_saved==i+1);
  assert(!strcmp(conn.failure_stage,"spi-config-baseline"));stopped();
 }
 for(unsigned fail=1;fail<=3;fail++) {
  config_setup();config_map_fail=fail;assert(config_run()==-ENOMEM && !config_writes);stopped();
 }
 /* Status loss before a table write never reaches that write. */
 for(unsigned change=1;change<=7;change++) {
  config_setup();config_change=change;
  if(change<=4)config_loss_map=3;
  else lose_config_access();
  assert(config_run()<0 && !config_writes && conn.spi_config_unsafe);retained();
 }
 /* Every corrupted target/readback recovers original values. */
 for(unsigned fail=1;fail<=36;fail++) {
  config_setup();config_corrupt_write=fail;
  assert(config_run()==-EIO && !conn.spi_config_cleanup_result);stopped();
  assert(conn.spi_config_applied==fail-1 && conn.spi_config_restored==fail);
  config_setup();config_bad_read=36+fail;
  assert(config_run()==-EIO && !conn.spi_config_cleanup_result);stopped();
  config_setup();config_drop_write=fail;
  bool changes=(expected[fail-1].original&expected[fail-1].mask)!=expected[fail-1].value;
  assert(config_run()==(changes?-EIO:16));stopped();
 }
 /* Every failed restoration retains resources, including dirty bits32..35. */
 for(unsigned fail=37;fail<=72;fail++) {
  config_setup();config_corrupt_write=fail;
  assert(config_run()==-EIO && conn.spi_config_cleanup_result==-EIO && conn.spi_config_dirty);
  retained();
  assert(spi_config_show(&dev,NULL,output)>0 && strlen(output)<4096);
  config_setup();config_bad_read=fail+36;
  assert(config_run()==-EIO && conn.spi_config_cleanup_result==-EIO && conn.spi_config_dirty);
  retained();
  config_setup();config_drop_write=fail;
  unsigned index=72-fail;
  bool changes=(expected[index].original&expected[index].mask)!=expected[index].value;
  assert(config_run()==(changes?-EIO:16));
  if(changes)retained();else stopped();
 }
 config_setup();config_bad_read=42;config_corrupt_write=7;
 assert(config_run()==-EIO && conn.spi_config_cleanup_result==-EIO);
 assert(!strcmp(conn.failure_stage,"spi-config-apply-readback"));retained();
 /* Loss after any write is latched; no extra restoration write is issued. */
 for(unsigned fail=1;fail<=72;fail++)for(unsigned change=1;change<=7;change++) {
  config_setup();config_loss_write=fail;config_change=change;
  assert(config_run()<0 && conn.spi_config_unsafe && conn.spi_config_dirty);
  assert(config_writes==fail);
  if(fail<=36)assert(conn.spi_config_cleanup_result==-EUCLEAN);
  else assert(conn.spi_config_cleanup_result==(change==2?-EIO:-EBUSY));
  retained();
 }
 /* Also catch loss after saved words, apply readbacks and the final restore. */
 for(unsigned fail=1;fail<=108;fail++)for(unsigned change=1;change<=7;change++) {
  config_setup();config_loss_read=fail;config_change=change;
  assert(config_run()<0 && conn.spi_config_unsafe);retained();
  if(fail<=36)assert(!config_writes);
  if(fail==108)assert(!conn.spi_config_dirty && conn.spi_config_restored==36);
 }
 for(unsigned word=0;word<2;word++) {
  config_setup();cfg[word]^=1;assert(config_run()==-ENODEV && !config_maps && !config_writes);stopped();
 }
 config_setup();conn.domain_allowed=false;
 assert(config_run()==-EOPNOTSUPP && !conn.attempted && !mmio_writes);
 config_setup();conn.cycle_allowed=false;
 assert(config_run()==-EOPNOTSUPP && !conn.attempted && !mmio_writes);
 puts("PASS: audited36-word SPI targets, length-last ordering,94-write success, exact baselines, "
      "all target/restore faults,64-bit dirty tracking,latched seven-way status loss at every access," 
      "final-restore uncertainty, retained resources and one-shot refusal");
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
