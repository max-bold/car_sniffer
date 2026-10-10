"""Version 1 binary transport, shared with firmware/include/protocol.h."""
from dataclasses import dataclass
from enum import IntEnum, IntFlag
import struct
import zlib

MAGIC = b'CS'
VERSION = 1
MAX_PAYLOAD = 1024
HEADER = struct.Struct('<2sBBHI')
CRC = struct.Struct('<I')

class Kind(IntEnum):
    COMMAND = 1
    RESPONSE = 2
    STATUS = 3
    CAN_RX = 4
    TX_STATUS = 5
    EVENT = 6
    ADC = 7
    RAW = 8
    AUTO = 9

class Command(IntEnum):
    STATUS = 1
    CAN_CONFIG = 2
    BRIDGE = 3
    CAPTURE = 4
    CHANNEL = 5
    PROFILE = 6
    RAW = 7
    CLEAR_COUNTERS = 8
    LOOPBACK_TEST = 9

class Quality(IntFlag):
    UNCALIBRATED = 1
    CLIPPING = 2
    SETTLING = 4
    OUT_OF_RANGE = 8
    OUTSIDE_PROFILE = 16
    DMA_LOSS = 32

class TxState(IntEnum):
    PENDING = 0
    SENT = 1
    FAILED = 2
    EXPIRED = 3
    DROPPED = 4

# Timestamp is unsigned MCU microseconds. CAN frame ID is a session-local counter.
CAN = struct.Struct('<QII5B8s')  # t, frame_id, can_id, side, IDE, RTR, DLC, CRC_OK, data
TX = struct.Struct('<QIBBb')  # t, frame_id, destination side, TxState, TX_ACK (-1=N/A,2=pending)
EVENT = struct.Struct('<QBBIII')  # t, side (255=device), code, detail, TEC, REC
ADC = struct.Struct('<QBBHfffI')  # window start, channel, range, quality, raw mean, raw std, volts, profile version
RAW = struct.Struct('<QBBH')  # t, channel, range, raw uint16
AUTO = struct.Struct('<QBBI')  # t, side, stage (0=trying,1=found,2=unknown), bitrate
STATUS = struct.Struct('<QIII12sBBBBII16I')
# t, boot_id, flags, capture_generation, uid, bridge,capture,modeA,modeB, rateA,rateB,
# 8 counters per side: RX,TX,error,rx_overflow,tx_drop,expired,TEC,REC

@dataclass(frozen=True)
class Packet:
    kind: int
    sequence: int
    payload: bytes

def encode(kind: int, sequence: int, payload: bytes = b'') -> bytes:
    if len(payload) > MAX_PAYLOAD:
        raise ValueError('payload too large')
    data = HEADER.pack(MAGIC, VERSION, kind, len(payload), sequence & 0xffffffff) + payload
    return data + CRC.pack(zlib.crc32(data))

class Parser:
    def __init__(self):
        self.buffer = bytearray()
        self.bad_crc = self.bad_header = self.gaps = 0
        self.last_sequence = None
        self.boot_id = None

    def reset(self):
        self.buffer.clear()
        self.last_sequence = None
        self.boot_id = None

    def feed(self, chunk: bytes):
        self.buffer.extend(chunk)
        packets = []
        while len(self.buffer) >= HEADER.size:
            pos = self.buffer.find(MAGIC)
            if pos < 0:
                self.buffer[:] = self.buffer[-1:] if self.buffer[-1:] == MAGIC[:1] else b''
                break
            if pos:
                del self.buffer[:pos]
            if len(self.buffer) < HEADER.size:
                break
            _, version, kind, length, seq = HEADER.unpack_from(self.buffer)
            if version != VERSION or length > MAX_PAYLOAD or not 1 <= kind <= 9:
                self.bad_header += 1
                del self.buffer[0]
                continue
            total = HEADER.size + length + CRC.size
            if len(self.buffer) < total:
                break
            if zlib.crc32(self.buffer[:total-4]) != CRC.unpack_from(self.buffer, total-4)[0]:
                self.bad_crc += 1
                del self.buffer[0]
                continue
            if kind == Kind.STATUS and length == STATUS.size:
                boot = struct.unpack_from('<I', self.buffer, HEADER.size + 8)[0]
                if self.boot_id is not None and boot != self.boot_id:
                    self.last_sequence = None
                self.boot_id = boot
            if self.last_sequence is not None:
                delta = (seq - self.last_sequence) & 0xffffffff
                if delta != 1:
                    self.gaps += delta - 1 if 1 < delta < 0x80000000 else 1
            self.last_sequence = seq
            packets.append(Packet(kind, seq, bytes(self.buffer[HEADER.size:total-4])))
            del self.buffer[:total]
        return packets

def records(layout, payload):
    if len(payload) % layout.size:
        raise ValueError('malformed record batch')
    return layout.iter_unpack(payload)
