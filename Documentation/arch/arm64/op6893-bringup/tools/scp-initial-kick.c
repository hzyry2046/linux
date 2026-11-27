// SPDX-License-Identifier: GPL-2.0-only
/* One bounded op6893 initial-release experiment, with the kernel RX stopped. */
#include <errno.h>
#include <fcntl.h>
#include <signal.h>
#include <stdint.h>
#include <stdio.h>
#include <stdlib.h>
#include <string.h>
#include <sys/mman.h>
#include <unistd.h>

#define OWNER "/sys/devices/platform/10724000.scp-resource-hold/"
static volatile sig_atomic_t interrupted;

static void stop(int signal)
{
	(void)signal;
	interrupted = 1;
}

static char *attribute(const char *path)
{
	static char buf[1024];
	FILE *file = fopen(path, "r");

	if (!file || !fgets(buf, sizeof(buf), file)) {
		perror(path);
		exit(1);
	}
	fclose(file);
	return buf;
}

static void require(const char *path, const char *first, const char *second)
{
	char *buf = attribute(path);

	if (!strstr(buf, first) || !strstr(buf, second)) {
		fprintf(stderr, "precondition failed: %s\n", path);
		exit(1);
	}
}

static uint32_t load(volatile uint32_t *page, unsigned int offset)
{
	uint32_t value = page[offset / 4];

	asm volatile("dmb sy" : : : "memory");
	return value;
}

static void store(volatile uint32_t *page, unsigned int offset, uint32_t value)
{
	page[offset / 4] = value;
	asm volatile("dsb sy" : : : "memory");
}

int main(int argc, char **argv)
{
	const unsigned long addresses[] = {
		0x10730000, 0x10740000, 0x107fb000, 0x107fc000,
		0x107fd000, 0x107fe000, 0x107ff000,
	};
	volatile uint32_t *pages[7];
	uint32_t old_addr, old_size, last[5] = {}, pending[5];
	unsigned long share, size;
	unsigned int i, round, changes = 0;
	uint32_t pc, next_pc;
	char *state, *base, *length;
	int fd, once;
	int ready = 0, ready1 = 0;

	if (argc != 2 || strcmp(argv[1], "initial-kick-2000ms")) {
		fprintf(stderr, "usage: %s initial-kick-2000ms\n", argv[0]);
		return 1;
	}
	setvbuf(stdout, NULL, _IONBF, 0);
	require(OWNER "state", "pin_verified=1", "fault=0");
	require(OWNER "irq", "gic_masked=5", "closing=1");
	require(OWNER "irq", "generation=0", "armed=0");
	require(OWNER "reset_state", "attempted=1", "writes=2");
	require("/sys/devices/platform/10730000.scp-observe/state",
		"selector=0", "gated=0");
	state = attribute("/sys/devices/platform/10730000.scp-observe/state");
	base = strstr(state, "share_base=");
	length = strstr(state, "share_size=");
	if (!base || !length || sscanf(base, "share_base=%lx", &share) != 1 ||
	    sscanf(length, "share_size=%lx", &size) != 1 || !share || !size ||
	    (share | size) & 3 || share > UINT32_MAX || size > UINT32_MAX - share)
		return 1;
	fd = open("/dev/mem", O_RDWR | O_SYNC);
	if (fd < 0) {
		perror("/dev/mem");
		return 1;
	}
	for (i = 0; i < 7; i++) {
		pages[i] = mmap(NULL, 4096, PROT_READ | PROT_WRITE, MAP_SHARED,
				fd, addresses[i]);
		if (pages[i] == MAP_FAILED) {
			perror("mmap");
			return 1;
		}
	}
	for (i = 0; i < 5; i++) {
		if (load(pages[i + 2], 0x10c)) {
			fprintf(stderr, "inherited pending on mailbox %u; abort\n", i);
			return 1;
		}
	}
	once = open("/run/scp-initial-kick.once", O_WRONLY | O_CREAT | O_EXCL, 0600);
	if (once < 0) {
		perror("one attempt per boot");
		return 1;
	}
	close(once);
	signal(SIGINT, stop);
	signal(SIGTERM, stop);
	old_addr = load(pages[0], 0x44);
	old_size = load(pages[0], 0x48);
	printf("before core0=%08x core1=%08x\n",
	       load(pages[0], 4), load(pages[1], 4));
	/* Same-board vendor reset_scp initial path; no TCM/DRAM restore writes. */
	store(pages[0], 0x44, share);
	store(pages[0], 0x48, size);
	store(pages[0], 0, 1);
	printf("released core0=%08x core1=%08x\n",
	       load(pages[0], 4), load(pages[1], 4));
	pc = load(pages[0], 0x80);
	for (round = 0; round < 200 && !interrupted; round++) {
		usleep(10000);
		next_pc = load(pages[0], 0x80);
		changes += next_pc != pc;
		pc = next_pc;
		for (i = 0; i < 5; i++)
			pending[i] = load(pages[i + 2], 0x10c);
		if (memcmp(last, pending, sizeof(last))) {
			printf("sample=%u pending=%08x,%08x,%08x,%08x,%08x\n",
			       round, pending[0], pending[1], pending[2], pending[3], pending[4]);
			memcpy(last, pending, sizeof(last));
		}
		/* Actual board table: READY0 channel9, mailbox1 offset40, IRQ20. */
		if (!ready && pending[1] & (1U << 20)) {
			ready = load(pages[3], 40 * 4) == 0x180000 ? 1 : -1;
			printf("ready0_size_matches=%d\n", ready == 1);
		}
		/* READY1 channel22: mailbox3 offset30, IRQ15, same A/V handler. */
		if (!ready1 && pending[3] & (1U << 15)) {
			ready1 = load(pages[5], 30 * 4) == 0x180000 ? 1 : -1;
			printf("ready1_size_matches=%d\n", ready1 == 1);
		}
	}
	store(pages[0], 4, 1);
	store(pages[1], 4, 1);
	printf("asserted core0=%08x core1=%08x pc_changes=%u ready0=%d ready1=%d\n",
	       load(pages[0], 4), load(pages[1], 4), changes, ready, ready1);
	/* No mailbox ACK or generation/READY claim; restore only AP GPR metadata. */
	store(pages[0], 0x44, old_addr);
	store(pages[0], 0x48, old_size);
	for (i = 0; i < 7; i++)
		munmap((void *)pages[i], 4096);
	close(fd);
	return 0;
}
