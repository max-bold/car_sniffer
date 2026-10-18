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


def test_fixed_divider_rejects_legacy_range_and_returns_eight_coefficients():
    d=DemoDevice(0)
    packets=p.Parser().feed(d.command(p.Command.CHANNEL,1,bytes([0,0,0])))
    assert struct.unpack('<IBBQ',packets[-1].payload)[2]==1 and d.enabled[0]
    packets=p.Parser().feed(d.command(p.Command.READ_COEFFICIENTS,2,b''))
    values=[r for packet in packets if packet.kind==p.Kind.COEFFICIENTS for r in p.records(p.COEFFICIENTS,packet.payload)]
    assert len(values)==8 and {r[1] for r in values}==set(range(8))
    assert all(r[2:5]==(1,0,0) and abs(r[5]*4095/3.3-6.17)<1e-5 for r in values)
