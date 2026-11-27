#!/usr/bin/env python3
# SPDX-License-Identifier: GPL-2.0-only
"""Actual one-shot/domain/rail glue with isolated strap outcome injection.

The strap transaction itself is executed separately by test_conn_strap.py.
"""
from pathlib import Path
import runpy
import subprocess
import tempfile

base = runpy.run_path(str(Path(__file__).with_name('test_conn_domain.py')))['harness']
harness = base[:base.index('int main(void) {')] + r'''
static void prepare(void) {
 domain_setup();fresh_mode=true;settle_change=4;strap_injected=0;strap_called=false;
}
static int strap_run(void) {return rail_cycle_store(&dev,NULL,"strap-cycle",11);}
int main(void) {
 char output[4096];
 prepare();assert(strap_run()==11 && strap_called && conn.strap_complete);
 assert(!conn.domain_uncertain && !conn.pins_dirty && !rails[2].enabled && !rails[3].enabled);
 assert(strap_status_show(&dev,NULL,output)>0 && strstr(output,"complete=1 dirty=0 unsafe=0"));
 assert(strap_run()==-EALREADY);
 for(unsigned fault=1;fault<=2;fault++) {
  prepare();strap_injected=fault;assert(strap_run()==-EIO && strap_called);
  assert(conn.domain_uncertain && conn.pins_dirty && rails[2].enabled && rails[3].enabled);
  assert(conn.domain_cleanup_result==-EUCLEAN && conn.cleanup_result==-EUCLEAN);
  assert(host==1 && spm[0x304/4]==13 && strap_run()==-EALREADY);
 }
 prepare();conn.domain_allowed=false;assert(strap_run()==-EOPNOTSUPP && !conn.attempted && !strap_called);
 prepare();conn.cycle_allowed=false;assert(strap_run()==-EOPNOTSUPP && !conn.attempted && !strap_called);
 prepare();cfg[0]^=1;assert(strap_run()==-ENODEV && !strap_called);
 puts("PASS: strap command routing,fresh-ID prerequisite,opt-outs,cached status,"
      "normal shutdown,independent dirty/unsafe containment and one-shot refusal");
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
