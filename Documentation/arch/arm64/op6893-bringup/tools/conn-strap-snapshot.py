#!/usr/bin/env python3
# SPDX-License-Identifier: GPL-2.0-only
"""Read GPIO180's AP-side baseline without changing pins or accessing CONN."""
import argparse
import json
from pathlib import Path
import shlex
import subprocess


REGISTERS = {
    'dir5': 0x10005050,
    'dout5': 0x10005150,
    'din5': 0x10005250,
    'mode22': 0x10005460,
    'drive': 0x11ea0000,
    'ies': 0x11ea0030,
    'pd': 0x11ea0050,
    'pu': 0x11ea0070,
    'smt': 0x11ea00c0,
}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--ssh-helper', required=True, type=Path)
    parser.add_argument('--expected-release', required=True)
    args = parser.parse_args()
    command = [
        'set -eu',
        '[ "$(uname -r)" = ' + shlex.quote(args.expected_release) + ' ]',
        "tr '\\000' '\\n' < /sys/firmware/devicetree/base/compatible "
        '| grep -qx realme,op6893',
        "printf 'release '; uname -r",
        "printf 'uptime '; cat /proc/uptime",
    ]
    for name, address in REGISTERS.items():
        command.append(f"printf '{name} '; /bin/busybox devmem {address:#x} 32")
    result = subprocess.run([str(args.ssh_helper), '\n'.join(command)],
                            capture_output=True, text=True, check=True, timeout=30)
    lines = dict(line.split(maxsplit=1) for line in result.stdout.splitlines())
    values = {name: int(lines[name], 16) for name in REGISTERS}
    print(json.dumps({
        'release': lines['release'], 'uptime': lines['uptime'],
        'registers': {name: {'address': hex(address), 'value': hex(values[name])}
                      for name, address in REGISTERS.items()},
        'gpio180': {
            'mode': (values['mode22'] >> 16) & 15,
            'output_enabled': bool(values['dir5'] & (1 << 20)),
            'output_latch': (values['dout5'] >> 20) & 1,
            'input_sample': (values['din5'] >> 20) & 1,
            'input_buffer_enabled': bool(values['ies'] & (1 << 18)),
            'pull_up': bool(values['pu'] & (1 << 18)),
            'pull_down': bool(values['pd'] & (1 << 18)),
            'shared_schmitt_178_182': bool(values['smt'] & (1 << 7)),
            'shared_drive_encoding': (values['drive'] >> 3) & 7,
        },
        'limits': [
            'Sequential AP-only reads, not an atomic snapshot.',
            'No SET/CLR aliases, pin writes, CONN reads or reset release.',
            'Input sample is not an oscillator or strap-latching measurement.',
            'Interpret alongside domain and pinctrl ownership records from the same boot.',
        ],
    }, indent=2))


if __name__ == '__main__':
    main()
