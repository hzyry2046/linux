/* SPDX-License-Identifier: GPL-2.0-only */
#ifndef OP6893_ACK_SCP_ABI_H
#define OP6893_ACK_SCP_ABI_H

/* Audited RV ABI. A direct import pins the scp provider throughout. */
enum scp_core_id {
	SCP_A_ID = 0,
	SCP_CORE_TOTAL = 1,
};

unsigned int is_scp_ready(enum scp_core_id id);

#endif
