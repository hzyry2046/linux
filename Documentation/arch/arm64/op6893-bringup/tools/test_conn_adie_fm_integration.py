#!/usr/bin/env python3
# SPDX-License-Identifier: GPL-2.0-only
"""Real nested FM transaction; format must restore before analog/mailbox cleanup."""
from pathlib import Path
import runpy
import subprocess
import tempfile

base = runpy.run_path(str(Path(__file__).with_name('test_conn_adie_route_integration.py')))['harness']
base = base[:base.index('int main(void) {')]
base = base.replace('static u32 therm[10],gpt[15];',
                    'static u32 therm[10],gpt[15];\n'
                    'static unsigned fm_writes,fm_drop,fm_loss,fm_kind,route_writes_at_loss;\n'
                    'static bool fm_bad_apply,fm_bad_restore;\n'
                    'static bool fm_dirty(void);\nstatic unsigned fm_issued(void);',1)
base = base.replace('  u32 result=*(u32 *)p;\n  if(route_reads==route_loss) {',r'''  u32 result=*(u32 *)p;
  if(p==adie_spi+3 && fm_issued()==1 && fm_bad_apply)result=0xdeadbeef;
  if(p==adie_spi+3 && fm_issued()==3 && fm_bad_restore)result=0xdeadbeef;
  if(route_reads==route_loss) {''',1)
base = base.replace('  if(route_reads==route_loss) {','  if(route_reads==route_loss) {\n   route_writes_at_loss=fm_writes;',1)
base = base.replace('static void writel(u32 value,void *p) {',r'''static void writel(u32 value,void *p) {
 if(p==adie_spi+3) {
  held_strap();assert(config_adie==3 && *MAILBOX==adie_response && prefix_dirty()==3);
  assert(analog[0]==0x7700 && analog[1]==0x21 && fm_dirty() && !config_busy);
  assert(value==0 || value==0x801f);
  unsigned n=++fm_writes;if(n!=fm_drop)*(u32 *)p=value;
  if(n==fm_loss) {
   if(fm_kind==0)fresh[0]&=~2;
   if(fm_kind==1)sema_hw[0x2400/4]=0;
   if(fm_kind==2)config_wt[2]^=0x4000000;
   if(fm_kind==3)config_busy=2;
   if(fm_kind==4)*MAILBOX^=1;
   if(fm_kind>=5 && fm_kind<=8)sema_hw[(0x400+(fm_kind-5)*0x1000)/4]|=BIT(13);
   if(fm_kind==9)therm[9]|=BIT(19);
   if(fm_kind==10)therm[9]|=BIT(18);
   if(fm_kind==11)gpt[14]|=1;
   if(fm_kind==12)therm[6]^=2;
   if(fm_kind==13)therm[1]^=2;
  }
  return;
 }
 if(p==adie_spi+0x54/4 && (adie_spi[0x50/4]==0xa064 || adie_spi[0x50/4]==0xa0bc) && value<=1)
  assert(!fm_dirty() && adie_spi[3]==0x801f);
''',1)
harness = base+r'''
static bool fm_dirty(void) {return conn.adie_fm_dirty;}
static unsigned fm_issued(void) {return conn.adie_fm_issued;}
static void fm_setup(void) {
 route_setup();adie_spi[3]=0x801f;therm[6]=0x50305a00;therm[1]=0x7f0300ff;
 fm_writes=fm_drop=fm_loss=fm_kind=route_writes_at_loss=0;fm_bad_apply=fm_bad_restore=false;
}
static int fm_run(void) {return rail_cycle_store(&dev,NULL,"adie-fm-cycle",13);}
int main(void) {
 char output[4096];fm_setup();assert(fm_run()==13);stopped();unsigned total_reads=route_reads;
 assert(conn.adie_fm_restored && conn.adie_fm_applied && conn.adie_fm_read==7 && !fm_dirty());
 assert(adie_writes==43 && fm_writes==2 && conn.adie_complete && conn.sema_released);
 assert(adie_spi[3]==0x801f && therm[6]==0x50305a00 && therm[1]==0x7f0300ff && !therm[9] && !gpt[14]);
 int len=adie_status_show(&dev,NULL,output);assert(len>0 && len<4096);
 assert(strstr(output,"fm_applied=1 fm_restored=1 fm_dirty=0 fm_cleanup=0"));
 assert(fm_run()==-EALREADY && fm_writes==2);
 fm_setup();fm_drop=1;assert(fm_run()==-EIO);stopped();
 assert(conn.adie_fm_restored && !conn.adie_fm_applied && conn.adie_mailbox_restored);
 fm_setup();fm_drop=2;assert(fm_run()==-EIO);retained();assert(fm_dirty() && adie_writes==28 && !sema_writes);
 for(unsigned n=1;n<=2;n++)for(unsigned kind=0;kind<14;kind++) {
  fm_setup();fm_loss=n;fm_kind=kind;assert(fm_run()<0);retained();
  assert(fm_writes==n && fm_dirty() && conn.adie_prefix_dirty==3 && conn.adie_mailbox_dirty);
  assert(adie_writes==28 && !sema_writes && config_writes==36 && rgu_writes==4 && remap_writes==4);
 }
 for(unsigned n=1;n<=total_reads;n++)for(unsigned kind=0;kind<9;kind++) {
  fm_setup();route_loss=n;route_kind=kind;assert(fm_run()<0);retained();
  assert(fm_writes==route_writes_at_loss && conn.adie_unsafe && conn.adie_prefix_dirty==3);
  assert(adie_writes==28 && !sema_writes && config_writes==36 && rgu_writes==4 && remap_writes==4);
 }
 fm_setup();fm_bad_apply=true;assert(fm_run()==-EIO);stopped();assert(conn.adie_fm_restored);
 assert(!strcmp(conn.failure_stage,"adie-fm-apply-readback"));
 fm_setup();fm_bad_restore=true;assert(fm_run()==-EIO);retained();assert(fm_dirty() && !sema_writes);
 fm_setup();fm_bad_apply=true;fm_drop=2;assert(fm_run()==-EIO);retained();
 assert(conn.adie_fm_cleanup==-EIO && !strcmp(conn.failure_stage,"adie-fm-apply-readback"));
 fm_setup();adie_drop=30;assert(fm_run()==-EIO);retained();assert(conn.adie_fm_restored && conn.adie_prefix_dirty);
 fm_setup();config_drop_write=37;assert(fm_run()==-EIO);retained();
 assert(conn.adie_complete && conn.adie_fm_restored && conn.sema_released && conn.spi_config_dirty);
 printf("PASS: nested FM apply/restore,2 dropped writes,28 write-time faults,%u read-time faults,"
        "digital-before-analog cleanup,readback corruption,double failure,outer cleanup,status size and one-shot\n",total_reads*9);
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
