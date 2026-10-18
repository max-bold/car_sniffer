"""Bench only: requires firmware built with CS_PHYSICAL_CAN_TEST=ON.

Two transceivers on one terminated bus, no external nodes; GUI disconnected.
The ordinary firmware's silent loopback cannot pass the peer-side assertions.
"""
import argparse
import json
import struct
import time
from pathlib import Path

import serial
import serial.tools.list_ports
from desktop import protocol as p


def run(port=None):
    if port is None:
        ports = [v.device for v in serial.tools.list_ports.comports()
                 if (v.vid, v.pid) == (0x0483, 0x5740)]
        if len(ports) != 1:
            raise RuntimeError(f'Expected one board, found {ports}')
        port = ports[0]
    parser = p.Parser()
    request = 0
    results = []
    with serial.Serial(port, 115200, timeout=.02, write_timeout=.5) as stream:
        def read(duration):
            packets = []
            deadline = time.monotonic() + duration
            while time.monotonic() < deadline:
                packets.extend(parser.feed(stream.read(max(1, min(stream.in_waiting, 8192)))))
            return packets

        def command(cmd, args=b''):
            nonlocal request
            request += 1
            stream.write(p.encode(p.Kind.COMMAND, request, struct.pack('<IB', request, cmd) + args))
            packets = []
            deadline = time.monotonic() + 5
            while time.monotonic() < deadline:
                packets.extend(read(.05))
                replies = [struct.unpack('<IBBQ', v.payload) for v in packets if v.kind == p.Kind.RESPONSE]
                matching = [r for r in replies if r[0] == request]
                if matching:
                    if matching[0][2] != 0:
                        raise RuntimeError(f'Command {cmd} failed: {matching[0]}')
                    return packets + read(.15)
            raise TimeoutError(f'Command {cmd} timed out')

        try:
            command(p.Command.BRIDGE, b'\0')
            command(p.Command.CAPTURE, b'\0')
            for channel in range(8):
                command(p.Command.CHANNEL, bytes([channel, 0, 1]))
            for rate in (125000, 250000, 500000, 1000000, 100000, 83333):
                for side in (0, 1):
                    command(p.Command.CAN_CONFIG, struct.pack('<BI', side, rate))
                command(p.Command.CAPTURE, b'\1')
                for source in (0, 1):
                    packets = command(p.Command.LOOPBACK_TEST, bytes([source]))
                    frames = [r for v in packets if v.kind == p.Kind.CAN_RX for r in p.records(p.CAN, v.payload)]
                    assert len(frames) == 32, (rate, source, len(frames))
                    for i, row in enumerate(frames):
                        extended, remote, dlc = i & 1, int(i % 8 == 7), i % 9
                        expected_id = (0x1230000 if extended else 0x500) + i
                        assert row[2:8] == (expected_id, source ^ 1, extended, remote, dlc, 1), row
                        if not remote:
                            assert row[8][:dlc] == bytes((i * 17 + j * 31 + source) & 255 for j in range(dlc))
                    results.append({'rate': rate, 'source': source, 'received': len(frames), 'ack_verified_by_firmware': True})
                command(p.Command.CAPTURE, b'\0')
        finally:
            command(p.Command.BRIDGE, b'\0')
            command(p.Command.CAPTURE, b'\0')
            for channel in range(8):
                command(p.Command.CHANNEL, bytes([channel, 1, 1]))
        packets = command(p.Command.STATUS)
        status = [r for v in packets if v.kind == p.Kind.STATUS for r in p.records(p.STATUS, v.payload)][-1]
        assert status[5:9] == (0, 0, 0, 0), status
        assert parser.bad_crc == 0 and parser.gaps == 0
    return {'port': port, 'results': results, 'bridge': False, 'capture': False,
            'can_modes': ['silent', 'silent'], 'bad_crc': parser.bad_crc, 'sequence_gaps': parser.gaps}


if __name__ == '__main__':
    arg = argparse.ArgumentParser()
    arg.add_argument('--port')
    arg.add_argument('--output')
    args = arg.parse_args()
    report = run(args.port)
    print(json.dumps(report, indent=2))
    if args.output:
        Path(args.output).write_text(json.dumps(report, indent=2), encoding='utf-8')
