#!/usr/bin/env python3
# SPDX-License-Identifier: GPL-2.0-only
"""Execute actual domain sequence and full rail integration against fake MMIO."""
from pathlib import Path
import re
import runpy
import subprocess
import tempfile

here = Path(__file__).resolve().parent
base = runpy.run_path(str(here / 'test_conn_rail_cycle.py'))['harness']
header = (here.parents[4] / 'arch/arm64/kernel/op6893-conn-domain.h').read_text()
header = header.replace('#include "op6893-conn-spi.h"',
                        (here.parents[4] / 'arch/arm64/kernel/op6893-conn-spi.h').read_text())
header = header.replace('#include "op6893-conn-sema.h"',
                        (here.parents[4] / 'arch/arm64/kernel/op6893-conn-sema.h').read_text())
header = header.replace('#include "op6893-conn-adie.h"',
                        (here.parents[4] / 'arch/arm64/kernel/op6893-conn-adie.h').read_text())
header = header.replace('#include "op6893-conn-sysram.h"',
                        (here.parents[4] / 'arch/arm64/kernel/op6893-conn-sysram.h').read_text())
header = header.replace('#include "op6893-conn-strap.h"',
                        '''static unsigned strap_injected; static bool strap_called;
static int op6893_conn_strap_cycle(struct op6893_conn *c, void *csr) {
 (void)csr; assert(c->strap_requested && c->id_samples==2 && c->hw_version==0x20010101);
 strap_called=true;c->strap_dirty=strap_injected==1;c->strap_unsafe=strap_injected==2;
 c->strap_complete=!strap_injected;return strap_injected?-EIO:0;
}''')
base = base[:base.index('int main(void) {')]
base = re.sub(r'static u32 readl\(void \*p\) \{.*?\n}', '', base, count=1, flags=re.S)
insert = base.index('static const char * const op6893_conn_rails[]')
fakes = r'''
#define BIT_ULL(n) (1ULL << (n))
static u64 adie_clock,adie_clock_step=1000;
static u64 ktime_get_ns(void) {return adie_clock+=adie_clock_step;}
static void udelay(unsigned us) {assert(us==1 || us==30);adie_clock+=us*1000ULL;}
struct pinctrl { int unused; };
struct pinctrl_state { int which; };
static struct pinctrl pins;
static struct pinctrl_state active={1}, idle={2};
static unsigned mmio_writes, drop_write, pin_fail, dark_reads, maps, unmaps;
static unsigned ack_fail, polls, io_fail, csr_stuck;
static bool pin_active, csr_mode, fresh_mode;
static u32 fresh[0x2d8/4];
static const unsigned remap_hw_offsets[]={0x1c4,0x1d4,0x1d8,0x1dc};
static bool remap_mode;
static unsigned remap_writes,remap_reads,remap_drop_write,remap_bad_read,remap_guard_fail;
static unsigned remap_guard_change;
static void lose_remap_access(void) {
 if(remap_guard_change==1)fresh[0]&=~2;
 if(remap_guard_change==2)fresh[0x2d4/4]=0;
 if(remap_guard_change==3)fresh[0x184/4]|=32;
 if(remap_guard_change==4)infra[0x228/4]|=0x2000;
}
static bool rgu_mode;
static u32 rgu[0x58/4];
static const unsigned rgu_hw_offsets[]={0x38,0x3c,0x50,0x54};
static unsigned rgu_map_fail,rgu_after_map;
static unsigned rgu_writes,rgu_reads,rgu_drop_write,rgu_bad_read,rgu_guard_fail;
static unsigned rgu_guard_change;
static void lose_rgu_access(void) {
 if(rgu_guard_change==1)fresh[0]&=~2;
 if(rgu_guard_change==2)fresh[0x2d4/4]=0;
 if(rgu_guard_change==3)fresh[0x184/4]|=32;
 if(rgu_guard_change==4)infra[0x228/4]|=0x2000;
}
static unsigned fresh_fail, reset_writes, id_reads, fresh_map_fail;
static unsigned changed_after_map, changed_after_id;
static const unsigned long post_hw_addresses[]={
 0x18000038,0x1800003c,0x18000050,0x18000054,
 0x18052830,0x18052834,0x18052838,
 0x180601c4,0x180601cc,0x180601d0,0x180601d4,0x180601d8,0x180601dc};
static u32 post_hw[13];
static unsigned post_reads,post_map_fail,post_guard_drop,post_change;
static const unsigned long spi_hw_addresses[]={
 0x18001900,0x18004000,0x18005008,
 0x18005070,0x18005074,0x18005078,0x1800507c,
 0x18005080,0x18005084,0x18005088,0x1800508c,
 0x18005090,0x18005094,0x18005098,0x18005004,
 0x18005010,0x18005014,0x18005018,0x1800501c,
 0x18005020,0x18005024,0x18005028,0x1800502c,
 0x18005030,0x18005034,0x18005038,0x1800503c,
 0x18005040,0x18005044,0x18005048,0x1800504c,
 0x18005050,0x18005054,0x18005058,0x1800505c,
 0x18005060,0x18005064,0x18005068,0x1800506c};
static u32 spi_hw[39];
static bool ram_mode;
static u32 ram_hw[4098],ram_adie;
static unsigned ram_writes,ram_reads,ram_drop,ram_bad_read,ram_loss_write,ram_loss_read;
static unsigned ram_change,ram_map_fail,ram_map_loss;
static void lose_ram_access(void) {
 if(ram_change==1)fresh[0]&=~2;
 if(ram_change==2)fresh[0x2d4/4]=0;
 if(ram_change==3)fresh[0x184/4]|=32;
 if(ram_change==4)infra[0x228/4]|=0x2000;
 if(ram_change==5)ram_adie|=1;
}
static int ram_index(void *p) {
 uintptr_t addr=(uintptr_t)p,start=(uintptr_t)(ram_hw+1);
 if(addr>=start && addr<start+16384){assert(!((addr-start)&3));return (addr-start)/4;}
 return -1;
}

static u32 sema_hw[0x3404/4];
static bool sema_mode,sema_map_fail,sema_drop_release;
static unsigned sema_grants,sema_writes,sema_reads,sema_response;
static unsigned sema_bad_report,sema_loss_read,sema_change;
static unsigned sema_release_delay,sema_release_polls,sema_loss_release;
static void lose_sema_access(void) {
 if(sema_change==1)fresh[0]&=~2;
 if(sema_change==2)fresh[0x2d4/4]=0;
 if(sema_change==3)fresh[0x184/4]|=32;
 if(sema_change==4)infra[0x228/4]|=0x2000;
}

static bool config_mode;
static u32 config_adie, config_busy, config_wt[0x9c/4];
static unsigned config_writes, config_reads, config_corrupt_write, config_drop_write;
static unsigned config_bad_read, config_map_fail, config_maps, config_loss_write;
static unsigned config_loss_read, config_loss_map, config_change;
static void lose_config_access(void) {
 if(config_change==1)fresh[0]&=~2;
 if(config_change==2)fresh[0x2d4/4]=0;
 if(config_change==3)fresh[0x184/4]|=32;
 if(config_change==4)infra[0x228/4]|=0x2000;
 if(config_change==5)config_adie|=1;
 if(config_change==6)config_busy=32;
 if(config_change==7)config_wt[8/4]^=0x4000000;
}

static bool spi_mode;
static unsigned spi_reads,spi_map_fail,spi_after_map,spi_after_read,spi_change;
static void lose_spi_access(void) {
 if(spi_change==1)fresh[0]&=~2;
 if(spi_change==2)fresh[0x2d4/4]=0;
 if(spi_change==3)fresh[0x184/4]|=32;
 if(spi_change==4)infra[0x228/4]|=0x2000;
}
static u32 csr, cfg[2], csr_diag[2];
static unsigned csr_reads, csr_map_fail, guard_drop;
static struct { void *addr; u32 value; } trace[128];
static bool access_ok(void) {
 return (spm[0x16c/4]&2) && (spm[0x170/4]&2) && (spm[0x304/4]&31)==13 &&
        !(infra[0x228/4]&0x6000) && !(infra[0x724/4]&4) && (host&1);
}
static bool csr_access_ok(void) {
 return (spm[0x16c/4]&2) && (spm[0x170/4]&2) && (spm[0x304/4]&31)==13 &&
        !(infra[0x228/4]&0x2000) && !(infra[0x724/4]&4) && (host&1);
}
static bool off_access_ok(void) {
 return csr_access_ok() && reset_writes && (fresh[0]&6)==6 &&
        (fresh[0x2d4/4]&1) && !(fresh[0x184/4]&32);
}
static u32 readl(void *p) {
 if(ram_mode) {
  if(p==&ram_adie){assert(off_access_ok() && id_reads==2);return ram_adie;}
  int index=ram_index(p);
  if(index>=0) {
   assert(off_access_ok() && ram_adie==2 && rgu[0x38/4]==0 && rgu[0x3c/4]==255 && rgu[0x50/4]==0 && rgu[0x54/4]==1);
   assert((unsigned)index==(ram_reads%4096));ram_reads++;
   u32 value=*(u32 *)p;
   if(ram_bad_read==ram_reads)value=1;
   if(ram_loss_read==ram_reads)lose_ram_access();
   return value;
  }
 }

 if(sema_mode) {
  if(p==sema_hw+0x202c/4) {
   assert(off_access_ok() && id_reads==2 && !sema_grants);sema_grants++;
   if(sema_response&1)sema_hw[0x2400/4]|=0x800;
   if(sema_loss_read==100)lose_sema_access();
   return sema_response;
  }
  for(unsigned i=0;i<4;i++)if(p==sema_hw+(0x400+i*0x1000)/4) {
   assert(off_access_ok() && id_reads==2);sema_reads++;
   if(i==2 && sema_writes && !sema_drop_release && ++sema_release_polls>=sema_release_delay)
    sema_hw[0x2400/4]&=~0x800;
   u32 value=*(u32 *)p;
   if(sema_bad_report==sema_reads)value^=0x800;
   if(sema_loss_read==sema_reads)lose_sema_access();
   return value;
  }
 }

 if(config_mode) {
  if(p==&config_adie || p==&config_busy || p==config_wt+8/4) {
   assert(off_access_ok() && id_reads==2);return *(u32 *)p;
  }
  for(unsigned i=0;i<0x9c/4;i++)if(p==config_wt+i) {
   assert(off_access_ok() && id_reads==2 && config_adie==2 && !config_busy && config_wt[2]==0x80000);
   assert((i>=4 && i<=0x98/4) || i==1);
   config_reads++;u32 value=*(u32 *)p;
   if(config_reads==config_bad_read)value^=1;
   if(config_reads==config_loss_read)lose_config_access();
   return value;
  }
 }

 for(unsigned i=0;i<39;i++)if(p==spi_hw+i) {
  assert(spi_mode && off_access_ok() && id_reads==2 && spi_reads==i);
  spi_reads++;u32 result=spi_hw[i];
  if(spi_after_read==i+1)lose_spi_access();
  return result;
 }
 if(fresh_mode) {
  if(remap_mode)for(unsigned i=0;i<4;i++)if(p==fresh+remap_hw_offsets[i]/4) {
   assert(off_access_ok() && id_reads==2);remap_reads++;
   u32 result=*(u32 *)p;
   if(remap_reads==remap_bad_read)result^=1;
   return result;
  }
  if(rgu_mode)for(unsigned i=0;i<4;i++)if(p==rgu+rgu_hw_offsets[i]/4) {
   assert(off_access_ok() && id_reads==2);rgu_reads++;
   u32 result=*(u32 *)p;
   if(rgu_reads==rgu_bad_read)result^=1;
   return result;
  }
  for(unsigned i=0;i<13;i++)if(p==post_hw+i) {
   assert(off_access_ok() && id_reads==2);post_reads++;return post_hw[i];
  }
  if(p==fresh || p==fresh+0x184/4 || p==fresh+0x2d4/4) {
   assert(csr_access_ok());csr_reads++;return *(u32 *)p;
  }
  if(p==cfg || p==cfg+1) {
   assert(off_access_ok());id_reads++;u32 value=*(u32 *)p;
   if(changed_after_id && id_reads==1) {
    if(changed_after_id==1)fresh[0]&=~2;
    if(changed_after_id==2)fresh[0x2d4/4]=0;
    if(changed_after_id==3)fresh[0x184/4]|=32;
    if(changed_after_id==4)infra[0x228/4]|=0x2000;
   }
   return value;
  }
 }

 if (p==csr_diag || p==csr_diag+1 || (p==&csr && csr_mode)) {
  assert(csr_access_ok()); csr_reads++;
  return *(u32 *)p;
 }
 if (p==&csr || p==&cfg[0] || p==&cfg[1]) {
  assert(access_ok()); dark_reads++;
 }
 return *(u32 *)p;
}
static void writel(u32 value,void *addr) {
 if(ram_mode) {
  assert(addr!=&ram_adie && addr!=ram_hw && addr!=ram_hw+4097);
  int index=ram_index(addr);
  if(index>=0) {
   assert(off_access_ok() && ram_adie==2 && !value && (unsigned)index==ram_writes);
   assert(rgu[0x38/4]==0 && rgu[0x3c/4]==255 && rgu[0x50/4]==0 && rgu[0x54/4]==1);
   ram_writes++;
   if(ram_drop!=ram_writes)*(u32 *)addr=value;
   if(ram_loss_write==ram_writes)lose_ram_access();
   return;
  }
 }

 if(sema_mode && addr==sema_hw+0x222c/4) {
  assert(off_access_ok() && id_reads==2 && sema_grants==1 && (sema_response&1) && value==1);
  assert(mmio_writes<128);trace[mmio_writes].addr=addr;trace[mmio_writes++].value=value;
  sema_writes++;
  if(sema_loss_release)lose_sema_access();
  return;
 }

 if(config_mode) {
  assert(addr!=&config_adie && addr!=&config_busy);
  for(unsigned i=0;i<0x9c/4;i++)if(addr==config_wt+i) {
   assert(off_access_ok() && id_reads==2 && config_adie==2 && !config_busy && config_wt[2]==0x80000);
   assert((i>=4 && i<=0x98/4) || i==1);
   assert(mmio_writes<128);trace[mmio_writes].addr=addr;trace[mmio_writes++].value=value;
   config_writes++;
   if(config_writes!=config_drop_write)*(u32 *)addr=value^(config_writes==config_corrupt_write);
   if(config_writes==config_loss_write)lose_config_access();
   return;
  }
 }

 for(unsigned i=0;i<39;i++)assert(addr!=spi_hw+i);
 assert(mmio_writes<128);trace[mmio_writes].addr=addr;trace[mmio_writes].value=value;
 if(++mmio_writes==drop_write)return;
 if(remap_mode)for(unsigned i=0;i<4;i++)if(addr==fresh+remap_hw_offsets[i]/4) {
  assert(off_access_ok() && id_reads==2);remap_writes++;
  if(remap_writes!=remap_drop_write)*(u32 *)addr=value;
  if(remap_writes==remap_guard_fail)lose_remap_access();
  return;
 }
 if(rgu_mode)for(unsigned i=0;i<4;i++)if(addr==rgu+rgu_hw_offsets[i]/4) {
  assert(off_access_ok() && id_reads==2);rgu_writes++;
  if(rgu_writes!=rgu_drop_write)*(u32 *)addr=value;
  if(rgu_writes==rgu_guard_fail)lose_rgu_access();
  return;
 }
 if(fresh_mode && addr==fresh) {
  assert(csr_access_ok() && (value&1));reset_writes++;
  fresh[0]=fresh_fail==1?0:value&~1;
  if(fresh_fail==2)fresh[0]&=~4;
  if(fresh_fail==3)fresh[0x2d4/4]=0;
  if(fresh_fail==4)fresh[0x184/4]|=32;
  if(fresh_fail==5)host=0;
  return;
 }
 for(unsigned i=0;i<13;i++)assert(addr!=post_hw+i);
 assert(addr!=&csr && addr!=cfg && addr!=cfg+1 && addr!=csr_diag && addr!=csr_diag+1);
 if(addr==&spm[0x304/4]) {
  assert(rails[2].enabled && rails[3].enabled && pin_active);
  *(u32 *)addr=value;
  if((value&12)==12) {
   spm[0x16c/4]=(spm[0x16c/4]&~2)|(ack_fail==1?0:2);
   spm[0x170/4]=(spm[0x170/4]&~2)|(ack_fail==1 || ack_fail==2?0:2);
  } else if(!(value&12)) {
   if(ack_fail!=3)spm[0x16c/4]&=~2;
   if(ack_fail!=3 && ack_fail!=4)spm[0x170/4]&=~2;
  }
 } else if(addr==&infra[0x2a0/4])infra[0x228/4]|=value;
 else if(addr==&infra[0x2a4/4])infra[0x228/4]&=~value;
 else if(addr==&infra[0x714/4])infra[0x724/4]|=value;
 else if(addr==&infra[0x718/4])infra[0x724/4]&=~value;
 else { assert(addr==spm || addr==&host);*(u32 *)addr=value; }
}
static int pinctrl_select_state(struct pinctrl *p,struct pinctrl_state *s) {
 assert(p==&pins);
 if(s->which==1) {pin_active=true;assert(rails[2].enabled && rails[3].enabled);}
 else {assert(!(spm[0x16c/4]&2) && !(spm[0x170/4]&2));if(pin_fail!=2)pin_active=false;}
 return pin_fail==(unsigned)s->which?-EIO:0;
}
static void *ioremap(unsigned long addr,unsigned long size) {
 if(ram_mode && (addr==0x18001900 || addr==0x18050000)) {
  assert(off_access_ok() && id_reads==2 && rgu_writes==4);
  unsigned which=addr==0x18001900?1:2;
  if(ram_map_fail==which)return NULL;
  maps++;
  if(ram_map_loss==which)lose_ram_access();
  if(which==1){assert(size==4);return &ram_adie;}
  assert(size==0x4000);return ram_hw+1;
 }

 if(addr==0x18070000) {
  assert(sema_mode && size==0x3404 && off_access_ok() && id_reads==2);
  if(sema_map_fail)return NULL;
  maps++;return sema_hw;
 }

 if(config_mode && (addr==0x18001900 || addr==0x18004000 || addr==0x18005000)) {
  assert(off_access_ok() && id_reads==2);
  config_maps++;
  if(config_map_fail==config_maps)return NULL;
  maps++;
  if(config_loss_map==config_maps)lose_config_access();
  if(addr==0x18001900){assert(size==4);return &config_adie;}
  if(addr==0x18004000){assert(size==4);return &config_busy;}
  assert(size==0x9c);return config_wt;
 }

 for(unsigned i=0;i<39;i++)if(addr==spi_hw_addresses[i]) {
  assert(spi_mode && size==4 && off_access_ok() && id_reads==2 && spi_reads==i);
  if(spi_map_fail==i+1)return NULL;
  maps++;
  if(spi_after_map==i+1)lose_spi_access();
  return spi_hw+i;
 }
 if(fresh_mode) {
  if(addr==0x18000000) {
   assert(rgu_mode && size==0x58 && off_access_ok() && id_reads==2);
   if(rgu_map_fail)return NULL;
   maps++;if(rgu_after_map)lose_rgu_access();return rgu;
  }
  for(unsigned i=0;i<13;i++)if(addr==post_hw_addresses[i]) {
   assert(size==4 && off_access_ok() && id_reads==2);
   if(post_map_fail==i+1)return NULL;
   maps++;
   if(post_guard_drop==i+1) {
    if(post_change==1)fresh[0]&=~2;
    if(post_change==2)fresh[0x2d4/4]=0;
    if(post_change==3)fresh[0x184/4]|=32;
    if(post_change==4)infra[0x228/4]|=0x2000;
   }
   return post_hw+i;
  }
  assert(csr_access_ok());
  if(addr==0x18060000) {
   assert(size==0x2d8);if(fresh_map_fail==1)return NULL;
   maps++;if(changed_after_map==1)host=0;return fresh;
  }
  assert(addr==0x18001000 && size==8 && off_access_ok());
  if(fresh_map_fail==2)return NULL;
  maps++;
  if(changed_after_map==2)fresh[0x184/4]|=32;
  return cfg;
 }

 if(csr_mode) {
  assert(csr_access_ok()); assert(size==4);
  unsigned index=addr==0x18060000?0:addr==0x18060184?1:2;
  assert(index!=2 || addr==0x180602d4);
  if(csr_map_fail==index+1)return NULL;
  maps++;
  if(guard_drop==index+1)infra[0x228/4]|=0x2000;
  return index==0?csr_diag:index==1?&csr:csr_diag+1;
 }
 assert(access_ok());
 if(addr==0x18060184 && size==4) {if(io_fail==1)return NULL;maps++;csr=csr_stuck?32:0;return &csr;}
 assert(addr==0x18001000 && size==8);if(io_fail==2)return NULL;maps++;return cfg;
}
static void iounmap(void *addr) {if(addr==&ram_adie || addr==ram_hw+1){unmaps++;return;}if(addr==sema_hw){unmaps++;return;}if(addr==&config_adie || addr==&config_busy || addr==config_wt){unmaps++;return;}for(unsigned i=0;i<39;i++)if(addr==spi_hw+i){unmaps++;return;}for(unsigned i=0;i<13;i++)if(addr==post_hw+i){unmaps++;return;}assert(addr==rgu || addr==&csr || addr==cfg || addr==csr_diag || addr==csr_diag+1 || addr==fresh);unmaps++;}
#define read_poll_timeout(op,val,cond,delay,limit,sleep,args...) ({ \
 int result=-ETIMEDOUT; assert((delay)==50 && (limit)==20000); \
 for(unsigned attempt=0;attempt<4;attempt++){polls++;val=op(args);if(cond){result=0;break;}} result; })
#define readl_poll_timeout(addr,val,cond,delay,limit) \
 read_poll_timeout(readl,val,cond,delay,limit,false,addr)
'''
base = base[:insert] + fakes + base[insert:]
base = base.replace('static void usleep_range(unsigned lo,unsigned hi) { assert(lo<=hi); }', '''static unsigned settle_change;
static void usleep_range(unsigned lo,unsigned hi) {
 assert(lo<=hi);
 if(lo!=6000)return;
 switch(settle_change) {
 case 1: spm[0x16c/4]&=~2;break;
 case 2: spm[0x170/4]&=~2;break;
 case 3: spm[0x304/4]|=2;break;
 case 4: infra[0x228/4]|=0x4000;break;
 case 5: infra[0x724/4]|=4;break;
 case 6: host&=~1;break;
 case 7: infra[0x228/4]|=0x2000;break;
 }
}''')
base = base.replace('static int op6893_conn_domain_cycle(struct op6893_conn *c) { (void)c; abort(); }', header)
harness = base + r'''
static void domain_setup(void) {
 ram_mode=false;ram_adie=2;ram_writes=ram_reads=ram_drop=ram_bad_read=ram_loss_write=ram_loss_read=0;
 ram_change=ram_map_fail=ram_map_loss=0;
 for(unsigned i=0;i<4098;i++)ram_hw[i]=0xa5000000+i;
 sema_mode=sema_map_fail=sema_drop_release=false;memset(sema_hw,0,sizeof(sema_hw));
 sema_grants=sema_writes=sema_reads=sema_bad_report=sema_loss_read=sema_change=0;
 sema_response=1;sema_release_delay=1;sema_release_polls=sema_loss_release=0;
 config_mode=false;config_adie=2;config_busy=0;memset(config_wt,0,sizeof(config_wt));config_wt[2]=0x80000;
 config_writes=config_reads=config_corrupt_write=config_drop_write=config_bad_read=0;
 config_map_fail=config_maps=config_loss_write=config_loss_read=config_loss_map=config_change=0;
 setup();conn.emi_base=0x8fb00000;conn.emi_size=0x450000;conn.emi_valid=true;conn.domain_allowed=true;conn.pins=&pins;conn.active_pins=&active;conn.idle_pins=&idle;
 memset(infra,0,sizeof(infra));infra[0x228/4]=0xe70c500e;infra[0x724/4]=0xe7;
 spm[0]=1;mmio_writes=drop_write=pin_fail=dark_reads=maps=unmaps=0;
 rgu_mode=false;rgu_writes=rgu_reads=rgu_drop_write=rgu_bad_read=rgu_guard_fail=rgu_guard_change=0;
 rgu_map_fail=rgu_after_map=0;memset(rgu,0,sizeof(rgu));rgu[0x38/4]=0xff;rgu[0x50/4]=1;
 remap_mode=false;remap_writes=remap_reads=remap_drop_write=remap_bad_read=remap_guard_fail=remap_guard_change=0;
 post_reads=post_map_fail=post_guard_drop=post_change=0;
 spi_mode=false;spi_reads=spi_map_fail=spi_after_map=spi_after_read=spi_change=0;
 for(unsigned i=0;i<39;i++)spi_hw[i]=0xb000+i;
 for(unsigned i=0;i<13;i++)post_hw[i]=0xa000+i;
 fresh_mode=false;fresh_fail=reset_writes=id_reads=fresh_map_fail=changed_after_map=changed_after_id=0;
 memset(fresh,0,sizeof(fresh));fresh[0]=0x4006;fresh[0x2d4/4]=1;
 for(unsigned i=0;i<4;i++)fresh[remap_hw_offsets[i]/4]=(0xa5b00000+i*0x100000)|0x1100;
 csr_reads=csr_map_fail=guard_drop=0;csr_mode=false;csr=32;csr_diag[0]=6;csr_diag[1]=1;
 ack_fail=polls=io_fail=csr_stuck=settle_change=0;pin_active=false;cfg[0]=0x20010101;cfg[1]=3;
}
static int run(void) { return rail_cycle_store(&dev,NULL,"domain-cycle",12); }
static int csr_run(void) {csr_mode=true;return rail_cycle_store(&dev,NULL,"csr-cycle",9);}
static int fresh_run(void) {fresh_mode=true;return rail_cycle_store(&dev,NULL,"id-cycle",8);}
static int post_run(void) {fresh_mode=true;return rail_cycle_store(&dev,NULL,"post-id-cycle",13);}
static int remap_run(void) {fresh_mode=remap_mode=true;return rail_cycle_store(&dev,NULL,"remap-cycle",11);}
static int rgu_run(void) {fresh_mode=rgu_mode=true;return rail_cycle_store(&dev,NULL,"rgu-cycle",9);}
static int spi_run(void) {fresh_mode=spi_mode=true;return rail_cycle_store(&dev,NULL,"spi-baseline",12);}
int main(void) {
 domain_setup();assert(run()==12);
 unsigned count=mmio_writes;
 char output[4096];
 assert(conn.trace_count==7 && protection_trace_show(&dev,NULL,output)>0);
 assert(strstr(output,"point=after-settle") && strstr(output,"point=after-stop"));
 for(unsigned n=1;n<conn.trace_count;n++)assert(conn.trace[n].time_ns>conn.trace[n-1].time_ns);
 assert(!conn.faulted && conn.id_read && conn.hw_version==0x20010101 && conn.config_id==3);
 assert(!conn.domain_uncertain && !conn.pins_dirty && !pin_active && !host);
 assert(!rails[2].enabled && !rails[3].enabled && rails[0].refs==1 && rails[1].refs==1);
 assert(infra[0x228/4]==(0xe70c500e|0x2000) && infra[0x724/4]==0xe7);
 assert(maps==unmaps && maps==2 && dark_reads>=3);
 /* Exact active ACK wrapper + PG_CONN success write trace. */
 void *addr[]={spm,&host,spm,&spm[0x304/4],&spm[0x304/4],&spm[0x304/4],&spm[0x304/4],&spm[0x304/4],
 &infra[0x2a4/4],&infra[0x718/4],&infra[0x2a4/4],spm,&infra[0x2a0/4],&infra[0x2a0/4],&infra[0x714/4],
 &spm[0x304/4],&spm[0x304/4],&spm[0x304/4],&spm[0x304/4],&spm[0x304/4],&host};
 u32 values[]={0x0b160001,1,0x0b160001,0x16,0x1e,0x0e,0x0c,0x0d,0x4000,4,0x2000,
 0x0b160001,0x2000,0x4000,4,0x0f,0x1f,0x1e,0x1a,0x12,0};
 assert(count==ARRAY_SIZE(values));
 for(unsigned i=0;i<count;i++)assert(trace[i].addr==addr[i] && trace[i].value==values[i]);
 assert(run()==-EALREADY);
 for(unsigned drop=1;drop<=count;drop++) {
  domain_setup();drop_write=drop;int result=run();assert(maps==unmaps);
  assert(rails[0].enabled && rails[1].enabled);
  if(conn.domain_uncertain || conn.pins_dirty)assert(rails[2].enabled && rails[3].enabled);
  if(result<0)assert(conn.faulted && conn.failure_stage);
 }
 for(unsigned mode=1;mode<=4;mode++) {
  domain_setup();ack_fail=mode;assert(run()<0);
  assert(conn.domain_uncertain && conn.pins_dirty && pin_active);
  assert(rails[2].enabled && rails[3].enabled && polls<100);
  if(mode<=2)assert(!dark_reads && !maps && spm[0x304/4]==0x1e);
 }
 for(unsigned fail=1;fail<=2;fail++) {
  domain_setup();pin_fail=fail;assert(run()==-EIO);
  if(fail==1)assert(!mmio_writes && !maps && !rails[2].enabled && !rails[3].enabled);
  else assert(conn.pins_dirty && rails[2].enabled && rails[3].enabled && !host);
 }
 for(unsigned fail=1;fail<=2;fail++) {
  domain_setup();io_fail=fail;assert(run()==-ENOMEM && maps==unmaps);
  assert(!conn.domain_uncertain && !conn.pins_dirty && !rails[2].enabled && !rails[3].enabled);
  assert(!strcmp(conn.failure_stage,fail==1?"id-access-guard":"id-sleep-protection"));
 }
 domain_setup();csr_stuck=1;assert(run()==-ETIMEDOUT && !conn.id_read);
 assert(maps==unmaps && !rails[2].enabled && !rails[3].enabled);
 for(unsigned word=0;word<2;word++) {
  domain_setup();cfg[word]^=1;assert(run()==-ENODEV && conn.id_read);
  assert(!conn.domain_uncertain && !rails[2].enabled && !rails[3].enabled);
  assert(!strcmp(conn.failure_stage,"read-digital-id"));
 }
 for(unsigned change=1;change<=6;change++) {
  domain_setup();settle_change=change;assert(run()==-EBUSY && !maps && !dark_reads);
  assert(!strcmp(conn.failure_stage,"id-access-guard") && !conn.domain_uncertain);
  assert(!rails[2].enabled && !rails[3].enabled);
  assert(!conn.id_read);
  if(change==1)assert(!(conn.access_status&2));
  if(change==2)assert(!(conn.access_status2&2));
  if(change==3)assert(conn.access_control&2);
  if(change==4)assert(conn.access_protect&0x4000);
  if(change==5)assert(conn.access_protect2&4);
  if(change==6)assert(!(conn.access_host&1));
 }
 /* CSR-only access tolerates reverse-path bit14; never maps/reads ID. */
 domain_setup();settle_change=4;assert(csr_run()==9);
 assert(conn.csr_requested && !conn.id_read && !dark_reads);
 assert(conn.csr_samples==3 && csr_reads==3 && maps==3 && unmaps==3);
 assert(conn.csr_words[0]==6 && conn.csr_words[1]==32 && conn.csr_words[2]==1);
 assert(!rails[2].enabled && !rails[3].enabled && !conn.domain_uncertain);
 assert(csr_run()==-EALREADY);
 for(unsigned fail=1;fail<=3;fail++) {
  domain_setup();settle_change=4;csr_map_fail=fail;
  assert(csr_run()==-ENOMEM && maps==unmaps && conn.csr_samples==fail-1);
  assert(!conn.id_read && !dark_reads && !rails[2].enabled && !rails[3].enabled);
  domain_setup();settle_change=4;guard_drop=fail;
  assert(csr_run()==-EBUSY && maps==unmaps && conn.csr_samples==fail-1);
  assert(!conn.id_read && !dark_reads && !rails[2].enabled && !rails[3].enabled);
 }
 for(unsigned change=1;change<=7;change++) {
  if(change==4)continue;
  domain_setup();settle_change=change;assert(csr_run()==-EBUSY && !maps && !csr_reads);
  assert(!conn.id_read && !dark_reads && !rails[2].enabled && !rails[3].enabled);
 }
 /* New ID path requires a reset request and all three internal checks. */
 domain_setup();settle_change=4;assert(fresh_run()==8);
 assert(reset_writes==1 && id_reads==2 && conn.id_samples==2 && conn.off_ready);
 assert(conn.hw_version==0x20010101 && conn.config_id==3 && maps==2 && unmaps==2);
 assert(!conn.domain_uncertain && !rails[2].enabled && !rails[3].enabled);
 assert(fresh_run()==-EALREADY);
 for(unsigned fail=1;fail<=5;fail++) {
  domain_setup();settle_change=4;fresh_fail=fail;
  assert(fresh_run()<0 && !id_reads && !conn.id_read && !conn.off_ready);
  assert(maps==unmaps && !rails[2].enabled && !rails[3].enabled);
  assert(polls<100);
 }
 for(unsigned fail=1;fail<=2;fail++) {
  domain_setup();settle_change=4;fresh_map_fail=fail;
  assert(fresh_run()==-ENOMEM && !id_reads && maps==unmaps);
  assert(!rails[2].enabled && !rails[3].enabled);
  domain_setup();settle_change=4;changed_after_map=fail;
  assert(fresh_run()<0 && !id_reads && maps==unmaps);
 }
 for(unsigned change=1;change<=4;change++) {
  domain_setup();settle_change=4;changed_after_id=change;
  assert(fresh_run()<0 && id_reads==1 && conn.id_samples==1 && conn.id_read);
  assert(!conn.off_ready && maps==unmaps && !rails[2].enabled && !rails[3].enabled);
 }
 for(unsigned word=0;word<2;word++) {
  domain_setup();settle_change=4;cfg[word]^=1;
  assert(fresh_run()==-ENODEV && id_reads==2 && maps==unmaps);
 }
 for(unsigned change=1;change<=7;change++) {
  if(change==4)continue;
  domain_setup();settle_change=change;assert(fresh_run()==-EBUSY && !maps && !id_reads);
 }
 /* Read-only post-ID baseline: no write outside existing reset request. */
 domain_setup();settle_change=4;assert(post_run()==13);
 assert(conn.post_samples==13 && post_reads==13 && id_reads==2 && maps==15 && unmaps==15);
 assert(mmio_writes==22 && reset_writes==1 && !conn.domain_uncertain);
 for(unsigned i=0;i<13;i++)assert(conn.post_words[i]==0xa000+i);
 assert(post_id_show(&dev,NULL,output)>0 && strstr(output,"samples=13"));
 assert(post_run()==-EALREADY);
 for(unsigned fail=1;fail<=13;fail++) {
  domain_setup();settle_change=4;post_map_fail=fail;
  assert(post_run()==-ENOMEM && conn.post_samples==fail-1 && maps==unmaps);
  assert(post_reads==fail-1 && !rails[2].enabled && !rails[3].enabled);
  for(unsigned change=1;change<=4;change++) {
   domain_setup();settle_change=4;post_guard_drop=fail;post_change=change;
   assert(post_run()<0 && post_reads==fail-1 && conn.post_samples==fail-1 && maps==unmaps);
   assert(!conn.domain_uncertain && !rails[2].enabled && !rails[3].enabled);
  }
 }
 domain_setup();conn.emi_valid=false;assert(post_run()==-EINVAL && !id_reads && !post_reads && !conn.attempted);
 assert(maps==unmaps && !rails[2].enabled && !rails[3].enabled);
 domain_setup();cfg[0]^=1;assert(post_run()==-ENODEV && !post_reads && maps==unmaps);
 assert(op6893_conn_emi_valid(0x50000000,0x450000));
 assert(op6893_conn_emi_valid(0x8fb00000,0x450000));
 assert(!op6893_conn_emi_valid(0x8fc00000,0x450000));
 assert(!op6893_conn_emi_valid(0x4ff00000,0x450000));
 assert(!op6893_conn_emi_valid(0x50000001,0x450000));
 assert(!op6893_conn_emi_valid(0x50000000,0));
 assert(!op6893_conn_emi_valid(0x50000000,~0ULL));
 assert(!op6893_conn_emi_valid(~0ULL,0x450000));
 /* Remap targets preserve high bits; originals restored before shutdown. */
 domain_setup();settle_change=4;assert(remap_run()==11);
 assert(remap_writes==8 && mmio_writes==30 && conn.remap_saved==4);
 assert(conn.remap_applied==4 && conn.remap_restored==4 && !conn.remap_dirty);
 assert(conn.remap_cleanup_result==0 && !conn.domain_uncertain && !rails[2].enabled && !rails[3].enabled);
 for(unsigned i=0;i<4;i++) {
  u32 original=(0xa5b00000+i*0x100000)|0x1100;
  u32 target=(original&~0xfffffU)|(i?0x1000:0x8fb0);
  assert(conn.remap_before[i]==original && conn.remap_on[i]==target && conn.remap_target[i]==target);
  assert(conn.remap_after[i]==original && fresh[remap_hw_offsets[i]/4]==original);
  assert(trace[12+i].addr==fresh+remap_hw_offsets[i]/4 && trace[12+i].value==target);
  assert(trace[16+i].addr==fresh+remap_hw_offsets[3-i]/4);
 }
 assert(remap_status_show(&dev,NULL,output)>0 && strstr(output,"applied=4 restored=4 dirty=0"));
 assert(remap_run()==-EALREADY);
 /* Every apply write/readback error attempts verified reverse restoration. */
 for(unsigned fail=1;fail<=4;fail++) {
  domain_setup();settle_change=4;remap_drop_write=fail;
  assert(remap_run()==-EIO && conn.remap_cleanup_result==0 && !conn.remap_dirty);
  assert(!conn.domain_uncertain && !rails[2].enabled && !rails[3].enabled);
  domain_setup();settle_change=4;remap_bad_read=4+fail;
  assert(remap_run()==-EIO && !conn.remap_dirty && !conn.domain_uncertain);
 }
 /* Unverified restoration retains on-domain resources and refuses retries. */
 for(unsigned fail=5;fail<=8;fail++) {
  domain_setup();settle_change=4;remap_drop_write=fail;
  assert(remap_run()==-EIO && conn.remap_cleanup_result==-EIO && conn.remap_dirty);
  assert(conn.domain_uncertain && conn.pins_dirty && pin_active && rails[2].enabled && rails[3].enabled);
  assert(spm[0x304/4]==13 && conn.domain_cleanup_result==-EUCLEAN && maps==unmaps);
  assert(remap_run()==-EALREADY);
  domain_setup();settle_change=4;remap_bad_read=fail+4;
  assert(remap_run()==-EIO && conn.remap_dirty && conn.domain_uncertain);
 }
 domain_setup();settle_change=4;remap_bad_read=7;remap_drop_write=4;
 assert(remap_run()==-EIO && conn.remap_cleanup_result==-EIO && conn.remap_dirty);
 assert(!strcmp(conn.failure_stage,"remap-apply-readback") && conn.domain_uncertain);
 for(unsigned fail=1;fail<=8;fail++)for(unsigned change=1;change<=4;change++) {
  domain_setup();settle_change=4;remap_guard_fail=fail;remap_guard_change=change;
  assert(remap_run()<0 && conn.remap_dirty && conn.remap_cleanup_result<0);
  assert(conn.domain_uncertain && conn.pins_dirty && rails[2].enabled && rails[3].enabled);
  assert(spm[0x304/4]==13 && maps==unmaps);
 }
 /* Isolated RGU policy: exact ACK values and reverse original restoration. */
 domain_setup();settle_change=4;conn.emi_valid=false;assert(rgu_run()==9);
 assert(rgu_writes==8 && mmio_writes==30 && !remap_writes && maps==3 && maps==unmaps);
 assert(conn.rgu_saved==4 && conn.rgu_applied==4 && conn.rgu_restored==4 && !conn.rgu_dirty);
 assert(!conn.rgu_cleanup_result && !conn.domain_uncertain && !rails[2].enabled && !rails[3].enabled);
 const u32 rgu_original[]={0xff,0,1,0},rgu_targets[]={0,0xff,0,1};
 for(unsigned i=0;i<4;i++) {
  assert(conn.rgu_before[i]==rgu_original[i] && conn.rgu_target[i]==rgu_targets[i]);
  assert(conn.rgu_on[i]==rgu_targets[i] && conn.rgu_after[i]==rgu_original[i]);
  assert(rgu[rgu_hw_offsets[i]/4]==rgu_original[i]);
  assert(trace[12+i].addr==rgu+rgu_hw_offsets[i]/4 && trace[12+i].value==rgu_targets[i]);
  assert(trace[16+i].addr==rgu+rgu_hw_offsets[3-i]/4 && trace[16+i].value==rgu_original[3-i]);
 }
 assert(rgu_status_show(&dev,NULL,output)>0 && strstr(output,"applied=4 restored=4 dirty=0"));
 assert(rgu_run()==-EALREADY);
 for(unsigned i=0;i<4;i++) {
  domain_setup();rgu[rgu_hw_offsets[i]/4]^=0x100;
  assert(rgu_run()==-EBUSY && !rgu_writes && maps==unmaps && conn.rgu_saved==i+1);
  assert(!conn.domain_uncertain && !rails[2].enabled && !rails[3].enabled);
 }
 domain_setup();rgu_map_fail=1;assert(rgu_run()==-ENOMEM && !rgu_writes && maps==unmaps);
 for(unsigned change=1;change<=4;change++) {
  domain_setup();rgu_after_map=1;rgu_guard_change=change;
  assert(rgu_run()<0 && !rgu_reads && !rgu_writes && maps==unmaps);
  assert(!conn.domain_uncertain && !rails[2].enabled && !rails[3].enabled);
 }
 domain_setup();cfg[0]^=1;assert(rgu_run()==-ENODEV && !rgu_reads && !rgu_writes);
 domain_setup();conn.domain_allowed=false;assert(rgu_run()==-EOPNOTSUPP && !conn.attempted);
 /* Every apply write/readback error attempts verified reverse restoration. */
 for(unsigned fail=1;fail<=4;fail++) {
  domain_setup();settle_change=4;rgu_drop_write=fail;
  assert(rgu_run()==-EIO && conn.rgu_cleanup_result==0 && !conn.rgu_dirty);
  assert(!conn.domain_uncertain && !rails[2].enabled && !rails[3].enabled);
  domain_setup();settle_change=4;rgu_bad_read=4+fail;
  assert(rgu_run()==-EIO && !conn.rgu_dirty && !conn.domain_uncertain);
 }
 /* Unverified restoration retains on-domain resources and refuses retries. */
 for(unsigned fail=5;fail<=8;fail++) {
  domain_setup();settle_change=4;rgu_drop_write=fail;
  assert(rgu_run()==-EIO && conn.rgu_cleanup_result==-EIO && conn.rgu_dirty);
  assert(conn.domain_uncertain && conn.pins_dirty && pin_active && rails[2].enabled && rails[3].enabled);
  assert(spm[0x304/4]==13 && conn.domain_cleanup_result==-EUCLEAN && maps==unmaps);
  assert(rgu_run()==-EALREADY);
  domain_setup();settle_change=4;rgu_bad_read=fail+4;
  assert(rgu_run()==-EIO && conn.rgu_dirty && conn.domain_uncertain);
 }
 domain_setup();settle_change=4;rgu_bad_read=7;rgu_drop_write=4;
 assert(rgu_run()==-EIO && conn.rgu_cleanup_result==-EIO && conn.rgu_dirty);
 assert(!strcmp(conn.failure_stage,"rgu-apply-readback") && conn.domain_uncertain);
 for(unsigned fail=1;fail<=8;fail++)for(unsigned change=1;change<=4;change++) {
  domain_setup();settle_change=4;rgu_guard_fail=fail;rgu_guard_change=change;
  assert(rgu_run()<0 && conn.rgu_dirty && conn.rgu_cleanup_result<0);
  assert(conn.domain_uncertain && conn.pins_dirty && rails[2].enabled && rails[3].enabled);
  assert(spm[0x304/4]==13 && maps==unmaps);
 }
 /* SPI baseline is read-only regardless of sampled status/configuration. */
 domain_setup();settle_change=4;conn.emi_valid=false;assert(spi_run()==12);
 assert(spi_reads==39 && conn.spi_samples==39 && maps==41 && maps==unmaps);
 assert(mmio_writes==22 && reset_writes==1 && !rgu_writes && !remap_writes);
 assert(conn.spi_end_ns>conn.spi_start_ns && !conn.domain_uncertain);
 assert(!rails[2].enabled && !rails[3].enabled && !conn.pins_dirty);
 for(unsigned i=0;i<39;i++)assert(conn.spi_words[i]==0xb000+i);
 unsigned captured_reads=csr_reads;
 assert(spi_baseline_show(&dev,NULL,output)>0 && strstr(output,"samples=39"));
 assert(strstr(output,"address=0x18001900 value=0xb000"));
 assert(strstr(output,"address=0x1800506c value=0xb026"));
 assert(csr_reads==captured_reads && spi_reads==39 && mmio_writes==22);
 assert(spi_run()==-EALREADY && spi_reads==39 && mmio_writes==22);
 for(unsigned fail=1;fail<=39;fail++) {
  domain_setup();spi_map_fail=fail;
  assert(spi_run()==-ENOMEM && spi_reads==fail-1 && conn.spi_samples==fail-1);
  assert(maps==unmaps && !strcmp(conn.failure_stage,"spi-baseline-map"));
  assert(!conn.domain_uncertain && !rails[2].enabled && !rails[3].enabled);
  assert(conn.spi_end_ns>conn.spi_start_ns);
  for(unsigned change=1;change<=4;change++) {
   domain_setup();spi_after_map=fail;spi_change=change;
   assert(spi_run()<0 && spi_reads==fail-1 && conn.spi_samples==fail-1);
   assert(maps==unmaps && mmio_writes==22 && !conn.domain_uncertain);
   assert(!rails[2].enabled && !rails[3].enabled && conn.spi_end_ns>conn.spi_start_ns);
   domain_setup();spi_after_read=fail;spi_change=change;
   assert(spi_run()<0 && spi_reads==fail && conn.spi_samples==fail);
   assert(maps==unmaps && mmio_writes==22 && !conn.domain_uncertain);
   assert(!rails[2].enabled && !rails[3].enabled && conn.spi_end_ns>conn.spi_start_ns);
  }
 }
 for(unsigned word=0;word<2;word++) {
  domain_setup();cfg[word]^=1;
  assert(spi_run()==-ENODEV && !spi_reads && !conn.spi_start_ns && maps==unmaps);
 }
 domain_setup();conn.domain_allowed=false;
 assert(spi_run()==-EOPNOTSUPP && !conn.attempted && !spi_reads && !mmio_writes);
 domain_setup();conn.cycle_allowed=false;
 assert(spi_run()==-EOPNOTSUPP && !conn.attempted && !spi_reads && !mmio_writes);
 domain_setup();conn.emi_valid=false;assert(remap_run()==-EINVAL && !conn.attempted && !remap_writes);
 domain_setup();cfg[0]^=1;assert(remap_run()==-ENODEV && !remap_writes);
 domain_setup();conn.domain_allowed=false;assert(remap_run()==-EOPNOTSUPP && !conn.attempted);
 domain_setup();conn.domain_allowed=false;assert(post_run()==-EOPNOTSUPP && !conn.attempted);
 domain_setup();conn.domain_allowed=false;assert(fresh_run()==-EOPNOTSUPP && !conn.attempted);
 domain_setup();conn.domain_allowed=false;assert(csr_run()==-EOPNOTSUPP && !conn.attempted);
 domain_setup();conn.domain_allowed=false;assert(run()==-EOPNOTSUPP && !calls && !conn.attempted);
 domain_setup();infra[0x228/4]&=~0x4000;assert(run()==-EBUSY && !mmio_writes && !maps);
 assert(!rails[2].enabled && !rails[3].enabled);
 printf("PASS: exact %u-write ACK sequence, dropped MMIO writes, four dual-ACK timeouts, "
        "pin failures, guarded mappings, sleep ACK timeout, bad IDs, retained rails, "
        "CSR-only snapshots, reset-requested clock/timeout/sleep gates, partial ID refusal, "
        "post-ID and 39-word SPI baselines, reversible remap/RGU writes, baseline refusal, retained failed restoration and one-shot integration\n",count);
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
