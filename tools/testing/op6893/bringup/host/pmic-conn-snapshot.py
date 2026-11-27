#!/usr/bin/env python3
# SPDX-License-Identifier: GPL-2.0-only
"""Read only fixed MT6359P connectivity regulator control/status registers.

Uses seeked regmap debugfs reads, not a full PMIC dump. No regulator driver
is loaded. Each returned address is validated against the requested address.
"""
import argparse
import json
from pathlib import Path
import subprocess

REGS = {
    'hwcid': 0x8,
    'vs2_con': 0x1888, 'vs2_vsel_actual': 0x18a6,
    'vs2_status': 0x18a8, 'vs2_vsel_requested': 0x18b4,
    'vcn33_1_con': 0x1be2, 'vcn33_1_status': 0x1be6,
    'vcn33_1_wifi_enable': 0x1bf4,
    'vcn33_2_con': 0x1c08, 'vcn33_2_status': 0x1c0c,
    'vcn33_2_wifi_enable': 0x1c1a,
    'vcn13_con': 0x1c1c, 'vcn13_status': 0x1c20,
    'vcn18_con': 0x1c2e, 'vcn18_status': 0x1c32,
    'vcn33_1_vsel': 0x1f98, 'vcn33_2_vsel': 0x1f9c,
    'vcn13_vsel': 0x202e,
}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--ssh-helper', type=Path,
                        default=Path(__file__).resolve().with_name('ssh-native.sh'))
    args = parser.parse_args()
    cmd = r'''set -eu
[ "$(uname -r)" = '7.3.0-op6893-d1-06374ef46937+' ]
tr '\000' '\n' < /sys/firmware/devicetree/base/compatible | grep -qx realme,op6893
map=/sys/kernel/debug/regmap/10026000.pwrap
[ "$(cat "$map/range")" = '0-fffe' ]
printf 'release '; uname -r
printf 'uptime '; cat /proc/uptime
'''
    for name, addr in REGS.items():
        cmd += (f"printf '{name} '; "
                f'dd if="$map/registers" bs=11 skip={addr // 2} count=1 status=none\n')
    res = subprocess.run([str(args.ssh_helper), cmd], check=True,
                         capture_output=True, text=True, timeout=30)
    lines = dict(line.split(maxsplit=1) for line in res.stdout.splitlines())
    values = {}
    for name, expected in REGS.items():
        address, value = lines[name].split(':')
        if int(address, 16) != expected:
            raise ValueError(f'{name}: unexpected regmap layout/address')
        values[name] = int(value, 16)
    if values['hwcid'] < 0x5930:
        raise ValueError('Not the expected MT6359P revision')
    decoded = {name + '_enabled_status': bool(values[name + '_status'] & 1)
               for name in ('vs2', 'vcn13', 'vcn18', 'vcn33_1', 'vcn33_2')}
    decoded['vcn33_probe_sync_would_write'] = [
        name for name in ('vcn33_1', 'vcn33_2')
        if values[name + '_wifi_enable'] & 0x8000]
    for key in ('actual', 'requested'):
        decoded['vs2_' + key + '_nominal_uv'] = 800000 + (values['vs2_vsel_' + key] & 0x7f) * 12500
    print(json.dumps({'release': lines['release'], 'uptime': lines['uptime'],
                      'registers': {k: {'address': hex(REGS[k]), 'value': hex(v)}
                                    for k, v in values.items()},
                      'decoded': decoded,
                      'limits': ['Sequential read-only samples; not atomic.',
                                 'Nominal selector voltage, not measured output.',
                                 'Probe-sync prediction excludes regulator constraints and other writes.']}, indent=2))


if __name__ == '__main__':
    main()
