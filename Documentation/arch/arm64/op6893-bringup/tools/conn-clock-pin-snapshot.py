#!/usr/bin/env python3
# SPDX-License-Identifier: GPL-2.0-only
"""Read fixed AP-side CONN pinmux/clock controls and MT6359P DCXO config.

No access to the powered-off CONN aperture, no SET/CLR or AUXOUT selection.
Addresses/fields come from ACK mt6893_pos.c and dcxo-6359p.c.
"""
import argparse
import json
from pathlib import Path
import subprocess

MMIO = {
    "gpio_mode19": 0x10005430,
    "gpio_mode21": 0x10005450,
    "gpio_mode22": 0x10005460,
    "iocfg_rt_drive": 0x11ea0000,
    "iocfg_rt_pd": 0x11ea0050,
    "iocfg_rt_pu": 0x11ea0070,
    "ap2conn_host_clock": 0x1020e504,
}
PMIC = {"hwcid": 0x8, "pmrc_con0": 0x1a6,
        "xo_wcn_vote": 0x54e, "dcxo_cw00": 0x788,
        "dcxo_cw09": 0x79e, "dcxo_cw12": 0x7a8,
        "dcxo_cw13": 0x7aa}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--ssh-helper", type=Path,
                        default=Path(__file__).resolve().with_name("ssh-native.sh"))
    args = parser.parse_args()
    cmd = r'''set -eu
[ "$(uname -r)" = '7.3.0-op6893-d1-d873de3b8963+' ]
tr '\000' '\n' < /sys/firmware/devicetree/base/compatible | grep -qx realme,op6893
map=/sys/kernel/debug/regmap/10026000.pwrap
[ "$(cat "$map/range")" = '0-fffe' ]
printf 'release '; uname -r
printf 'uptime '; cat /proc/uptime
'''
    for name, address in MMIO.items():
        cmd += f"printf '{name} '; /bin/busybox devmem {address:#x} 32\n"
    for name, address in PMIC.items():
        cmd += (f"printf '{name} '; "
                f'dd if="$map/registers" bs=11 skip={address // 2} count=1 status=none\n')
    result = subprocess.run([str(args.ssh_helper), cmd], check=True,
                            capture_output=True, text=True, timeout=30)
    lines = dict(line.split(maxsplit=1) for line in result.stdout.splitlines())
    values = {name: int(lines[name], 16) for name in MMIO}
    for name, address in PMIC.items():
        actual, value = lines[name].split(':')
        if int(actual, 16) != address:
            raise ValueError(f"{name}: unexpected regmap layout/address")
        values[name] = int(value, 16)
    if values['hwcid'] != 0x5930:
        raise ValueError("Unexpected PMIC revision")
    modes = {str(pin): (values['gpio_mode21' if pin < 176 else 'gpio_mode22']
                       >> ((pin % 8) * 4)) & 7 for pin in range(172, 183)}
    print(json.dumps({
        "release": lines["release"], "uptime": lines["uptime"],
        "registers": {name: {"address": hex(address), "value": hex(values[name])}
                      for name, address in (MMIO | PMIC).items()},
        "decoded": {
            "pin_modes_172_182": modes,
            "all_conn_pins_function1": all(mode == 1 for mode in modes.values()),
            "gpio155_mode": (values['gpio_mode19'] >> 12) & 7,
            "ap2conn_host_clock_request": bool(values['ap2conn_host_clock'] & 1),
            "extbuf2_mode": (values['dcxo_cw00'] >> 3) & 3,
            "extbuf2_software_enable": bool(values['dcxo_cw00'] & 0x20),
            "extbuf2_bblpm_mask": bool(values['dcxo_cw12'] & 4),
            "xo_wcn_vote_bits": hex(values['xo_wcn_vote'] & 0x7ff),
            "vendor_drive_bits_match": values['iocfg_rt_drive'] & 0x3fff8 == 0x8248,
            "top_bt_data_pullup_bits": hex(values['iocfg_rt_pu'] & 0x4800),
            "top_bt_data_pulldown_bits": hex(values['iocfg_rt_pd'] & 0x4800),
        },
        "limits": ["Sequential read-only snapshot, not atomic.",
                   "No oscillator output/frequency measurement or hardware-ready proof.",
                   "Software enable is not output status in hardware-controlled modes.",
                   "No CONN MMIO, pin reconfiguration, AUXOUT selection or clock writes."],
    }, indent=2))


if __name__ == '__main__':
    main()
