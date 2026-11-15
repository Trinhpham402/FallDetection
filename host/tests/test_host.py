import contextlib
import csv
import io
from pathlib import Path
import signal
import socket
import struct
import subprocess
import sys
import tempfile
import unittest

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))
from host.collector import CaptureWriter, Stats, parse_datagram, iq_to_complex, FIELDS
from host.check_capture import analyze, report

# Golden bytes from the firmware C protocol test, independent of Python structs.
CSI = bytes.fromhex('57 43 53 31 02 06 d6 a0 01 00 04 00 78 56 34 12 '
                    '08 07 06 05 04 03 02 01 02 03 04 05 06 07 00 00 80 7f ff 00')
EVENT = bytes.fromhex('57 54 58 31 01 06 d6 00 78 56 34 12 '
                      '08 07 06 05 04 03 02 01 09 00 00 00 00 00 00 00 02 03 04 05 06 07')
CSI_V2 = bytes.fromhex('57 43 53 32 02 06 d6 a0 00 01 80 00 78 56 34 12 '
                       '08 07 06 05 04 03 02 01 02 03 04 05 06 07 '
                       '01 00 00 00 00 00 09 00 00 00') + bytes([3, 4]) * 64


def event(seq, tx, rx, node=1):
    return struct.pack('<4sBBbBIQQ6s', b'WTX1', node, 6, -42, 0, seq, tx, rx,
                       bytes.fromhex('020304050607'))


class ProtocolTests(unittest.TestCase):
    def test_firmware_golden_packets(self):
        packet = parse_datagram(CSI)
        self.assertEqual((packet.node_id, packet.rssi, packet.noise), (2, -42, -96))
        self.assertEqual(packet.csi_seq, 0x12345678)
        self.assertEqual(packet.rx_local_us, 0x0102030405060708)
        self.assertEqual(packet.tx_mac, '02:03:04:05:06:07')
        self.assertEqual(packet.iq, bytes.fromhex('807fff00'))
        self.assertEqual(iq_to_complex(packet), [])
        packet = parse_datagram(EVENT)
        self.assertEqual(packet.tx_seq, 0x12345678)
        self.assertEqual(packet.tx_local_us, 0x0102030405060708)
        self.assertEqual(packet.rx_local_us, 9)
        self.assertIsNone(packet.csi_seq)
        self.assertEqual(iq_to_complex(packet), [])

    def test_signed_iq_order_and_skip(self):
        raw = bytearray(CSI)
        raw[8] = 0
        self.assertEqual(iq_to_complex(parse_datagram(raw)), [complex(127, -128), -1j])
        raw[8] = 1
        raw[10:12] = struct.pack('<H', 6)
        raw.extend(b'\x03\x04')
        self.assertEqual(iq_to_complex(parse_datagram(raw)), [4 + 3j])

    def test_invalid_datagrams(self):
        invalid = [b'', b'BAD!', CSI[:31], CSI[:-1], CSI + b'0', EVENT[:-1], EVENT + b'0']
        for offset, value in [(4, 0), (4, 3), (5, 0), (5, 14), (8, 2), (9, 1), (30, 1)]:
            raw = bytearray(CSI)
            raw[offset] = value
            invalid.append(raw)
        for size in (0, 3, 514):
            raw = bytearray(CSI[:32])
            raw[10:12] = struct.pack('<H', size)
            invalid.append(raw + bytes(size))
        raw = bytearray(EVENT)
        raw[7] = 1
        invalid.append(raw)
        for raw in invalid:
            with self.subTest(raw=raw), self.assertRaises(ValueError):
                parse_datagram(raw)

    def test_maximum_iq(self):
        raw = bytearray(CSI[:32])
        raw[10:12] = struct.pack('<H', 512)
        self.assertEqual(parse_datagram(raw + bytes(512)).iq_len, 512)

    def test_gaps_wrap_duplicates_and_restart(self):
        stats = Stats()
        for seq, tx, rx in [(0xfffffffe, 10, 10), (1, 20, 20), (1, 20, 20),
                            (0, 1, 30), (1, 2, 40)]:
            stats.add(parse_datagram(event(seq, tx, rx)))
        stats.add(parse_datagram(event(50, 50, 50, node=2)))
        self.assertEqual(stats.nodes[1], {'CSI': 0, 'TX_EVENT': 5, 'tx_gaps': 2})
        self.assertEqual(stats.nodes[2]['tx_gaps'], 0)


class CaptureTests(unittest.TestCase):
    def test_append_round_trip_and_invalid_not_saved(self):
        with tempfile.TemporaryDirectory() as temporary:
            prefix = Path(temporary) / 'nested' / 'session.01'
            for raw in (CSI, EVENT):
                with CaptureWriter(prefix) as writer:
                    writer.write(raw, '127.0.0.1', '2026-10-24T00:00:00+00:00', 123)
                    with self.assertRaises(ValueError):
                        writer.write(b'bad', '', '', 0)
            path = Path(str(prefix) + '.dat')
            self.assertEqual(path.read_bytes(), struct.pack('<I', len(CSI)) + CSI +
                             struct.pack('<I', len(EVENT)) + EVENT)
            with Path(str(prefix) + '.csv').open() as stream:
                reader = csv.DictReader(stream)
                self.assertEqual(reader.fieldnames, FIELDS)
                rows = list(reader)
            self.assertEqual(len(rows), 2)
            self.assertEqual(rows[0]['tx_seq'], '')
            self.assertEqual(rows[1]['noise'], '')
            nodes, bad = analyze(path)
            self.assertEqual(bad, 0)
            self.assertEqual(nodes[2]['counts']['CSI'], 1)
            self.assertEqual(nodes[1]['counts']['TX_EVENT'], 1)

    def test_corruption_is_bounded(self):
        record = struct.pack('<I', len(EVENT)) + EVENT
        with tempfile.TemporaryDirectory() as temporary:
            path = Path(temporary) / 'capture.dat'
            for tail in (b'\x01', struct.pack('<I', 0xffffffff),
                         struct.pack('<I', 34) + b'WT', struct.pack('<I', 0)):
                path.write_bytes(record + tail)
                nodes, bad = analyze(path)
                self.assertEqual(bad, 1)
                self.assertEqual(nodes[1]['counts']['TX_EVENT'], 1)
            path.write_bytes(struct.pack('<I', 4) + b'BAD!' + record)
            nodes, bad = analyze(path)
            self.assertEqual((bad, nodes[1]['counts']['TX_EVENT']), (1, 1))

    def test_rates_amplitude_and_regression(self):
        with tempfile.TemporaryDirectory() as temporary:
            prefix = Path(temporary) / 'capture'
            raw = bytearray(CSI[:32])
            raw[8] = 0
            raw[10:12] = struct.pack('<H', 2)
            raw.extend(b'\x03\x04')
            with CaptureWriter(prefix) as writer:
                for rx in (1000000, 1050000):
                    struct.pack_into('<Q', raw, 16, rx)
                    writer.write(raw, '', '', 0)
                for rx in (100, 50):
                    writer.write(event(1, 1, rx), '', '', 0)
            nodes, bad = analyze(str(prefix) + '.dat')
            self.assertEqual(nodes[2]['amplitude_sum'], 10)
            output = io.StringIO()
            with contextlib.redirect_stdout(output):
                report(prefix, nodes, bad)
            self.assertIn('~20.00 records/s', output.getvalue())
            self.assertIn('timestamp regression', output.getvalue())
            self.assertIn('mean=5.00', output.getvalue())

    def test_incompatible_csv(self):
        with tempfile.TemporaryDirectory() as temporary:
            prefix = Path(temporary) / 'capture'
            prefix.with_suffix('.csv').write_text('wrong,header\n')
            with self.assertRaises(ValueError):
                CaptureWriter(prefix)


class UdpTests(unittest.TestCase):
    def test_real_udp_and_ctrl_c(self):
        with tempfile.TemporaryDirectory() as temporary:
            prefix = Path(temporary) / 'udp'
            # Port zero lets the OS choose a free loopback port for this test.
            code = 'from host.collector import run; import sys; run("127.0.0.1", 0, sys.argv[1])'
            process = subprocess.Popen([sys.executable, '-u', '-c', code, str(prefix)],
                                       cwd=ROOT, stdout=subprocess.PIPE, stderr=subprocess.PIPE,
                                       text=True)
            try:
                import select
                ready, _, _ = select.select([process.stdout], [], [], 5)
                self.assertTrue(ready, 'collector did not start')
                line = process.stdout.readline()
                if not line:
                    _, errors = process.communicate(timeout=3)
                    self.fail(f'collector failed to start: {errors}')
                self.assertTrue(line.startswith('Listening UDP'), line)
                port = int(line.split(';')[0].rsplit(':', 1)[1])
                with socket.socket(socket.AF_INET, socket.SOCK_DGRAM) as sender:
                    for raw in (b'bad', CSI, EVENT, CSI_V2):
                        sender.sendto(raw, ('127.0.0.1', port))
                # Wait for the periodic flush before interrupting the collector.
                import time
                deadline = time.monotonic() + 8
                dat = prefix.with_suffix('.dat')
                expected_size = sum(4 + len(raw) for raw in (CSI, EVENT, CSI_V2))
                while time.monotonic() < deadline and dat.stat().st_size < expected_size:
                    time.sleep(0.05)
                self.assertEqual(dat.stat().st_size, expected_size)
                process.send_signal(signal.SIGINT)
                stdout, stderr = process.communicate(timeout=3)
                self.assertEqual(process.returncode, 0, stderr)
                self.assertIn('invalid=1', stdout)
                nodes, bad = analyze(dat)
                self.assertEqual(bad, 0)
                self.assertEqual(set(nodes), {1, 2})
                self.assertEqual(nodes[2]['counts']['CSI'], 2)
                self.assertEqual(nodes[2]['profiles'][1], 1)
                check = subprocess.run([sys.executable, str(ROOT / 'host/check_capture.py'), str(dat)],
                                       capture_output=True, text=True, timeout=3)
                self.assertEqual(check.returncode, 0, check.stderr)
                self.assertIn('bad=0', check.stdout)
            finally:
                if process.poll() is None:
                    process.kill()
                process.communicate()


if __name__ == '__main__':
    unittest.main()
