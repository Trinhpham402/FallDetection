#!/usr/bin/env python3
"""Export one labelled, continuous RX trial as ESP-Fi-HAR-shaped CSIamp MAT.

The 100 Hz target and HT-LTF data-carrier map are this project's explicit
collection convention. Upstream temporal/subcarrier equivalence is unverified.
No NumPy/SciPy dependency; output is a real float64 MATLAB v5 matrix.
"""
import argparse
import bisect
import json
import math
from pathlib import Path
import statistics
import struct

if __package__:
    from .collector import LENGTH, MAX_PACKET, parse_datagram
else:
    from collector import LENGTH, MAX_PACKET, parse_datagram


ROWS = 950
RATE_HZ = 100
PERIOD_US = 1_000_000 // RATE_HZ
MAX_GAP_US = 30_000
MIN_NATIVE_HZ = 90
ACTIVITIES = ('arm_wave', 'fall', 'jump', 'run', 'squat', 'turn', 'walk')
# Observed folder/filename mapping in the audited archive, NOT upstream README.
FILENAME_IDS = dict(run=1, walk=2, jump=3, squat=4, arm_wave=5, turn=6, fall=7)
PILOTS = {-21, -7, 7, 21}
SUBCARRIERS = tuple(k for k in range(-28, 29) if k != 0 and k not in PILOTS)


def amplitude52(packet):
    """Select HT20 data carriers in ascending signed frequency order.

    ESP-IDF HT20 HT-LTF buffer order is k=0..31,-32..-1. Keep absolute
    buffer indices when first_word_invalid is set; shifting would corrupt
    the frequency map. Its invalid +1 carrier makes that record unusable.
    """
    if (packet.kind != 'CSI' or packet.profile != 1 or packet.iq_len != 128
            or (packet.sig_mode, packet.cwb, packet.mcs, packet.stbc,
                packet.secondary_channel, packet.sgi) != (1, 0, 0, 0, 0, 0)):
        raise ValueError('requires WCS2 profile 1 (HT20 MCS0 HT-LTF only); recapture with the new RX firmware')
    if packet.flags & 1:
        raise ValueError('invalid first CSI word overlaps selected subcarrier +1; record cannot supply 52 valid columns')
    raw = struct.unpack('128b', packet.iq)
    return [math.hypot(raw[2 * (k % 64)], raw[2 * (k % 64) + 1]) for k in SUBCARRIERS]


def read_packets(path):
    with Path(path).open('rb') as stream:
        while prefix := stream.read(LENGTH.size):
            if len(prefix) != LENGTH.size:
                raise ValueError('truncated DAT length prefix')
            size, = LENGTH.unpack(prefix)
            if not 0 < size <= MAX_PACKET:
                raise ValueError('invalid DAT record length')
            raw = stream.read(size)
            if len(raw) != size:
                raise ValueError('truncated DAT record')
            yield parse_datagram(raw)


def collect_trial(packets, node, start_us=None):
    stamps, amplitudes, sequences = [], [], []
    identity = None
    first_packet = None
    sequence_gaps = 0
    for packet in packets:
        if packet.kind != 'CSI' or packet.node_id != node:
            continue
        if start_us is not None and packet.rx_local_us < start_us:
            if stamps:
                raise ValueError('RX clock regressed during trial; use a fresh capture')
            continue
        values = amplitude52(packet)
        key = (packet.tx_mac, packet.channel, packet.profile)
        if identity is not None and key != identity:
            raise ValueError('TX MAC/channel/profile changed during trial')
        if stamps:
            gap = packet.rx_local_us - stamps[-1]
            if gap <= 0:
                raise ValueError('duplicate/regressing RX timestamp; restart or UDP reordering')
            if gap > MAX_GAP_US:
                raise ValueError(f'CSI gap {gap / 1000:.3f} ms exceeds 30 ms; select a continuous trial with --start-us')
            delta = (packet.csi_seq - sequences[-1]) & 0xffffffff
            if not 0 < delta < 0x80000000:
                raise ValueError('CSI sequence repeated or regressed; restart/reordering')
            sequence_gaps += delta - 1
        else:
            identity, first_packet = key, packet
        stamps.append(packet.rx_local_us)
        amplitudes.append(values)
        sequences.append(packet.csi_seq)
        if stamps[-1] - stamps[0] >= (ROWS - 1) * PERIOD_US:
            break
    if not stamps or stamps[-1] - stamps[0] < (ROWS - 1) * PERIOD_US:
        raise ValueError('need at least 9.49 seconds of continuous CSI for 950 points at 100 Hz')
    native_hz = (len(stamps) - 1) * 1_000_000 / (stamps[-1] - stamps[0])
    if native_hz < MIN_NATIVE_HZ:
        raise ValueError(f'native CSI rate {native_hz:.2f} Hz below 90 Hz; do not upsample sparse legacy captures')
    if sequence_gaps / (len(stamps) + sequence_gaps) > 0.1:
        raise ValueError('more than 10% CSI sequence loss in the trial')
    # Linear time interpolation corrects bounded radio jitter. No padding,
    # extrapolation, long-gap filling, or interpolation across RX clocks.
    matrix = []
    for index in range(ROWS):
        stamp = stamps[0] + index * PERIOD_US
        right = bisect.bisect_left(stamps, stamp)
        if stamps[right] == stamp:
            matrix.append(amplitudes[right][:])
        else:
            left = right - 1
            weight = (stamp - stamps[left]) / (stamps[right] - stamps[left])
            matrix.append([a + weight * (b - a) for a, b in zip(amplitudes[left], amplitudes[right])])
    differences = [b - a for a, b in zip(stamps, stamps[1:])]
    metadata = {
        'node_id': node, 'tx_mac': first_packet.tx_mac, 'wifi_channel': first_packet.channel,
        'wire_profile': 1, 'phy': 'HT20/MCS0/long-GI/non-STBC', 'ltf': 'HT-LTF only',
        'subcarrier_indices': list(SUBCARRIERS), 'subcarrier_order': 'ascending signed frequency',
        'iq_order': 'imaginary,real', 'shape': [ROWS, 52], 'variable': 'CSIamp',
        'sample_rate_hz': RATE_HZ, 'sample_span_us': (ROWS - 1) * PERIOD_US,
        'rx_start_us': stamps[0], 'rx_end_us': stamps[0] + (ROWS - 1) * PERIOD_US,
        'native_records': len(stamps), 'native_rate_hz': native_hz,
        'native_interval_median_us': statistics.median(differences),
        'native_interval_max_us': max(differences), 'sequence_gaps': sequence_gaps,
        'interpolation': 'linear on local RX time; max gap 30 ms; native rate >=90 Hz',
        'normalization': 'none; upstream loader applies whole-sample Z-score',
        'upstream_temporal_equivalence_verified': False,
        'upstream_subcarrier_equivalence_verified': False,
    }
    return matrix, metadata


def write_mat(path, matrix):
    if len(matrix) != ROWS or any(len(row) != 52 for row in matrix):
        raise ValueError('CSIamp must have shape (950,52)')
    if any(not math.isfinite(x) or x < 0 for row in matrix for x in row):
        raise ValueError('CSIamp must contain finite nonnegative amplitude')

    def element(kind, data):
        return struct.pack('<II', kind, len(data)) + data + b'\0' * (-len(data) % 8)

    # MATLAB stores columns consecutively, not Python's row-major order.
    real = b''.join(struct.pack('<950d', *(row[column] for row in matrix)) for column in range(52))
    payload = (element(6, struct.pack('<II', 6, 0))
               + element(5, struct.pack('<ii', ROWS, 52))
               + element(1, b'CSIamp') + element(9, real))
    header = b'MATLAB 5.0 MAT-file, local ESP-Fi-HAR-shaped CSI amplitude'
    with Path(path).open('xb') as stream:
        stream.write(header.ljust(116, b' ') + b'\0' * 8 + struct.pack('<H', 0x100) + b'IM')
        stream.write(element(14, payload))


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('capture', type=Path)
    parser.add_argument('--out', type=Path, required=True, help='dataset base; writes rxN/split/label/*.mat')
    parser.add_argument('--node', type=int, choices=(1, 2), required=True)
    parser.add_argument('--label', choices=ACTIVITIES, required=True, help='activity performed for this whole trial')
    parser.add_argument('--subject', type=int, required=True)
    parser.add_argument('--scenario', type=int, required=True, help='local room ID, not an upstream room identity')
    parser.add_argument('--trial', type=int, required=True)
    parser.add_argument('--split', choices=('train_amp', 'test_amp'), required=True)
    parser.add_argument('--start-us', type=int, help='start at the first selected RX record at/after this local timestamp')
    args = parser.parse_args()
    if min(args.subject, args.scenario, args.trial) <= 0 or (args.start_us is not None and args.start_us < 0):
        parser.error('IDs must be positive and --start-us must be nonnegative')
    directory = args.out / f'rx{args.node}' / args.split / args.label
    stem = f'{args.scenario}-{args.subject}-{FILENAME_IDS[args.label]}-{args.trial}'
    mat_path = directory / (stem + '.mat')
    manifest_path = directory / (stem + '.json')
    try:
        if mat_path.exists() or manifest_path.exists():
            raise ValueError('output trial already exists; choose a new trial ID/output directory')
        matrix, metadata = collect_trial(read_packets(args.capture), args.node, args.start_us)
        metadata.update(source_capture=str(args.capture.resolve()), label=args.label,
                        label_index=ACTIVITIES.index(args.label), classes=list(ACTIVITIES),
                        filename_activity_ids=FILENAME_IDS,
                        label_mapping_provenance='folder labels and filename IDs observed in audited ZIP; contradict upstream README',
                        subject=args.subject, scenario=args.scenario, trial=args.trial, split=args.split)
        # Keep folder layout accepted by the upstream loader; users still need
        # actual samples in both splits before training/testing.
        for split in ('train_amp', 'test_amp'):
            for label in ACTIVITIES:
                (args.out / f'rx{args.node}' / split / label).mkdir(parents=True, exist_ok=True)
        write_mat(mat_path, matrix)
        with manifest_path.open('x', encoding='utf-8') as stream:
            json.dump(metadata, stream, ensure_ascii=False, indent=2)
            stream.write('\n')
    except (OSError, ValueError) as error:
        parser.exit(1, f'export_esp_fi: {error}\n')
    print(f'Saved {mat_path}: CSIamp=(950,52), native={metadata["native_rate_hz"]:.2f} Hz')
    print(f'Metadata: {manifest_path}; upstream timing/carrier equivalence remains unverified')


if __name__ == '__main__':
    main()
