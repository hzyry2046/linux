// SPDX-License-Identifier: GPL-2.0-only
/* Unique MD boot owner: gated preparation and one explicit CPU release. */
#include <linux/arm-smccc.h>
#include <linux/device.h>
#include <linux/errno.h>
#include <linux/kernel.h>
#include <linux/mutex.h>
#include <linux/slab.h>
#include <linux/soc/mediatek/mtk_sip_svc.h>
#include <linux/sysfs.h>

#include "ccci-ccif.h"
#include "ccci-md-boot.h"
#include "ccci-nvram-cache.h"
#include "ccci-port-dispatch.h"
#include "ccci-runtime.h"
#include "ccci-smem.h"

#define MD_POWER_CONFIG		6
#define MD_KERNEL_BOOT_UP	0
#define SPM_PCM_REG13_MD1_SLEEP	BIT(2)

enum boot_state {
	BOOT_IDLE,
	BOOT_PREPARED,
	BOOT_RELEASED,
	BOOT_STOPPED,
	BOOT_FAILED,
};

struct ccci_md_boot {
	/* Parent lifecycle lock; no callback re-enters this owner. */
	struct mutex lock;
	struct ccci_ccif *ccif;
	struct ccci_port_dispatch *dispatch;
	struct ccci_nvram_cache *cache;
	struct ccci_runtime_offer offers[CCCI_RUNTIME_FEATURES];
	u64 generation;
	enum boot_state state;
	enum ccci_runtime_crystal crystal;
	int error;
	bool attempted;
	bool released;
	bool cache_prepared;
	bool dispatch_prepared;
	u32 boot_ret;
	u32 boot_status0;
	u32 boot_status1;
	u32 pcm_r13;
	bool pcm_sampled;
};

static int boot_fault(struct ccci_md_boot *boot, int error)
{
	boot->state = BOOT_FAILED;
	boot->error = error;
	return error;
}

int ccci_md_boot_prepare(struct ccci_md_boot *boot, const struct ccci_smem_layout *smem,
			 u64 generation, enum ccci_runtime_crystal crystal)
{
	struct ccci_runtime_boot info = { .crystal = crystal };
	int ret;

	if (!boot || !smem || !generation)
		return -EINVAL;
	mutex_lock(&boot->lock);
	if (boot->state == BOOT_FAILED) {
		ret = -EIO;
		goto out;
	}
	if (boot->attempted) {
		ret = -EALREADY;
		goto out;
	}
	boot->attempted = true;
	boot->generation = generation;
	boot->crystal = crystal;
	/* Vendor normal boot, MODE_IDLE logging: (0 << 8) | NORMAL_BOOT_ID. */
	info.booting_start_id = 0;
	ret = ccci_ccif_prepare(boot->ccif);
	if (!ret)
		ret = ccci_nvram_cache_prepare(boot->cache);
	if (!ret)
		boot->cache_prepared = true;
	if (!ret)
		ret = ccci_runtime_bootstrap(smem, &info, boot->offers);
	if (!ret)
		ret = ccci_port_dispatch_prepare(boot->dispatch, generation);
	if (!ret)
		boot->dispatch_prepared = true;
	if (ret) {
		boot_fault(boot, ret);
		goto out;
	}
	boot->state = BOOT_PREPARED;
out:
	mutex_unlock(&boot->lock);
	return ret;
}

int ccci_md_boot_release(struct ccci_md_boot *boot)
{
	struct arm_smccc_res res;
	int ret;

	if (!boot)
		return -EINVAL;
	mutex_lock(&boot->lock);
	if (boot->state != BOOT_PREPARED) {
		ret = boot->state == BOOT_RELEASED ? -EALREADY : -EAGAIN;
		goto out;
	}
	/* RX/handshake must accept the first SRAM HS1 before MD runs. */
	ret = ccci_port_dispatch_start(boot->dispatch, boot->offers);
	if (ret) {
		boot_fault(boot, ret);
		goto out;
	}
	arm_smccc_smc(MTK_SIP_KERNEL_CCCI_CONTROL, MD_POWER_CONFIG, MD_KERNEL_BOOT_UP,
		      0, 0, 0, 0, 0, &res);
	boot->boot_ret = res.a0;
	boot->boot_status0 = res.a1;
	boot->boot_status1 = res.a2;
	if (res.a0 == SMCCC_RET_NOT_SUPPORTED) {
		ret = boot_fault(boot, -EOPNOTSUPP);
		goto out;
	}
	if (res.a0) {
		ret = boot_fault(boot, -EIO);
		goto out;
	}
	boot->released = true;
	boot->state = BOOT_RELEASED;
	ret = 0;
out:
	mutex_unlock(&boot->lock);
	return ret;
}

int ccci_md_boot_stop(struct ccci_md_boot *boot, bool md_stopped)
{
	int ret;

	if (!boot)
		return 0;
	if (!md_stopped)
		return -EBUSY;
	mutex_lock(&boot->lock);
	if (!boot->attempted || boot->state == BOOT_STOPPED) {
		ret = 0;
		goto out;
	}
	/* CCIF was already reset before power-off; this joins services and SCP. */
	ret = boot->dispatch_prepared ? ccci_port_dispatch_stop(boot->dispatch, true) : 0;
	if (!ret && boot->cache_prepared)
		ret = ccci_nvram_cache_stop(boot->cache);
	if (!ret)
		boot->state = BOOT_STOPPED;
out:
	mutex_unlock(&boot->lock);
	return ret;
}

int ccci_md_boot_offline(struct ccci_md_boot *boot)
{
	int ret;

	if (!boot)
		return 0;
	mutex_lock(&boot->lock);
	ret = boot->attempted && boot->state != BOOT_STOPPED ? -EBUSY : 0;
	mutex_unlock(&boot->lock);
	return ret;
}

bool ccci_md_boot_active(struct ccci_md_boot *boot)
{
	bool ret;

	if (!boot)
		return false;
	mutex_lock(&boot->lock);
	ret = boot->attempted && boot->state != BOOT_STOPPED;
	mutex_unlock(&boot->lock);
	return ret;
}

void ccci_md_boot_note_pcm(struct ccci_md_boot *boot, u32 r13)
{
	if (!boot)
		return;
	mutex_lock(&boot->lock);
	boot->pcm_r13 = r13;
	boot->pcm_sampled = true;
	mutex_unlock(&boot->lock);
}

ssize_t ccci_md_boot_status(struct ccci_md_boot *boot, char *buf)
{
	static const char * const states[] = {
		"idle", "prepared", "released", "stopped", "failed"
	};
	ssize_t ret;

	if (!boot)
		return -EOPNOTSUPP;
	mutex_lock(&boot->lock);
	ret = sysfs_emit(buf,
			 "state=%s generation=%llu attempted=%u released=%u crystal=%u boot_ret=%u boot_status0=0x%x boot_status1=0x%x pcm_sampled=%u pcm_md1_sleep=%u error=%d service_ready=0\n",
			 states[boot->state], boot->generation, boot->attempted,
			 boot->released, boot->crystal, boot->boot_ret,
			 boot->boot_status0, boot->boot_status1, boot->pcm_sampled,
			 boot->pcm_sampled && !(boot->pcm_r13 & SPM_PCM_REG13_MD1_SLEEP),
			 boot->error);
	mutex_unlock(&boot->lock);
	return ret;
}

static void boot_cleanup(void *context)
{
	struct ccci_md_boot *boot = context;

	/* No callback holds this owner; active removal still has no caller. */
	kfree(boot);
}

struct ccci_md_boot *
ccci_md_boot_create(struct device *dev, struct ccci_ccif *ccif,
		    struct ccci_port_dispatch *dispatch,
		    struct ccci_nvram_cache *cache)
{
	struct ccci_md_boot *boot;
	int ret;

	if (!dev || !ccif || !dispatch || !cache)
		return ERR_PTR(-EINVAL);
	boot = kzalloc_obj(*boot);
	if (!boot)
		return ERR_PTR(-ENOMEM);
	mutex_init(&boot->lock);
	boot->ccif = ccif;
	boot->dispatch = dispatch;
	boot->cache = cache;
	ret = devm_add_action_or_reset(dev, boot_cleanup, boot);
	if (ret)
		return ERR_PTR(ret);
	return boot;
}
