#!/usr/bin/env python3
# SPDX-License-Identifier: GPL-2.0-only
"""Actual NVRAM cache, 32 kHz fact and MD boot owner with deterministic fakes.

The model checks lifecycle, order, one-attempt and failure containment. It does
not prove mapping attributes, SMC behaviour, MD firmware or hardware stop.
"""
from pathlib import Path
import subprocess
import tempfile

K = Path(__file__).resolve().parents[5]
SRC = K / 'drivers/misc/mediatek/ccci'

TEST = r'''
#include <assert.h>
#include <stdarg.h>
#include <stdio.h>
#include <stdlib.h>
#include <string.h>
#include <linux/types.h>
#include <linux/errno.h>

#define CONFIG_OP6893_CCCI_NVRAM_CACHE 1
#define CONFIG_OP6893_CCCI_MD_BOOT 1
#define __CCCI_SMEM_H
#define __CCCI_RUNTIME_H
#define __CCCI_NVRAM_CACHE_H
#define __CCCI_RTC32K_H
#define __CCCI_MD_BOOT_H
#define __CCCI_CCIF_H
#define __CCCI_PORT_DISPATCH_H

#define BIT(n) (1UL << (n))
#define BIT_ULL(n) (1ULL << (n))
#define ARRAY_SIZE(a) (sizeof(a) / sizeof((a)[0]))
#define __iomem
#define SMCCC_RET_NOT_SUPPORTED (~0UL)
#define MTK_SIP_KERNEL_CCCI_CONTROL 0x82000204UL
#define ERR_PTR(e) ((void *)(intptr_t)(e))
#define IS_ERR(p) ((uintptr_t)(p) >= (uintptr_t)-4095)
#define PTR_ERR(p) ((int)(intptr_t)(p))
#define WARN_ON(x) (!!(x))
#ifndef EPROBE_DEFER
#define EPROBE_DEFER 517
#endif

struct arm_smccc_res { unsigned long a0, a1, a2, a3; };
struct device_node { bool no_external_32k; };
#define MAX_ACTIONS 32
struct device { struct device_node *of_node; void (*actions[MAX_ACTIONS])(void *);
		void *ctx[MAX_ACTIONS]; unsigned n; };
struct mutex { bool held; };
struct nvmem_cell { int unused; };
struct ccci_ccif { int unused; };
struct ccci_port_dispatch { int unused; };
struct ccci_nvram_cache;
struct ccci_md_boot;

struct ccci_lk_region { u64 base, size; };
static inline bool ccci_lk_contains(const struct ccci_lk_region *r, u64 base, u64 size)
{
	return r->size && size && base >= r->base && base - r->base < r->size &&
	       size <= r->size - (base - r->base);
}

#define CCCI_SMEM_USERS 42
#define CCCI_SMEM_NVRAM 32
struct ccci_smem_region {
	u64 ap; u32 md, offset, size;
	bool present, cached, preserve_first, no_map, from_lk;
};
struct ccci_smem_layout {
	struct ccci_lk_region noncached, cached;
	struct ccci_smem_region users[CCCI_SMEM_USERS];
	u32 cache_md_base, cache_gap_bytes, noncache_gap_bytes, count;
};

enum ccci_runtime_crystal {
	CCCI_RUNTIME_CRYSTAL_UNKNOWN,
	CCCI_RUNTIME_CRYSTAL_PRESENT,
	CCCI_RUNTIME_CRYSTAL_ABSENT,
};
enum ccci_rtc32k_source {
	CCCI_RTC32K_SOURCE_NONE,
	CCCI_RTC32K_SOURCE_NVMEM,
	CCCI_RTC32K_SOURCE_DT,
};
#define CCCI_RUNTIME_FEATURES 64
struct ccci_runtime_offer { bool supported; u8 version; u16 length; u8 data[64]; };
struct ccci_runtime_boot { u32 booting_start_id; enum ccci_runtime_crystal crystal; };

static unsigned char *map_buf;
static unsigned map_size;
static u64 map_off;
static bool map_fail, read_fault;
static unsigned logn;
static char order[64];
static int fail_ccif_prepare, fail_ccif_stop, fail_runtime;
static int fail_dispatch_prepare, fail_dispatch_start, fail_dispatch_stop;
static unsigned smc_calls;
static unsigned long smc_a0, smc_a1, smc_a2;
static unsigned long smc_seen[3];
static bool nvmem_present;
static u8 nvmem_value;
static size_t nvmem_length = 1;
static int nvmem_get_error, nvmem_read_error;
static enum ccci_runtime_crystal expect_crystal;

static void note(char c) { assert(logn + 1 < sizeof(order)); order[logn++] = c; order[logn] = 0; }

static void mutex_init(struct mutex *m) { m->held = false; }
static void mutex_lock(struct mutex *m) { assert(!m->held); m->held = true; }
static void mutex_unlock(struct mutex *m) { assert(m->held); m->held = false; }

static int devm_add_action_or_reset(struct device *d, void (*fn)(void *), void *ctx)
{
	if (d->n == MAX_ACTIONS) {
		fn(ctx);
		return -ENOMEM;
	}
	d->actions[d->n] = fn;
	d->ctx[d->n] = ctx;
	d->n++;
	return 0;
}
static void free_map(void *p) { free(p); }
static void run_actions(struct device *d)
{
	while (d->n) {
		d->n--;
		d->actions[d->n](d->ctx[d->n]);
	}
}
static void *devm_ioremap_wc(struct device *d, u64 off, u64 size)
{
	if (map_fail)
		return NULL;
	map_off = off;
	map_size = size;
	map_buf = malloc(size);
	assert(map_buf);
	memset(map_buf, 0xaa, size);
	assert(!devm_add_action_or_reset(d, free_map, map_buf));
	return map_buf;
}
static void memset_io(void *p, int c, size_t n) { memset(p, c, n); }
static u32 readl(const void *p)
{
	if (read_fault) {
		read_fault = false;
		return 1;
	}
	return *(const u32 *)p;
}
static void *kzalloc_obj_(size_t n) { return calloc(1, n); }
#define kzalloc_obj(x) kzalloc_obj_(sizeof(x))
#define kfree(p) free(p)
static int sysfs_emit(char *b, const char *fmt, ...)
{
	va_list a;
	int r;
	va_start(a, fmt);
	r = vsnprintf(b, 4096, fmt, a);
	va_end(a);
	return r;
}
static struct nvmem_cell fake_cell;
static struct nvmem_cell *nvmem_cell_get(struct device *d, const char *name)
{
	(void)d;
	assert(!strcmp(name, "external-32k"));
	if (nvmem_get_error)
		return ERR_PTR(nvmem_get_error);
	return nvmem_present ? &fake_cell : ERR_PTR(-ENOENT);
}
static void *nvmem_cell_read(struct nvmem_cell *c, size_t *len)
{
	u8 *p;
	assert(c == &fake_cell);
	if (nvmem_read_error)
		return ERR_PTR(nvmem_read_error);
	p = malloc(1);
	assert(p);
	*p = nvmem_value;
	*len = nvmem_length;
	return p;
}
static void nvmem_cell_put(struct nvmem_cell *c) { assert(c == &fake_cell); }
static bool of_property_present(struct device_node *n, const char *name)
{
	assert(!strcmp(name, "mediatek,no-external-32k"));
	return n && n->no_external_32k;
}

static int deny_dispatch_rearm;
int ccci_ccif_rearm(struct ccci_ccif *c, bool commit)
{ (void)c; note(commit ? 'A' : 'a'); return 0; }
int ccci_port_dispatch_rearm(struct ccci_port_dispatch *d, bool commit)
{ (void)d; note(commit ? 'B' : 'b'); return deny_dispatch_rearm; }
int ccci_ccif_prepare(struct ccci_ccif *c) { (void)c; note('C'); return fail_ccif_prepare; }
int ccci_ccif_stop(struct ccci_ccif *c) { (void)c; note('K'); return fail_ccif_stop; }
int ccci_port_dispatch_prepare(struct ccci_port_dispatch *d, u64 g)
{
	(void)d;
	assert(g == 0x1234 || g == 0x1235);
	note('P');
	return fail_dispatch_prepare;
}
int ccci_port_dispatch_start(struct ccci_port_dispatch *d, const struct ccci_runtime_offer *o)
{
	(void)d;
	assert(o && o[0].supported);
	note('S');
	return fail_dispatch_start;
}
int ccci_port_dispatch_stop(struct ccci_port_dispatch *d, bool s)
{
	(void)d;
	assert(s);
	note('T');
	return fail_dispatch_stop;
}
int ccci_runtime_bootstrap(const struct ccci_smem_layout *smem,
			   const struct ccci_runtime_boot *b,
			   struct ccci_runtime_offer o[CCCI_RUNTIME_FEATURES])
{
	(void)smem;
	assert(b && b->crystal == expect_crystal);
	note('R');
	if (fail_runtime)
		return fail_runtime;
	memset(o, 0, sizeof(*o) * CCCI_RUNTIME_FEATURES);
	o[0].supported = true;
	return 0;
}
void arm_smccc_smc(unsigned long a0, unsigned long a1, unsigned long a2,
		   unsigned long a3, unsigned long a4, unsigned long a5,
		   unsigned long a6, unsigned long a7, struct arm_smccc_res *r)
{
	(void)a3; (void)a4; (void)a5; (void)a6; (void)a7;
	assert(a0 == MTK_SIP_KERNEL_CCCI_CONTROL);
	smc_calls++;
	smc_seen[0] = a0; smc_seen[1] = a1; smc_seen[2] = a2;
	r->a0 = smc_a0; r->a1 = smc_a1; r->a2 = smc_a2; r->a3 = 0;
}

static int fail_smem_clear;
int ccci_smem_clear_first(struct device *dev, const struct ccci_smem_layout *smem)
{
	(void)dev;
	assert(smem);
	note('M');
	return fail_smem_clear;
}

int ccci_smem_clear_restart(const struct ccci_smem_layout *smem)
{
	assert(smem);
	note('D');
	return fail_smem_clear;
}

#include "ccci-nvram-cache.c"
#include "ccci-rtc32k.c"
#include "ccci-md-boot.c"

static void layout_init(struct ccci_smem_layout *l)
{
	struct ccci_smem_region *r = &l->users[CCCI_SMEM_NVRAM];
	memset(l, 0, sizeof(*l));
	l->cached.base = 0x90000000ULL;
	l->cached.size = 0x800000;
	r->present = true;
	r->cached = true;
	r->offset = 0x1000;
	r->ap = l->cached.base + r->offset;
	r->md = 0x40001000;
	r->size = 0x1000;
}
static struct ccci_nvram_cache *new_cache(struct device *dev, struct ccci_smem_layout *l)
{
	struct ccci_nvram_cache *c;
	layout_init(l);
	c = ccci_nvram_cache_create(dev, l);
	assert(!IS_ERR(c));
	return c;
}
static void test_cache(void)
{
	struct device dev = { 0 };
	struct ccci_smem_layout l = { 0 };
	struct ccci_nvram_cache *c;
	char buf[512];
	u32 v;

	assert(IS_ERR(ccci_nvram_cache_create(NULL, &l)));
	assert(IS_ERR(ccci_nvram_cache_create(&dev, NULL)));

	layout_init(&l);
	l.users[CCCI_SMEM_NVRAM].present = false;
	assert(PTR_ERR(ccci_nvram_cache_create(&dev, &l)) == -ERANGE);
	layout_init(&l);
	l.users[CCCI_SMEM_NVRAM].cached = false;
	assert(PTR_ERR(ccci_nvram_cache_create(&dev, &l)) == -ERANGE);
	layout_init(&l);
	l.users[CCCI_SMEM_NVRAM].no_map = true;
	assert(PTR_ERR(ccci_nvram_cache_create(&dev, &l)) == -ERANGE);
	layout_init(&l);
	l.users[CCCI_SMEM_NVRAM].size = 0;
	assert(PTR_ERR(ccci_nvram_cache_create(&dev, &l)) == -ERANGE);
	layout_init(&l);
	l.users[CCCI_SMEM_NVRAM].ap = l.cached.base + 0x2000;
	assert(PTR_ERR(ccci_nvram_cache_create(&dev, &l)) == -ERANGE);
	layout_init(&l);
	l.users[CCCI_SMEM_NVRAM].md = 0xfffff800;
	assert(PTR_ERR(ccci_nvram_cache_create(&dev, &l)) == -ERANGE);
	layout_init(&l);
	l.users[CCCI_SMEM_NVRAM].size = 0x800001;
	assert(PTR_ERR(ccci_nvram_cache_create(&dev, &l)) == -ERANGE);

	c = new_cache(&dev, &l);
	assert(!ccci_nvram_cache_prepared(c));
	assert(!ccci_nvram_cache_offline(c));
	assert(!ccci_nvram_cache_prepare(c));
	assert(ccci_nvram_cache_prepared(c));
	assert(map_off == l.users[CCCI_SMEM_NVRAM].ap);
	assert(map_size == 0x1000);
	for (v = 0; v < map_size; v++)
		assert(map_buf[v] == 0);
	/* A reconnect attempt must not re-zero a live cache. */
	memset(map_buf, 0x5a, map_size);
	assert(ccci_nvram_cache_prepare(c) == -EALREADY);
	assert(map_buf[0] == 0x5a && map_buf[map_size - 1] == 0x5a);
	assert(ccci_nvram_cache_offline(c) == -EBUSY);
	assert(!ccci_nvram_cache_stop(c));
	assert(!ccci_nvram_cache_prepared(c));
	assert(!ccci_nvram_cache_offline(c));
	assert(!ccci_nvram_cache_stop(c));
	assert(ccci_nvram_cache_prepare(c) == -EALREADY);
	assert(ccci_nvram_cache_status(c, buf) > 0);
	assert(strstr(buf, "state=stopped") && strstr(buf, "cleared=1") &&
	       strstr(buf, "size=0x1000"));

	/* Mapping failure latches and blocks later use. */
	c = new_cache(&dev, &l);
	map_fail = true;
	assert(ccci_nvram_cache_prepare(c) == -ENOMEM);
	map_fail = false;
	assert(!ccci_nvram_cache_prepared(c));
	assert(ccci_nvram_cache_offline(c) == -EBUSY);
	assert(ccci_nvram_cache_prepare(c) == -EIO);
	assert(ccci_nvram_cache_stop(c) == -EIO);
	assert(ccci_nvram_cache_status(c, buf) > 0 && strstr(buf, "state=failed"));

	/* Failed read-back also latches instead of claiming a cleared cache. */
	c = new_cache(&dev, &l);
	read_fault = true;
	assert(ccci_nvram_cache_prepare(c) == -EIO);
	assert(!ccci_nvram_cache_prepared(c));
	assert(ccci_nvram_cache_offline(c) == -EBUSY);
	run_actions(&dev);
}

static void test_rtc32k(void)
{
	struct device dev = { 0 };
	struct device_node node = { 0 };
	enum ccci_runtime_crystal crystal;
	enum ccci_rtc32k_source source;

	assert(ccci_rtc32k_read(NULL, &crystal, &source) == -EINVAL);
	assert(ccci_rtc32k_read(&dev, NULL, &source) == -EINVAL);
	assert(ccci_rtc32k_read(&dev, &crystal, NULL) == -EINVAL);

	dev.of_node = &node;
	nvmem_present = true;
	nvmem_value = 0;
	assert(!ccci_rtc32k_read(&dev, &crystal, &source));
	assert(crystal == CCCI_RUNTIME_CRYSTAL_ABSENT && source == CCCI_RTC32K_SOURCE_NVMEM);
	nvmem_value = 1;
	assert(!ccci_rtc32k_read(&dev, &crystal, &source));
	assert(crystal == CCCI_RUNTIME_CRYSTAL_PRESENT && source == CCCI_RTC32K_SOURCE_NVMEM);
	nvmem_length = 0;
	assert(ccci_rtc32k_read(&dev, &crystal, &source) == -ENODATA);
	nvmem_length = 1;
	nvmem_read_error = -EIO;
	assert(ccci_rtc32k_read(&dev, &crystal, &source) == -EIO);
	nvmem_read_error = 0;

	/* Missing cell without an explicit board fact stays unknown. */
	nvmem_present = false;
	assert(ccci_rtc32k_read(&dev, &crystal, &source) == -ENODATA);
	assert(crystal == CCCI_RUNTIME_CRYSTAL_UNKNOWN);
	node.no_external_32k = true;
	assert(!ccci_rtc32k_read(&dev, &crystal, &source));
	assert(crystal == CCCI_RUNTIME_CRYSTAL_ABSENT && source == CCCI_RTC32K_SOURCE_DT);
	node.no_external_32k = false;
	nvmem_get_error = -EPROBE_DEFER;
	assert(ccci_rtc32k_read(&dev, &crystal, &source) == -EPROBE_DEFER);
	nvmem_get_error = 0;
}

struct boot_fixture {
	struct device dev;
	struct ccci_smem_layout layout;
	struct ccci_nvram_cache *cache;
	struct ccci_ccif ccif;
	struct ccci_port_dispatch dispatch;
	struct ccci_md_boot *boot;
};

static void boot_init(struct boot_fixture *f, enum ccci_runtime_crystal crystal)
{
	memset(f, 0, sizeof(*f));
	expect_crystal = crystal;
	logn = 0; order[0] = 0;
	fail_ccif_prepare = fail_ccif_stop = fail_runtime = fail_smem_clear = 0;
	fail_dispatch_prepare = fail_dispatch_start = fail_dispatch_stop = 0;
	smc_calls = 0; smc_a0 = 0; smc_a1 = 0x11; smc_a2 = 0x22;
	f->cache = new_cache(&f->dev, &f->layout);
	f->boot = ccci_md_boot_create(&f->dev, &f->ccif, &f->dispatch, f->cache);
	assert(!IS_ERR(f->boot));
}
static void boot_free(struct boot_fixture *f)
{
	/* LIFO devres unwind: boot owner, mapping, cache owner. */
	run_actions(&f->dev);
}

static void test_boot(void)
{
	struct boot_fixture f;
	char buf[512];
	u32 v;

	assert(IS_ERR(ccci_md_boot_create(NULL, &f.ccif, &f.dispatch, NULL)));
	assert(IS_ERR(ccci_md_boot_create(&f.dev, NULL, &f.dispatch, NULL)));
	assert(IS_ERR(ccci_md_boot_create(&f.dev, &f.ccif, NULL, NULL)));
	assert(IS_ERR(ccci_md_boot_create(&f.dev, &f.ccif, &f.dispatch, NULL)));

	/* Ready gate order and one attempt. */
	boot_init(&f, CCCI_RUNTIME_CRYSTAL_ABSENT);
	assert(!ccci_md_boot_active(f.boot));
	assert(!ccci_md_boot_offline(f.boot));
	assert(ccci_md_boot_prepare(f.boot, &f.layout, 0, CCCI_RUNTIME_CRYSTAL_ABSENT) == -EINVAL);
	assert(ccci_md_boot_prepare(f.boot, NULL, 0x1234, CCCI_RUNTIME_CRYSTAL_ABSENT) == -EINVAL);
	assert(ccci_md_boot_prepare(f.boot, &f.layout, 0x1234, CCCI_RUNTIME_CRYSTAL_ABSENT) == 0);
	assert(!strcmp(order, "CMRP"));
	for (v = 0; v < map_size; v++)
		assert(map_buf[v] == 0);
	assert(ccci_md_boot_active(f.boot));
	assert(ccci_md_boot_offline(f.boot) == -EBUSY);
	assert(ccci_md_boot_prepare(f.boot, &f.layout, 0x1234, CCCI_RUNTIME_CRYSTAL_ABSENT) == -EALREADY);

	assert(ccci_md_boot_release(f.boot) == 0);
	assert(!strcmp(order, "CMRPS"));
	assert(smc_calls == 1);
	assert(smc_seen[1] == 6 && smc_seen[2] == 0);
	assert(ccci_md_boot_release(f.boot) == -EALREADY);

	/* Operator mask: frozen after the attempt, applied before publication. */
	assert(ccci_md_boot_set_feature_mask(f.boot, BIT_ULL(0)) == -EBUSY);
	assert(ccci_md_boot_feature_mask(f.boot) == 0);
	assert(ccci_md_boot_status(f.boot, buf) > 0);
	assert(strstr(buf, "state=released") && strstr(buf, "released=1") &&
	       strstr(buf, "boot_status0=0x11") && strstr(buf, "cpu_release") == NULL);
	assert(strstr(buf, "service_ready=0"));

	/* No software stop evidence: zero actions. */
	assert(ccci_md_boot_stop(f.boot, false) == -EBUSY);
	assert(!strcmp(order, "CMRPS"));
	ccci_md_boot_note_pcm(f.boot, BIT(2));
	assert(ccci_md_boot_status(f.boot, buf) > 0 && strstr(buf, "pcm_md1_sleep=0"));
	ccci_md_boot_note_pcm(f.boot, 0);
	assert(ccci_md_boot_status(f.boot, buf) > 0 && strstr(buf, "pcm_md1_sleep=1"));

	assert(ccci_md_boot_stop(f.boot, true) == 0);
	assert(!strcmp(order, "CMRPST"));
	assert(!ccci_md_boot_active(f.boot));
	assert(!ccci_md_boot_offline(f.boot));
	assert(ccci_md_boot_status(f.boot, buf) > 0 && strstr(buf, "state=stopped"));
	assert(ccci_md_boot_stop(f.boot, true) == 0);
	assert(!strcmp(order, "CMRPST"));
	deny_dispatch_rearm = -EBUSY;
	assert(ccci_md_boot_rearm(f.boot) == -EBUSY);
	assert(!strcmp(order, "CMRPSTab"));
	deny_dispatch_rearm = 0;
	assert(!ccci_md_boot_rearm(f.boot));
	assert(ccci_md_boot_release(f.boot) == -EAGAIN);
	assert(ccci_md_boot_prepare(f.boot, &f.layout, 0x1234,
				    CCCI_RUNTIME_CRYSTAL_ABSENT) == -ESTALE);
	assert(ccci_md_boot_prepare(f.boot, &f.layout, 0x1235,
				    CCCI_RUNTIME_CRYSTAL_ABSENT) == 0);
	assert(!ccci_md_boot_release(f.boot));
	assert(smc_calls == 2);
	assert(!ccci_md_boot_stop(f.boot, true));
	assert(!strcmp(order, "CMRPSTababABCDRPST"));
	boot_free(&f);

	/* The mask reaches publication: exactly the selected offers are dropped. */
	boot_init(&f, CCCI_RUNTIME_CRYSTAL_ABSENT);
	assert(ccci_md_boot_set_feature_mask(f.boot, BIT_ULL(0) | BIT_ULL(27)) == 0);
	assert(ccci_md_boot_feature_mask(f.boot) == (BIT_ULL(0) | BIT_ULL(27)));
	assert(ccci_md_boot_prepare(f.boot, &f.layout, 0x1234, CCCI_RUNTIME_CRYSTAL_ABSENT) == 0);
	assert(!f.boot->offers[0].supported && !f.boot->offers[0].length);
	assert(!f.boot->offers[27].supported);
	boot_free(&f);

	/* Each preparation failure stops at the failing stage. */
	boot_init(&f, CCCI_RUNTIME_CRYSTAL_PRESENT);
	fail_ccif_prepare = -EIO;
	assert(ccci_md_boot_prepare(f.boot, &f.layout, 0x1234, CCCI_RUNTIME_CRYSTAL_PRESENT) == -EIO);
	assert(!strcmp(order, "C"));
	assert(ccci_md_boot_prepare(f.boot, &f.layout, 0x1234, CCCI_RUNTIME_CRYSTAL_PRESENT) == -EIO);
	assert(ccci_md_boot_release(f.boot) == -EAGAIN);
	assert(ccci_md_boot_stop(f.boot, true) == 0);
	assert(!strcmp(order, "C"));
	boot_free(&f);

	boot_init(&f, CCCI_RUNTIME_CRYSTAL_PRESENT);
	fail_runtime = -ENODATA;
	assert(ccci_md_boot_prepare(f.boot, &f.layout, 0x1234, CCCI_RUNTIME_CRYSTAL_PRESENT) == -ENODATA);
	assert(!strcmp(order, "CMR"));
	assert(ccci_md_boot_release(f.boot) == -EAGAIN);
	assert(ccci_md_boot_stop(f.boot, true) == 0);
	assert(!strcmp(order, "CMR"));
	boot_free(&f);

	boot_init(&f, CCCI_RUNTIME_CRYSTAL_PRESENT);
	fail_dispatch_prepare = -ENOTCONN;
	assert(ccci_md_boot_prepare(f.boot, &f.layout, 0x1234, CCCI_RUNTIME_CRYSTAL_PRESENT) == -ENOTCONN);
	assert(!strcmp(order, "CMRP"));
	assert(ccci_md_boot_stop(f.boot, true) == 0);
	assert(!strcmp(order, "CMRP"));
	boot_free(&f);

	/* SMC failures are not reported as a release. */
	boot_init(&f, CCCI_RUNTIME_CRYSTAL_ABSENT);
	smc_a0 = SMCCC_RET_NOT_SUPPORTED;
	assert(ccci_md_boot_prepare(f.boot, &f.layout, 0x1234, CCCI_RUNTIME_CRYSTAL_ABSENT) == 0);
	assert(ccci_md_boot_release(f.boot) == -EOPNOTSUPP);
	assert(ccci_md_boot_status(f.boot, buf) > 0 && strstr(buf, "state=failed"));
	assert(ccci_md_boot_release(f.boot) == -EAGAIN);
	assert(ccci_md_boot_stop(f.boot, true) == 0);
	boot_free(&f);

	boot_init(&f, CCCI_RUNTIME_CRYSTAL_ABSENT);
	smc_a0 = 5;
	assert(ccci_md_boot_prepare(f.boot, &f.layout, 0x1234, CCCI_RUNTIME_CRYSTAL_ABSENT) == 0);
	assert(ccci_md_boot_release(f.boot) == -EIO);
	assert(ccci_md_boot_status(f.boot, buf) > 0 && strstr(buf, "boot_ret=5"));
	assert(ccci_md_boot_stop(f.boot, true) == 0);
	boot_free(&f);
}

int main(void)
{
	test_cache();
	test_rtc32k();
	test_boot();
	return 0;
}
'''


def main():
    with tempfile.TemporaryDirectory(prefix='op6893-md-boot-') as directory:
        root = Path(directory)
        inc = root / 'linux'
        (inc / 'soc' / 'mediatek').mkdir(parents=True)
        files = {
            'types.h': '#pragma once\n#include <stdint.h>\n#include <stdbool.h>\n'
                       '#include <stddef.h>\ntypedef uint8_t u8;typedef uint16_t u16;'
                       'typedef uint32_t u32;typedef uint64_t u64;typedef int32_t s32;\n',
            'errno.h': '#include <asm-generic/errno.h>\n',
            'kconfig.h': '#pragma once\n#define IS_ENABLED(x) (x)\n',
            'kernel.h': '#pragma once\n#include <linux/types.h>\n',
            'mutex.h': '',
            'slab.h': '',
            'io.h': '',
            'device.h': '',
            'sysfs.h': '',
            'arm-smccc.h': '',
            'of.h': '',
            'nvmem-consumer.h': '',
        }
        for name, data in files.items():
            (inc / name).write_text(data)
        (inc / 'soc' / 'mediatek' / 'mtk_sip_svc.h').write_text('')
        (root / 'test.c').write_text(TEST)
        subprocess.run(['cc', '-O1', '-g', '-Wall', '-Wextra', '-Werror',
                        '-Wno-misleading-indentation', '-fsanitize=address,undefined',
                        '-fno-sanitize-recover=all', '-no-pie', '-I' + str(root),
                        '-I' + str(SRC), str(root / 'test.c'), '-o', str(root / 'test')],
                       check=True)
        subprocess.run([str(root / 'test')], check=True)


if __name__ == '__main__':
    main()
