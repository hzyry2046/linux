#!/usr/bin/env python3
# SPDX-License-Identifier: GPL-2.0-only
"""Actual AT/MUX byte pipe; modelled kernel services only.

The kernel owns the CCCI header and nothing else: userspace reads and writes
the raw 0710 stream. This checks the pipe contract (exclusive open, payload
only, bounded ring, chunked transmit, latched faults, stop proof), not the MD
or the muxing.
"""
from pathlib import Path
import subprocess
import tempfile

K = Path(__file__).resolve().parents[5]
SRC = K / 'drivers/misc/mediatek/ccci'

HEADERS = {
    'types.h': '#pragma once\n#include <stdint.h>\n#include <stdbool.h>\n#include <stddef.h>\n'
               '#define container_of(p,t,m) ((t *)((char *)(p)-offsetof(t,m)))\n'
               '#ifndef __user\n#define __user\n#endif\n'
               'typedef uint8_t u8;typedef uint16_t u16;typedef uint32_t u32;'
               'typedef uint64_t u64;\n',
    'errno.h': '#pragma once\n#include <asm-generic/errno.h>\n',
    'kconfig.h': '#pragma once\n#define IS_ENABLED(x) (x)\n',
    'device.h': '#pragma once\nstruct device { int unused; };\n'
                'static inline const char *dev_name(const struct device *d){(void)d;return "model";}\n'
                'int devm_add_action_or_reset(struct device *d, void (*f)(void *), void *c);\n',
    'fs.h': '#pragma once\n#include <linux/types.h>\n'
            'struct file { int f_flags; void *private_data; };\n'
            'struct inode { int unused; };\n'
            '#define O_NONBLOCK 00004000\n'
            'static inline int nonseekable_open(struct inode *i, struct file *f){(void)i;(void)f;return 0;}\n'
            'static inline loff_t noop_llseek(struct file *f, loff_t o, int w){(void)f;(void)o;(void)w;return 0;}\n'
            'typedef struct { unsigned long v; } poll_table;\n'
            'typedef unsigned int __poll_t;\n'
            '#define THIS_MODULE ((void *)0)\n'
            'struct file_operations { void *owner; int (*open)(struct inode *,struct file *);'
            ' int (*release)(struct inode *,struct file *);'
            ' long (*read)(struct file *,char *,size_t,loff_t *);'
            ' long (*write)(struct file *,const char *,size_t,loff_t *);'
            ' __poll_t (*poll)(struct file *,poll_table *);'
            ' loff_t (*llseek)(struct file *,loff_t,int); };\n'
            '#define EPOLLIN 0x1u\n#define EPOLLRDNORM 0x40u\n#define EPOLLOUT 0x4u\n'
            '#define EPOLLWRNORM 0x100u\n#define EPOLLERR 0x8u\n#define EPOLLHUP 0x10u\n',
    'kref.h': '#pragma once\nstruct kref { int refcount; };\n'
              'static inline void kref_init(struct kref *k){(void)k;}\n'
              'static inline void kref_put(struct kref *k, void (*f)(struct kref *)){f(k);}\n',
    'miscdevice.h': '#pragma once\n#include <linux/fs.h>\n'
                    '#define MISC_DYNAMIC_MINOR (-1)\n'
                    'struct miscdevice { int minor; const char *name; unsigned short mode;'
                    ' const struct file_operations *fops; struct device *parent; };\n'
                    'int misc_register(struct miscdevice *m);\n'
                    'void misc_deregister(struct miscdevice *m);\n',
    'mutex.h': '#pragma once\n#include <pthread.h>\n'
               'struct mutex { pthread_mutex_t lock; };\n'
               'static inline void mutex_init(struct mutex *m){pthread_mutex_init(&m->lock,NULL);}\n'
               'static inline void mutex_lock(struct mutex *m){pthread_mutex_lock(&m->lock);}\n'
               'static inline void mutex_unlock(struct mutex *m){pthread_mutex_unlock(&m->lock);}\n',
    'slab.h': '#pragma once\n#include <linux/types.h>\n#include <stdlib.h>\n#include <string.h>\n'
              '#define GFP_KERNEL 0\n'
              'static inline void *kzalloc(size_t n,int f){(void)f;return calloc(1,n);}\n'
              '#define kzalloc_obj(x) calloc(1,sizeof(x))\n'
              'static inline void *kmalloc(size_t n,int f){(void)f;return malloc(n);}\n'
              '#define min_t(type,a,b) ((type)((a)<(b)?(a):(b)))\n'
              '#define min(a,b) ((a)<(b)?(a):(b))\n'
              'static inline void *kvmalloc(size_t n,int f){(void)f;return malloc(n);}\n'
              'static inline void kvfree(void *p){free(p);}\n'
              'static inline void kfree(const void *p){free((void *)p);}\n'
              'static inline void kfree_sensitive(const void *p){free((void *)p);}\n'
              '#define IS_ERR(p) ((unsigned long)(void *)(p) >= (unsigned long)-4095)\n'
              '#define PTR_ERR(p) ((long)(p))\n'
              '#define ERR_PTR(e) ((void *)(long)(e))\n'
              'static inline void *kasprintf(int f,const char *fmt,...){(void)f;'
              'char *p=malloc(64);assert(p);snprintf(p,64,"%s","ccci-at-model");return p;}\n',
    'spinlock.h': '#pragma once\nstruct spinlock { int unused; };\n'
                  'typedef struct spinlock spinlock_t;\n'
                  '#define spin_lock_init(l) ((void)(l))\n'
                  '#define spin_lock_irqsave(l,f) ((void)(l),(f)=0)\n'
                  '#define spin_unlock_irqrestore(l,f) ((void)(l),(void)(f))\n',
    'string.h': '#pragma once\n#include <string.h>\n'
                'static inline void *memdup_user(const void *p,size_t n){'
                'void *v=malloc(n);if(!v)return (void *)-12;memcpy(v,p,n);return v;}\n',
    'uaccess.h': '#pragma once\n#include <string.h>\n'
                 'static inline unsigned long copy_to_user(void *to,const void *from,unsigned long n){'
                 'memcpy(to,from,n);return 0;}\n',
    'unaligned.h': '#pragma once\n#include <linux/types.h>\n'
                   'static inline u32 get_unaligned_le32(const void *p){const u8 *b=p;'
                   'return (u32)b[0]|(u32)b[1]<<8|(u32)b[2]<<16|(u32)b[3]<<24;}\n'
                   'static inline void put_unaligned_le32(u32 v,void *p){u8 *b=p;'
                   'for(unsigned i=0;i<4;i++)b[i]=v>>(8*i);}\n',
    'wait.h': '#pragma once\n#include <linux/types.h>\n'
              'struct wait_queue_head { int unused; };\n'
              'typedef struct wait_queue_head wait_queue_head_t;\n'
              '#define init_waitqueue_head(w) ((void)(w))\n'
              '#define wake_up_interruptible(w) ((void)(w))\n'
              '#define wake_up_interruptible_all(w) ((void)(w))\n'
              '#define wait_event_interruptible(w,cond) ({ (void)(w); (cond) ? 0 : -512; })\n'
              '#define poll_wait(f,w,t) ((void)(f),(void)(w),(void)(t))\n',
    'completion.h': '#pragma once\nstruct completion { bool done; };\n'
                    '#define init_completion(c) ((c)->done=false)\n'
                    '#define reinit_completion(c) ((c)->done=false)\n'
                    '#define complete_all(c) ((c)->done=true)\n'
                    '#define wait_for_completion_timeout(c,t) ((void)(t),(c)->done ? 1ul : 0ul)\n'
                    '#define msecs_to_jiffies(n) (n)\n',
    'sysfs.h': '#pragma once\n#define sysfs_emit(b,fmt,...) snprintf(b,4096,fmt,__VA_ARGS__)\n',
}

TEST = r'''
#include <assert.h>
#include <stdio.h>
#include <stdlib.h>
#include <string.h>
#include <linux/types.h>
#include <linux/errno.h>
#include <linux/fs.h>
#include <linux/miscdevice.h>
#include <linux/slab.h>

#include "ccci-md-at.h"

#include "ccci-md-at.c"

/* --- models ------------------------------------------------------------- */
static char model_ccif_storage[64];
#define model_ccif (*(struct ccci_ccif *)model_ccif_storage)
static unsigned sent_frames, sent_bytes, actions;
static int send_result;
static u8 last_sent[CCCI_CCIF_AT_MAX * 4];
static u32 last_sent_len;

int ccci_ccif_at_send(struct ccci_ccif *ccif, const void *payload, u32 size, bool hs2)
{
	assert(ccif == &model_ccif && hs2);
	if (send_result)
		return send_result;
	assert(size <= CCCI_CCIF_AT_MAX && last_sent_len + size <= sizeof(last_sent));
	memcpy(last_sent + last_sent_len, payload, size);
	last_sent_len += size;
	sent_frames++;
	sent_bytes += size;
	return 0;
}

int misc_register(struct miscdevice *m) { assert(m->mode == 0600); return 0; }
void misc_deregister(struct miscdevice *m) { (void)m; }
int devm_add_action_or_reset(struct device *d, void (*f)(void *), void *c)
{
	(void)d; (void)f; (void)c; actions++; return 0;
}

static u8 frame[64];
static struct ccci_ccif_event at_event(u32 length)
{
	static u8 storage[64];
	struct ccci_ccif_event e = {0};

	assert(length + CCCI_CCIF_HEADER <= sizeof(storage));
	memset(storage, 0xee, sizeof(storage));
	memcpy(storage + CCCI_CCIF_HEADER, frame, length);
	e.type = CCCI_CCIF_EVENT_RING;
	e.size = CCCI_CCIF_HEADER + length;
	e.header.channel = 10;
	e.data = storage;
	return e;
}

/* misc_open() hands the fops the embedded miscdevice; model that exactly. */
static int open_pipe(struct ccci_md_at *at, struct file *f)
{
	int ret;

	f->private_data = &at->misc;
	ret = at_open(NULL, f);
	if (!ret)
		assert(f->private_data == at);
	return ret;
}

static struct ccci_md_at *new_pipe(void)
{
	struct ccci_md_at *at = ccci_md_at_create(NULL, &model_ccif);
	struct device dev;

	assert(IS_ERR(at));            /* no device: refuse to build */
	at = ccci_md_at_create(&dev, NULL);
	assert(IS_ERR(at));            /* no CCIF owner */
	at = ccci_md_at_create(&dev, &model_ccif);
	assert(!IS_ERR(at));
	return at;
}

int main(void)
{
	struct ccci_md_at *at;
	struct file file;
	char status[512];
	char out[128];
	ssize_t n;

	/* --- construction and exclusive open -------------------------------- */
	at = new_pipe();
	assert(actions == 1);
	memset(&file, 0, sizeof(file));
	assert(!open_pipe(at, &file));
	assert(file.private_data == at);
	{
		struct file second = {0};

		assert(open_pipe(at, &second) == -EBUSY);   /* one owner only */
	}
	assert(at->hs2 == false);

	/* --- MD -> AP: payload only, header never leaks --------------------- */
	memset(frame, 0, sizeof(frame));
	memcpy(frame, "\xf9\x03\x3f\x01\x1c\xf9", 6);
	assert(!ccci_md_at_receive(at, &(struct ccci_ccif_event){0}));   /* NULL event */
	{
		struct ccci_ccif_event e = at_event(6);

		assert(!ccci_md_at_receive(at, &e));
		assert(at->rx_frames == 1 && at->rx_bytes == 6);
		n = at_read(&file, out, sizeof(out), NULL);
		assert(n == 6 && !memcmp(out, frame, 6));
		assert(at_read(&file, out, sizeof(out), NULL) == -512);  /* empty, blocking model */
	}
	/* A different channel is not AT traffic. */
	{
		struct ccci_ccif_event e = at_event(6);

		e.header.channel = 12;
		assert(!ccci_md_at_receive(at, &e));
		assert(at->rx_frames == 1);
	}

	/* --- bounded ring: overflow latches instead of losing bytes --------- */
	{
		/* One byte more than the ring: the pipe must refuse, not wrap. */
		u8 big[CCCI_AT_RING + CCCI_CCIF_HEADER + 1];
		struct ccci_ccif_event e = at_event(0);

		memset(big, 0x5a, sizeof(big));
		e.data = big;
		e.size = sizeof(big);
		e.header.channel = 10;
		assert(ccci_md_at_receive(at, &e) == -ENOSPC);
		assert(at->rx_dropped == 1 && at->error == -ENOSPC);
		assert(ccci_md_at_receive(at, &e) == -ENOSPC);
		n = at_read(&file, out, sizeof(out), NULL);
		assert(n == -ENOSPC);
	}

	/* --- AP -> MD: refused before HS2, chunked after ------------------- */
	at_release(NULL, &file);
	at_remove(at);                     /* devm action: deregister and free */
	at = new_pipe();
	memset(&file, 0, sizeof(file));
	assert(!open_pipe(at, &file));
	memset(frame, 0x33, 8);
	assert(at_write(&file, (const char *)frame, 8, NULL) == -ENOTCONN);
	assert(!ccci_md_at_hs2(at));
	assert(at->hs2);
	assert(at_write(&file, (const char *)frame, 8, NULL) == 8);
	assert(sent_frames == 1 && sent_bytes == 8 && !memcmp(last_sent, frame, 8));
	/* Chunking above the wire maximum keeps the order and the byte count. */
	{
		static u8 large[CCCI_CCIF_AT_MAX * 2 + 7];

		last_sent_len = 0;
		sent_frames = 0;
		sent_bytes = 0;
		for (size_t i = 0; i < sizeof(large); i++)
			large[i] = (u8)i;
		assert(at_write(&file, (const char *)large, sizeof(large), NULL) == (ssize_t)sizeof(large));
		assert(sent_frames == 3 && sent_bytes == sizeof(large));
		assert(!memcmp(last_sent, large, sizeof(large)));
	}
	/* Backpressure is reported, not latched as a fault. */
	send_result = -EBUSY;
	assert(at_write(&file, (const char *)frame, 8, NULL) == -EAGAIN);
	assert(at->error == 0);
	send_result = 0;
	/* A real transport fault latches. */
	send_result = -EIO;
	assert(at_write(&file, (const char *)frame, 8, NULL) == -EIO);
	assert(at->error == -EIO && at->tx_error == -EIO);
	send_result = 0;
	assert(at_write(&file, (const char *)frame, 8, NULL) == -EIO);
	assert(at->tx_frames == 4);

	/* --- stop needs real MD proof and the owner to close --------------- */
	assert(ccci_md_at_stop(at, false) == -EBUSY);
	at->error = 0;
	at->stopped = false;
	at_release(NULL, &file);           /* completion already satisfied */
	assert(!ccci_md_at_stop(at, true));
	assert(at->stopped && at->error == -ESHUTDOWN);
	assert(ccci_md_at_status(at, status) > 0 && strstr(status, "stopped=1"));
	assert(ccci_md_at_offline(at) == 0);
	at_remove(at);

	/* --- a fresh pipe reports honest counters ------------------------- */
	at = new_pipe();
	memset(&file, 0, sizeof(file));
	assert(!open_pipe(at, &file));
	assert(ccci_md_at_status(at, status) > 0);
	assert(strstr(status, "open=1") && strstr(status, "hs2=0") &&
	       strstr(status, "rx_frames=0") && strstr(status, "tx_frames=0"));
	assert(at_poll(&file, NULL) == 0);
	ccci_md_at_abort(at, -EIO);
	assert(ccci_md_at_status(at, status) > 0 && strstr(status, "error=-5"));
	assert(at_poll(&file, NULL) == (EPOLLERR | EPOLLHUP));
	at_release(NULL, &file);
	at_remove(at);

	puts("PASS: actual AT/MUX byte pipe: exclusive open, payload-only receive,");
	puts("      latched ring overflow, chunked transmit, backpressure vs fault,");
	puts("      HS2 gate, stop proof and honest status counters");
	return 0;
}
'''


def main():
    with tempfile.TemporaryDirectory(prefix='op6893-md-at-') as directory:
        root = Path(directory)
        inc = root / 'linux'
        inc.mkdir()
        for name, content in HEADERS.items():
            (inc / name).write_text(content)
        (root / 'test.c').write_text(TEST)
        subprocess.run(['cc', '-O1', '-g', '-Wall', '-Wextra', '-Werror',
                        '-Wno-misleading-indentation', '-Wno-unused-parameter',
                        '-Wno-sign-compare', '-fsanitize=address,undefined',
                        '-fno-sanitize-recover=all', '-no-pie',
                        '-D__iomem=', '-DCONFIG_OP6893_CCCI_DISPATCH=1',
                        '-DCONFIG_OP6893_CCCI_CCIF=1', '-I' + str(root), '-I' + str(SRC),
                        str(root / 'test.c'), '-o', str(root / 'test')], check=True)
        subprocess.run([str(root / 'test')], check=True)


if __name__ == '__main__':
    main()
