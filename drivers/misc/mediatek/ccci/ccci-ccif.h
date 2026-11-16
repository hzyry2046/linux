/* SPDX-License-Identifier: GPL-2.0-only */
#ifndef __CCCI_CCIF_H
#define __CCCI_CCIF_H

#include <linux/types.h>
#include <linux/kconfig.h>
#include <linux/errno.h>

#include "ccci-ccif-rx.h"

struct platform_device;
struct ccci_smem_layout;
struct regmap;
struct ccci_ccif;
struct ccci_runtime_offer;

#if IS_ENABLED(CONFIG_OP6893_CCCI_CCIF)
struct ccci_ccif *ccci_ccif_create(struct platform_device *pdev,
				   const struct ccci_smem_layout *smem, struct regmap *infra);
/* Owner mutex held; powered domain, clocks held, MD CPU not released. */
int ccci_ccif_prepare(struct ccci_ccif *ccif);
/* Same power/lifecycle lock; callback restrictions are in ccci-ccif-rx.h. */
int ccci_ccif_receive_start(struct ccci_ccif *ccif, ccci_ccif_consume_fn consume, void *context);
/* MD CPU stopped; caller must establish real SCP/service prerequisites first. */
int ccci_ccif_handshake_start(struct ccci_ccif *ccif, const struct ccci_runtime_offer *offers,
			      ccci_ccif_consume_fn port, void *context);
ssize_t ccci_ccif_handshake_status(struct ccci_ccif *ccif, char *buf);
int ccci_ccif_stop(struct ccci_ccif *ccif);
ssize_t ccci_ccif_status(struct ccci_ccif *ccif, char *buf);
#else
static inline struct ccci_ccif *ccci_ccif_create(struct platform_device *pdev,
						 const struct ccci_smem_layout *smem,
						 struct regmap *infra)
{
	return NULL;
}

static inline int ccci_ccif_prepare(struct ccci_ccif *ccif) { return -EOPNOTSUPP; }
static inline int ccci_ccif_receive_start(struct ccci_ccif *ccif,
					  ccci_ccif_consume_fn consume, void *context)
{
	return -EOPNOTSUPP;
}

static inline int ccci_ccif_handshake_start(struct ccci_ccif *ccif,
					    const struct ccci_runtime_offer *offers,
					    ccci_ccif_consume_fn port, void *context)
{
	return -EOPNOTSUPP;
}

static inline ssize_t ccci_ccif_handshake_status(struct ccci_ccif *ccif, char *buf)
{
	return -EOPNOTSUPP;
}

static inline int ccci_ccif_stop(struct ccci_ccif *ccif) { return -EOPNOTSUPP; }
static inline ssize_t ccci_ccif_status(struct ccci_ccif *ccif, char *buf)
{
	return -EOPNOTSUPP;
}
#endif

#endif
