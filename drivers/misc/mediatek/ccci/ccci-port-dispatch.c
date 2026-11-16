// SPDX-License-Identifier: GPL-2.0-only
/* Accepted control transitions and normal ports; no CPU-release caller. */
#include <linux/bitops.h>
#include <linux/device.h>
#include <linux/err.h>
#include <linux/mutex.h>
#include <linux/slab.h>
#include <linux/spinlock.h>
#include <linux/sysfs.h>
#include <linux/workqueue.h>

#include "ccci-ccif.h"
#include "ccci-ccism.h"
#include "ccci-ccism-bridge.h"
#include "ccci-port-dispatch.h"
#include "ccci-service-endpoint.h"

enum dispatch_state {
	DISPATCH_IDLE,
	DISPATCH_PREPARED,
	DISPATCH_WAIT_HS1,
	DISPATCH_WAIT_HS2,
	DISPATCH_HS2,
	DISPATCH_STOPPING,
	DISPATCH_STOPPED,
	DISPATCH_FAILED,
};

struct ccci_port_dispatch {
	/* Parent lock may nest this mutex, callbacks never take the parent lock. */
	struct mutex lock;
	/* Control fault callbacks only latch and enqueue; no mutex or I/O. */
	spinlock_t fault_lock;
	struct work_struct fault_work;
	struct ccci_ccif *ccif;
	struct ccci_ccism_bridge *bridge;
	struct ccci_service_endpoint *endpoint;
	u64 generation;
	enum dispatch_state state;
	int error;
	bool attempted;
	bool fault_closed;
};

static void dispatch_fault(void *context, int error)
{
	struct ccci_port_dispatch *dispatch = context;
	unsigned long flags;

	spin_lock_irqsave(&dispatch->fault_lock, flags);
	if (!dispatch->error)
		dispatch->error = error < 0 ? error : -EIO;
	schedule_work(&dispatch->fault_work);
	spin_unlock_irqrestore(&dispatch->fault_lock, flags);
}

static void dispatch_fault_work(struct work_struct *work)
{
	struct ccci_port_dispatch *dispatch =
		container_of(work, struct ccci_port_dispatch, fault_work);

	mutex_lock(&dispatch->lock);
	if (dispatch->state != DISPATCH_STOPPED && !dispatch->fault_closed) {
		dispatch->state = DISPATCH_FAILED;
		dispatch->fault_closed = true;
		ccci_service_endpoint_abort(dispatch->endpoint, dispatch->generation,
					    READ_ONCE(dispatch->error));
		ccci_ccif_abort(dispatch->ccif, READ_ONCE(dispatch->error));
	}
	mutex_unlock(&dispatch->lock);
}

/* Called only by the real controller after its wire/state validation. */
static int dispatch_port(void *context, const struct ccci_ccif_event *event)
{
	struct ccci_port_dispatch *dispatch = context;
	struct ccci_ccif_header header;
	int ret;

	mutex_lock(&dispatch->lock);
	ret = READ_ONCE(dispatch->error);
	if (ret)
		goto out;
	if (dispatch->state < DISPATCH_WAIT_HS1 || dispatch->state > DISPATCH_HS2) {
		ret = -ESHUTDOWN;
		goto out;
	}
	if (!event) {
		ret = -EINVAL;
		goto out;
	}
	if (event->type == CCCI_CCIF_EVENT_NOTIFY) {
		ret = event->notifications & ~BIT(7) ? -EREMOTEIO : 0;
		goto out;
	}
	ret = ccci_ccif_header_decode(event->data, event->size, &header);
	if (ret)
		goto out;
	if (event->type == CCCI_CCIF_EVENT_SRAM) {
		if (dispatch->state != DISPATCH_WAIT_HS1 ||
		    event->size != CCCI_CCIF_HS1_SIZE ||
		    ccci_ccif_control_decode(&header) != CCCI_CCIF_CONTROL_HS1) {
			ret = -EPROTO;
			goto out;
		}
		/* Publication is complete before the controller forwards this event. */
		ret = ccci_service_endpoint_arm(dispatch->endpoint, dispatch->generation);
		if (!ret)
			dispatch->state = DISPATCH_WAIT_HS2;
		goto out;
	}
	if (event->type != CCCI_CCIF_EVENT_RING) {
		ret = -EPROTO;
		goto out;
	}
	if (!header.channel) {
		if (dispatch->state != DISPATCH_WAIT_HS2 || event->queue ||
		    event->size != CCCI_CCIF_HEADER_SIZE ||
		    ccci_ccif_control_decode(&header) != CCCI_CCIF_CONTROL_HS2) {
			ret = -EPROTO;
			goto out;
		}
		ret = ccci_service_endpoint_hs2(dispatch->endpoint, dispatch->generation);
		if (!ret)
			ret = ccci_ccism_bridge_port(dispatch->bridge, event);
		if (!ret)
			dispatch->state = DISPATCH_HS2;
	} else if (header.channel == CCCI_FS_RX || header.channel == CCCI_RPC_RX) {
		ret = dispatch->state == DISPATCH_WAIT_HS1 ? -EPROTO :
			ccci_service_endpoint_receive(dispatch->endpoint,
						      dispatch->generation, event);
	} else if (header.channel == 2 && dispatch->state == DISPATCH_HS2) {
		ret = ccci_ccism_bridge_port(dispatch->bridge, event);
	} else {
		/* No silent consumption or fake reply for an unimplemented port. */
		ret = -EOPNOTSUPP;
	}
out:
	if (ret)
		dispatch_fault(dispatch, ret);
	mutex_unlock(&dispatch->lock);
	return ret;
}

int ccci_port_dispatch_prepare(struct ccci_port_dispatch *dispatch, u64 generation)
{
	int ret;

	if (!dispatch || !generation)
		return -EINVAL;
	mutex_lock(&dispatch->lock);
	if (dispatch->attempted) {
		ret = -EALREADY;
		goto out;
	}
	dispatch->attempted = true;
	dispatch->generation = generation;
	ret = ccci_service_endpoint_reserve(dispatch->endpoint, generation);
	if (!ret)
		ret = ccci_ccism_bridge_arm(dispatch->bridge);
	if (!ret)
		dispatch->state = DISPATCH_PREPARED;
	else
		dispatch_fault(dispatch, ret);
out:
	mutex_unlock(&dispatch->lock);
	return ret;
}

int ccci_port_dispatch_start(struct ccci_port_dispatch *dispatch,
			     const struct ccci_runtime_offer *offers)
{
	int ret;

	mutex_lock(&dispatch->lock);
	ret = READ_ONCE(dispatch->error);
	if (!ret && dispatch->state != DISPATCH_PREPARED)
		ret = -EAGAIN;
	if (!ret)
		dispatch->state = DISPATCH_WAIT_HS1;
	mutex_unlock(&dispatch->lock);
	if (ret)
		return ret;
	/* Never nest dispatch->lock outside the controller's lock. */
	ret = ccci_ccif_set_fault(dispatch->ccif, dispatch_fault, dispatch);
	if (!ret)
		ret = ccci_ccif_handshake_start(dispatch->ccif, offers, dispatch_port, dispatch);
	if (ret)
		dispatch_fault(dispatch, ret);
	return ret;
}

int ccci_port_dispatch_stop(struct ccci_port_dispatch *dispatch, bool md_stopped)
{
	int ret;

	if (!md_stopped)
		return -EBUSY;
	/* Parent serializes lifecycle; no dispatch mutex while joining callbacks. */
	ret = ccci_ccif_stop(dispatch->ccif);
	if (ret)
		return ret;
	cancel_work_sync(&dispatch->fault_work);
	mutex_lock(&dispatch->lock);
	dispatch->state = DISPATCH_STOPPING;
	mutex_unlock(&dispatch->lock);
	ret = ccci_service_endpoint_stop(dispatch->endpoint, true);
	if (!ret)
		ret = ccci_ccism_bridge_stop(dispatch->bridge, true);
	if (!ret)
		ret = ccci_ccism_bridge_offline(dispatch->bridge);
	mutex_lock(&dispatch->lock);
	if (!ret)
		dispatch->state = DISPATCH_STOPPED;
	mutex_unlock(&dispatch->lock);
	return ret;
}

int ccci_port_dispatch_offline(struct ccci_port_dispatch *dispatch)
{
	int ret;

	if (!dispatch)
		return 0;
	mutex_lock(&dispatch->lock);
	ret = dispatch->attempted && dispatch->state != DISPATCH_STOPPED ? -EBUSY : 0;
	mutex_unlock(&dispatch->lock);
	return ret;
}

ssize_t ccci_port_dispatch_status(struct ccci_port_dispatch *dispatch, char *buf)
{
	ssize_t ret;

	if (!dispatch)
		return -EOPNOTSUPP;
	mutex_lock(&dispatch->lock);
	ret = sysfs_emit(buf,
			 "state=%u generation=%llu error=%d attempted=%u cpu_release_issued=0 service_ready=0\n",
			 dispatch->state, dispatch->generation, READ_ONCE(dispatch->error),
			 dispatch->attempted);
	mutex_unlock(&dispatch->lock);
	return ret;
}

static void dispatch_cleanup(void *context)
{
	struct ccci_port_dispatch *dispatch = context;

	/* Built-in, dormant unwind only; active unbind is not supported. */
	if (WARN_ON(ccci_port_dispatch_offline(dispatch)))
		return;
	cancel_work_sync(&dispatch->fault_work);
	kfree(dispatch);
}

struct ccci_port_dispatch *
ccci_port_dispatch_create(struct device *dev, struct ccci_ccif *ccif,
			  struct ccci_ccism_bridge *bridge,
			  struct ccci_service_endpoint *endpoint)
{
	struct ccci_port_dispatch *dispatch;
	int ret;

	if (!dev || !ccif || !bridge || !endpoint)
		return ERR_PTR(-EINVAL);
	dispatch = kzalloc_obj(*dispatch);
	if (!dispatch)
		return ERR_PTR(-ENOMEM);
	mutex_init(&dispatch->lock);
	spin_lock_init(&dispatch->fault_lock);
	INIT_WORK(&dispatch->fault_work, dispatch_fault_work);
	dispatch->ccif = ccif;
	dispatch->bridge = bridge;
	dispatch->endpoint = endpoint;
	ret = devm_add_action_or_reset(dev, dispatch_cleanup, dispatch);
	if (ret)
		return ERR_PTR(ret);
	return dispatch;
}
