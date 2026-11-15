#!/usr/bin/env python3
# SPDX-License-Identifier: GPL-2.0-only
"""Build the optional ACK 6.6 observer; never connect, upload or load it."""
import argparse
from pathlib import Path
import shutil
import subprocess

parser = argparse.ArgumentParser(description=__doc__)
parser.add_argument('--common', type=Path, required=True)
parser.add_argument('--out', type=Path, required=True)
parser.add_argument('--scp-symvers', type=Path, required=True)
parser.add_argument('--stage', type=Path, required=True)
parser.add_argument('--llvm', type=Path, default=Path('/usr/lib/llvm18/bin'))
parser.add_argument('--sign-key', type=Path)
parser.add_argument('--sign-cert', type=Path)
args = parser.parse_args()
if bool(args.sign_key) != bool(args.sign_cert):
    parser.error('--sign-key and --sign-cert must be supplied together')
tools = Path(__file__).resolve().parent
kernel = tools.parents[4]
stage = args.stage.resolve()
if stage.exists():
    raise SystemExit('Use a new staging directory; refusing to overwrite it')
if (args.out / 'include/config/kernel.release').read_text().strip() != '6.6.30-4k-g6974e26f087e':
    raise SystemExit('This observer was audited only for the current ACK 6.6 build')
stage.mkdir(parents=True)
for src in (tools / 'scp-cache-observe').iterdir():
    if src.is_file():
        shutil.copy2(src, stage / src.name)
for name in ('ccci-scp-memory.c', 'ccci-scp-memory.h'):
    shutil.copy2(kernel / 'drivers/misc/mediatek/ccci' / name, stage / name)
# Mainline moved the public unaligned header; preserve the tested C unchanged.
compat = stage / 'compat/linux'
compat.mkdir(parents=True)
(compat / 'unaligned.h').write_text('#include <asm/unaligned.h>\n')
mrel = '../android_kernel_modules_oneplus_mt6833/kernel/kernel_device_modules-6.6'
subprocess.run([
    'make', '-C', str(args.common.resolve()), f'O={args.out.resolve()}',
    'ARCH=arm64', f'LLVM={args.llvm}/', f'M={stage}',
    f'KCONFIG_EXT_PREFIX={mrel}/', f'DEVICE_MODULES_REL_DIR={mrel}',
    f'KBUILD_EXTRA_SYMBOLS={args.scp_symvers.resolve()}', '-j4', 'modules',
], check=True)
module = stage / 'op6893_scp_cache.ko'
if args.sign_key:
    # Existing ACK packaging policy; never disable MODULE_SIG_PROTECT.
    subprocess.run([str(args.out.resolve() / 'scripts/sign-file'), 'sha1',
                    str(args.sign_key.resolve()), str(args.sign_cert.resolve()),
                    str(module)], check=True)
print(module)
