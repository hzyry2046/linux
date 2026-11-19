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
    def test_reconnect_waits_for_packet_attach_without_rat_override(self):
        events = []

        def at(command):
            self.assertEqual(command, 'AT+CGATT?')
            events.append('check attach')
            if events.count('check attach') == 1:
                return ['+CGATT: 0', 'OK']
            return ['+CGATT: 1', 'OK']

        def session(*_args):
            events.append('activate')
            return events.count('activate') == 2

        args = SimpleNamespace(slot=2, rat=None, reconnects=1)
        with (patch.object(modem, 'select_data_slot', return_value=at),
              patch.object(modem, 'run_session', side_effect=session),
              patch.object(modem.time, 'sleep'), contextlib.redirect_stdout(io.StringIO())):
            self.assertEqual(modem.run_modem(0, args, lambda: False), 0)
        self.assertEqual(events, ['activate', 'check attach', 'check attach', 'activate'])

    def test_rat_policy_is_restored_after_session_failure(self):
        calls = []
        profile = ('6', '4')

        def at(text, timeout=8):
            nonlocal profile
            if text == 'AT+ERAT?':
                return [f'+ERAT: 7,0,{",".join(profile)},0', 'OK']
            if text.startswith('AT+ERAT='):
                profile = tuple(text[8:].split(','))
                calls.append(profile)
            return ['OK']

        args = SimpleNamespace(slot=2, rat='nr-lte', policy_routing=True, reconnects=0)
        with (patch.object(modem, 'select_data_slot', return_value=at),
              patch.object(modem, 'wait_for_rat'),
              patch.object(modem, 'run_session', side_effect=modem.AtError('test failure'))):
            with self.assertRaisesRegex(modem.AtError, 'test failure'):
                modem.run_modem(0, args, lambda: False)
        self.assertEqual(calls, [('19', '128'), ('6', '4')])

    def test_ra_retry_while_ipv4_and_cid_stay_active(self):
        now = 0
        active = False
        actions = []
        args = SimpleNamespace(policy_routing=True, targets=[], apn='test',
                               ipv4_only=False, probe=False, seconds=8, radio_status=False,
                               activation_mapping=False)

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
              patch.object(modem, 'check_interface'),
              contextlib.ExitStack() as stack):
            with self.assertRaisesRegex(modem.AtError, 'PDP already active'):
                args = SimpleNamespace(slot=1, restore_slot=2, policy_routing=False)
                modem.select_data_slot(None, None, args, stack)
        self.assertEqual([call.args[:2] for call in mux.exchange.call_args_list],
                         [(3, 'AT+CGACT?'), (8, 'AT+CGACT?')])

    def test_selection_restores_slot_even_after_missing_ack(self):
        mux = Mock()

        def exchange(_dlci, text, _timeout, prefix=None):
            if text == 'AT+EDATASIM=2':
                raise modem.AtError('missing ack')
            return ['+CGACT: 1,0', 'OK'] if prefix else ['OK']

        mux.exchange.side_effect = exchange
        args = SimpleNamespace(slot=2, restore_slot=1, policy_routing=False)
        with (patch.object(modem, 'BasicMux', return_value=mux),
              patch.object(modem, 'check_interface'),
              contextlib.redirect_stdout(io.StringIO()), contextlib.ExitStack() as stack):
            with self.assertRaisesRegex(modem.AtError, 'missing ack'):
                modem.select_data_slot(None, None, args, stack)
        self.assertEqual([call.args[:2] for call in mux.exchange.call_args_list][-2:],
                         [(3, 'AT+EDATASIM=2'), (3, 'AT+EDATASIM=1')])

    def test_radio_status_omits_placeholders_and_identifiers(self):
        replies = {
            'AT+COPS?': ['+COPS: 0,0,"carrier",11', 'OK'],
            'AT+EPHYCONFIG=2': ['+EPHYCONFIG: 1,0,0,0,0,0,0,0',
                               '+EPHYCONFIG: 128,504990,503172,20000,20000,41,987,1',
                               '+EPHYCONFIG: 4,1850,2,20000,0,3,654,1,extra', 'OK'],
        }
        with contextlib.redirect_stdout(io.StringIO()) as out:
            modem.report_radio(replies.__getitem__)
        self.assertEqual(out.getvalue().splitlines(), [
            'COPS AcT: 11',
            'Physical channel: NR n41, DL/UL channel 504990/503172, '
            'DL/UL bandwidth fields 20000/20000',
        ])

    def test_activation_mapping_detects_repeated_and_ambiguous_requests(self):
        before = (8, {0: (0, 3), 1: (0, 5)})
        self.assertEqual(modem.activation_mapping(before, (9, {0: (0, 3), 1: (0, 6)})),
                         (1, 0))
        for after in (before, (10, {0: (0, 4), 1: (0, 6)}),
                      (9, {0: (0, 3), 1: (0, 5)})):
            with self.subTest(after=after), self.assertRaises(modem.AtError):
                modem.activation_mapping(before, after)


if __name__ == '__main__':
    unittest.main()
