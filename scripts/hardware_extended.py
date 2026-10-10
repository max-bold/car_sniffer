"""Non-destructive protocol/ADC/backpressure checks; CAN remains silent."""
from collections import defaultdict
import json
from pathlib import Path
import struct
import time
import serial
from desktop import protocol as p

def main():
    parser=p.Parser();request=100;report={}
    with serial.Serial('COM8',115200,timeout=.01,write_timeout=.3) as stream:
        def read(duration):
            end=time.monotonic()+duration;packets=[]
            while time.monotonic()<end:packets+=parser.feed(stream.read(max(1,min(stream.in_waiting,8192))))
            return packets
        def command(cmd,args=b'',expected=0,fragment=False):
            nonlocal request
            request+=1;packet=p.encode(p.Kind.COMMAND,request,struct.pack('<IB',request,cmd)+args)
            if fragment:
                for b in packet:stream.write(bytes([b]))
            else:stream.write(packet)
            packets=read(.12)
            response=[struct.unpack('<IBBQ',v.payload) for v in packets if v.kind==p.Kind.RESPONSE]
            assert any(v[0]==request and v[2]==expected for v in response),(cmd,response)
            return packets
        command(p.Command.CAPTURE,b'\0',fragment=True);report['fragmented_command']=True
        bad=bytearray(p.encode(p.Kind.COMMAND,8,struct.pack('<IB',999,p.Command.CAPTURE)+b'\1'));bad[-1]^=1;stream.write(bad)
        packets=command(p.Command.STATUS);st=[p.STATUS.unpack(v.payload) for v in packets if v.kind==p.Kind.STATUS][-1]
        assert st[6]==0;report['bad_crc_not_executed']=True
        stream.write(b'CS\x01\x01\xff\xff\0\0\0\0')
        command(p.Command.STATUS);report['bad_length_resync']=True
        command(p.Command.BRIDGE,b'\1',expected=2);report['unconfirmed_bridge_rejected']=True
        command(p.Command.CHANNEL,b'\0\0\1');command(p.Command.CAPTURE,b'\1')
        packets=read(.4);channels={row[1] for packet in packets if packet.kind==p.Kind.ADC for row in p.records(p.ADC,packet.payload)}
        assert channels==set(range(1,8));report['independent_channel_disable']=True
        command(p.Command.CHANNEL,b'\0\1\1')
        packets=command(p.Command.RAW,struct.pack('<BH',0,400))+read(.4)
        raw=[row for packet in packets if packet.kind==p.Kind.RAW for row in p.records(p.RAW,packet.payload)]
        assert len(raw)>=500 and all(b[0]-a[0]==625 for a,b in zip(raw,raw[1:]));report['raw_samples']=len(raw);report['raw_step_us']=625
        # Fill bounded telemetry by ceasing host reads; acquisition must continue and losses be visible.
        read(.1);stream.close();time.sleep(1);stream.open();parser.reset();read(.2)
        packets=command(p.Command.STATUS)
        statuses=[p.STATUS.unpack(v.payload) for v in packets if v.kind==p.Kind.STATUS]
        report['loss_before_backpressure']=st[2];report['loss_after_backpressure']=statuses[-1][2]
        assert statuses[-1][2]>st[2]
        command(p.Command.CAPTURE,b'\0')
        command(p.Command.CAN_CONFIG,struct.pack('<BI',0,0));packets=read(2.)
        results=[v for packet in packets if packet.kind==p.Kind.AUTO for v in p.records(p.AUTO,packet.payload)]
        assert any(v[1]==0 and v[2]==2 for v in results);report['silent_auto_no_traffic_unknown']=True
        command(p.Command.CAN_CONFIG,struct.pack('<BI',0,500000))
        command(p.Command.CAN_CONFIG,struct.pack('<BI',1,500000))
        command(p.Command.CHANNEL,b'\0\1\1')
        final=[p.STATUS.unpack(v.payload) for v in command(p.Command.STATUS) if v.kind==p.Kind.STATUS][-1]
        assert final[5:9]==(0,0,0,0)
        report.update(bridge=False,capture=False,range0=1,transport_bad_crc=parser.bad_crc,transport_gaps=parser.gaps)
    Path('docs/hardware-extended.json').write_text(json.dumps(report,indent=2),encoding='utf-8');print(json.dumps(report,indent=2))

if __name__=='__main__':main()
