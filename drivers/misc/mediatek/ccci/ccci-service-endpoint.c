// SPDX-License-Identifier: GPL-2.0-only
/* Experimental leased backend; opening it never advertises modem readiness. */
#include <linux/capability.h>
#include <linux/device.h>
#include <linux/fs.h>
#include <linux/kref.h>
#include <linux/miscdevice.h>
#include <linux/mutex.h>
#include <linux/poll.h>
#include <linux/slab.h>
#include <linux/spinlock.h>
#include <linux/sysfs.h>
#include <linux/uaccess.h>
#include <linux/unaligned.h>
#include <linux/vmalloc.h>

#include "ccci-service-endpoint.h"

struct endpoint_request {
	u64 token;
	u32 length;
	bool pending;
	bool delivered;
	bool replied;
	u8 packet[CCCI_FS_MESSAGE_MAX];
};

struct ccci_service_endpoint {
	struct miscdevice misc;
	struct kref refs;
	/* fops/lifecycle only; backend callbacks never take this mutex. */
	struct mutex lock;
	/* Protects request copies, connection admission and fault scalars. */
	spinlock_t queue_lock;
	wait_queue_head_t wait;
	struct ccci_service_session *session;
	struct endpoint_request requests[CCCI_SERVICE_SLOTS];
	u64 generation;
	u32 pending;
	u32 cursor;
	int error;
	bool connected;
	bool armed;
	bool removed;
};

static void endpoint_free(struct kref *refs)
{
	struct ccci_service_endpoint *endpoint =
		container_of(refs, struct ccci_service_endpoint, refs);

	kfree(endpoint->misc.name);
	kvfree_sensitive(endpoint, sizeof(*endpoint));
}

static int endpoint_index(enum ccci_service_kind kind, u32 slot)
{
	if (kind == CCCI_SERVICE_FS && slot < CCCI_FS_SLOTS)
		return slot;
	if (kind == CCCI_SERVICE_RPC && slot < CCCI_SERVICE_RPC_SLOTS)
		return CCCI_FS_SLOTS + slot;
	return -EINVAL;
}

static int endpoint_submit(void *context, u64 generation, u64 token,
			   enum ccci_service_kind kind, u32 slot,
			   const void *packet, size_t length)
{
	struct ccci_service_endpoint *endpoint = context;
	struct endpoint_request *request;
	unsigned long flags;
	int index = endpoint_index(kind, slot), ret = 0;

	if (index < 0 || !packet || length > CCCI_FS_MESSAGE_MAX)
		return -EINVAL;
	spin_lock_irqsave(&endpoint->queue_lock, flags);
	if (endpoint->removed || !endpoint->connected || !endpoint->armed) {
		ret = -EPIPE;
	} else if (generation != endpoint->generation) {
		ret = -ESTALE;
	} else if (endpoint->error) {
		ret = endpoint->error;
	} else {
		request = &endpoint->requests[index];
		if (request->pending || (request->delivered && !request->replied)) {
			ret = -EBUSY;
		} else {
			memzero_explicit(request, sizeof(*request));
			memcpy(request->packet, packet, length);
			request->length = length;
			request->token = token;
			request->pending = true;
			endpoint->pending++;
		}
	}
	spin_unlock_irqrestore(&endpoint->queue_lock, flags);
	wake_up_interruptible(&endpoint->wait);
	return ret;
}

static void endpoint_fault(void *context, u64 generation, int error)
{
	struct ccci_service_endpoint *endpoint = context;
	unsigned long flags;

	spin_lock_irqsave(&endpoint->queue_lock, flags);
	if (generation == endpoint->generation && !endpoint->error)
		endpoint->error = error;
	spin_unlock_irqrestore(&endpoint->queue_lock, flags);
	wake_up_interruptible(&endpoint->wait);
}

static void endpoint_closing(void *context, u64 generation)
{
	struct ccci_service_endpoint *endpoint = context;
	unsigned long flags;

	/* The session gate is already closed; this joins all read/write calls. */
	mutex_lock(&endpoint->lock);
	spin_lock_irqsave(&endpoint->queue_lock, flags);
	endpoint->armed = false;
	endpoint->error = endpoint->error ?: -ESHUTDOWN;
	endpoint->pending = 0;
	memzero_explicit(endpoint->requests, sizeof(endpoint->requests));
	spin_unlock_irqrestore(&endpoint->queue_lock, flags);
	mutex_unlock(&endpoint->lock);
	wake_up_interruptible(&endpoint->wait);
}

static const struct ccci_service_backend_ops endpoint_ops = {
	.submit = endpoint_submit,
	.fault = endpoint_fault,
	.closing = endpoint_closing,
};

static int endpoint_open(struct inode *inode, struct file *file)
{
	struct ccci_service_endpoint *endpoint =
		container_of(file->private_data, struct ccci_service_endpoint, misc);
	unsigned long flags;
	int ret = 0;

	if (!capable(CAP_SYS_RAWIO))
		return -EPERM;
	mutex_lock(&endpoint->lock);
	spin_lock_irqsave(&endpoint->queue_lock, flags);
	if (endpoint->removed) {
		ret = -ENODEV;
	} else if (endpoint->connected || endpoint->armed || endpoint->error) {
		ret = -EBUSY;
	} else {
		endpoint->connected = true;
		kref_get(&endpoint->refs);
		file->private_data = endpoint;
	}
	spin_unlock_irqrestore(&endpoint->queue_lock, flags);
	mutex_unlock(&endpoint->lock);
	return ret;
}

static int endpoint_release(struct inode *inode, struct file *file)
{
	struct ccci_service_endpoint *endpoint = file->private_data;
	unsigned long flags;
	bool armed;
	u64 generation;

	mutex_lock(&endpoint->lock);
	spin_lock_irqsave(&endpoint->queue_lock, flags);
	endpoint->connected = false;
	armed = endpoint->armed;
	generation = endpoint->generation;
	if (armed && !endpoint->error)
		endpoint->error = -EPIPE;
	spin_unlock_irqrestore(&endpoint->queue_lock, flags);
	if (armed && !endpoint->removed)
		ccci_service_session_abort(endpoint->session, generation, -EPIPE);
	mutex_unlock(&endpoint->lock);
	wake_up_interruptible(&endpoint->wait);
	kref_put(&endpoint->refs, endpoint_free);
	return 0;
}

static bool endpoint_readable(struct ccci_service_endpoint *endpoint)
{
	return READ_ONCE(endpoint->pending) || READ_ONCE(endpoint->error) ||
		READ_ONCE(endpoint->removed);
}

static ssize_t endpoint_read(struct file *file, char __user *buffer,
			     size_t count, loff_t *offset)
{
	struct ccci_service_endpoint *endpoint = file->private_data;
	struct endpoint_request *request;
	unsigned long flags;
	u8 *record;
	u32 i, index = 0, length = 0;
	ssize_t ret;

	record = kvmalloc(CCCI_SERVICE_RECORD_HEADER + CCCI_FS_MESSAGE_MAX, GFP_KERNEL);
	if (!record)
		return -ENOMEM;
	for (;;) {
		mutex_lock(&endpoint->lock);
		spin_lock_irqsave(&endpoint->queue_lock, flags);
		ret = endpoint->removed ? -ENODEV : endpoint->error;
		if (!ret && endpoint->pending) {
			for (i = 0; i < CCCI_SERVICE_SLOTS; i++) {
				index = (endpoint->cursor + i) % CCCI_SERVICE_SLOTS;
				if (endpoint->requests[index].pending)
					break;
			}
			request = &endpoint->requests[index];
			length = CCCI_SERVICE_RECORD_HEADER + request->length;
			if (count < length) {
				ret = -EMSGSIZE;
			} else {
				put_unaligned_le32(CCCI_SERVICE_RECORD_VERSION, record);
				put_unaligned_le32(index < CCCI_FS_SLOTS ? CCCI_SERVICE_FS :
						   CCCI_SERVICE_RPC, record + 4);
				put_unaligned_le64(endpoint->generation, record + 8);
				put_unaligned_le64(request->token, record + 16);
				put_unaligned_le32(index < CCCI_FS_SLOTS ? index :
						   index - CCCI_FS_SLOTS, record + 24);
				put_unaligned_le32(request->length, record + 28);
				memcpy(record + CCCI_SERVICE_RECORD_HEADER,
				       request->packet, request->length);
			}
		}
		spin_unlock_irqrestore(&endpoint->queue_lock, flags);
		if (ret || length)
			break;
		mutex_unlock(&endpoint->lock);
		if (file->f_flags & O_NONBLOCK) {
			ret = -EAGAIN;
			goto free;
		}
		ret = wait_event_interruptible(endpoint->wait, endpoint_readable(endpoint));
		if (ret)
			goto free;
	}
	if (!ret) {
		if (copy_to_user(buffer, record, length)) {
			ret = -EFAULT;
		} else {
			spin_lock_irqsave(&endpoint->queue_lock, flags);
			request = &endpoint->requests[index];
			request->pending = false;
			request->delivered = true;
			endpoint->pending--;
			endpoint->cursor = (index + 1) % CCCI_SERVICE_SLOTS;
			spin_unlock_irqrestore(&endpoint->queue_lock, flags);
			ret = length;
		}
	}
	mutex_unlock(&endpoint->lock);
free:
	kvfree_sensitive(record, CCCI_SERVICE_RECORD_HEADER + CCCI_FS_MESSAGE_MAX);
	return ret;
}

/* queue_lock held: pure bounded validation, no allocations or callbacks. */
static int endpoint_validate(const struct endpoint_request *request,
			     enum ccci_service_kind kind, u32 slot,
			     const u8 *packet, size_t length)
{
	struct ccci_fs_message fs;
	struct ccci_rpc_message rpc;
	int ret;

	if (kind == CCCI_SERVICE_RPC) {
		ret = ccci_rpc_decode_request(request->packet, request->length, &rpc);
		return ret ?: ccci_rpc_validate_reply(&rpc, packet, length);
	}
	if (length < 24 || length > CCCI_FS_MESSAGE_MAX ||
	    get_unaligned_le32(packet + 4) != length ||
	    (get_unaligned_le32(packet + 8) & 0xffff) != CCCI_FS_TX ||
	    get_unaligned_le32(packet + 12) != slot ||
	    (get_unaligned_le32(packet) & CCCI_FS_MORE) ||
	    get_unaligned_le32(packet + 16) != get_unaligned_le32(request->packet + 16))
		return -EPROTO;
	return ccci_fs_decode(packet + 16, length - 16, &fs);
}

static ssize_t endpoint_write(struct file *file, const char __user *buffer,
			      size_t count, loff_t *offset)
{
	struct ccci_service_endpoint *endpoint = file->private_data;
	struct endpoint_request *request;
	unsigned long flags;
	u64 generation, token;
	u32 kind, slot, length;
	u8 *record;
	int index, ret;

	if (count < CCCI_SERVICE_RECORD_HEADER + 24 ||
	    count > CCCI_SERVICE_RECORD_HEADER + CCCI_FS_MESSAGE_MAX)
		return -EMSGSIZE;
	record = memdup_user(buffer, count);
	if (IS_ERR(record))
		return PTR_ERR(record);
	kind = get_unaligned_le32(record + 4);
	generation = get_unaligned_le64(record + 8);
	token = get_unaligned_le64(record + 16);
	slot = get_unaligned_le32(record + 24);
	length = get_unaligned_le32(record + 28);
	index = endpoint_index(kind, slot);
	if (get_unaligned_le32(record) != CCCI_SERVICE_RECORD_VERSION ||
	    !token || !generation || index < 0 ||
	    length != count - CCCI_SERVICE_RECORD_HEADER) {
		ret = -EINVAL;
		goto free;
	}
	mutex_lock(&endpoint->lock);
	spin_lock_irqsave(&endpoint->queue_lock, flags);
	request = &endpoint->requests[index];
	ret = endpoint->removed ? -ENODEV : endpoint->error;
	if (!ret && (!endpoint->armed || generation != endpoint->generation ||
		     !request->delivered || request->token != token))
		ret = -ESTALE;
	if (!ret && request->replied)
		ret = -EALREADY;
	if (!ret)
		ret = endpoint_validate(request, kind, slot,
					record + CCCI_SERVICE_RECORD_HEADER, length);
	if (!ret)
		request->replied = true;
	spin_unlock_irqrestore(&endpoint->queue_lock, flags);
	if (!ret) {
		ret = ccci_service_session_reply(endpoint->session, generation, token, kind, slot,
						 record + CCCI_SERVICE_RECORD_HEADER, length);
		/* No publication on enqueue failure; this generation cannot recover. */
		if (ret)
			ccci_service_session_abort(endpoint->session, generation, ret);
	}
	mutex_unlock(&endpoint->lock);
free:
	kfree_sensitive(record);
	return ret ?: count;
}

static __poll_t endpoint_poll(struct file *file, poll_table *wait)
{
	struct ccci_service_endpoint *endpoint = file->private_data;
	unsigned long flags;
	__poll_t mask = 0;

	poll_wait(file, &endpoint->wait, wait);
	spin_lock_irqsave(&endpoint->queue_lock, flags);
	if (endpoint->removed || endpoint->error)
		mask = EPOLLERR | EPOLLHUP;
	else if (endpoint->pending)
		mask = EPOLLIN | EPOLLRDNORM;
	spin_unlock_irqrestore(&endpoint->queue_lock, flags);
	return mask;
}

static const struct file_operations endpoint_fops = {
	.owner = THIS_MODULE,
	.open = endpoint_open,
	.release = endpoint_release,
	.read = endpoint_read,
	.write = endpoint_write,
	.poll = endpoint_poll,
	.llseek = noop_llseek,
};

static void endpoint_remove(void *context)
{
	struct ccci_service_endpoint *endpoint = context;
	unsigned long flags;
	int ret;

	misc_deregister(&endpoint->misc);
	mutex_lock(&endpoint->lock);
	spin_lock_irqsave(&endpoint->queue_lock, flags);
	endpoint->removed = true;
	spin_unlock_irqrestore(&endpoint->queue_lock, flags);
	ret = ccci_service_session_destroy(endpoint->session);
	mutex_unlock(&endpoint->lock);
	wake_up_interruptible(&endpoint->wait);
	/* No active remove is supported: retain callback storage on refusal. */
	if (ret) {
		pr_err("ccci-service: active endpoint removal refused: %d\n", ret);
		return;
	}
	kref_put(&endpoint->refs, endpoint_free);
}

struct ccci_service_endpoint *
ccci_service_endpoint_create(struct device *dev, struct ccci_ccif *ccif)
{
	struct ccci_service_endpoint *endpoint;
	int ret;

	endpoint = kvzalloc_obj(*endpoint);
	if (!endpoint)
		return ERR_PTR(-ENOMEM);
	kref_init(&endpoint->refs);
	mutex_init(&endpoint->lock);
	spin_lock_init(&endpoint->queue_lock);
	init_waitqueue_head(&endpoint->wait);
	endpoint->misc.name = kasprintf(GFP_KERNEL, "ccci-service-%s", dev_name(dev));
	if (!endpoint->misc.name) {
		ret = -ENOMEM;
		goto put;
	}
	endpoint->misc.minor = MISC_DYNAMIC_MINOR;
	endpoint->misc.mode = 0600;
	endpoint->misc.parent = dev;
	endpoint->misc.fops = &endpoint_fops;
	endpoint->session = ccci_service_session_create(dev, ccif, &endpoint_ops, endpoint);
	if (IS_ERR(endpoint->session)) {
		ret = PTR_ERR(endpoint->session);
		goto put;
	}
	ret = misc_register(&endpoint->misc);
	if (ret) {
		ccci_service_session_destroy(endpoint->session);
		goto put;
	}
	ret = devm_add_action_or_reset(dev, endpoint_remove, endpoint);
	if (ret)
		return ERR_PTR(ret);
	return endpoint;
put:
	kref_put(&endpoint->refs, endpoint_free);
	return ERR_PTR(ret);
}

int ccci_service_endpoint_arm(struct ccci_service_endpoint *endpoint, u64 generation)
{
	unsigned long flags;
	int ret;

	if (!endpoint || !generation)
		return -EINVAL;
	mutex_lock(&endpoint->lock);
	spin_lock_irqsave(&endpoint->queue_lock, flags);
	ret = endpoint->removed ? -ENODEV : endpoint->error;
	if (!ret && (!endpoint->connected || endpoint->armed))
		ret = -EBUSY;
	if (!ret) {
		endpoint->generation = generation;
		endpoint->armed = true;
	}
	spin_unlock_irqrestore(&endpoint->queue_lock, flags);
	if (!ret) {
		ret = ccci_service_session_arm(endpoint->session, generation);
		if (ret)
			endpoint_fault(endpoint, generation, ret);
	}
	mutex_unlock(&endpoint->lock);
	return ret;
}

int ccci_service_endpoint_receive(struct ccci_service_endpoint *endpoint, u64 generation,
				  const struct ccci_ccif_event *event)
{
	return ccci_service_session_receive(endpoint->session, generation, event);
}

int ccci_service_endpoint_hs2(struct ccci_service_endpoint *endpoint, u64 generation)
{
	return ccci_service_session_hs2(endpoint->session, generation);
}

int ccci_service_endpoint_abort(struct ccci_service_endpoint *endpoint,
				u64 generation, int error)
{
	return ccci_service_session_abort(endpoint->session, generation, error);
}

int ccci_service_endpoint_offline(struct ccci_service_endpoint *endpoint)
{
	return endpoint ? ccci_service_session_offline(endpoint->session) : 0;
}

int ccci_service_endpoint_stop(struct ccci_service_endpoint *endpoint, bool md_stopped)
{
	return ccci_service_session_stop(endpoint->session, md_stopped);
}

ssize_t ccci_service_endpoint_status(struct ccci_service_endpoint *endpoint, char *buf)
{
	struct ccci_service_session_status status;
	unsigned long flags;
	bool connected;
	u32 pending;

	if (!endpoint)
		return -EOPNOTSUPP;
	mutex_lock(&endpoint->lock);
	ccci_service_session_status(endpoint->session, &status);
	spin_lock_irqsave(&endpoint->queue_lock, flags);
	connected = endpoint->connected;
	pending = endpoint->pending;
	spin_unlock_irqrestore(&endpoint->queue_lock, flags);
	mutex_unlock(&endpoint->lock);
	return sysfs_emit(buf,
			  "connected=%u generation=%llu armed=%u accepting=%u stopped=%u error=%d queued=%u pending=%u experimental=1 service_ready=0\n",
			  connected, status.generation, status.armed, status.accepting,
			  status.stopped, status.error, status.queued, pending);
}
