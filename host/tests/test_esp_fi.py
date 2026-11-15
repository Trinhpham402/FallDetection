import csv
from dataclasses import replace
import json
from pathlib import Path
import shutil
import struct
import subprocess
import sys
import tempfile
import unittest

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))
from host.collector import CaptureWriter, parse_datagram
from host.export_esp_fi import amplitude52, collect_trial, read_packets, write_mat


def csi(seq=0, stamp=1_000_000, node=1, value=5):
    # Build using fixed documented wire offsets, independently of parser Struct.
    raw = bytearray(168)
    raw[:4] = b'WCS2'
    raw[4:10] = bytes([node, 11, 214, 166, 0, 1])
    struct.pack_into('<HIQ', raw, 10, 128, seq, stamp)
    raw[24:30] = bytes.fromhex('020304050607')
    raw[30] = 1
    struct.pack_into('<I', raw, 36, stamp & 0xffffffff)
    raw[40:] = bytes([0, value]) * 64
    return bytes(raw)


class ProfileTests(unittest.TestCase):
    def test_wcs2_storage_signed_data_and_malformed_phy(self):
        raw = csi()
        packet = parse_datagram(raw)
        self.assertEqual((packet.profile, packet.channel, packet.rx_hw_us), (1, 11, 1_000_000))
        self.assertEqual(packet.iq_len, 128)
        for offset, value in [(4, 3), (5, 14), (8, 2), (9, 0), (10, 126),
                              (30, 0), (31, 1), (32, 1), (33, 1), (34, 1), (35, 1)]:
            broken = bytearray(raw)
            broken[offset] = value
            with self.subTest(offset=offset), self.assertRaises(ValueError):
                parse_datagram(broken)
        for broken in (raw[:39], raw[:-1], raw + b'\0'):
            with self.assertRaises(ValueError):
                parse_datagram(broken)
        signed = bytearray(raw)
        signed[40:44] = bytes.fromhex('807fff00')
        with tempfile.TemporaryDirectory() as temporary:
            prefix = Path(temporary) / 'sample'
            with CaptureWriter(prefix) as writer:
                writer.write(signed, '127.0.0.1', '2026-11-14T00:00:00Z', 1)
            with prefix.with_suffix('.csv').open() as stream:
                row = next(csv.DictReader(stream))
            self.assertEqual(json.loads(row['data'])[:4], [-128, 127, -1, 0])
            self.assertEqual(row['profile'], '1')
            self.assertEqual(list(read_packets(prefix.with_suffix('.dat')))[0].iq, signed[40:])

    @unittest.skipUnless(shutil.which('cc'), 'host C compiler unavailable')
    def test_actual_firmware_encoder_matches_host(self):
        source = '''#include <stdio.h>
#include "protocol.h"
int main(void) {
    uint8_t out[CSI_HEADER_BYTES + CSI_MAX_BYTES];
    uint8_t mac[6] = {2,3,4,5,6,7}; int8_t iq[128];
    for (int i=0; i<128; ++i) iq[i] = i % 2 ? 5 : 0;
    size_t n = encode_csi(out, 1, 11, -42, -90, false, 0, 1000000,
        mac, iq, 128, 1, 0, 0, 0, 0, 0, 1000000);
    return fwrite(out, 1, n, stdout) == n ? 0 : 1;
}'''
        with tempfile.TemporaryDirectory() as temporary:
            path = Path(temporary)
            (path / 'encoder.c').write_text(source)
            subprocess.run(['cc', '-std=c11', '-Wall', '-Wextra', '-Werror',
                            '-I', str(ROOT / 'wifi_csi_rx/main'),
                            str(path / 'encoder.c'), '-o', str(path / 'encoder')], check=True, capture_output=True)
            raw = subprocess.check_output([str(path / 'encoder')])
        self.assertEqual(raw, csi())
        self.assertEqual(amplitude52(parse_datagram(raw)), [5.0] * 52)

    def test_frequency_mapping_and_invalid_word(self):
        packet = parse_datagram(csi())
        # k=0..31,-32..-1: index value identifies each source carrier.
        raw = bytes(x for index in range(64) for x in (0, index))
        values = amplitude52(replace(packet, iq=raw))
        self.assertEqual(len(values), 52)
        self.assertEqual(values[:6], [36, 37, 38, 39, 40, 41])  # -28 through -23
        self.assertEqual(values[24:29], [62, 63, 1, 2, 3])
        self.assertEqual(values[-1], 28)
        for excluded_index in (0, 7, 21, 43, 57):
            self.assertNotIn(excluded_index, values)  # DC and four pilots
        self.assertEqual(amplitude52(replace(packet, iq=bytes([3, 4]) * 64)), [5.0] * 52)
        for invalid in (replace(packet, flags=1), replace(packet, profile=None)):
            with self.assertRaises(ValueError):
                amplitude52(invalid)


class TrialTests(unittest.TestCase):
    def test_jitter_interpolation_and_rx_isolation(self):
        packets = []
        for index in range(951):
            stamp = 1_000_000 + index * 10_000 + (1000 if index % 2 else 0)
            packets.append(parse_datagram(csi(index, stamp, value=10 if index % 2 else 0)))
            packets.append(parse_datagram(csi(index, 100 + index * 10_000, node=2, value=80)))
        matrix, metadata = collect_trial(packets, 1)
        self.assertEqual((len(matrix), len(matrix[0])), (950, 52))
        self.assertAlmostEqual(matrix[1][0], 100 / 11)
        self.assertTrue(all(0 <= v <= 10 for row in matrix for v in row))
        self.assertEqual(metadata['rx_start_us'], 1_000_000)
        self.assertFalse(metadata['upstream_subcarrier_equivalence_verified'])

    def test_reject_gaps_slow_rate_clock_and_identity_changes(self):
        def packets(period=10_000):
            return [parse_datagram(csi(i, 1_000_000 + i * period)) for i in range(951)]
        for period in (50_000, 12_000):
            with self.subTest(period=period), self.assertRaises(ValueError):
                collect_trial(packets(period), 1)
        for replacement in (replace(packets()[1], rx_local_us=1_000_000),
                            replace(packets()[1], rx_local_us=1_100_000),
                            replace(packets()[1], channel=6),
                            replace(packets()[1], csi_seq=0)):
            trial = packets()
            trial[1] = replacement
            with self.assertRaises(ValueError):
                collect_trial(trial, 1)
        with self.assertRaises(ValueError):
            collect_trial(packets()[:100], 1)
        many_lost = [replace(p, csi_seq=p.csi_seq * 2) for p in packets()]
        with self.assertRaisesRegex(ValueError, 'sequence loss'):
            collect_trial(many_lost, 1)

    def test_start_time_and_sequence_wrap(self):
        packets = [parse_datagram(csi((0xffffff00 + i) & 0xffffffff,
                                     1_000_000 + i * 10_000)) for i in range(1050)]
        _, metadata = collect_trial(packets, 1, start_us=2_000_000)
        self.assertEqual(metadata['rx_start_us'], 2_000_000)
        self.assertEqual(metadata['sequence_gaps'], 0)

    def test_cli_mat_layout_manifest_and_no_overwrite(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            capture = root / 'trial.dat'
            capture.write_bytes(b''.join(struct.pack('<I', 168) + csi(i, 1_000_000 + i * 10_000)
                                         for i in range(950)))
            command = [sys.executable, '-B', str(ROOT / 'host/export_esp_fi.py'), str(capture),
                       '--out', str(root / 'dataset'), '--node', '1', '--label', 'fall',
                       '--subject', '2', '--scenario', '1', '--trial', '1', '--split', 'train_amp']
            completed = subprocess.run(command, capture_output=True, text=True)
            self.assertEqual(completed.returncode, 0, completed.stderr)
            mat = root / 'dataset/rx1/train_amp/fall/1-2-7-1.mat'
            blob = mat.read_bytes()
            self.assertEqual(blob[126:128], b'IM')
            self.assertEqual(struct.unpack_from('<ii', blob, 160), (950, 52))
            self.assertEqual(blob[176:182], b'CSIamp')
            self.assertEqual(len(blob), 395392)
            self.assertEqual(struct.unpack_from('<d', blob, 192), (5.0,))
            metadata = json.loads(mat.with_suffix('.json').read_text())
            self.assertEqual((metadata['label'], metadata['label_index']), ('fall', 1))
            self.assertEqual(metadata['native_rate_hz'], 100)
            self.assertNotEqual(subprocess.run(command, capture_output=True).returncode, 0)
            # An independent MAT reader is also exercised by the validation command.
            variable = [[float(row * 100 + col) for col in range(52)] for row in range(950)]
            varied = root / 'varied.mat'
            write_mat(varied, variable)
            data = varied.read_bytes()
            self.assertEqual(struct.unpack_from('<d', data, 192 + 8 * 950), (1.0,))
            self.assertEqual(struct.unpack_from('<d', data, 192 + 8), (100.0,))

    def test_truncated_dat_rejected(self):
        for raw in (b'\x01', struct.pack('<I', 10000), struct.pack('<I', 168) + b'WCS2'):
            with tempfile.TemporaryDirectory() as temporary:
                path = Path(temporary) / 'bad.dat'
                path.write_bytes(raw)
                with self.assertRaises(ValueError):
                    list(read_packets(path))


if __name__ == '__main__':
    unittest.main()
