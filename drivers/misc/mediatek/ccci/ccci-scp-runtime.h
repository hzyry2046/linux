/* SPDX-License-Identifier: GPL-2.0-only */
#ifndef __CCCI_SCP_RUNTIME_H
#define __CCCI_SCP_RUNTIME_H

#include <linux/completion.h>
#include <linux/mutex.h>
#include <linux/workqueue.h>
#include "ccci-scp-awake.h"

struct ccci_scp_resource_owner;
struct platform_device;
struct device_attribute;

struct ccci_scp_runtime {
	/* Outer lifecycle lock; never acquired by the receive callback. */
	struct mutex control;
	struct completion ready_event;
	struct work_struct fault_work;
	struct ccci_scp_resource_owner *owner;
	struct ccci_scp_awake awake;
	u32 gpr[2];
	u32 logger_events;
	u32 other_events;
	u32 apccci_events;
	u32 apccci_state;
	u32 awake_pairs;
	u32 tx_completed;
	int error;
	int cleanup_error;
	bool active;
	bool ready;
	bool saved;
	bool closing;
};

int ccci_scp_runtime_create(struct platform_device *pdev,
			    struct ccci_scp_resource_owner *owner);
extern struct device_attribute dev_attr_runtime;
extern struct device_attribute dev_attr_runtime_state;

#endif
