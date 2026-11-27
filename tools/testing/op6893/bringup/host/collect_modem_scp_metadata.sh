#!/system/bin/sh
# SPDX-License-Identifier: GPL-2.0-only
# Run explicitly on Android; no adb, MMIO, debugfs, writes, wakeup or reset.
# Optional filesystem root is for offline fixtures, not device discovery.
set -eu

if [ "$#" -gt 1 ]; then
	printf 'usage: sh collect_modem_scp_metadata.sh [fixture-root]\n' >&2
	exit 2
fi
scp_root=${1:-}

emit_ready()
{
	scp_status_file=$scp_root/sys/class/misc/scp/scp_A_status
	if [ ! -r "$scp_status_file" ]; then
		printf '%s=unavailable\n' "$1"
		return
	fi
	scp_status=$(dd if="$scp_status_file" bs=128 count=1 2>/dev/null) || scp_status=
	case "$scp_status" in
		'SCP A is ready') scp_status=ready ;;
		'SCP A is not ready') scp_status=not-ready ;;
		*) scp_status=unrecognized ;;
	esac
	# Never echo arbitrary sysfs content, including unrecognized status text.
	printf '%s=%s\n' "$1" "$scp_status"
}

emit_property()
{
	scp_file=$scp_dt/$1
	if [ ! -r "$scp_file" ]; then
		printf 'dt:%s=unavailable\n' "$1"
		return
	fi
	if ! scp_hex=$(od -An -v -tx1 -N1025 "$scp_file" 2>/dev/null); then
		printf 'dt:%s=read-error\n' "$1"
		return
	fi
	scp_hex=$(printf '%s' "$scp_hex" | tr -d ' \n')
	if [ "${#scp_hex}" -gt 2048 ]; then
		printf 'dt:%s=oversize\n' "$1"
	else
		printf 'dt:%s=hex:%s\n' "$1" "$scp_hex"
	fi
}

printf 'schema=op6893-scp-metadata-v1\n'
emit_ready ready-before
scp_dt=$scp_root/sys/firmware/devicetree/base
if [ ! -d "$scp_dt" ]; then
	scp_dt=$scp_root/proc/device-tree
fi

# Fixed hardware-property allowlist. Never enumerate arbitrary sysfs attributes.
for scp_property in \
	scp@10700000/reg scp@10700000/reg-names \
	scp@10700000/interrupts scp@10700000/interrupt-names \
	scp@10700000/core_nums scp@10700000/core_0 scp@10700000/core_1 \
	scp@10700000/twohart scp@10700000/scp_sramSize \
	scp@10700000/secure_dump scp@10700000/scp_hwvoter \
	scp@10700000/scp-read-infra-irq-status \
	scp@10700000/scp-scpsys-regmap scp@10700000/awake-timeout \
	scp@10700000/mbox_count scp@10700000/send_table scp@10700000/recv_table \
	scp_dvfs/clock-names scp_dvfs/clocks \
	scp_dvfs/scp-clk-hw-ver scp_dvfs/scp-dvfs-feature \
	scp_clk_ctrl@10721000/reg scp_infra@10001000/reg \
	reserved-memory/mblock-21-SCP-reserved/reg \
	reserved-memory/mblock-21-SCP-reserved/no-map \
	reserved-memory/reserve-memory-scp_share/reg \
	reserved-memory/reserve-memory-scp_share/size \
	reserved-memory/reserve-memory-scp_share/alignment \
	reserved-memory/reserve-memory-scp_share/alloc-ranges \
	reserved-memory/reserve-memory-scp_share/no-map
do
	emit_property "$scp_property"
done
emit_ready ready-after
