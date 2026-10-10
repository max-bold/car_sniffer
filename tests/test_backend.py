import time
import struct
from desktop.backend import DeviceWorker,DemoDevice
from desktop import protocol as p

def test_demo_requires_bitrate_confirmation():
    d=DemoDevice(100)
    result=p.Parser().feed(d.command(p.Command.BRIDGE,1,b'\1'))[-1]
    assert struct.unpack('<IBBQ',result.payload)[2]==2
    for side in (0,1):d.command(p.Command.CAN_CONFIG,2+side,struct.pack('<BI',side,500000))
    d.command(p.Command.BRIDGE,4,b'\1');assert d.bridge
    d.command(p.Command.CAPTURE,5,b'\1');time.sleep(.03)
    assert any(v.kind==p.Kind.CAN_RX for v in p.Parser().feed(d.poll()))
    d.command(p.Command.CAPTURE,6,b'\0');time.sleep(.03)
    packets=p.Parser().feed(d.poll());assert not any(v.kind in (p.Kind.ADC,p.Kind.CAN_RX) for v in packets)
    assert d.bridge

def test_worker_lifecycle():
    w=DeviceWorker('DEMO');w.start()
    deadline=time.monotonic()+2
    while not w.connected and time.monotonic()<deadline:time.sleep(.01)
    w.send(p.Command.CAPTURE,b'\1');time.sleep(.08)
    assert w.drain() and not w.error
    w.close();assert not w.thread.is_alive()
