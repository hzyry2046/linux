#!/usr/bin/env python3
# SPDX-License-Identifier: GPL-2.0-only

import os
import unittest

from modem_at_probe import AtError, FdReader
from modem_slot_probe import BasicMux, SLOTS, UA, UIH, frame


class SlotProbeTest(unittest.TestCase):
    def setUp(self):
        read, self.write = os.pipe()
        self.addCleanup(os.close, read)
        self.addCleanup(os.close, self.write)
        self.sent = []

        def send(data):
            self.sent.append(data)
            return len(data)

        self.mux = BasicMux(FdReader(read), send)

    def feed(self, data):
        os.write(self.write, data)

    def test_vendor_sabm_wire_vectors(self):
        self.assertEqual(frame(0, 0x3f), bytes.fromhex('f9033f011cf9'))
        self.assertEqual(frame(3, 0x3f), bytes.fromhex('f90f3f019bf9'))
        self.assertEqual(frame(8, 0x3f), bytes.fromhex('f9233f01c9f9'))

    def test_open_waits_for_matching_dlci(self):
        self.feed(frame(0, UA | 0x10) + frame(3, UA | 0x10))
        with self.assertRaisesRegex(AtError, 'DLCI 8 did not acknowledge'):
            self.mux.open_channel(SLOTS[2], 0.03)
        self.assertEqual(self.sent[0][1:4], bytes.fromhex('233f01'))

    def test_slot_query_filters_foreign_frames_and_unframed_lines(self):
        self.feed(b'\r\n+CPIN: READY\r\nOK\r\n'
                  + frame(3, UIH, b'\r\n+CPIN: READY\r\nOK\r\n')
                  + frame(8, UIH, b'\r\n+CP')
                  + frame(8, UIH, b'IN: SIM PIN\r\nOK\r\n')[1:])
        self.assertEqual(self.mux.query(SLOTS[2], 'AT+CPIN?', 0.1),
                         ['+CPIN: SIM PIN', 'OK'])

    def test_long_payload_with_embedded_flag_and_bad_fcs(self):
        bad = bytearray(frame(8, UIH, b'+ERAT: 9\r\nOK\r\n'))
        bad[-2] ^= 1
        payload = b'x' * 130 + b'\xf9\r\n+ERAT: 6,4\r\nOK\r\n'
        self.feed(bad + frame(8, UIH, payload))
        self.assertEqual(self.mux.query(SLOTS[2], 'AT+ERAT?', 0.1),
                         ['+ERAT: 6,4', 'OK'])

    def test_bare_ok_is_not_a_slot_status(self):
        self.feed(frame(8, UIH, b'\r\nOK\r\n'))
        with self.assertRaisesRegex(AtError, 'returned OK without'):
            self.mux.query(SLOTS[2], 'AT+CPIN?', 0.1)


if __name__ == '__main__':
    unittest.main()
