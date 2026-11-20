import contextlib
import csv
import io
import json
from pathlib import Path
import queue
import shutil
import signal
import socket
import struct
import subprocess
import sys
import tempfile
import threading
import time
import unittest
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / 'host'))
import collector


def csi(node=1, seq=1, legacy=False):
    iq = struct.pack('4b', -128, 127, -1, 0) * 32
    mac = bytes.fromhex('7ce8b1b272d0')
    if legacy:
        return collector.CSI_HEADER.pack(
            b'WCS1', node, 6, -45, -95, 1, 128, seq, 1000000, mac) + iq
    return collector.CSI_V2_HEADER.pack(
        b'WCS2', node, 6, -45, -95, 1, 1, 128, seq, 1000000, mac,
        1, 0, 0, 0, 0, 0, 2000000) + iq


def event():
    return collector.TX_EVENT.pack(
        b'WTX1', 1, 6, -45, 0, 3, 100, 200, bytes.fromhex('7ce8b1b272d0'))


class ProtocolTests(unittest.TestCase):
    def test_six_csv_columns_and_raw_iq_for_both_protocols(self):
        stream = io.StringIO()
        writer = collector.CsvWriter(stream)
        for legacy in (False, True):
            packet = collector.parse_datagram(csi(seq=0xffffffff, legacy=legacy))
            self.assertTrue(writer.write(packet))
        self.assertFalse(writer.write(collector.parse_datagram(event())))
        reader = csv.DictReader(io.StringIO(stream.getvalue()))
        self.assertEqual(reader.fieldnames, ['timestamp', 'csi_seq', 'node_id', 'mac', 'len', 'buf'])
        rows = list(reader)
        self.assertEqual(len(rows), 2)
        for row in rows:
            self.assertEqual(row['timestamp'], '1000000')
            self.assertEqual(row['csi_seq'], '4294967295')
            self.assertEqual(row['node_id'], '1')
            self.assertEqual(row['mac'], '7C:E8:B1:B2:72:D0')
            self.assertEqual(row['len'], '128')
            self.assertEqual(json.loads(row['buf']), [-128, 127, -1, 0] * 32)

    def test_malformed_packets(self):
        invalid = [b'', b'nope', csi()[:-1], csi() + b'0', event()[:-1]]
        for source, index, value in [
            (csi(), 4, 3), (csi(), 5, 0), (csi(), 8, 2),
            (csi(), 9, 2), (csi(), 10, 126), (csi(), 30, 0),
            (csi(), 31, 1), (csi(), 32, 1), (csi(), 33, 1),
            (csi(), 34, 1), (csi(), 35, 1),
            (csi(legacy=True), 9, 1), (csi(legacy=True), 30, 1),
            (csi(legacy=True), 10, 127), (event(), 7, 1),
            (event(), 4, 0),
        ]:
            data = bytearray(source)
            data[index] = value
            invalid.append(bytes(data))
        for data in invalid:
            with self.subTest(data=data[:40]), self.assertRaises(ValueError):
                collector.parse_datagram(data)

    @unittest.skipUnless(shutil.which('cc'), 'requires C compiler')
    def test_actual_firmware_encoder(self):
        source = '''
#include <stdio.h>
#include "protocol.h"
int main(void) {
    uint8_t out[552], mac[6] = {0x7c,0xe8,0xb1,0xb2,0x72,0xd0};
    int8_t iq[128];
    for (int i = 0; i < 128; ++i) iq[i] = (int8_t)(i - 64);
    size_t n = encode_csi(out,2,6,-45,-95,true,42,1234567,mac,iq,128,
                          1,0,0,0,0,0,7654321);
    return fwrite(out,1,n,stdout) == n ? 0 : 1;
}
'''
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp)
            (path / 'probe.c').write_text(source)
            subprocess.run(['cc', '-std=c11', '-Wall', '-Wextra', '-Werror',
                            '-I', str(ROOT / 'wifi_csi_rx/main'), str(path / 'probe.c'),
                            '-o', str(path / 'probe')], check=True, capture_output=True)
            raw = subprocess.check_output([str(path / 'probe')])
        packet = collector.parse_datagram(raw)
        self.assertEqual((packet.node_id, packet.csi_seq, packet.rx_local_us),
                         (2, 42, 1234567))
        self.assertEqual(struct.unpack('128b', packet.iq), tuple(range(-64, 64)))


class CaptureTests(unittest.TestCase):
    def test_idle_deadline_and_stale_queue(self):
        with socket.socket(socket.AF_INET, socket.SOCK_DGRAM) as receiver, \
                socket.socket(socket.AF_INET, socket.SOCK_DGRAM) as sender:
            receiver.bind(('127.0.0.1', 0))
            receiver.setblocking(False)
            sender.sendto(csi(seq=999), receiver.getsockname())
            stream = io.StringIO()
            start = time.monotonic()
            with patch.object(collector, 'CAPTURE_SECONDS', 0.08), \
                    contextlib.redirect_stdout(io.StringIO()):
                stats = collector.capture(receiver, stream)
        self.assertGreaterEqual(time.monotonic() - start, 0.08)
        self.assertLess(time.monotonic() - start, 1)
        self.assertEqual(stats.counts, {1: 0, 2: 0})
        self.assertEqual(list(csv.DictReader(io.StringIO(stream.getvalue()))), [])

    def test_existing_output_is_untouched(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / 'trial.csv'
            path.write_text('existing capture')
            with self.assertRaises(FileExistsError):
                collector.run('127.0.0.1', 0, path, 0)
            self.assertEqual(path.read_text(), 'existing capture')

    def start_cli(self, path):
        process = subprocess.Popen(
            [sys.executable, '-B', str(ROOT / 'host/collector.py'),
             '--bind', '127.0.0.1', '--port', str(self.port), '--out', str(path)],
            stdin=subprocess.PIPE, stdout=subprocess.PIPE, stderr=subprocess.STDOUT,
            text=True, bufsize=1)
        messages = queue.Queue()
        output = []

        def read_output():
            for line in process.stdout:
                output.append(line)
                messages.put(line)

        reader = threading.Thread(target=read_output)
        reader.start()

        def cleanup():
            if process.poll() is None:
                process.kill()
            process.wait(timeout=5)
            reader.join(timeout=5)
            process.stdin.close()
            process.stdout.close()

        self.addCleanup(cleanup)

        def wait_for(text):
            deadline = time.monotonic() + 5
            while time.monotonic() < deadline:
                line = messages.get(timeout=max(0.01, deadline - time.monotonic()))
                if text in line:
                    return
            self.fail(f'missing output: {text}; {output}')

        wait_for('Listening UDP')
        return process, wait_for, output

    def setUp(self):
        # Reserve an ephemeral port number; the collector owns the actual socket.
        with socket.socket(socket.AF_INET, socket.SOCK_DGRAM) as sock:
            sock.bind(('127.0.0.1', 0))
            self.port = sock.getsockname()[1]

    def test_udp_interactive_countdown_and_full_17_second_trial(self):
        with tempfile.TemporaryDirectory() as tmp, \
                socket.socket(socket.AF_INET, socket.SOCK_DGRAM) as sender:
            path = Path(tmp) / 'trial.csv'
            process, wait_for, output = self.start_cli(path)
            address = ('127.0.0.1', self.port)
            stale = bytearray(csi(seq=998))
            struct.pack_into('<Q', stale, 16, 9999999)
            sender.sendto(stale, address)
            process.stdin.write('bad\n1\n')
            process.stdin.flush()
            wait_for('Bắt đầu sau:')
            sender.sendto(stale, address)
            self.assertFalse(path.exists())
            wait_for('Đang ghi CSI')
            started = time.monotonic()
            sender.sendto(csi(node=1, legacy=True), address)
            sender.sendto(csi(node=2), address)
            sender.sendto(event(), address)
            sender.sendto(b'invalid datagram', address)
            process.wait(timeout=21)
            self.assertGreater(time.monotonic() - started, 16.8)
            self.assertEqual(process.returncode, 0)
            with path.open() as stream:
                rows = list(csv.DictReader(stream))
            self.assertEqual([row['node_id'] for row in rows], ['1', '2'])
            self.assertEqual([row['timestamp'] for row in rows], ['1000000', '1000000'])
            self.assertEqual([row['csi_seq'] for row in rows], ['1', '1'])
            self.assertTrue(all(set(row) == {'timestamp', 'csi_seq', 'node_id', 'mac', 'len', 'buf'}
                                for row in rows))
            self.assertTrue(all(json.loads(row['buf']) == [-128, 127, -1, 0] * 32
                                for row in rows))
            self.assertTrue(any('Gói lỗi: 1; WTX1 đã bỏ qua: 1' in line for line in output))

    def test_ctrl_c_preserves_partial_csv(self):
        with tempfile.TemporaryDirectory() as tmp, \
                socket.socket(socket.AF_INET, socket.SOCK_DGRAM) as sender:
            path = Path(tmp) / 'partial.csv'
            process, wait_for, output = self.start_cli(path)
            process.stdin.write('0\n')
            process.stdin.flush()
            wait_for('Đang ghi CSI')
            sender.sendto(csi(), ('127.0.0.1', self.port))
            wait_for('RX1: 1 CSI')
            process.send_signal(signal.SIGINT)
            process.wait(timeout=5)
            self.assertEqual(process.returncode, 130)
            with path.open() as stream:
                self.assertEqual(len(list(csv.DictReader(stream))), 1)


if __name__ == '__main__':
    unittest.main()
