#!/usr/bin/env python3
# SPDX-License-Identifier: GPL-2.0-only

import contextlib
import io
import ipaddress
from types import SimpleNamespace
import unittest
from unittest.mock import MagicMock, Mock, patch

import modem_data_session as modem


class SessionTest(unittest.TestCase):
    def test_ra_retry_while_ipv4_and_cid_stay_active(self):
        now = 0
        active = False
        actions = []
        args = SimpleNamespace(policy_routing=True, targets=[], apn='test',
                               ipv4_only=False, probe=False, seconds=8)

        def at(text, _timeout=0):
            nonlocal active
            if text == 'AT+CGACT?':
                return [f'+CGACT: 1,{int(active)}']
            if text == 'AT+CGPADDR=1':
                return ['+CGPADDR: 1,"192.0.2.2","0.0.0.0.0.0.0.0.0.0.0.0.0.0.0.1"']
            if text.startswith('AT+CGACT='):
                active = text == 'AT+CGACT=1,1'
                actions.append('activate' if active else 'deactivate')
            return ['OK']

        def sleep(seconds):
            nonlocal now
            now += seconds

        def solicit(_local, _report, attempts=1):
            nonlocal probes
            self.assertTrue(active)
            self.assertIn(('-4', 'rule', 'add'), actions)
            self.assertNotIn(('-4', 'rule', 'del'), actions)
            probes += 1
            return int(ipaddress.IPv6Address('2001:db8::')) >> 64 if probes > 1 else None

        probes = 0
        with (patch.object(modem, 'check_interface'), patch.object(modem, 'check_policy_routes'),
              patch.object(modem, 'Path', return_value=MagicMock()),
              patch.object(modem, 'MD_NET', Mock(**{'read_text.return_value':
                                                   'lhif0 net_if=0 lhif_q=0 queue=0'})),
              patch.object(modem, 'UL_STATUS', Mock(**{'read_text.return_value':
                                                      'started=1 queue=0'})),
              patch.object(modem, 'ip', side_effect=lambda *cmd: actions.append(cmd[:3])),
              patch.object(modem, 'solicit', side_effect=solicit),
              patch.object(modem.time, 'monotonic', side_effect=lambda: now),
              patch.object(modem.time, 'sleep', side_effect=sleep),
              contextlib.redirect_stdout(io.StringIO())):
            self.assertTrue(modem.run_session(at, args, lambda: False))
        self.assertEqual(probes, 2)
        self.assertFalse(active)
        self.assertEqual(actions.count('activate'), 1)
        self.assertEqual(actions.count('deactivate'), 1)
        self.assertLess(actions.index(('-6', 'rule', 'add')), actions.index(('-4', 'rule', 'del')))
        self.assertIn(('-6', 'rule', 'del'), actions)

    def test_selection_refuses_another_active_pdp(self):
        mux = Mock()
        mux.exchange.side_effect = lambda dlci, *_args, **_kwargs: [
            '+CGACT: 1,0', f'+CGACT: 2,{int(dlci == 8)}', 'OK']
        with (patch.object(modem, 'BasicMux', return_value=mux),
              patch.object(modem, 'check_interface')):
            with self.assertRaisesRegex(modem.AtError, 'PDP already active'):
                modem.select_data_slot(None, None, 1, False)
        self.assertEqual([call.args[:2] for call in mux.exchange.call_args_list],
                         [(3, 'AT+CGACT?'), (8, 'AT+CGACT?')])


if __name__ == '__main__':
    unittest.main()
