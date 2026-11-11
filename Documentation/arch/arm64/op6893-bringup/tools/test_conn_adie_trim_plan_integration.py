#!/usr/bin/env python3
# SPDX-License-Identifier: GPL-2.0-only
"""Planner inside real thermal read, handoff and parent restoration paths."""
from pathlib import Path
import runpy
import subprocess
import tempfile

base = runpy.run_path(str(Path(__file__).with_name('test_conn_adie_thermal_integration.py')))['harness']
base = base.replace('static bool thermal_mode(void);', 'static bool thermal_mode(void);\nstatic unsigned plan_fault;')
base = base.replace('conn->adie_trim_plan_cleared = true;', 'conn->adie_trim_plan_cleared = true;\n if(plan_fault==1)adie_clock+=2000000000ULL;\n if(plan_fault==2)config_busy=2;', 1)
# Clear the disputed synthetic baseline bits so the first case must diverge.
base = base.replace('91ab7342', '91aa7342').replace('5e3196cd', '4a3196cd')
harness = base.replace('"adie-thermal-read",18', '"adie-thermal-plan",18')
harness = harness.replace('assert(conn.adie_thermal_complete && thermal_reads==4',
    'assert(conn.adie_trim_plan_complete && conn.adie_trim_plan_cleared);\n '
    'assert(!conn.adie_trim_vendor_noop && !conn.adie_trim_bounded_noop && !conn.adie_trim_equivalent);\n '
    'assert(conn.adie_thermal_complete && thermal_reads==4',1)
harness = harness.replace('assert(conn.adie_mailbox_dirty && !conn.adie_thermal_complete);',
    'assert(conn.adie_mailbox_dirty && !conn.adie_thermal_complete && !conn.adie_trim_plan_complete);',1)
harness = harness.replace('assert(conn.adie_thermal_complete);',
    'assert(conn.adie_thermal_complete && conn.adie_trim_plan_complete && conn.adie_trim_plan_cleared);')
harness = harness.replace(' puts("PASS: thermal fixed', r'''
 for(unsigned k=1;k<=2;k++) {
  thermal_setup();plan_fault=k;assert(data_run()<0);thermal_clean();retained();
  assert(conn.adie_thermal_complete && conn.adie_trim_plan_cleared && !conn.adie_trim_plan_complete);
  assert(conn.adie_unsafe && conn.adie_fm_dirty && !sema_writes && fm_writes==1);
  assert(efuse_status_show(&dev,NULL,output)>0);
  assert(strstr(output,"plan_complete=0 plan_cleared=1 vendor_noop=0 bounded_noop=0 policies_equivalent=0"));
 }
 plan_fault=0;
 puts("PASS: thermal fixed''', 1)
harness = harness.replace('puts("PASS: thermal fixed', 'puts("PASS: plan integration + thermal fixed')
with tempfile.TemporaryDirectory() as tmp:
    path = Path(tmp)
    (path / 'test.c').write_text(harness)
    subprocess.run(['cc', '-O1', '-Wall', '-Wextra', '-Werror',
                    '-Wno-unused-parameter', '-Wno-unused-variable', '-Wno-unused-function',
                    '-fsanitize=undefined', '-fno-sanitize-recover=all',
                    str(path / 'test.c'), '-o', str(path / 'test')], check=True)
    subprocess.run([str(path / 'test')], check=True)
