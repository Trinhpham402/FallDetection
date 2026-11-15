#!/usr/bin/env python3
"""Inspect a length-prefixed CSI capture without loading it all into memory."""
import argparse
from collections import Counter
from pathlib import Path

if __package__:
    from .collector import LENGTH, MAX_PACKET, parse_datagram, iq_to_complex
else:
    from collector import LENGTH, MAX_PACKET, parse_datagram, iq_to_complex


def analyze(path):
    nodes = {}
    bad = 0
    with Path(path).open('rb') as stream:
        while True:
            prefix = stream.read(LENGTH.size)
            if not prefix:
                break
            if len(prefix) != LENGTH.size:
                bad += 1
                break
            size, = LENGTH.unpack(prefix)
            # A corrupt framing length cannot be safely resynchronized.
            if not 0 < size <= MAX_PACKET:
                bad += 1
                break
            raw = stream.read(size)
            if len(raw) != size:
                bad += 1
                break
            try:
                packet = parse_datagram(raw)
            except ValueError:
                bad += 1
                continue
            node = nodes.setdefault(packet.node_id, {
                'counts': Counter(), 'macs': Counter(), 'timing': {},
                'amplitude_count': 0, 'amplitude_sum': 0.0,
                'amplitude_min': float('inf'), 'amplitude_max': 0.0,
                'profiles': Counter(), 'iq_lengths': Counter(), 'invalid_first_word': 0,
            })
            node['counts'][packet.kind] += 1
            node['macs'][packet.tx_mac] += 1
            timing = node['timing'].setdefault(packet.kind, {
                'first': packet.rx_local_us, 'last': packet.rx_local_us,
                'regressed': False, 'max_gap_us': 0})
            timing['max_gap_us'] = max(timing['max_gap_us'], packet.rx_local_us - timing['last'])
            if packet.rx_local_us < timing['last']:
                timing['regressed'] = True
            timing['last'] = packet.rx_local_us
            if packet.kind == 'CSI':
                node['profiles'][packet.profile if packet.profile is not None else 'legacy/unknown'] += 1
                node['iq_lengths'][packet.iq_len] += 1
                node['invalid_first_word'] += bool(packet.flags & 1)
            iq = iq_to_complex(packet)
            if iq:
                amplitude = sum(map(abs, iq)) / len(iq)
                node['amplitude_count'] += 1
                node['amplitude_sum'] += amplitude
                node['amplitude_min'] = min(node['amplitude_min'], amplitude)
                node['amplitude_max'] = max(node['amplitude_max'], amplitude)
    return nodes, bad


def report(path, nodes, bad):
    print(f'Capture: {path}  bad={bad}')
    if not nodes:
        print('  No valid records')
    for node_id, node in sorted(nodes.items()):
        counts = node['counts']
        print(f"  RX{node_id}: CSI={counts['CSI']}, TX_EVENT={counts['TX_EVENT']}, source_MAC={node['macs'].most_common()}")
        for kind, timing in node['timing'].items():
            elapsed = timing['last'] - timing['first']
            if timing['regressed']:
                print(f'    {kind}: throughput unavailable (timestamp regression; restart/reordering)')
            elif counts[kind] < 2 or elapsed <= 0:
                print(f'    {kind}: throughput unavailable (insufficient timestamp span)')
            else:
                rate = (counts[kind] - 1) * 1e6 / elapsed
                print(f'    {kind}: measured mean throughput ~{rate:.2f} records/s')
            print(f'    {kind}: largest timestamp gap {timing["max_gap_us"] / 1000:.3f} ms')
        if node['counts']['CSI']:
            print(f'    CSI profiles={dict(node["profiles"])} iq_bytes={dict(node["iq_lengths"])} '
                  f'first_word_invalid={node["invalid_first_word"]}')
        if node['amplitude_count']:
            mean = node['amplitude_sum'] / node['amplitude_count']
            print(f"    CSI mean |H|: mean={mean:.2f}, range={node['amplitude_min']:.2f}..{node['amplitude_max']:.2f} (uncalibrated)")


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('capture', type=Path)
    args = parser.parse_args()
    try:
        nodes, bad = analyze(args.capture)
    except OSError as error:
        parser.exit(1, f'check_capture: {error}\n')
    report(args.capture, nodes, bad)
    if bad:
        parser.exit(1)


if __name__ == '__main__':
    main()
