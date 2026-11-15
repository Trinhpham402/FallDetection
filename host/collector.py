#!/usr/bin/env python3
"""Receive WCS2, legacy WCS1, and WTX1 UDP using the standard library."""
import argparse
import csv
import json
from dataclasses import dataclass, asdict
from datetime import datetime, timezone
from pathlib import Path
import socket
import struct
import time

CSI_HEADER = struct.Struct('<4sBBbbBxHIQ6s2x')
CSI_V2_HEADER = struct.Struct('<4sBBbbBBHIQ6sBBBBBBI')
TX_EVENT = struct.Struct('<4sBBbBIQQ6s')
LENGTH = struct.Struct('<I')
MAX_PACKET = 40 + 512
FIELDS = ['recv_utc', 'host_monotonic_ns', 'sender_ip', 'kind', 'node_id',
          'channel', 'rssi', 'noise', 'flags', 'csi_seq', 'tx_seq',
          'rx_local_us', 'tx_local_us', 'tx_mac', 'iq_len', 'profile',
          'sig_mode', 'cwb', 'mcs', 'stbc', 'secondary_channel', 'sgi',
          'rx_hw_us', 'data']


@dataclass(frozen=True)
class Packet:
    kind: str
    node_id: int
    channel: int
    rssi: int
    noise: int | None
    flags: int
    csi_seq: int | None
    tx_seq: int | None
    rx_local_us: int
    tx_local_us: int | None
    tx_mac: str
    iq_len: int
    iq: bytes = b''
    profile: int | None = None
    sig_mode: int | None = None
    cwb: int | None = None
    mcs: int | None = None
    stbc: int | None = None
    secondary_channel: int | None = None
    sgi: int | None = None
    rx_hw_us: int | None = None


def parse_datagram(data: bytes) -> Packet:
    """Validate a complete datagram; preserve raw I/Q, including invalid words."""
    magic = data[:4]
    if magic == b'WCS2':
        if len(data) < CSI_V2_HEADER.size:
            raise ValueError('truncated WCS2 header')
        (_, node, channel, rssi, noise, flags, profile, size, seq, rx, mac,
         sig_mode, cwb, mcs, stbc, secondary, sgi, hw_time) = CSI_V2_HEADER.unpack_from(data)
        if (profile != 1 or size != 128 or len(data) != CSI_V2_HEADER.size + size
                or flags & ~1 or (sig_mode, cwb, mcs, stbc, secondary, sgi) != (1, 0, 0, 0, 0, 0)):
            raise ValueError('invalid WCS2 HT20/HT-LTF profile')
        packet = Packet('CSI', node, channel, rssi, noise, flags, seq, None,
                        rx, None, mac.hex(':').upper(), size, data[40:],
                        profile, sig_mode, cwb, mcs, stbc, secondary, sgi, hw_time)
    elif magic == b'WCS1':
        if len(data) < CSI_HEADER.size:
            raise ValueError('truncated WCS1 header')
        _, node, channel, rssi, noise, flags, size, seq, rx, mac = CSI_HEADER.unpack_from(data)
        if not 0 < size <= 512 or size % 2 or len(data) != CSI_HEADER.size + size:
            raise ValueError('invalid WCS1 I/Q length')
        if flags & ~1 or data[9] or data[30:32] != b'\0\0':
            raise ValueError('unsupported WCS1 flags/reserved bytes')
        packet = Packet('CSI', node, channel, rssi, noise, flags, seq, None,
                        rx, None, mac.hex(':').upper(), size, data[32:])
    elif magic == b'WTX1':
        if len(data) != TX_EVENT.size:
            raise ValueError('invalid WTX1 length')
        _, node, channel, rssi, reserved, seq, tx, rx, mac = TX_EVENT.unpack(data)
        if reserved:
            raise ValueError('unsupported WTX1 reserved byte')
        packet = Packet('TX_EVENT', node, channel, rssi, None, 0, None, seq,
                        rx, tx, mac.hex(':').upper(), 0)
    else:
        raise ValueError('unknown datagram magic')
    if packet.node_id not in (1, 2) or not 1 <= packet.channel <= 13:
        raise ValueError('invalid node ID or channel')
    return packet


def iq_to_complex(packet: Packet) -> list[complex]:
    """Convert signed (imaginary, real) pairs, skipping the invalid first word."""
    raw = packet.iq[4:] if packet.flags & 1 else packet.iq
    return [complex(real, imag) for imag, real in struct.iter_unpack('bb', raw)]


class CaptureWriter:
    def __init__(self, prefix):
        self.dat_path = Path(str(prefix) + '.dat')
        self.csv_path = Path(str(prefix) + '.csv')
        self.dat_path.parent.mkdir(parents=True, exist_ok=True)
        self.dat = self.dat_path.open('ab')
        try:
            self.csv = self.csv_path.open('a+', newline='', encoding='utf-8')
            self.csv.seek(0)
            header = next(csv.reader(self.csv), None)
            if header is not None and header != FIELDS:
                raise ValueError('existing CSV has an incompatible header')
            self.csv.seek(0, 2)
            self.writer = csv.DictWriter(self.csv, fieldnames=FIELDS)
            if header is None:
                self.writer.writeheader()
        except BaseException:
            self.dat.close()
            if hasattr(self, 'csv'):
                self.csv.close()
            raise

    def write(self, data, sender_ip, recv_utc, monotonic_ns):
        packet = parse_datagram(data)
        row = asdict(packet)
        iq = row.pop('iq')
        row['data'] = json.dumps(list(struct.unpack(f'{len(iq)}b', iq)),
                                 separators=(',', ':')) if packet.kind == 'CSI' else ''
        row.update(recv_utc=recv_utc, host_monotonic_ns=monotonic_ns, sender_ip=sender_ip)
        self.dat.write(LENGTH.pack(len(data)) + data)
        self.writer.writerow(row)
        return packet

    def flush(self):
        self.dat.flush()
        self.csv.flush()

    def close(self):
        try:
            self.dat.close()
        finally:
            self.csv.close()

    def __enter__(self):
        return self

    def __exit__(self, *args):
        self.close()


class Stats:
    def __init__(self):
        self.nodes = {}
        self.previous = {}

    def add(self, packet):
        counts = self.nodes.setdefault(packet.node_id, {'CSI': 0, 'TX_EVENT': 0, 'tx_gaps': 0})
        counts[packet.kind] += 1
        if packet.kind != 'TX_EVENT':
            return
        key = (packet.node_id, packet.tx_mac)
        old = self.previous.get(key)
        if old is not None:
            seq, tx_time, rx_time = old
            # Reset the baseline after a clock regression (restart or reordering).
            if packet.tx_local_us >= tx_time and packet.rx_local_us >= rx_time:
                delta = (packet.tx_seq - seq) & 0xffffffff
                if 0 < delta < 0x80000000:
                    counts['tx_gaps'] += delta - 1
                elif delta != 0:
                    return
        self.previous[key] = (packet.tx_seq, packet.tx_local_us, packet.rx_local_us)


def run(bind, port, prefix):
    stats = Stats()
    invalid = 0
    with socket.socket(socket.AF_INET, socket.SOCK_DGRAM) as sock:
        sock.bind((bind, port))
        sock.settimeout(0.5)
        with CaptureWriter(prefix) as writer:
            print(f'Listening UDP {bind}:{sock.getsockname()[1]}; writing {writer.dat_path} and {writer.csv_path}', flush=True)
            deadline = time.monotonic() + 5
            try:
                while True:
                    try:
                        data, sender = sock.recvfrom(65535)
                    except socket.timeout:
                        pass
                    else:
                        stamp = time.monotonic_ns()
                        utc = datetime.now(timezone.utc).isoformat()
                        try:
                            packet = writer.write(data, sender[0], utc, stamp)
                        except ValueError as error:
                            invalid += 1
                            if invalid == 1 or invalid % 100 == 0:
                                print(f'Ignore invalid UDP ({invalid} total): {error}', flush=True)
                        else:
                            stats.add(packet)
                    if time.monotonic() >= deadline:
                        writer.flush()
                        print(f'Stats: {stats.nodes} invalid={invalid}', flush=True)
                        deadline = time.monotonic() + 5
            except KeyboardInterrupt:
                print(f'\nStats: {stats.nodes} invalid={invalid}', flush=True)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--bind', default='0.0.0.0')
    parser.add_argument('--port', type=int, default=5005)
    parser.add_argument('--out', type=Path, required=True, help='output prefix (append mode)')
    args = parser.parse_args()
    if not 1 <= args.port <= 65535:
        parser.error('port must be in 1..65535')
    try:
        run(args.bind, args.port, args.out)
    except (OSError, ValueError) as error:
        parser.exit(1, f'collector: {error}\n')


if __name__ == '__main__':
    main()
