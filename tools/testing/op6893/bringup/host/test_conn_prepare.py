#!/usr/bin/env python3
# SPDX-License-Identifier: GPL-2.0-only
"""Execute all actual nested preparation functions against the existing MMIO model."""
from pathlib import Path
import runpy
import re
import subprocess
import tempfile

here = Path(__file__).resolve().parent
root = here.parents[4]
base = runpy.run_path(str(here / 'test_conn_domain.py'))['harness']
base = base[:base.index('int main(void) {')]
# The isolated fakes had separate ADIE words; composition has one physical word.
base = re.sub(r'\bram_adie\b', 'config_adie', base)
start = base.index('static unsigned strap_injected;')
end = base.index('\n}', start) + 2
base = base[:start] + (root / 'arch/arm64/kernel/op6893-conn-strap.h').read_text() + base[end:]
# Preserve the already-tested lower MMIO fakes and wrap only composition checks.
for name, result in [('readl', 'u32'), ('writel', 'void'), ('pinctrl_select_state', 'int')]:
    base = base.replace(f'static {result} {name}(', f'static {result} lower_{name}(', 1)
base = base.replace('static void *ioremap(', 'static void *lower_ioremap(', 1)
base = base.replace('static void iounmap(', 'static void lower_iounmap(', 1)
point = base.index('static const char * const op6893_conn_rails[]')
wrap = r'''
static u32 gpio[0x470/4],io[0xd0/4],expected_config[36],config_offsets[36];
static struct pinctrl_state strap_states[5]={{3},{4},{5},{6},{7}};
static unsigned strap_phase,strap_fail,strap_drop,strap_guard_loss;
static void held_remap(void) {
 assert((fresh[0x1c4/4]&0xfffff)==0x8fb0);
 for(unsigned i=1;i<4;i++)assert((fresh[remap_hw_offsets[i]/4]&0xfffff)==0x1000);
}
static void held_rgu(void) {
 held_remap();assert(rgu[0x38/4]==0 && rgu[0x3c/4]==255 && !rgu[0x50/4] && rgu[0x54/4]==1);
}
static void held_config(void) {
 held_rgu();for(unsigned i=0;i<36;i++)assert(config_wt[config_offsets[i]/4]==expected_config[i]);
}
static void held_strap(void) {
 held_config();assert((gpio[0x50/4]&BIT(20)) && (gpio[0x150/4]&BIT(20)));
 assert(!(gpio[0x460/4]&0xf0000));assert(ram_writes==4096 && ram_reads==8192);
}
static u32 readl(void *p) {
 if(ram_index(p)>=0)held_config();
 if(p==sema_hw+0x202c/4)held_strap();
 return lower_readl(p);
}
static void writel(u32 value,void *p) {
 if(ram_index(p)>=0)held_config();
 if(p==sema_hw+0x222c/4)held_strap();
 for(unsigned i=0;i<36;i++)if(p==config_wt+config_offsets[i]/4)held_rgu();
 for(unsigned i=0;i<4;i++)if(p==rgu+rgu_hw_offsets[i]/4)held_remap();
 lower_writel(value,p);
}
static int pinctrl_select_state(struct pinctrl *p,struct pinctrl_state *s) {
 if(s->which<=2)return lower_pinctrl_select_state(p,s);
 held_config();assert(pin_active && p==&pins);strap_phase=s->which-2;
 if(strap_phase!=strap_drop) {
  unsigned mode=strap_phase==2?0:1,dir=strap_phase<5,level=strap_phase<4;
  gpio[0x460/4]=(gpio[0x460/4]&~0xf0000)|(mode<<16);
  gpio[0x150/4]=(gpio[0x150/4]&~BIT(20))|(level<<20);
  gpio[0x50/4]=(gpio[0x50/4]&~BIT(20))|(dir<<20);
 }
 if(strap_phase==strap_guard_loss)fresh[0]&=~2;
 return strap_phase==strap_fail?-EIO:0;
}
static void *ioremap(unsigned long addr,unsigned long size) {
 if(addr==0x10005000){assert(size==sizeof(gpio));maps++;return gpio;}
 if(addr==0x11ea0000){assert(size==sizeof(io));maps++;return io;}
 return lower_ioremap(addr,size);
}
static void iounmap(void *p) {
 if(p==gpio || p==io){unmaps++;return;}
 lower_iounmap(p);
}
'''
base = base[:point] + wrap + base[point:]
harness = base + r'''
static void prepare(void) {
 domain_setup();fresh_mode=remap_mode=rgu_mode=config_mode=ram_mode=sema_mode=true;
 settle_change=4;strap_phase=strap_fail=strap_drop=strap_guard_loss=0;
 memset(gpio,0,sizeof(gpio));memset(io,0,sizeof(io));
 gpio[0x50/4]=0xa2800000;gpio[0x150/4]=0x02800000;gpio[0x460/4]=0x01111111;
 io[0]=0x8248;io[0x30/4]=0xffffffff;io[0x50/4]=0x0c7fb43f;io[0x70/4]=0x01804bc0;io[0xc0/4]=0x1c01;
 for(unsigned i=0;i<5;i++)conn.strap_pins[i]=&strap_states[i];
 for(unsigned i=0;i<36;i++) {
  const struct op6893_conn_spi_setting *s=&op6893_conn_spi_settings[i];
  config_wt[s->offset/4]=s->baseline;config_offsets[i]=s->offset;
  expected_config[i]=(s->baseline&~s->mask)|s->value;
 }
}
static int prepare_run(void) {return rail_cycle_store(&dev,NULL,"prepare-cycle",13);}
static void stopped(void) {
 assert(maps==unmaps && !conn.remap_dirty && !conn.rgu_dirty && !conn.spi_config_dirty);
 assert(!conn.strap_dirty && !conn.strap_unsafe && !conn.sema_pending && !conn.sema_unsafe);
 assert(!conn.domain_uncertain && !conn.pins_dirty && !host);
 assert(!rails[2].enabled && !rails[3].enabled);
 assert(prepare_run()==-EALREADY);
}
static void retained(void) {
 assert(maps==unmaps && conn.domain_uncertain && conn.pins_dirty && host==1);
 assert(rails[2].enabled && rails[3].enabled && conn.domain_cleanup_result==-EUCLEAN);
 assert(conn.cleanup_result==-EUCLEAN && prepare_run()==-EALREADY);
}
int main(void) {
 prepare();assert(prepare_run()==13);stopped();
 assert(conn.sysram_complete && conn.strap_complete && conn.sema_released);
 assert(conn.remap_restored==4 && conn.rgu_restored==4 && conn.spi_config_restored==36);
 assert(conn.strap_selected==6 && conn.strap_samples==7 && sema_grants==1 && sema_writes==1);
 assert(ram_writes==4096 && ram_reads==8192 && mmio_writes==111);
 /* Clean refusal of the innermost lock must still restore every outer stage. */
 prepare();sema_response=0;assert(prepare_run()==-EBUSY);stopped();
 assert(conn.strap_complete && !sema_writes && !strcmp(conn.failure_stage,"sema-own-report"));
 prepare();sema_map_fail=true;assert(prepare_run()==-ENOMEM);stopped();
 prepare();sema_response=0;strap_fail=4;assert(prepare_run()==-EBUSY);retained();
 assert(!strcmp(conn.failure_stage,"sema-own-report") && config_writes==36 && rgu_writes==4);
 for(unsigned change=1;change<=4;change++) {
  prepare();sema_loss_read=100;sema_change=change;
  assert(prepare_run()<0);retained();
  assert(strap_phase==2 && !sema_writes && config_writes==36 && rgu_writes==4 && remap_writes==4);
 }
 for(unsigned change=1;change<=7;change++) {
  prepare();config_loss_write=36;config_change=change;
  assert(prepare_run()<0);retained();
  assert(!ram_writes && !strap_phase && rgu_writes==4 && remap_writes==4);
 }
 for(unsigned change=1;change<=5;change++) {
  prepare();ram_loss_read=8192;ram_change=change;
  assert(prepare_run()<0);retained();
  assert(!conn.sysram_complete && !strap_phase && config_writes==36 && rgu_writes==4);
 }
 for(unsigned phase=1;phase<=5;phase++) {
  prepare();strap_fail=phase;assert(prepare_run()==-EIO);retained();
  assert(conn.remap_dirty==15 && conn.rgu_dirty==15 && conn.spi_config_dirty==((1ULL<<36)-1));
  assert(config_writes==36 && rgu_writes==4 && remap_writes==4);
  prepare();strap_guard_loss=phase;assert(prepare_run()<0);retained();
  assert(config_writes==36 && rgu_writes==4 && remap_writes==4);
 }
 for(unsigned phase=1;phase<=5;phase++) {
  prepare();strap_drop=phase;assert(prepare_run()==-EIO);retained();
 }
 prepare();sema_drop_release=true;assert(prepare_run()==-ETIMEDOUT);retained();
 assert(strap_phase==2 && conn.strap_unsafe && config_writes==36 && rgu_writes==4 && remap_writes==4);
 prepare();sema_hw[0x400/4]=0x800;assert(prepare_run()==-EBUSY);retained();assert(!sema_grants);
 prepare();sema_response=3;assert(prepare_run()==-EIO);retained();assert(!sema_writes);
 prepare();ram_bad_read=1;assert(prepare_run()==-EIO);stopped();assert(!strap_phase && !sema_grants);
 prepare();ram_loss_write=4096;ram_change=5;assert(prepare_run()<0);retained();
 assert(config_writes==36 && rgu_writes==4 && remap_writes==4 && !strap_phase);
 for(unsigned n=1;n<=8;n++) {
  prepare();remap_drop_write=n;assert(prepare_run()==-EIO);
  if(n<=4)stopped();else retained();
 }
 for(unsigned n=1;n<=8;n++) {
  prepare();rgu_drop_write=n;assert(prepare_run()==-EIO);
  if(n<=4)stopped();else {retained();assert(remap_writes==4);}
 }
 for(unsigned n=1;n<=72;n++) {
  prepare();config_drop_write=n;
  int ret=prepare_run();
  /* Ten target words already match their originals; dropping them is benign. */
  if(ret==13){stopped();continue;}
  assert(ret==-EIO);
  if(n<=36)stopped();else {retained();assert(rgu_writes==4 && remap_writes==4);}
 }
 prepare();conn.emi_valid=false;assert(prepare_run()==-EINVAL && !conn.attempted);
 prepare();conn.domain_allowed=false;assert(prepare_run()==-EOPNOTSUPP && !conn.attempted);
 prepare();conn.cycle_allowed=false;assert(prepare_run()==-EOPNOTSUPP && !conn.attempted);
 prepare();cfg[0]^=1;assert(prepare_run()==-ENODEV && !remap_writes && !rgu_writes);stopped();
 puts("PASS: actual nested remap/RGU/SPI/SYSRAM/strap/semaphore,held-parent assertions,"
      "clean lock denial unwind,inner uncertainty prevents all outer restore writes,"
      "every remap/RGU/SPI dropped write,strap faults and one-shot integration");
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
