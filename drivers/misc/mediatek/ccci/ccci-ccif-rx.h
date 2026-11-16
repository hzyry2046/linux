/* SPDX-License-Identifier: GPL-2.0-only */
#ifndef __CCCI_CCIF_RX_H
#define __CCCI_CCIF_RX_H

#include <linux/types.h>

#include "ccci-ccif-protocol.h"

struct device;
struct ccci_ccif_ring;
struct ccci_ccif_rx;

enum ccci_ccif_event_type {
	CCCI_CCIF_EVENT_SRAM,
	CCCI_CCIF_EVENT_RING,
	CCCI_CCIF_EVENT_NOTIFY,
};

struct ccci_ccif_event {
	enum ccci_ccif_event_type type;
	struct ccci_ccif_header header;
	const void *data;
	u32 size;
	u32 queue;
	u32 notifications;
};

/*
 * Serialized sleepable worker callback. Copy data before returning zero.
 * Any error contains the receiver; there is no implicit drop or retry.
 * Must not take the MD owner's mutex or call start/stop: stop waits for it
 * while holding that mutex. It may enqueue work with its own lifetime rules.
 */
typedef int (*ccci_ccif_consume_fn)(void *context, const struct ccci_ccif_event *event);

/* No I/O, IRQ requests or enables. IRQ actions remain in the CCIF owner. */
struct ccci_ccif_rx *ccci_ccif_rx_create(struct device *dev, void __iomem *ap,
					 struct ccci_ccif_ring *rings, const int irq[2]);
void ccci_ccif_rx_interrupt(struct ccci_ccif_rx *rx, int irq);
/* Caller serializes lifecycle, holds powered domain/clocks until stop returns. */
int ccci_ccif_rx_start(struct ccci_ccif_rx *rx, ccci_ccif_consume_fn consume, void *context);
void ccci_ccif_rx_stop(struct ccci_ccif_rx *rx);
int ccci_ccif_rx_error(struct ccci_ccif_rx *rx);
bool ccci_ccif_rx_armed(struct ccci_ccif_rx *rx);

#endif
