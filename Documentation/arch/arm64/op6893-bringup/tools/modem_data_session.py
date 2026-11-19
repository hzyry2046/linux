#!/usr/bin/env python3
# SPDX-License-Identifier: GPL-2.0-only
"""Run a foreground op6893 dual-stack session after HS2 and DL ring setup."""
import argparse
from contextlib import ExitStack
import fcntl
import ipaddress
import json
import os
from pathlib import Path
import re
import signal
import subprocess
import time

from modem_at_probe import AtError, FdReader, command, establish
from modem_ipv6_probe import IFACE, UL_STATUS, dns_reply, ip, pdp_iid, solicit

AT_DEVICE = '/dev/ccci-at-10209000.modem-platform'
MD_NET = Path('/sys/devices/platform/10209000.modem-platform/md_net')
RESOLVERS = ('8.8.8.8', '2001:4860:4860::8888')
POLICY_TABLE = '6893'
POLICY_PRIORITY = 11000


class AddressPending(AtError):
    pass


def context_active(at):
    lines = at('AT+CGACT?')
    for line in lines:
        state = re.fullmatch(r'\+CGACT:\s*1,\s*([01])', line)
        if state:
            return state[1] == '1'
    raise AtError('missing CID 1 status')


def tx_queue(status):
    mapping = re.search(r'^lhif\d+ net_if=0 lhif_q=\d+ queue=([0-3])$', status, re.M)
    if not mapping:
        raise AtError('missing queue mapping for CCMNI channel 0')
    return int(mapping[1])


def check_interface():
    link = json.loads(ip('-j', 'link', 'show', 'dev', IFACE).stdout)[0]
    addresses = json.loads(ip('-j', 'addr', 'show', 'dev', IFACE).stdout)
    if 'UP' in link['flags'] or any(dev.get('addr_info') for dev in addresses):
        raise AtError(f'{IFACE} must start down and without configured addresses')


def check_policy_routes():
    for family in ('-4', '-6'):
        try:
            rules = json.loads(ip('-N', '-j', family, 'rule', 'show').stdout)
            routes = json.loads(ip('-N', '-j', family, 'route', 'show', 'table', 'all').stdout)
        except subprocess.CalledProcessError:
            raise AtError('policy routing requires IPv4 and IPv6 multiple tables') from None
        # Numeric output avoids overlooking a table with an alias in rt_tables.
        if any(rule.get('priority') == POLICY_PRIORITY for rule in rules):
            raise AtError(f'policy rule priority {POLICY_PRIORITY} is in use')
        if any(str(item.get('table')) == POLICY_TABLE for item in rules + routes):
            raise AtError(f'policy routing table {POLICY_TABLE} is in use')


def setup_policy_routes(stack, v4, v6):
    for family, src in (('-4', v4), ('-6', v6)):
        route = ('default', 'dev', IFACE, 'src', str(src), 'table', POLICY_TABLE)
        rule = ('priority', str(POLICY_PRIORITY), 'oif', IFACE, 'table', POLICY_TABLE)
        ip(family, 'route', 'add', *route)
        stack.callback(ip, family, 'route', 'del', *route)
        ip(family, 'rule', 'add', *rule)
        stack.callback(ip, family, 'rule', 'del', *rule)


def setup_link(stack, v4, iid, targets, policy_routing):
    conf = Path('/proc/sys/net/ipv6/conf', IFACE)
    for name in ('accept_ra', 'autoconf', 'router_solicitations'):
        path = conf / name
        previous = path.read_text()
        stack.callback(path.write_text, previous)
        path.write_text('0\n')

    ip('link', 'set', IFACE, 'up')
    stack.callback(ip, 'link', 'set', IFACE, 'down')

    def address(addr, family, flags=()):
        ip(family, 'addr', 'add', addr, 'dev', IFACE, *flags)
        stack.callback(ip, family, 'addr', 'del', addr, 'dev', IFACE)

    address(f'{v4}/32', '-4')
    link_local = ipaddress.IPv6Address(int(ipaddress.IPv6Address('fe80::')) | iid)
    address(f'{link_local}/64', '-6', ('nodad',))
    ra = {}
    prefix = solicit(link_local, ra, attempts=5)
    if prefix is None:
        if ra.get('ra_received'):
            raise AddressPending('IPv6 RA lacked a usable autonomous prefix')
        raise AddressPending('no IPv6 router advertisement received')
    v6 = ipaddress.IPv6Address((prefix << 64) | iid)
    address(f'{v6}/64', '-6', ('nodad', 'noprefixroute') if policy_routing else ('nodad',))
    if policy_routing:
        setup_policy_routes(stack, v4, v6)
    for dst in targets:
        family, src = ('-4', v4) if dst.version == 4 else ('-6', v6)
        target = f'{dst}/{dst.max_prefixlen}'
        ip(family, 'route', 'add', target, 'dev', IFACE, 'src', str(src))
        stack.callback(ip, family, 'route', 'del', target, 'dev', IFACE, 'src', str(src))


def deactivate(at):
    if context_active(at):
        at('AT+CGACT=0,1', 14)
    if context_active(at):
        raise AtError('CID 1 remains active after shutdown')


def run_session(at, args, stopping):
    check_interface()
    if args.policy_routing:
        check_policy_routes()
    if context_active(at):
        raise AtError('CID 1 already active; refusing to take over')
    with ExitStack() as stack:
        if args.apn:
            at(f'AT+CGDCONT=1,"IPV4V6","{args.apn}"')
        # A timeout does not prove the command failed to reach the modem.
        stack.callback(deactivate, at)
        at('AT+CGACT=1,1', 14)
        if stopping():
            return True
        response = '\n'.join(at('AT+CGPADDR=1'))
        match = re.search(r'\+CGPADDR:\s*1,"([0-9.]+)"', response)
        if not match:
            raise AtError('missing CID 1 IPv4 address')
        try:
            v4 = ipaddress.IPv4Address(match[1])
            iid = pdp_iid(response)
        except ValueError:
            raise AtError('invalid or missing dual-stack CID 1 addresses') from None
        if v4.is_unspecified:
            raise AtError('CID 1 has an unspecified IPv4 address')

        queue = tx_queue(MD_NET.read_text())
        ul = dict(field.split('=') for field in UL_STATUS.read_text().split())
        if ul['started'] == '0':
            UL_STATUS.with_name('ul_start').write_text(f'{queue} 60 0\n')
        elif int(ul['queue']) != queue:
            raise AtError('armed UL ring does not match the modem queue mapping')

        setup_link(stack, v4, iid, args.targets, args.policy_routing)
        print('CID 1 active, IPv4 and IPv6 configured', flush=True)
        if args.probe and not stopping():
            success = []
            for resolver in RESOLVERS:
                ok = any(dns_reply(resolver) for _ in range(3))
                success.append(ok)
                version = ipaddress.ip_address(resolver).version
                print(f'IPv{version} DNS: {"matched" if ok else "no match"}', flush=True)
            if not all(success):
                raise AtError('dual-stack DNS check failed')

        deadline = None if args.seconds is None else time.monotonic() + args.seconds
        while not stopping() and (deadline is None or
                                  (remaining := deadline - time.monotonic()) > 0):
            time.sleep(5 if deadline is None else min(5, remaining))
            if not context_active(at):
                print('CID 1 disconnected', flush=True)
                return False
    print('CID 1 deactivated and link cleaned up', flush=True)
    return True


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--apn', help='optionally set the CID 1 dual-stack APN')
    parser.add_argument('--target', action='append', type=ipaddress.ip_address, default=[],
                        help='install a host route through the data interface; repeatable')
    parser.add_argument('--probe', action='store_true', help='verify IPv4 and IPv6 UDP DNS')
    parser.add_argument('--policy-routing', action='store_true',
                        help='route interface-bound sockets through a dedicated dual-stack table')
    parser.add_argument('--seconds', type=int, help='stop after this many seconds online')
    parser.add_argument('--reconnects', type=int, default=2,
                        help='maximum retries on CID loss or missing IPv6 prefix (default 2)')
    args = parser.parse_args()
    if args.apn and not re.fullmatch(r'[A-Za-z0-9.-]{1,100}', args.apn):
        parser.error('invalid APN')
    if (args.seconds is not None and args.seconds < 0) or args.reconnects < 0:
        parser.error('seconds and reconnects must be nonnegative')
    if args.policy_routing and args.target:
        parser.error('--policy-routing and --target are mutually exclusive')
    args.targets = list(dict.fromkeys(args.target +
                                     ([ipaddress.ip_address(x) for x in RESOLVERS]
                                      if args.probe and not args.policy_routing else [])))

    stop_requested = False

    def stop(_signum, _frame):
        nonlocal stop_requested
        stop_requested = True

    def stopping():
        return stop_requested

    signal.signal(signal.SIGINT, stop)
    signal.signal(signal.SIGTERM, stop)
    lock = os.open('/run/op6893-data-session.lock',
                   os.O_CREAT | os.O_CLOEXEC | os.O_NOFOLLOW | os.O_RDWR, 0o600)
    try:
        fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
    except BlockingIOError:
        os.close(lock)
        raise AtError('a data session is already running') from None

    with ExitStack() as stack:
        stack.callback(os.close, lock)
        fd = os.open(AT_DEVICE, os.O_RDWR | os.O_NOFOLLOW | os.O_CLOEXEC)
        stack.callback(os.close, fd)
        return run_modem(fd, args, stopping)


def run_modem(fd, args, stopping):
    try:
        reader = FdReader(fd)

        def write(data):
            return os.write(fd, data)

        def at(text, timeout=8):
            lines = command(reader, write, text, timeout)
            if 'OK' not in lines:
                # Do not emit response payloads, which can contain carrier addresses.
                raise AtError(f'{text.split("=")[0]} failed')
            return lines

        establish(reader, write, 8)
        for retry in range(args.reconnects + 1):
            try:
                if stopping() or run_session(at, args, stopping):
                    return 0
            except AddressPending as error:
                if retry == args.reconnects:
                    raise
                print(error, flush=True)
            if retry < args.reconnects:
                print('waiting before the next CID 1 activation', flush=True)
                for _ in range(10):
                    if stopping():
                        return 0
                    time.sleep(1)
        raise AtError('CID 1 reconnect budget exhausted')
    except subprocess.CalledProcessError as error:
        raise AtError(f'{error.cmd[0]} operation failed') from None


if __name__ == '__main__':
    try:
        raise SystemExit(main())
    except AtError as error:
        raise SystemExit(str(error)) from None
    except OSError as error:
        raise SystemExit(f'local I/O failed: {error.strerror}') from None
