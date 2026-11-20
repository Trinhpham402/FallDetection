#!/usr/bin/env python3
"""Collect a 17-second CSI-only CSV trial from ESP32 receivers (Python 3.10+)."""
import argparse
import csv
from dataclasses import dataclass, field
from datetime import datetime
import json
import os
from pathlib import Path
import select
import socket
import struct
import sys
import time


CAPTURE_SECONDS = 17
TARGET_RATE = 50
CSI_HEADER = struct.Struct('<4sBBbbBxHIQ6s2x')
CSI_V2_HEADER = struct.Struct('<4sBBbbBBHIQ6sBBBBBBI')
TX_EVENT = struct.Struct('<4sBBbBIQQ6s')
FIELDS = ['timestamp', 'csi_seq', 'node_id', 'mac', 'len', 'buf']


@dataclass(frozen=True)
class Packet:
    protocol: str
    node_id: int
    channel: int
    rssi: int
    tx_mac: str
    rx_local_us: int
    noise: int | None = None
    flags: int = 0
    csi_seq: int | None = None
    iq: bytes = b''
    profile: int | None = None
    sig_mode: int | None = None
    cwb: int | None = None
    mcs: int | None = None
    stbc: int | None = None
    secondary_channel: int | None = None
    sgi: int | None = None
    rx_hw_us: int | None = None


def parse_datagram(data):
    """Validate wire layout; preserve signed Q/I bytes and invalid-word flags."""
    magic = data[:4]
    if magic == b'WCS2':
        if len(data) < CSI_V2_HEADER.size:
            raise ValueError('truncated WCS2 header')
        (_, node, channel, rssi, noise, flags, profile, size, seq, rx, mac,
         sig_mode, cwb, mcs, stbc, secondary, sgi, hw) = CSI_V2_HEADER.unpack_from(data)
        if (profile != 1 or size != 128 or len(data) != 40 + size
                or flags & ~1
                or (sig_mode, cwb, mcs, stbc, secondary, sgi) != (1, 0, 0, 0, 0, 0)):
            raise ValueError('invalid WCS2 HT20/HT-LTF profile')
        packet = Packet('WCS2', node, channel, rssi, mac.hex(':').upper(), rx,
                        noise, flags, seq, data[40:], profile, sig_mode, cwb,
                        mcs, stbc, secondary, sgi, hw)
    elif magic == b'WCS1':
        if len(data) < CSI_HEADER.size:
            raise ValueError('truncated WCS1 header')
        _, node, channel, rssi, noise, flags, size, seq, rx, mac = CSI_HEADER.unpack_from(data)
        if (not 0 < size <= 512 or size % 2 or len(data) != 32 + size
                or flags & ~1 or data[9] or data[30:32] != b'\0\0'):
            raise ValueError('invalid WCS1 length/flags/reserved bytes')
        packet = Packet('WCS1', node, channel, rssi, mac.hex(':').upper(), rx,
                        noise, flags, seq, data[32:])
    elif magic == b'WTX1':
        if len(data) != TX_EVENT.size:
            raise ValueError('invalid WTX1 length')
        _, node, channel, rssi, reserved, seq, tx, rx, mac = TX_EVENT.unpack(data)
        if reserved:
            raise ValueError('invalid WTX1 reserved byte')
        packet = Packet('WTX1', node, channel, rssi, mac.hex(':').upper(), rx)
    else:
        raise ValueError('unknown datagram magic')
    if packet.node_id not in (1, 2) or not 1 <= packet.channel <= 13:
        raise ValueError('invalid node ID/channel')
    return packet


class CsvWriter:
    def __init__(self, stream):
        self.writer = csv.DictWriter(stream, fieldnames=FIELDS)
        self.writer.writeheader()

    def write(self, packet):
        if packet.protocol == 'WTX1':
            return False
        self.writer.writerow({
            'timestamp': packet.rx_local_us,
            'csi_seq': packet.csi_seq,
            'node_id': packet.node_id,
            'mac': packet.tx_mac,
            'len': len(packet.iq),
            'buf': json.dumps(list(struct.unpack(f'{len(packet.iq)}b', packet.iq)),
                              separators=(',', ':')),
        })
        return True


def countdown_seconds(value):
    try:
        seconds = int(value)
    except ValueError:
        raise argparse.ArgumentTypeError('số giây phải là số nguyên không âm') from None
    if seconds < 0:
        raise argparse.ArgumentTypeError('số giây phải là số nguyên không âm')
    return seconds


def prompt_countdown(sock):
    """Drain UDP while waiting for terminal input (Ubuntu terminals/pipes)."""
    print('Nhập số giây đếm ngược: ', end='', flush=True)
    pending = b''
    while True:
        ready, _, _ = select.select([sock, sys.stdin], [], [], 0.2)
        if sock in ready:
            sock.recvfrom(65535)
        if sys.stdin in ready:
            # Avoid TextIO buffering hiding a second piped line from select().
            chunk = os.read(sys.stdin.fileno(), 4096)
            if not chunk and not pending:
                raise ValueError('stdin đã đóng; dùng --countdown N để chạy không tương tác')
            pending += chunk
            if not chunk:
                pending += b'\n'
            while b'\n' in pending:
                line, pending = pending.split(b'\n', 1)
                try:
                    return countdown_seconds(line.decode('utf-8', errors='replace').strip())
                except argparse.ArgumentTypeError as error:
                    print(f'{error}. Nhập lại: ', end='', flush=True)


def discard_pending(sock):
    """Empty the receive queue before recording; fail instead of hanging on flood."""
    deadline = time.monotonic() + 0.2
    while time.monotonic() < deadline:
        try:
            sock.recvfrom(65535)
        except BlockingIOError:
            return
    raise ValueError('UDP đến quá nhanh để xóa hàng đợi trước phiên thu')


def wait_countdown(sock, seconds):
    deadline = time.monotonic() + seconds
    previous = None
    while True:
        remaining = deadline - time.monotonic()
        if remaining <= 0:
            return
        display = int(remaining) + 1
        if display != previous:
            print(f'Bắt đầu sau: {display} giây', flush=True)
            previous = display
        ready, _, _ = select.select([sock], [], [], min(remaining, 0.1))
        if ready:
            sock.recvfrom(65535)


@dataclass
class CaptureStats:
    counts: dict = field(default_factory=lambda: {1: 0, 2: 0})
    invalid: int = 0
    ignored_events: int = 0
    invalid_first_word: int = 0
    elapsed: float = 0.0
    interrupted: bool = False


def print_counts(stats):
    print(f'RX1: {stats.counts[1]} CSI | RX2: {stats.counts[2]} CSI', flush=True)


def capture(sock, stream):
    writer = CsvWriter(stream)
    stream.flush()
    discard_pending(sock)
    stats = CaptureStats()
    start = time.monotonic()
    deadline = start + CAPTURE_SECONDS
    next_report = start + 1
    print(f'Đang ghi CSI trong {CAPTURE_SECONDS} giây...', flush=True)
    try:
        while True:
            now = time.monotonic()
            if now >= deadline:
                break
            if now >= next_report:
                print_counts(stats)
                stream.flush()
                next_report = now + 1
            ready, _, _ = select.select([sock], [], [], min(deadline - now, 0.1))
            if not ready:
                continue
            data, _ = sock.recvfrom(65535)
            stamp_ns = time.monotonic_ns()
            if stamp_ns >= deadline * 1_000_000_000:
                break
            try:
                packet = parse_datagram(data)
            except ValueError:
                stats.invalid += 1
                continue
            if writer.write(packet):
                stats.counts[packet.node_id] += 1
                stats.invalid_first_word += bool(packet.flags & 1)
            else:
                stats.ignored_events += 1
    except KeyboardInterrupt:
        stats.interrupted = True
        print('\nĐã dừng sớm theo yêu cầu.', flush=True)
    stats.elapsed = min(time.monotonic() - start, CAPTURE_SECONDS)
    stream.flush()
    return stats


def output_path(value):
    path = Path(value)
    return path if path.suffix.lower() == '.csv' else Path(str(path) + '.csv')


def run(bind, port, path, countdown=None):
    if path.exists():
        raise FileExistsError(f'{path} đã tồn tại; chọn tên file mới')
    with socket.socket(socket.AF_INET, socket.SOCK_DGRAM) as sock:
        sock.bind((bind, port))
        sock.setblocking(False)
        print(f'Listening UDP {bind}:{sock.getsockname()[1]}', flush=True)
        if countdown is None:
            countdown = prompt_countdown(sock)
        wait_countdown(sock, countdown)
        path.parent.mkdir(parents=True, exist_ok=True)
        with path.open('x', newline='', encoding='utf-8') as stream:
            stats = capture(sock, stream)
    print_counts(stats)
    for node, count in stats.counts.items():
        rate = count / stats.elapsed if stats.elapsed else 0
        print(f'RX{node}: {rate:.2f} CSI/s (mục tiêu {TARGET_RATE} CSI/s)', flush=True)
    print(f'Gói lỗi: {stats.invalid}; WTX1 đã bỏ qua: {stats.ignored_events}; '
          f'CSI có cờ invalid đầu: {stats.invalid_first_word}', flush=True)
    print(f'Đã ghi {stats.elapsed:.3f} giây. Đã đóng file CSV: {path}', flush=True)
    return stats


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--bind', default='0.0.0.0', help='IPv4 lắng nghe')
    parser.add_argument('--port', type=int, default=5005)
    parser.add_argument('--out', default='captures/trial_' + datetime.now().strftime('%Y%m%d_%H%M%S'),
                        help='prefix hoặc đường dẫn CSV mới; không ghi đè/ghi nối')
    parser.add_argument('--countdown', type=countdown_seconds,
                        help='giây đếm ngược; bỏ qua để nhập tương tác')
    args = parser.parse_args()
    if not 1 <= args.port <= 65535:
        parser.error('--port phải nằm trong 1..65535')
    try:
        stats = run(args.bind, args.port, output_path(args.out), args.countdown)
    except KeyboardInterrupt:
        print('\nĐã hủy trước khi ghi dữ liệu.', flush=True)
        return 130
    except (OSError, ValueError) as error:
        print(f'collector: {error}', file=sys.stderr)
        return 1
    return 130 if stats.interrupted else 0


if __name__ == '__main__':
    sys.exit(main())
