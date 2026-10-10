"""Serial transport and bounded demo device. All device I/O runs off the GUI thread."""
from collections import deque
import math
import queue
import random
import struct
import threading
import time
import serial
from . import protocol as p

class DemoDevice:
    def __init__(self, frames_per_second=2000):
        self.start = time.monotonic()
        self.capture = self.bridge = False
        self.rates = [500000, 500000]
        self.confirmed = [False, False]
        self.ranges = [1] * 8
        self.enabled = [True] * 8
        self.counters = [[0] * 8 for _ in range(2)]
        self.sequence = self.frame_id = self.generation = 0
        self.boot = random.getrandbits(32)
        self.last_adc = self.last_status = self.last_can = 0
        self.raw_end = 0
        self.raw_ch = 0
        self.last_raw = 0
        self.profiles = {}
        self.saved_profiles = {}
        self.fps = frames_per_second
        self.auto = {}

    def now(self):
        return int((time.monotonic() - self.start) * 1e6)

    def packet(self, kind, data):
        packet = p.encode(kind, self.sequence, data)
        self.sequence = (self.sequence + 1) & 0xffffffff
        return packet

    def status(self):
        data = p.STATUS.pack(self.now(), self.boot, 0, self.generation, b'CS-DEMO-0001', self.bridge, self.capture,
                             int(self.bridge), int(self.bridge), *self.rates, *self.counters[0], *self.counters[1])
        return self.packet(p.Kind.STATUS, data)

    def command(self, command, request, args):
        now = self.now()
        result, packets = 0, []
        if command == p.Command.STATUS:
            packets.append(self.status())
        elif command == p.Command.CAPTURE:
            self.capture = bool(args[0])
            self.generation += int(self.capture)
            self.last_adc = now // 10000 * 10000
            packets.append(self.packet(p.Kind.EVENT, p.EVENT.pack(now, 255, 11, self.capture, 0, 0)))
        elif command == p.Command.CAN_CONFIG:
            side, rate = struct.unpack('<BI', args)
            self.bridge = False
            self.rates[side] = rate
            self.confirmed[side] = bool(rate)
            if not rate:
                self.auto[side] = now + 600000
                packets.append(self.packet(p.Kind.AUTO, p.AUTO.pack(now, side, 0, 500000)))
        elif command == p.Command.BRIDGE:
            if args[0] and (not all(self.confirmed) or self.rates[0] != self.rates[1]):
                result = 2
            else:
                self.bridge = bool(args[0])
        elif command == p.Command.CHANNEL:
            ch, enabled, range_ = args
            self.enabled[ch], self.ranges[ch] = bool(enabled), range_
            packets.append(self.packet(p.Kind.EVENT, p.EVENT.pack(now, 255, 9, ch << 8 | range_, 0, 0)))
        elif command == p.Command.RAW:
            self.raw_ch, duration = struct.unpack('<BH', args)
            self.last_raw = now
            self.raw_end = now + duration * 1000
        elif command == p.Command.PROFILE:
            from .calibration import Profile
            ch, range_, version, count = struct.unpack_from('<BBIB', args)
            points = list(struct.iter_unpack('<Hf', args[7:]))
            try:
                self.profiles[ch, range_] = Profile(ch, range_, version, points).validate()
            except ValueError:
                result = 1
        elif command == p.Command.LINEAR_PROFILE:
            from .calibration import LinearProfile
            ch,r,version,zero,gain=struct.unpack('<BBIff',args)
            try:self.profiles[ch,r]=LinearProfile(ch,r,version,zero,gain).validate()
            except ValueError:result=1
        elif command == p.Command.SAVE_CALIBRATION:
            if self.capture or self.bridge or len(self.profiles)!=16:result=2
            else:self.saved_profiles=dict(self.profiles)
        elif command == p.Command.RELOAD_CALIBRATION:
            if self.capture or self.bridge:result=2
            else:self.profiles=dict(self.saved_profiles)
        elif command == p.Command.READ_COEFFICIENTS:
            from .calibration import LinearProfile
            values=[]
            for ch in range(8):
                for r in range(2):
                    profile=self.profiles.get((ch,r))
                    if isinstance(profile,LinearProfile):source,version,a,b=1,profile.version,profile.gain,-profile.zero*profile.gain
                    elif profile:source,version,a,b=2,profile.version,float('nan'),float('nan')
                    else:source,version,a,b=0,0,(1.47,6.17)[r]*3.3/4095,-1.551
                    values.append(p.COEFFICIENTS.pack(request,ch,r,source,version,a,b))
            packets.append(self.packet(p.Kind.COEFFICIENTS,b''.join(values)))
        elif command == p.Command.CLEAR_COUNTERS:
            self.counters = [[0] * 8 for _ in range(2)]
        elif command == p.Command.LOOPBACK_TEST:
            packets.append(self.packet(p.Kind.EVENT, p.EVENT.pack(now, args[0], 12, 1, 0, 0)))
        packets.append(self.packet(p.Kind.RESPONSE, struct.pack('<IBBQ', request, command, result, now)))
        return b''.join(packets)

    def poll(self):
        now, packets = self.now(), []
        for side, deadline in list(self.auto.items()):
            if now >= deadline:
                self.rates[side], self.confirmed[side] = 500000, True
                packets.append(self.packet(p.Kind.AUTO, p.AUTO.pack(now, side, 1, 500000)))
                del self.auto[side]
        if now - self.last_status >= 500000:
            self.last_status = now
            packets.append(self.status())
        can_data, tx_data, adc_data, raw_data = bytearray(), bytearray(), bytearray(), bytearray()
        count = min(1000, int((now - self.last_can) * self.fps / 1e6))
        if count:
            self.last_can = now
        for i in range(count):
            side = self.frame_id & 1
            self.frame_id += 1
            self.counters[side][0] += 1
            if self.capture:
                ide, rtr = int(self.frame_id % 7 == 0), int(self.frame_id % 19 == 0)
                can_data.extend(p.CAN.pack(now, self.frame_id, (0x18daf100 if ide else 0x100) + self.frame_id % 16,
                                           side, ide, rtr, 8, 1, b'\0' * 8 if rtr else self.frame_id.to_bytes(8, 'little')))
                if self.bridge:
                    tx_data.extend(p.TX.pack(now + 200, self.frame_id, side ^ 1, p.TxState.SENT, 1))
            if self.bridge:
                self.counters[side ^ 1][1] += 1
        if self.capture:
            for _ in range(min(20, (now - self.last_adc) // 10000)):
                self.last_adc += 10000
                t = self.last_adc
                for ch in range(8):
                    if not self.enabled[ch]:
                        continue
                    volts = (1.5 + math.sin(t / 1e6 * (ch + 1) * .7)) * (3 if self.ranges[ch] else 1)
                    raw = (volts+3.3*.47) / (6.17 if self.ranges[ch] else 1.47) / 3.3 * 4095
                    profile = self.profiles.get((ch, self.ranges[ch]))
                    q, version = p.Quality.UNCALIBRATED, 0
                    if profile:
                        converted, outside = profile.convert([raw])
                        volts = float(converted[0]); q = p.Quality.OUTSIDE_PROFILE if outside[0] else 0; version = profile.version
                    adc_data.extend(p.ADC.pack(t, ch, self.ranges[ch], q, raw, 1., volts, version))
        for _ in range(min(400, max(0, (min(now, self.raw_end) - self.last_raw) // 625))):
            self.last_raw += 625
            v = 1.5 + math.sin(self.last_raw / 1e6 * 2 * math.pi * 5)
            raw_data.extend(p.RAW.pack(self.last_raw, self.raw_ch, self.ranges[self.raw_ch], round(v / 3.3 * 4095)))
        for kind, layout, data in ((p.Kind.CAN_RX, p.CAN, can_data), (p.Kind.TX_STATUS, p.TX, tx_data),
                                   (p.Kind.ADC, p.ADC, adc_data), (p.Kind.RAW, p.RAW, raw_data)):
            size = p.MAX_PAYLOAD // layout.size * layout.size
            for i in range(0, len(data), size):
                packets.append(self.packet(kind, data[i:i+size]))
        return b''.join(packets)

class DeviceWorker:
    """Bounded inbox/outbox; GUI drains 25 times/sec. No Qt object in worker."""
    def __init__(self, port, demo_fps=2000):
        self.port = port
        self.demo_fps = demo_fps
        self.commands = queue.Queue(maxsize=128)
        self.inbox = deque()
        self.lock = threading.Lock()
        self.stop_event = threading.Event()
        self.parser = p.Parser()
        self.dropped = 0
        self.error = ''
        self.connected = False
        self.thread = threading.Thread(target=self.run, daemon=True)
        self.request = 0

    def start(self):
        self.thread.start()

    def close(self):
        self.stop_event.set()
        self.thread.join(timeout=2)

    def send(self, command, args=b''):
        self.request += 1
        self.commands.put_nowait((command, self.request, args))
        return self.request

    def drain(self, limit=2000):
        with self.lock:
            return [self.inbox.popleft() for _ in range(min(limit, len(self.inbox)))]

    def receive(self, data):
        packets = self.parser.feed(data)
        with self.lock:
            for packet in packets:
                if len(self.inbox) == 4096:
                    self.inbox.popleft(); self.dropped += 1
                self.inbox.append(packet)

    def run(self):
        stream = None
        try:
            demo = DemoDevice(self.demo_fps) if self.port == 'DEMO' else None
            if not demo:
                stream = serial.Serial(self.port, 115200, timeout=.005, write_timeout=.2)
                stream.reset_input_buffer()
            self.connected = True
            tx_seq = 0
            while not self.stop_event.is_set():
                for _ in range(32):
                    try:
                        command, request, args = self.commands.get_nowait()
                    except queue.Empty:
                        break
                    if demo:
                        self.receive(demo.command(command, request, args))
                    else:
                        stream.write(p.encode(p.Kind.COMMAND, tx_seq, struct.pack('<IB', request, command) + args))
                        tx_seq = (tx_seq + 1) & 0xffffffff
                if demo:
                    self.receive(demo.poll())
                    self.stop_event.wait(.005)
                else:
                    self.receive(stream.read(min(max(stream.in_waiting, 1), 8192)))
        except Exception as exc:
            self.error = str(exc)
        finally:
            self.connected = False
            if stream:
                stream.close()
