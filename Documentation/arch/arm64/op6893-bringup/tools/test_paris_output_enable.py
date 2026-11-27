#!/usr/bin/env python3
# SPDX-License-Identifier: GPL-2.0-only
"""Execute complete actual Paris pinconf get/set against isolated field fakes."""
from pathlib import Path
import re
import subprocess
import tempfile

root = Path(__file__).resolve().parents[5]
source = (root / 'drivers/pinctrl/mediatek/pinctrl-paris.c').read_text()
code = source[source.index('static int mtk_pinconf_get('):
              source.index('static struct mtk_pinctrl_group *')]
params = sorted(set(re.findall(r'\b(?:PIN_CONFIG_|MTK_PIN_CONFIG_)[A-Z_]+', code)))
fields = sorted(set(re.findall(r'\bPINCTRL_PIN_REG_[A-Z_]+', code)))
harness = r'''#include <assert.h>
#include <errno.h>
#include <stdbool.h>
#include <stdint.h>
#include <stdio.h>
#include <string.h>
#define ENOTSUPP 524
#define MTK_PUPD_SET_R1R0_00 100
#define MTK_DISABLE 0
#define MTK_OUTPUT 1
typedef uint32_t u32;
''' + 'enum pin_config_param {' + ','.join(params) + '};\n' + \
    'enum fields {' + ','.join(fields) + ', NFIELDS};\n' + r'''
struct mtk_pin_desc { unsigned number; };
struct mtk_pinctrl;
struct soc {
 unsigned npins;
 struct mtk_pin_desc pins[220];
 int (*bias_get_combo)(struct mtk_pinctrl *, const struct mtk_pin_desc *, int *, int *);
 int (*bias_set_combo)(struct mtk_pinctrl *, const struct mtk_pin_desc *, int, u32);
 int (*drive_get)(struct mtk_pinctrl *, const struct mtk_pin_desc *, int *);
 int (*adv_drive_get)(struct mtk_pinctrl *, const struct mtk_pin_desc *, int *);
 int (*drive_set)(struct mtk_pinctrl *, const struct mtk_pin_desc *, u32);
 int (*adv_drive_set)(struct mtk_pinctrl *, const struct mtk_pin_desc *, u32);
 int (*adv_pull_get)(struct mtk_pinctrl *, const struct mtk_pin_desc *, bool, int *);
 int (*adv_pull_set)(struct mtk_pinctrl *, const struct mtk_pin_desc *, bool, u32);
};
struct mtk_pinctrl { struct soc *soc; };
struct pinctrl_dev { struct mtk_pinctrl *hw; };
static struct mtk_pinctrl *pinctrl_dev_get_drvdata(struct pinctrl_dev *p) {return p->hw;}
static u32 pinconf_to_config_param(unsigned long v) {return v & 0xffff;}
static unsigned long pinconf_to_config_packed(u32 p, u32 arg) {return p | ((unsigned long)arg << 16);}
static int mtk_drv_adv_to_uA(int arg) {return arg;}
static int mtk_drv_uA_to_adv(u32 arg) {return arg;}
static int values[220][NFIELDS], original[220][NFIELDS];
static unsigned reads,writes,fail_read,fail_write;
static int error;
static int mtk_hw_get_value(struct mtk_pinctrl *hw, const struct mtk_pin_desc *d,
                            int field,int *out) {
 assert(d->number<hw->soc->npins);
 if(++reads==fail_read)return error;
 *out=values[d->number][field];return 0;
}
static int mtk_hw_set_value(struct mtk_pinctrl *hw, const struct mtk_pin_desc *d,
                            int field,int value) {
 assert(d->number<hw->soc->npins);
 if(++writes==fail_write)return error;
 values[d->number][field]=value;return 0;
}
''' + code + r'''
static struct soc soc={.npins=220};
static struct mtk_pinctrl hw={.soc=&soc};
static struct pinctrl_dev dev={.hw=&hw};
static void setup(unsigned dir,unsigned latch,unsigned smt) {
 for(unsigned p=0;p<220;p++) {
  soc.pins[p].number=p;
  for(unsigned f=0;f<NFIELDS;f++)values[p][f]=(p+f)&1;
 }
 values[180][PINCTRL_PIN_REG_DIR]=dir;
 values[180][PINCTRL_PIN_REG_DO]=latch;
 values[180][PINCTRL_PIN_REG_SMT]=smt;
 memcpy(original,values,sizeof(values));
 reads=writes=fail_read=fail_write=0;error=-EIO;
}
int main(void) {
 unsigned long config,saved;
 unsigned args[]={0,1,2,0xffffffffU};
 for(unsigned dir=0;dir<2;dir++)for(unsigned latch=0;latch<2;latch++)
 for(unsigned smt=0;smt<2;smt++)for(unsigned i=0;i<4;i++) {
  setup(dir,latch,smt);
  assert(!mtk_pinconf_set(&dev,180,PIN_CONFIG_OUTPUT_ENABLE,args[i]));
  assert(writes==1 && !reads);
  original[180][PINCTRL_PIN_REG_DIR]=!!args[i];
  assert(!memcmp(values,original,sizeof(values)));
  config=saved=pinconf_to_config_packed(PIN_CONFIG_OUTPUT_ENABLE,99);
  assert(mtk_pinconf_get(&dev,180,&config)==(args[i]?0:-EINVAL));
  assert(config==(args[i]?pinconf_to_config_packed(PIN_CONFIG_OUTPUT_ENABLE,1):saved));
  assert(reads==1 && writes==1);
 }
 int errors[]={-EIO,-EINVAL,-ENOTSUPP};
 for(unsigned i=0;i<3;i++)for(unsigned arg=0;arg<2;arg++) {
  setup(arg,1,0);error=errors[i];fail_write=1;
  assert(mtk_pinconf_set(&dev,180,PIN_CONFIG_OUTPUT_ENABLE,arg)==error);
  assert(!memcmp(values,original,sizeof(values)) && writes==1 && !reads);
  fail_read=1;config=saved=pinconf_to_config_packed(PIN_CONFIG_OUTPUT_ENABLE,7);
  assert(mtk_pinconf_get(&dev,180,&config)==error && config==saved);
 }
 setup(0,0,0);config=pinconf_to_config_packed(PIN_CONFIG_OUTPUT_ENABLE,1);
 assert(mtk_pinconf_set(&dev,220,PIN_CONFIG_OUTPUT_ENABLE,1)==-EINVAL);
 assert(mtk_pinconf_get(&dev,220,&config)==-EINVAL && !reads && !writes);
 /* Existing LEVEL preloads DO then enables output; disabling preserves DO. */
 setup(0,0,0);assert(!mtk_pinconf_set(&dev,180,PIN_CONFIG_LEVEL,1));
 assert(values[180][PINCTRL_PIN_REG_DO]==1 && values[180][PINCTRL_PIN_REG_DIR]==1);
 assert(!mtk_pinconf_set(&dev,180,PIN_CONFIG_OUTPUT_ENABLE,0));
 original[180][PINCTRL_PIN_REG_DO]=1;assert(!memcmp(values,original,sizeof(values)));
 setup(0,0,0);fail_write=1;
 assert(mtk_pinconf_set(&dev,180,PIN_CONFIG_LEVEL,1)==-EIO && writes==1);
 assert(!memcmp(values,original,sizeof(values)));
 puts("PASS: actual Paris get/set,32 direction/latch/Schmitt/argument combinations,"
      "all unrelated pins/fields preserved,provider errors,invalid pin,LEVEL interoperability");
}
'''
with tempfile.TemporaryDirectory() as tmp:
    path = Path(tmp)
    (path / 'test.c').write_text(harness)
    subprocess.run(['cc', '-O1', '-Wall', '-Wextra', '-Werror',
                    '-fsanitize=undefined', '-fno-sanitize-recover=all',
                    str(path / 'test.c'), '-o', str(path / 'test')], check=True)
    subprocess.run([str(path / 'test')], check=True)
