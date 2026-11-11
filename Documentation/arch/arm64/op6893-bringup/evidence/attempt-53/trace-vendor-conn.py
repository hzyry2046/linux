#!/usr/bin/env python3
# SPDX-License-Identifier: GPL-2.0-only
"""Execute the actual vendor CONN MTCMOS function against host fake MMIO.

No device access. This proves software write order, not electrical correctness.
"""
import hashlib
import json
from pathlib import Path
import re
import subprocess
import tempfile

SOURCES = [
    Path('/data/src/6.6-exp/android_kernel_modules_oneplus_mt6833/kernel/kernel_device_modules-6.6/drivers/clk/mediatek/clk-mt6893-pg.c'),
    Path('/data/src/kernel_oddo_mt6893/drivers/clk/mediatek/clk-mt6885-pg.c'),
]
HARNESS = r'''
#include <stdio.h>
#include <stdint.h>
#include <stdlib.h>
#define SPM_REG(x) (0x10006000u + (x))
#define INFRACFG_REG(x) (0x10001000u + (x))
#define STA_POWER_DOWN 0
#define STA_POWER_ON 1
#define DBG_ID_CONN 1
#define INCREASE_STEPS ((void)0)
static int DBG_ID, DBG_STA, DBG_STEP, fault, polls;
static uint32_t ctl, sta, sta2, bp, bp2;
static void ram_console_update(void) {
 if (++polls > 8) { puts("SIMULATOR_ABORT: vendor loop has not returned"); exit(77); }
}
static uint32_t spm_read(uint32_t a) {
 switch(a) {
 case 0x10006304: return ctl;
 case 0x1000616c: return sta;
 case 0x10006170: return sta2;
 case 0x10001228: return bp;
 case 0x10001724: return bp2;
 default: fprintf(stderr,"unexpected read %x\n",a); exit(2);
 }
}
static void spm_write(uint32_t a,uint32_t v) {
 printf("%08x %08x\n",a,v);
 switch(a) {
 case 0x10006000: break;
 case 0x10006304:
  ctl=v;
  sta=(!fault && (v&4))?2:0; sta2=(!fault && (v&8))?2:0;
  break;
 case 0x100012a0: bp|=v; break;
 case 0x100012a4: bp&=~v; break;
 case 0x10001714: bp2|=v; break;
 case 0x10001718: bp2&=~v; break;
 default: fprintf(stderr,"unexpected write %x\n",a); exit(2);
 }
}
'''


def trace(path):
    src = path.read_text()
    start = src.index('int spm_mtcmos_ctrl_conn(int state)')
    end = src.index('\nint ', start + 5)
    fn = src[start:end]
    definitions = dict(re.findall(r'^\s*#define\s+(\w+)\s+([^\n]+)', src, re.M))
    needed = set(re.findall(r'\b[A-Z][A-Z0-9_]+\b', fn))
    selected = {}
    while needed:
        name = needed.pop()
        if name in selected or name not in definitions or name in ('INCREASE_STEPS',):
            continue
        value = definitions[name]
        if '\\' in value:
            raise ValueError('unexpected multiline macro: ' + name)
        selected[name] = value
        needed.update(re.findall(r'\b[A-Z][A-Z0-9_]+\b', value))
    # Debug IDs and state are supplied by harness; IGNORE_MTCMOS_CHECK stays undefined.
    for name in ('DBG_ID_CONN', 'STA_POWER_DOWN', 'STA_POWER_ON', 'IGNORE_MTCMOS_CHECK'):
        selected.pop(name, None)
    c = HARNESS + '\n'.join(f'#define {k} {v}' for k,v in selected.items()) + '\n' + fn
    c += r'''
int main(int argc,char **argv) {
 int on=argc<2 || argv[1][0]!='0'; fault=argc>2;
 ctl=on?0x12:0xd; sta=sta2=on?0:2; bp=on?0x6000:0; bp2=on?4:0;
 return spm_mtcmos_ctrl_conn(on?STA_POWER_ON:STA_POWER_DOWN);
}
'''
    with tempfile.TemporaryDirectory() as tmp:
        p=Path(tmp); (p/'test.c').write_text(c)
        subprocess.run(['cc','-std=c11','-Wall','-Wextra','-Werror','-fsanitize=undefined',str(p/'test.c'),'-o',str(p/'test')],check=True)
        traces={}
        for label,args in [('on',['1']),('off',['0']),('on_no_ack',['1','fault'])]:
            r=subprocess.run([str(p/'test'),*args],capture_output=True,text=True,timeout=2)
            if r.returncode != (77 if label=='on_no_ack' else 0):
                raise RuntimeError((label,r.returncode,r.stderr))
            traces[label]=r.stdout.splitlines()
    return {'source':str(path),'sha256':hashlib.sha256(path.read_bytes()).hexdigest(),'traces':traces}

if __name__ == '__main__':
    result=[trace(p) for p in SOURCES]
    assert result[0]['traces']==result[1]['traces'], 'vendor traces disagree'
    print(json.dumps({'vendors':result,'identical':True,
                      'limits':'ACK success/fault trace in a fake-MMIO model; no hardware validation.'},indent=2))
