#!/usr/bin/env python3
# SPDX-License-Identifier: GPL-2.0-only
"""Read fixed SPM/infra status only; never access the CONN power island.

Offsets: ACK clk-mt6893-pg.c and mainline mt6893-pm-domains.h.
This observes inherited state, not power-sequence correctness.
"""
import argparse
import datetime
import json
from pathlib import Path
import subprocess

REGISTERS = {
    "spm_poweron_config": 0x10006000,
    "spm_pwr_status": 0x1000616c,
    "spm_pwr_status_2nd": 0x10006170,
    "spm_conn_pwr_con": 0x10006304,
    "infra_protect_sta1": 0x10001228,
    "infra_protect_1_sta1": 0x10001258,
    "infra_protect_2_sta1": 0x10001724,
}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--ssh-helper", type=Path,
                        default=Path(__file__).resolve().with_name("ssh-native.sh"))
    args = parser.parse_args()
    command = r'''set -eu
tr '\000' '\n' < /sys/firmware/devicetree/base/compatible | grep -qx realme,op6893
release=$(uname -r)
case "$release" in 7.3.0-op6893-d1-06374ef46937+) ;; *) exit 1;; esac
printf 'release %s\n' "$release"
printf 'uptime '; cat /proc/uptime
'''
    for name, addr in REGISTERS.items():
        command += f"printf '{name} '; /bin/busybox devmem {addr:#x} 32\n"
    result = subprocess.run([str(args.ssh_helper), command], check=True,
                            capture_output=True, text=True, timeout=30)
    fields = dict(line.split(maxsplit=1) for line in result.stdout.splitlines())
    regs = {name: int(fields[name], 16) for name in REGISTERS}
    a = bool(regs['spm_pwr_status'] & 2)
    b = bool(regs['spm_pwr_status_2nd'] & 2)
    ctl = regs['spm_conn_pwr_con']
    print(json.dumps({
        'captured_at_utc': datetime.datetime.now(datetime.timezone.utc).isoformat(),
        'release': fields['release'], 'uptime': fields['uptime'],
        'registers': {n: {'address': hex(REGISTERS[n]), 'value': hex(v)}
                      for n, v in regs.items()},
        'decoded': {
            'conn_status': 'on' if a and b else 'off' if not a and not b else 'mixed',
            'reset_released': bool(ctl & 1), 'isolation': bool(ctl & 2),
            'power_on_request': bool(ctl & 4), 'power_on_2nd_request': bool(ctl & 8),
            'clock_disabled': bool(ctl & 16),
            'ack_protect_step1_bit13': bool(regs['infra_protect_sta1'] & (1 << 13)),
            'ack_protect_step2_bit14': bool(regs['infra_protect_sta1'] & (1 << 14)),
            'ack_protect_step2_1_bit2': bool(regs['infra_protect_2_sta1'] & 4),
            'mainline_extra_step1_bit18': bool(regs['infra_protect_sta1'] & (1 << 18)),
            'mainline_step3_bit10': bool(regs['infra_protect_1_sta1'] & (1 << 10)),
        },
        'limits': ['Sequential read-only snapshot, not atomic.',
                   'No CONN MMIO or SET/CLR writes; no power transition.',
                   'Status does not establish which bus-protection table is correct.'],
    }, indent=2))


if __name__ == '__main__':
    main()
