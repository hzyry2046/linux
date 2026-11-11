#!/usr/bin/env python3
# SPDX-License-Identifier: GPL-2.0-only
"""Compare compiled staged CONN pin states with ACK register-mask intent.

Models final register fields from the real MT6893 pin tables; no device access.
Does not validate pinctrl runtime ordering, analogue behavior or ownership.
"""
import argparse
import hashlib
import json
from pathlib import Path
import re
import subprocess

ROOT = Path('/data/src/mainline/linux')
VENDOR = Path('/data/src/6.6-exp/android_kernel_modules_oneplus_mt6833/vendor/'
              'mediatek/kernel_modules/connectivity/conninfra/conn_drv/connv2/'
              'platform/mt6893/mt6893_pos.c')
TABLE = ROOT / 'drivers/pinctrl/mediatek/pinctrl-mt6893.c'
PIO = '/soc/pinctrl@10005000'


def fdt(dtb, node, prop=None, option='-t x'):
    result = subprocess.run(['fdtget', *option.split(), str(dtb), node,
                             *([prop] if prop else [])],
                            capture_output=True, text=True, check=True)
    return result.stdout.split()


def fields(table, kind, pin):
    body = table.split('mt6893_pin_' + kind + '_range[] = {', 1)[1].split('};', 1)[0]
    for match in re.finditer(r'(PINS?_FIELD_BASE)\(([^)]+)\)', body):
        first, last, bank, address, stride, bit, width = [int(v.strip(), 0)
                                                        for v in match[2].split(',')]
        if first <= pin <= last:
            shift = bit if match[1] == 'PINS_FIELD_BASE' else bit + (pin - first) * width
            return (bank, address + (shift // 32) * stride), shift % 32, width
    raise ValueError((kind, pin))


def apply(dtb, state, registers, table):
    paths = [PIO + '/' + item for item in state]
    found = set()
    assigned = {}

    def update(key, mask, value):
        registers[key] = (registers[key] & ~mask) | (value & mask)

    nodes = [path + '/' + group for path in paths for group in fdt(dtb, path, option='-l')]
    for node in nodes:
        props = fdt(dtb, node, option='-p')
        for cell in fdt(dtb, node, 'pinmux'):
            packed = int(cell, 16)
            pin, mode = packed >> 8, packed & 0xff
            assert pin not in found
            found.add(pin)
            key, shift = (0, 0x300 + (pin // 8) * 0x10), (pin % 8) * 4
            update(key, 0xf << shift, mode << shift)
            if 'drive-strength' in props:
                strength = int(fdt(dtb, node, 'drive-strength')[0], 16)
                assert 2 <= strength <= 16 and strength % 2 == 0
                value = strength // 2 - 1  # actual DRV_GRP4 descriptor
                key, shift, width = fields(table, 'drv', pin)
                field = (key, shift, width)
                assert field not in assigned or assigned[field] == value
                assigned[field] = value
                update(key, ((1 << width) - 1) << shift, value << shift)
            if 'output-high' in props or 'output-low' in props:
                update((0, 0x150), 1 << 20, int('output-high' in props) << 20)
                update((0, 0x50), 1 << 20, 1 << 20)
            if 'output-disable' in props:
                update((0, 0x50), 1 << 20, 0)
            for bias, up in [('bias-pull-up', True), ('bias-pull-down', False)]:
                if bias not in props:
                    continue
                for kind, enabled in [('pu', up), ('pd', not up)]:
                    key, shift, width = fields(table, kind, pin)
                    assert width == 1
                    update(key, 1 << shift, int(enabled) << shift)
    assert found == set(range(172, 183)), found


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('dtb', type=Path)
    args = parser.parse_args()
    consumer = '/conn-preflight'
    names = ['conn-active', 'conn-idle', 'strap-prepare', 'strap-high',
             'strap-mux', 'strap-low', 'strap-input']
    states = [['conn-active-pins', 'conn180-active-pins'], ['conn-idle-pins']]
    states += [['conn-active-pins', 'conn180-' + name + '-pins']
               for name in ['prepare', 'high', 'mux', 'low', 'input']]
    assert fdt(args.dtb, consumer, 'pinctrl-names', '-t s') == names
    for i, state in enumerate(states):
        expected = [fdt(args.dtb, PIO + '/' + node, 'phandle')[0] for node in state]
        assert fdt(args.dtb, consumer, f'pinctrl-{i}') == expected
    table = TABLE.read_text()
    vendor = VENDOR.read_text().split('void consys_set_if_pinmux_mt6893(', 1)[1]
    vendor = vendor.split('/* If TCXO mode', 1)[0]
    # These values are extracted from the first-on vendor block, not a
    # duplicate of the new DT. SET/CLR aliases are modeled as field effects.
    writes = re.findall(r'CONSYS_REG_WRITE_MASK\(\s*(\w+) \+ (\w+),\s*(0x[0-9a-f]+),\s*(0x[0-9a-f]+)\)', vendor)
    assert len(writes) == 6, writes
    keys = {'GPIO_MODE21': (0, 0x450), 'GPIO_MODE22': (0, 0x460),
            'IOCFG_RT_DRV_CFG0': (5, 0),
            'IOCFG_RT_PD_CFG0_CLR': (5, 0x50),
            'IOCFG_RT_PU_CFG0_SET': (5, 0x70)}
    cases = []
    for seed in (0, 0xffffffff, 0xa5a5a5a5, 0xdeadbeef):
        actual = {key: seed for key in keys.values()}
        expected = dict(actual)
        for _, offset, value, mask in writes:
            key = keys[offset]
            value, mask = int(value, 16), int(mask, 16)
            if offset.endswith('_CLR'):
                expected[key] &= ~value
            elif offset.endswith('_SET'):
                expected[key] |= value
            else:
                expected[key] = (expected[key] & ~mask) | (value & mask)
        apply(args.dtb, states[0], actual, table)
        assert actual == expected, (actual, expected)
        apply(args.dtb, states[1], actual, table)
        expected[(0, 0x450)] &= ~0xffff0000
        expected[(0, 0x460)] &= ~0x0fffffff
        expected[(5, 0x50)] |= 0x4800
        expected[(5, 0x70)] &= ~0x4800
        assert actual == expected
        cases.append({'initial_register_fill': hex(seed),
                      'active_matches_vendor': True, 'idle_matches_vendor': True})
    strap_cases = []
    for seed in (0, 0xffffffff, 0xa5a5a5a5, 0xdeadbeef):
        registers = {key: seed for key in keys.values()}
        registers[(0, 0x50)] = seed & ~(1 << 20)
        registers[(0, 0x150)] = seed & ~(1 << 20)
        registers[(5, 0xc0)] = seed & ~(1 << 7)
        apply(args.dtb, states[0], registers, table)
        baseline = dict(registers)
        sequence = [(2, 1, 1, 1), (3, 0, 1, 1), (4, 1, 1, 1),
                    (5, 1, 1, 0), (6, 1, 0, 0), (0, 1, 0, 0)]
        for state, mode, direction, latch in sequence:
            apply(args.dtb, states[state], registers, table)
            expected = dict(baseline)
            expected[(0, 0x460)] = (expected[(0, 0x460)] & ~0xf0000) | (mode << 16)
            expected[(0, 0x50)] = (expected[(0, 0x50)] & ~(1 << 20)) | (direction << 20)
            expected[(0, 0x150)] = (expected[(0, 0x150)] & ~(1 << 20)) | (latch << 20)
            assert registers == expected, (state, registers, expected)
        assert registers == baseline
        strap_cases.append({'seed': hex(seed), 'all_six_transitions_match': True})
    print(json.dumps({'strap_cases': strap_cases, 'cases': cases, 'gpio155_included': False,
                      'automatic_boot_selection': False, 'explicit_consumer': '/conn-preflight',
                      'inputs': {str(p): hashlib.sha256(p.read_bytes()).hexdigest()
                                 for p in (TABLE, VENDOR, args.dtb)},
                      'limits': 'Offline final-field model; not a hardware or driver lifecycle test.'},
                     indent=2))


if __name__ == '__main__':
    main()
